"""Static guards for one asset-free Windows integration job; no native execution."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'aella/wgpu-1080p-diagnostics'


class GpuSessionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (ROOT / '.github/workflows/gpu-session-contract.yml').read_text()
        cls.workflow = yaml.load(cls.body, Loader=yaml.BaseLoader)
        cls.job = cls.workflow['jobs']['windowed-gpu-session']
        cls.steps = cls.job['steps']

    def test_single_bounded_windows_push_without_dispatch_merge_or_cancellation(self):
        self.assertEqual(set(self.workflow['on']), {'push'})
        self.assertEqual(self.workflow['on']['push']['branches'], [BRANCH])
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(self.workflow['concurrency'], {
            'group': 'gpu-session-contract-${{ github.ref }}', 'cancel-in-progress': 'false'})
        self.assertEqual(set(self.workflow['jobs']), {'windowed-gpu-session'})
        self.assertEqual(self.job['runs-on'], 'windows-latest')
        self.assertEqual(self.job['timeout-minutes'], '30')
        self.assertIn("github.ref == 'refs/heads/" + BRANCH + "'", self.job['if'])
        for forbidden in ('workflow_dispatch', 'pull_request:', 'secrets.', 'continue-on-error',
                          'workflow_call', 'strategy:', 'merge-pull-request', 'gh pr merge'):
            self.assertNotIn(forbidden, self.body)

    def test_all_source_bound_tools_trigger_native_revalidation(self):
        # Includes transitive process/atomic-output helpers and any future tools
        # that enter source_binding(), not only the top-level runner/readers.
        self.assertIn('tools/**', self.workflow['on']['push']['paths'])

    def test_checkout_contains_compile_sources_but_no_optional_or_private_assets(self):
        checkout = next(step['with'] for step in self.steps if step.get('uses') == 'actions/checkout@v4')
        self.assertEqual(checkout['persist-credentials'], 'false')
        self.assertEqual(checkout['sparse-checkout-cone-mode'], 'false')
        paths = set(checkout['sparse-checkout'].splitlines())
        self.assertTrue({'/Cargo.toml', '/Cargo.lock', '/build.rs', '/build_number.rs',
                         '/rust-toolchain.toml', '/.cargo/', '/src/', '/updater/', '/tools/',
                         '/examples/gpu_session_contract.rs'} <= paths)
        for path in paths:
            self.assertNotIn('/assets', path)
            self.assertNotIn('uploaded_references', path)
        self.assertEqual(self.workflow['env'], {'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': 'core.autocrlf', 'GIT_CONFIG_VALUE_0': 'false'})
        self.assertNotIn('actions/download-artifact', self.body)

    def test_existing_strict_guards_precede_exact_source_runner(self):
        guards = next(step for step in self.steps if 'python -m unittest' in step.get('run', ''))
        execution = next(step for step in self.steps if 'run_gpu_session_contract.py --root' in step.get('run', ''))
        self.assertLess(self.steps.index(guards), self.steps.index(execution))
        for name in ('test_gpu_session_contract', 'test_summarize_gpu_timing',
                     'test_dx12_contract_process', 'test_gpu_session_workflow',
                     'test_summarize_cpu_encode_detail', 'test_staging_encode_detail', 'test_cpu_encode_substages', 'test_cpu_encode_detail_source'):
            self.assertIn(name, guards['run'])
        self.assertEqual(execution['timeout-minutes'], '24')
        for argument in ('--root .', '--evidence evidence/gpu-session', '--timeout 90', '--build-timeout 1200'):
            self.assertIn(argument, execution['run'])
        for forbidden in ('--renderer=vulkan', '--renderer=gl', '--disable-validation', 'Start-Process'):
            self.assertNotIn(forbidden, self.body)

    def test_failed_process_evidence_is_retained_without_binaries_or_assets(self):
        upload = next(step for step in self.steps if step.get('uses') == 'actions/upload-artifact@v4')
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['retention-days'], '7')
        self.assertEqual(upload['with']['include-hidden-files'], 'true')
        self.assertEqual(upload['with']['path'].splitlines(), [
            'evidence/gpu-session/**', '!evidence/gpu-session/target/**',
            '!evidence/gpu-session/**/*.exe', '!evidence/gpu-session/**/*.dll',
            '!evidence/gpu-session/**/assets/**'])


if __name__ == '__main__':
    unittest.main()
