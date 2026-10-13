"""Bounded native staging job and original-source evidence contracts."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = '.github/workflows/staging-buffer-pool.yml'


class StagingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / WORKFLOW).read_text()
        cls.value = yaml.load(cls.text, Loader=yaml.BaseLoader)
        cls.job = cls.value['jobs']['native-staging-pool']
        cls.steps = cls.job['steps']

    def test_bounded_owned_branches_and_read_only_native_job(self):
        self.assertEqual(set(self.value['on']), {'push'})
        branches = ['halcyon/bounded-staging-upload', 'aella/wgpu-1080p-diagnostics']
        self.assertEqual(self.value['on']['push']['branches'], branches)
        for branch in branches:
            self.assertIn("github.ref == 'refs/heads/" + branch + "'", self.job['if'])
        self.assertIn("github.repository == 'RHS059/rust_duty'", self.job['if'])
        self.assertEqual(self.value['permissions'], {'contents': 'read'})
        self.assertEqual(self.value['concurrency']['cancel-in-progress'], 'false')
        self.assertEqual(self.job['runs-on'], 'windows-latest')
        self.assertEqual(self.job['timeout-minutes'], '30')
        self.assertNotIn('continue-on-error', self.text)

    def test_all_bound_inputs_are_materialized_and_trigger_the_job(self):
        checkout = next(s['with'] for s in self.steps if s.get('uses') == 'actions/checkout@v4')
        self.assertEqual(checkout['persist-credentials'], 'false')
        self.assertEqual(checkout['sparse-checkout-cone-mode'], 'false')
        paths = set(checkout['sparse-checkout'].splitlines())
        trigger = set(self.value['on']['push']['paths'])
        inventory = next(line for line in self.text.splitlines() if '$sources = @(git ls-files' in line)
        for name in ('Cargo.toml', 'Cargo.lock', 'build.rs', 'build_number.rs',
                     'rust-toolchain', 'rust-toolchain.toml', 'LICENSE',
                     'THIRD_PARTY_LICENSES.txt', '.gitattributes', WORKFLOW,
                     'tests/fixtures/triangle.vrm', 'tests/fixtures/two_bone_triangle.vrs'):
            self.assertIn('/' + name, paths)
            self.assertIn(name, trigger)
            self.assertIn(name, inventory)
        for name in ('src', 'updater', 'tools', '.cargo'):
            self.assertIn('/' + name + '/', paths)
            self.assertIn(name + '/**', trigger)
            self.assertIn(' ' + name + ' ', inventory)
        self.assertFalse(any(path.startswith('/assets') for path in paths))

    def test_guard_dependencies_and_actual_compiler_precede_rust_execution(self):
        commands = [step.get('run', '') for step in self.steps]
        install = next(i for i, command in enumerate(commands) if 'pip install' in command)
        guards = next(i for i, command in enumerate(commands) if '-m unittest' in command)
        rust = next(i for i, command in enumerate(commands) if 'cargo check' in command)
        self.assertLess(install, guards)
        self.assertLess(guards, rust)
        self.assertIn('PyYAML==6.0.3', commands[install])
        self.assertIn('test_staging_workflow test_staging_encode_detail', commands[guards])
        self.assertEqual(self.value['env']['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertEqual(self.value['env']['RUSTUP_TOOLCHAIN'], '1.99.0')
        self.assertIn("-Pattern '^release: 1\\.99\\.0$'", self.text)
        self.assertIn('Test-Path Env:VR_WEAPON_ASSET', self.text)

    def test_native_execution_binds_binary_and_preserves_failure_evidence(self):
        self.assertIn('& $exe render::upload_cache::staging_tests --nocapture --test-threads=1', self.text)
        self.assertIn("-SimpleMatch -Pattern 'test result: ok. 3 passed; 0 failed; 0 ignored;'", self.text)
        for phrase in ('Test executable changed during native proof',
                       'Test PDB changed during native proof', 'Compiled source changed',
                       'Tested input changed', 'source-before.json', 'source-after.json'):
            self.assertIn(phrase, self.text)
        upload = self.steps[-1]
        self.assertEqual(upload['uses'], 'actions/upload-artifact@v4')
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['id'], 'staging_native_evidence')
        self.assertIn('github.run_attempt', upload['with']['name'])
        self.assertEqual(upload['with']['path'], 'staging-pool-evidence/**')

    def test_pure_frame_filter_excludes_only_the_explicit_hardware_contract(self):
        step = next(step for step in self.steps
                    if step.get('name') == 'Run pure staging, destination and frame contracts')
        command = step['run']
        native = 'render::frame::tests::native_depth_slices_preserve_clip_planes_and_ordered_fades'
        self.assertIn('--lib $filter -- --skip ' + native + ' 2>&1', command)
        self.assertEqual(command.count('--skip'), 1)
        self.assertNotIn('--ignored', command)
        self.assertIn("'render::frame::tests'", command)
        self.assertIn("-Pattern 'test result: ok\\. [1-9][0-9]* passed; 0 failed; 0 ignored;'", command)
        self.assertIn('if ($LASTEXITCODE -ne 0)', command)
        source = (ROOT / 'src/render/frame.rs').read_text()
        self.assertRegex(source, r'#\[ignore = "explicit native viewport-depth clipping/order/alpha contract"\]\s+'
                         r'fn native_depth_slices_preserve_clip_planes_and_ordered_fades\(')


if __name__ == '__main__':
    unittest.main()
