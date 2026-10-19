"""Exercise the applicability CLI against real, small Git source histories."""
import json
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import check_graphics_cpu_applicability as applicability

native = applicability.native


class ApplicabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.git('init', '-q')
        baseline = {name: b'old:' + name.encode() for name in native.CHANGED - native.ADDED}
        baseline.update({name: b'unchanged' for name in (
            'Cargo.toml', 'Cargo.lock', 'examples/renderer_contract.rs')})
        for name, raw in baseline.items():
            self.write(name, raw)
        before = self.commit()
        for name in native.CHANGED:
            self.write(name, b'new:' + name.encode())
        after = self.commit()
        self.addCleanup(patch.stopall)
        patch.object(native, 'BASELINE_SOURCE', before).start()
        patch.object(native, 'CANDIDATE_SOURCE', after).start()

    def git(self, *arguments):
        return subprocess.check_output(['git', '-C', str(self.root), *arguments], text=True).strip()

    def write(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Public test fixture')
        return self.git('rev-parse', 'HEAD')

    def test_matching_source_requires_native_controls_without_claiming_a_pass(self):
        report = applicability.assess(self.root)
        self.assertEqual(report['status'], 'applicable')
        self.assertEqual(report['changed_compile_inputs'], [])
        self.assertFalse(report['native_controls_executed'])
        self.assertEqual(report['current_source_commit'], native.CANDIDATE_SOURCE)

    def test_committed_lockfile_evolution_is_explicitly_not_current_native_proof(self):
        self.write('Cargo.lock', b'updated dependencies')
        current = self.commit()
        report = applicability.assess(self.root)
        self.assertEqual(report['status'], 'not-applicable')
        self.assertEqual(report['current_source_commit'], current)
        self.assertEqual(report['changed_compile_inputs'], ['Cargo.lock'])
        self.assertFalse(report['native_controls_executed'])
        self.assertIn('does not validate the current renderer', report['reason'])

    def test_added_and_removed_committed_compile_inputs_are_reported(self):
        self.write('src/new.rs', b'new module')
        (self.root / 'src/app.rs').unlink()
        self.commit()
        report = applicability.assess(self.root)
        self.assertEqual(report['status'], 'not-applicable')
        self.assertEqual(report['changed_compile_inputs'], ['src/app.rs', 'src/new.rs'])

    def test_exact_reviewed_test_fixture_repair_stays_applicable(self):
        repaired = (Path(__file__).resolve().parents[1] / 'src/asset_path.rs').read_bytes().replace(b'\r\n', b'\n')
        original = native.finite_source._asset_path_test_base(repaired)
        self.assertNotEqual(original, repaired)
        self.git('reset', '--hard', native.BASELINE_SOURCE)
        self.write('src/asset_path.rs', original)
        baseline = self.commit()
        for name in native.CHANGED:
            self.write(name, b'new:' + name.encode())
        candidate = self.commit()
        self.write('src/asset_path.rs', repaired)
        self.commit()
        with patch.object(native, 'BASELINE_SOURCE', baseline), patch.object(native, 'CANDIDATE_SOURCE', candidate):
            report = applicability.assess(self.root)
        self.assertEqual(report['status'], 'applicable')
        self.assertEqual(report['changed_compile_inputs'], [])

    def test_dirty_missing_and_untracked_compile_inputs_fail_instead_of_skip(self):
        path = self.root / 'Cargo.lock'
        for action in (lambda: path.write_bytes(b'dirty'), lambda: path.unlink(),
                       lambda: self.write('src/untracked.rs', b'extra')):
            action()
            with self.assertRaisesRegex(ValueError, 'clean committed compile inputs'):
                applicability.assess(self.root)
            self.git('reset', '--hard', 'HEAD')
        (self.root / 'src/untracked.rs').unlink()

    def test_unavailable_frozen_revision_is_an_error(self):
        with patch.object(native, 'CANDIDATE_SOURCE', '0' * 40):
            with self.assertRaises(subprocess.CalledProcessError):
                applicability.assess(self.root)

    def test_incomplete_source_tree_is_an_error(self):
        (self.root / 'Cargo.toml').unlink()
        self.commit()
        with self.assertRaisesRegex(ValueError, 'incomplete source tree'):
            applicability.assess(self.root)

    def test_cli_retains_report_and_emits_only_applicability_output(self):
        self.write('Cargo.lock', b'updated dependencies')
        self.commit()
        output = self.root / 'applicability.json'
        github_output = self.root / 'github-output'
        summary = self.root / 'summary'
        with patch.dict(os.environ, GITHUB_OUTPUT=str(github_output), GITHUB_STEP_SUMMARY=str(summary)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(applicability.main(['--repository', str(self.root), '--output', str(output)]), 0)
        report = json.loads(output.read_text())
        self.assertEqual(report['status'], 'not-applicable')
        self.assertEqual(github_output.read_text(), 'applicable=false\n')
        self.assertIn('not-applicable', summary.read_text())
        self.assertIn('Cargo.lock', summary.read_text())


if __name__ == '__main__':
    unittest.main()
