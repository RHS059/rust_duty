import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml
import check_historical_pair_admission as admission

ROOT = Path(__file__).resolve().parents[1]


class HistoricalPairAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Source Fixture')
        self.git('config', 'user.email', 'source@example.invalid')
        (self.root / 'src').mkdir()
        (self.root / 'src/main.rs').write_bytes(b'fn main() {}\n')
        (self.root / 'Cargo.toml').write_bytes(b'[package]\n')
        self.commit()
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop('GITHUB_SHA', None)
        self.paths = patch.object(admission.pair, 'PRODUCTION_PATHS', ['src', 'Cargo.toml'])
        self.paths.start()
        self.addCleanup(self.paths.stop)
        sources = admission.pair.read_sources(self.root, 'HEAD', admission.pair.PRODUCTION_PATHS)
        self.expected = admission.pair.matrix.canonical_hash(admission.pair.hashes(sources))
        self.manifest = patch.object(admission.pair, 'PRODUCTION_MANIFEST', self.expected)
        self.manifest.start()
        self.addCleanup(self.manifest.stop)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args])

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'source fixture')

    def test_exact_source_admits_but_does_not_claim_validation(self):
        result = admission.inspect(self.root)
        self.assertTrue(result['admitted'])
        self.assertFalse(result['validation_result'])
        self.assertEqual(result['input_count'], 2)
        self.assertEqual(result['production_manifest_sha256'], self.expected)

    def test_committed_change_addition_and_deletion_skip_closed_pair(self):
        for change in ('changed', 'added', 'deleted'):
            with self.subTest(change=change):
                original = self.git('rev-parse', 'HEAD').decode().strip()
                path = self.root / 'src/main.rs'
                if change == 'changed':
                    path.write_bytes(b'fn main() { changed(); }\n')
                elif change == 'added':
                    (self.root / 'src/new.rs').write_bytes(b'new production source\n')
                else:
                    path.unlink()
                self.commit()
                result = admission.inspect(self.root)
                self.assertFalse(result['admitted'])
                self.assertFalse(result['validation_result'])
                self.assertNotEqual(result['production_manifest_sha256'], self.expected)
                self.git('reset', '--hard', original)

    def test_dirty_or_missing_source_and_wrong_ci_identity_fail_without_output(self):
        for change in ('dirty', 'missing', 'wrong-ci'):
            with self.subTest(change=change):
                path = self.root / 'src/main.rs'
                if change == 'dirty':
                    path.write_bytes(b'changed\n')
                elif change == 'missing':
                    path.unlink()
                else:
                    os.environ['GITHUB_SHA'] = '0' * 40
                output = self.root / 'github-output'
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(admission.main(['--root', str(self.root), '--github-output', str(output)]), 2)
                self.assertFalse(output.exists())
                self.git('checkout', '--', 'src/main.rs')
                os.environ.pop('GITHUB_SHA', None)

    def test_cli_writes_exact_boolean_and_retains_required_digest(self):
        output = self.root / 'github-output'
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(admission.main(['--root', str(self.root), '--github-output', str(output)]), 0)
        self.assertEqual(output.read_text(), 'admitted=true\n')
        self.assertIn(self.expected, stdout.getvalue())
        (self.root / 'src/main.rs').write_bytes(b'new revision\n')
        self.commit()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(admission.main(['--root', str(self.root), '--github-output', str(output)]), 0)
        self.assertEqual(output.read_text(), 'admitted=true\nadmitted=false\n')

    def test_all_expensive_jobs_depend_on_explicit_admission(self):
        for filename, native in (('cpu-image-preservation.yml', 'exact-cpu-image-pair'),
                                 ('windows-cpu-profile.yml', 'cpu-sampling')):
            workflow = yaml.load((ROOT / '.github/workflows' / filename).read_text(), Loader=yaml.BaseLoader)
            jobs = workflow['jobs']
            gate = jobs['pair-admission']
            self.assertEqual(gate['runs-on'], 'ubuntu-latest')
            self.assertEqual(gate['timeout-minutes'], '5')
            self.assertEqual(gate['outputs'], {'admitted': '${{ steps.source.outputs.admitted }}'})
            self.assertEqual(gate['env']['PYTHONDONTWRITEBYTECODE'], '1')
            steps = gate['steps']
            check = next(s for s in steps if s.get('id') == 'source')
            self.assertEqual(check['run'], 'python tools/check_historical_pair_admission.py --root . --github-output "$GITHUB_OUTPUT"')
            install = next(s for s in steps if 'pip install Pillow==11.3.0 PyYAML==6.0.3' in s.get('run', ''))
            self.assertLess(steps.index(install), steps.index(check))
            checkout = steps[0]['with']
            self.assertEqual(checkout['persist-credentials'], 'false')
            sparse = set(checkout['sparse-checkout'].splitlines())
            self.assertTrue({'/src/', '/updater/', '/tools/', '/Cargo.lock', '/LICENSE',
                             '/THIRD_PARTY_LICENSES.txt', '/.cargo/', '/rust-toolchain',
                             '/rust-toolchain.toml'} <= sparse)
            self.assertFalse(any('assets' in x for x in sparse))
            for name in ('animation-assets', 'walk-assets', 'ads-assets',
                         'directional-assets', 'jump-assets', native):
                self.assertIn('pair-admission', jobs[name]['needs'])
                self.assertIn("needs.pair-admission.outputs.admitted == 'true'", jobs[name]['if'])
            for name in ('ads-assets', 'directional-assets', 'jump-assets'):
                self.assertIn('walk-assets', jobs[name]['needs'])


if __name__ == '__main__':
    unittest.main()
