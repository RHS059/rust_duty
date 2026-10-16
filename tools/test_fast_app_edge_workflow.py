"""Wiring guards for early receipt feedback; not native Windows/game evidence.

These run in the authoritative full Python suite, which already has PyYAML.
The fast lane itself needs only standard-library Python and the existing Pillow
pin required by the complete app-edge PNG receipt tests.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class FastAppEdgeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (ROOT / '.github/workflows/app-edge-receipts.yml').read_text(encoding='utf-8')
        cls.workflow = yaml.load(cls.body, Loader=yaml.BaseLoader)
        cls.job = cls.workflow['jobs']['receipts']
        cls.steps = cls.job['steps']
        cls.test_step = cls.steps[-1]

    def test_triggers_cover_checkout_contracts_without_base_branch_bypass(self):
        events = self.workflow['on']
        self.assertEqual(set(events), {'pull_request', 'push', 'workflow_dispatch'})
        self.assertEqual(set(events['pull_request']), {'paths'})
        self.assertEqual(events['push']['branches'],
                         ['main', 'aella/**', 'halcyon/**', '!aella/release-channel'])
        paths = ['.github/workflows/app-edge-receipts.yml', '.gitattributes',
                 '**/*.rs', 'tools/**', 'assets/animations.cfg']
        self.assertEqual(events['pull_request']['paths'], paths)
        self.assertEqual(events['push']['paths'], paths)

    def test_independent_read_only_windows_job_keeps_failures_fatal(self):
        self.assertEqual(set(self.workflow['jobs']), {'receipts'})
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(self.job['runs-on'], 'windows-latest')
        self.assertEqual(self.job['timeout-minutes'], '10')
        self.assertEqual(self.workflow['concurrency'], {
            'group': 'app-edge-receipts-${{ github.event_name }}-${{ github.ref }}',
            'cancel-in-progress': "${{ github.ref != 'refs/heads/main' }}"})
        for forbidden in ('needs', 'if', 'continue-on-error', 'uses', 'strategy'):
            self.assertNotIn(forbidden, self.job)
        for step in self.steps:
            self.assertNotIn('if', step)
            self.assertNotIn('continue-on-error', step)

    def test_only_checkout_python_and_existing_png_dependency_are_needed(self):
        self.assertFalse(Path(__file__).match('test_app_edge*.py'))
        self.assertEqual(len(self.steps), 4)
        self.assertEqual(self.steps[0], {
            'uses': 'actions/checkout@v4', 'with': {'persist-credentials': 'false'}})
        self.assertEqual(self.steps[1], {
            'uses': 'actions/setup-python@v5', 'with': {'python-version': '3.12'}})
        self.assertEqual(self.steps[2]['run'],
                         'python -m pip install --only-binary=:all: Pillow==11.3.0')
        for step in self.steps[2:]:
            self.assertEqual(step['working-directory'], '${{ github.workspace }}')
        self.assertEqual(self.test_step['shell'], 'python')

    def test_checkout_bytes_console_utf8_and_real_locale_temp_are_preserved(self):
        self.assertEqual(self.job['env'], {
            'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.autocrlf',
            'GIT_CONFIG_VALUE_0': 'false', 'PYTHONIOENCODING': 'utf-8',
            'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertNotIn('env', self.workflow)
        self.assertTrue(all('env' not in step for step in self.steps))

    def run_discovery(self, files):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tools').mkdir()
            for name, content in files.items():
                (root / 'tools' / name).write_text(content, encoding='utf-8')
            # Execute the exact workflow Python body, from its declared checkout cwd.
            script = root / 'workflow-step.py'
            script.write_text(self.test_step['run'], encoding='utf-8')
            return subprocess.run([sys.executable, str(script)], cwd=root,
                                  env=dict(os.environ, PYTHONIOENCODING='utf-8',
                                           PYTHONDONTWRITEBYTECODE='1'),
                                  capture_output=True, text=True, encoding='utf-8',
                                  check=False, timeout=20)

    def test_dynamic_discovery_includes_new_app_edge_files_and_ignores_unrelated_tests(self):
        passed = 'import unittest\nclass Case(unittest.TestCase):\n def test_ok(self): pass\n'
        result = self.run_discovery({
            'test_app_edges.py': passed,
            'test_app_edge_future_receipt.py': passed,
            'test_app_edge_canonical_fixture_paths.py': passed,
            'test_unrelated.py': 'raise AssertionError("Outside the early lane")\n'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Ran 3 tests', result.stderr)

    def test_real_test_failures_import_errors_and_empty_discovery_fail_the_step(self):
        cases = ({},
                 {'test_app_edge_receipts.py': 'raise ImportError("fixture missing")\n'},
                 {'test_app_edge_receipts.py':
                  'import unittest\nclass Case(unittest.TestCase):\n'
                  ' def test_bad(self): self.fail("receipt rejected")\n'})
        for files in cases:
            with self.subTest(files=list(files)):
                result = self.run_discovery(files)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
