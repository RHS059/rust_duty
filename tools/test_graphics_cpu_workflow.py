"""The current native controls reuse only reviewed baseline bytes and keep all gates."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class GraphicsCpuWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (ROOT / '.github/workflows/graphics-cpu-feedback.yml').read_text(encoding='utf-8')
        cls.data = yaml.load(cls.body, Loader=yaml.BaseLoader)
        cls.steps = cls.data['jobs']['validate']['steps']

    def test_current_source_trigger_and_separate_non_canceling_group(self):
        self.assertEqual(set(self.data['on']), {'push'})
        self.assertEqual(self.data['on']['push']['branches'], ['main'])
        for path in ('src/**', 'examples/graphics_cpu_contract.rs', 'tools/run_graphics_cpu_contract.py'):
            self.assertIn(path, self.data['on']['push']['paths'])
        self.assertEqual(self.data['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(self.data['concurrency'], {
            'group': 'graphics-cpu-feedback-${{ github.ref }}', 'cancel-in-progress': 'false'})
        sparse = self.steps[0]['with']['sparse-checkout'].splitlines()
        self.assertIn('/.github/workflows/graphics-cpu-feedback.yml', sparse)
        self.assertNotIn('/assets/', sparse)
        self.assertEqual(self.steps[0]['with']['persist-credentials'], 'false')

    def test_guarded_exact_artifact_and_compiler_precede_single_native_invocation(self):
        guard = next(s for s in self.steps if 'python -m unittest' in s.get('run', ''))
        metadata = next(s for s in self.steps if s.get('uses') == 'actions/github-script@v7')
        provider = next(s for s in self.steps if 'baseline_provider(read_json' in s.get('run', ''))
        download = next(s for s in self.steps if s.get('uses') == 'actions/download-artifact@v4')
        compiler = next(s for s in self.steps if 'rustup toolchain install' in s.get('run', ''))
        native = next(s for s in self.steps if 'python tools/run_graphics_cpu_contract.py' in s.get('run', ''))
        positions = [self.steps.index(s) for s in (guard, metadata, provider, download, compiler, native)]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('artifact_id: 11422371812', metadata['with']['script'])
        self.assertEqual(download['with']['artifact-ids'], '11422371812')
        self.assertEqual(download['with']['run-id'], '37482428571')
        self.assertEqual(download['with']['repository'], 'RHS059/rust_duty')
        self.assertIn('1.99.0-x86_64-pc-windows-msvc --profile minimal', compiler['run'])
        self.assertEqual(native['timeout-minutes'], '30')
        for unwanted in ('continue-on-error', 'workflow_dispatch', '--bin vector-range', 'secrets.'):
            self.assertNotIn(unwanted, self.body)

    def test_failure_artifacts_preserve_sources_pixels_and_receipts(self):
        uploads = [s for s in self.steps if s.get('uses') == 'actions/upload-artifact@v4']
        self.assertEqual(len(uploads), 2)
        self.assertTrue(all(s['if'] == 'always()' and s['with']['include-hidden-files'] == 'true' for s in uploads))
        full, review = [s['with']['path'] for s in uploads]
        self.assertIn('!evidence/graphics-cpu/target/**', full)
        self.assertIn('!evidence/graphics-cpu/temp/**', full)
        for part in ('baseline-provider.json', '*-source/**', 'baseline-original/**',
                     'verifier/**', '*-renderer-contract/**', 'preferences/**', 'windowed-*/**'):
            self.assertIn(part, review)
        self.assertNotIn('*.exe', review)


if __name__ == '__main__':
    unittest.main()
