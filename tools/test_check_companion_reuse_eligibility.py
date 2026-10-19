"""Original offline Git fixtures test scheduling, never pack or native acceptance."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import check_companion_reuse_eligibility as precheck
import revalidate_reused_companions as reuse


TOOL = Path(precheck.__file__).resolve()
LOCK = TOOL.with_name('source_bound_companion_reuse_lock.json')


class CompanionSourceSchedulingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'source'
        self.root.mkdir()
        self.lock = copy.deepcopy(reuse.read_json(LOCK))
        self.git('init', '-q')
        for row in self.lock['source_files']:
            path = self.root / row['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = ('Original scheduling fixture: ' + row['path'] + '\n').encode()
            path.write_bytes(raw)
            row.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                       git_blob=hashlib.sha1(b'blob ' + str(len(raw)).encode()
                                             + b'\0' + raw).hexdigest())
        self.commit = self.commit_source()
        self.lock['eligible_assets_tree'] = self.git('rev-parse', 'HEAD:assets')
        self.lock_path = self.directory / 'reuse-lock.json'
        self.lock_path.write_text(json.dumps(self.lock), encoding='utf-8')
        self.output = self.directory / 'github-output'
        self.summary = self.directory / 'summary.md'

    def git(self, *arguments):
        return subprocess.check_output(
            ['git', '-C', str(self.root), '-c', 'core.autocrlf=false',
             '-c', 'user.name=Scheduling fixture',
             '-c', 'user.email=scheduling-fixture@example.invalid',
             '-c', 'commit.gpgsign=false', *arguments],
            text=True, stderr=subprocess.PIPE, timeout=30).strip()

    def commit_source(self):
        self.git('add', '-A')
        self.git('commit', '-qm', 'Original isolated scheduling fixture')
        return self.git('rev-parse', 'HEAD')

    def arguments(self, commit=None):
        return ['--source-root', str(self.root), '--expected-source-commit', commit or self.commit,
                '--lock', str(self.lock_path), '--github-output', str(self.output),
                '--summary', str(self.summary)]

    def invoke(self, commit=None):
        return subprocess.run([sys.executable, '-B', str(TOOL), *self.arguments(commit)],
                              capture_output=True, text=True, timeout=30)

    def report(self, result, matches):
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertIs(report['source_matches'], matches)
        self.assertEqual(self.output.read_text(encoding='utf-8'),
                         'source_matches=' + str(matches).lower() + '\n')
        self.assertIn('Committed source identities only', report['scope'])
        self.assertIn('produces no validated packs, playable preview, or native evidence',
                      self.summary.read_text(encoding='utf-8'))
        return report

    def failure(self, result, message):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertFalse(self.output.exists())
        self.assertFalse(self.summary.exists())

    def test_cli_matching_committed_source_is_only_a_scheduling_candidate(self):
        report = self.report(self.invoke(), True)
        self.assertEqual(report['mismatches'], [])
        self.assertEqual(report['current_source_commit'], self.commit)
        self.assertFalse((self.root / self.lock['jump_source']['path']).exists())
        self.assertFalse((self.root / 'evidence').exists())
        self.assertIn('all original recovery checks are still required',
                      self.summary.read_text(encoding='utf-8'))

    def test_cli_changed_assets_tree_is_explicitly_inapplicable(self):
        (self.root / 'assets/new-original-fixture.txt').write_bytes(b'new asset fixture\n')
        commit = self.commit_source()
        report = self.report(self.invoke(commit), False)
        self.assertEqual([row['path'] for row in report['mismatches']], ['assets'])
        summary = self.summary.read_text(encoding='utf-8')
        self.assertIn('inapplicable and is skipped', summary)
        self.assertIn('actions/workflows/build.yml', summary)
        self.assertIn('for this same commit', summary)
        self.assertIn('does not establish that this artifact exists', summary)

    def test_cli_changed_pinned_source_rejects_with_unchanged_assets(self):
        path = self.root / 'src/lib.rs'
        path.write_bytes(path.read_bytes() + b'changed committed source\n')
        commit = self.commit_source()
        self.assertEqual(self.git('rev-parse', 'HEAD:assets'), self.lock['eligible_assets_tree'])
        report = self.report(self.invoke(commit), False)
        self.assertEqual([row['path'] for row in report['mismatches']], ['src/lib.rs'])

    def test_cli_deleted_pinned_source_is_a_known_committed_difference(self):
        (self.root / 'src/lib.rs').unlink()
        report = self.report(self.invoke(self.commit_source()), False)
        self.assertEqual([row['path'] for row in report['mismatches']], ['src/lib.rs'])
        self.assertIsNone(report['mismatches'][0]['actual'])

    def test_worktree_bytes_are_still_owned_by_unchanged_recovery_verifier(self):
        # The early scheduling precheck deliberately reads committed identities.
        # Admission must not be described as byte or pack validation.
        path = self.root / 'src/lib.rs'
        path.write_bytes(path.read_bytes() + b'uncommitted source edit\n')
        self.report(self.invoke(), True)
        with self.assertRaisesRegex(ValueError, 'byte/hash mismatch'):
            reuse.verify_source(self.root, self.commit,
                                self.directory / 'absent-external-jump.blend', self.lock)

    def test_cli_wrong_expected_head_is_a_hard_failure(self):
        self.failure(self.invoke('0' * 40), 'current checkout commit mismatch')

    def test_cli_short_expected_head_is_a_hard_failure(self):
        self.failure(self.invoke(self.commit[:7]), 'expected source commit must be full lowercase SHA')

    def test_cli_invalid_lock_is_not_an_inapplicable_result(self):
        self.lock['schema'] = 'invalid'
        self.lock_path.write_text(json.dumps(self.lock), encoding='utf-8')
        self.failure(self.invoke(), 'unsupported lock schema')

    def test_cli_duplicate_lock_key_is_a_hard_failure(self):
        self.lock_path.write_text('{"schema":1,"schema":2}', encoding='utf-8')
        self.failure(self.invoke(), 'duplicate JSON key')

    def test_cli_missing_lock_is_a_hard_failure(self):
        self.lock_path.unlink()
        self.failure(self.invoke(), 'companion source scheduling precheck failed')

    def test_git_error_emits_no_admission_or_skip_receipt(self):
        error = subprocess.CalledProcessError(128, ['git', 'ls-tree'])
        with mock.patch.object(precheck, 'committed_entries', side_effect=error), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(precheck.main(self.arguments()), 1)
        self.assertIn('precheck failed', errors.getvalue())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.summary.exists())

    def test_checkout_change_during_precheck_is_a_hard_failure(self):
        with mock.patch.object(reuse, 'git', side_effect=[self.commit, '0' * 40]):
            with self.assertRaisesRegex(ValueError, 'checkout changed during'):
                precheck.inspect_sources(self.root, self.commit, self.lock_path)

    def test_malformed_git_output_is_never_classified_as_source_difference(self):
        valid = b'100644 blob ' + b'1' * 40 + b'\tsrc/lib.rs\0'
        for raw in (b'bad-entry\0', valid.replace(b'100644', b'abcdef'),
                    valid.replace(b'1' * 40, b'x' * 40), valid + valid):
            with self.subTest(raw=raw), \
                    mock.patch.object(precheck.subprocess, 'check_output', return_value=raw), \
                    self.assertRaises(ValueError):
                precheck.committed_entries(self.root, self.commit)


if __name__ == '__main__':
    unittest.main()
