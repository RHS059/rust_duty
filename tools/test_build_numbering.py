"""Build labels must agree without changing the updater's release ordering."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import build_identity as identity
import package_game
from test_publish_game_build import environment


class BuildNumberingTests(unittest.TestCase):
    def setUp(self):
        self.env = environment()
        self.env.pop("RUST_DUTY_BUILD_VERSION")

    def test_distinct_runs_branches_and_attempts(self):
        labels = set()
        for run, branch, attempt in [(1000, 'aella/one', 1), (1001, 'halcyon/two', 1),
                                     (1000, 'aella/one', 2), (1002, 'main', 1)]:
            env = {**self.env, 'GITHUB_RUN_ID': str(run), 'GITHUB_REF_NAME': branch,
                   'GITHUB_RUN_ATTEMPT': str(attempt)}
            item = identity.context(env)
            labels.add(item['display_version'])
            self.assertEqual(item['build_number'], f'{run}.{attempt}')
            self.assertEqual(item['source']['run_attempt'], attempt)
            self.assertEqual(item['version'], identity.package_version())
        self.assertEqual(len(labels), 4)

    def test_same_attempt_is_repeatable_and_platform_independent(self):
        self.assertEqual(identity.context(self.env), identity.context(dict(self.env)))
        self.assertNotIn('target', identity.context(self.env))

    def test_older_run_rerun_is_unique_but_cannot_change_release_order(self):
        older = {**self.env, 'GITHUB_RUN_ID': '999', 'GITHUB_RUN_ATTEMPT': '20'}
        newer = {**self.env, 'GITHUB_RUN_ID': '1000', 'GITHUB_RUN_ATTEMPT': '1'}
        with mock.patch.object(identity, 'package_version', return_value='0.1.9'):
            old = identity.context(older)
        with mock.patch.object(identity, 'package_version', return_value='0.1.10'):
            new = identity.context(newer)
        self.assertNotEqual(old['display_version'], new['display_version'])
        self.assertLess(identity.release_update.stable_version(old['version']),
                        identity.release_update.stable_version(new['version']))

    def test_missing_attempt_never_silently_reuses_attempt_one(self):
        for bad in [None, '', '0', '01', '-1', '1.5', str(2**64)]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                identity.context({**self.env, 'GITHUB_RUN_ATTEMPT': bad})

    def test_stamp_rejects_cached_binary_from_previous_attempt(self):
        expected = identity.context(self.env)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'vector-range').write_bytes(b'\x7fELFfixture')
            outputs = [expected['version'], expected['version'] + '+build.1000.2']
            with mock.patch.object(identity.subprocess, 'check_output', side_effect=outputs):
                with self.assertRaisesRegex(ValueError, 'build label'):
                    identity.stamp(root, 'linux', self.env)
            self.assertFalse((root/identity.IDENTITY_FILE).exists())

    def test_stamp_cli_and_manifest_agree_on_each_platform(self):
        expected = identity.context(self.env)
        for platform, (_, executable, _, magic) in identity.TARGETS.items():
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/executable).write_bytes(magic+b'fixture')
                with mock.patch.object(identity.subprocess, 'check_output',
                                       side_effect=[expected['version'], expected['display_version']]):
                    identity.stamp(root, platform, self.env)
                record = identity.verify(root, platform, expected)
                self.assertEqual(record['display_version'], expected['display_version'])
                changed = copy.deepcopy(expected)
                changed['source']['run_attempt'] += 1
                with self.assertRaises(ValueError):
                    identity.verify(root, platform, changed)

    def test_repackaging_preserves_only_matching_bounded_identity(self):
        expected = identity.context(self.env)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root/'vector-range'
            binary.write_bytes(b'\x7fELFfixture')
            self.assertIsNone(package_game.preserved_build_identity(root, binary))
            with mock.patch.object(identity.subprocess, 'check_output',
                                   side_effect=[expected['version'], expected['display_version']]):
                identity.stamp(root, 'linux', self.env)
            path = package_game.preserved_build_identity(root, binary)
            self.assertEqual(path, root/identity.IDENTITY_FILE)
            original = json.loads(path.read_text())
            for field, value in [('display_version', '0.1.9+build.1000.2'),
                                 ('target', 'wrong-target')]:
                broken = {**original, field: value}
                path.write_text(json.dumps(broken))
                with self.assertRaises(ValueError):
                    package_game.preserved_build_identity(root, binary)
            path.write_text(json.dumps(original))
            binary.write_bytes(b'\x7fELFchanged')
            with self.assertRaisesRegex(ValueError, 'executable'):
                package_game.preserved_build_identity(root, binary)
            path.write_text(' ' * (16 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, 'oversized'):
                package_game.preserved_build_identity(root, binary)

    def test_cli_label_matches_artifact_naming_input(self):
        completed = subprocess.run([os.sys.executable, str(Path(identity.__file__).resolve()),
                                    '--print-label'], env={**os.environ, **self.env},
                                   check=True, capture_output=True, text=True)
        self.assertEqual(completed.stdout.strip(), identity.context(self.env)['display_version'])
        workflow = (Path(identity.__file__).resolve().parents[1]/'.github/workflows/build.yml').read_text()
        self.assertIn('Rust-Duty-${{ steps.identity.outputs.label }}-Windows-x64', workflow)
        self.assertIn('Rust-Duty-${{ steps.identity.outputs.label }}-Linux-x64', workflow)
        self.assertIn("'!aella/release-channel'", workflow)
        self.assertIn('contents: read', workflow)


if __name__ == '__main__':
    unittest.main()
