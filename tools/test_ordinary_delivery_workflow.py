"""Ordinary delivery wiring only; never runs exporters, renderers, or native code."""
from pathlib import Path
import unittest

import yaml

import ci_quality_checks

ROOT = Path(__file__).resolve().parents[1]
MATERIALIZE = ('python tools/package_game.py materialize --root . --include-walk '
               '--include-ads --include-directional --include-jump --require-generated')


def load(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(encoding='utf-8'),
                     Loader=yaml.BaseLoader)


def assert_ordinary_closure(case, build, linux):
    case.assertEqual(set(build['jobs']), {'changes', 'native-validation', 'build', 'publish-game-update'})
    case.assertEqual(build['jobs']['native-validation']['uses'], './.github/workflows/native-validation.yml')
    for name in ('native-validation', 'build'):
        case.assertEqual(build['jobs'][name]['needs'], ['changes'])
        case.assertNotIn('continue-on-error', build['jobs'][name])
    case.assertEqual(set(linux['jobs']), {'validate'})
    for job in (build['jobs']['build'], linux['jobs']['validate']):
        commands = [step.get('run', '') for step in job['steps']]
        case.assertIn(MATERIALIZE, commands)
        case.assertTrue(any('tools/ci_quality_checks.py' in command for command in commands))
        for step in job['steps']:
            case.assertNotIn('continue-on-error', step)
            case.assertNotEqual(step.get('uses'), 'actions/download-artifact@v4')
            command = step.get('run', '')
            for forbidden in ('--sampler', '--verify-sampler', 'sample_viewmodel_clip',
                              '--capture', 'run_dx12_', 'run_windows_same_platform_return',
                              'build_blender_assets.py', 'build_walk_assets.py',
                              'build_ads_assets.py', 'build_directional_assets.py', 'build_jump_assets.py'):
                case.assertNotIn(forbidden, command)


class OrdinaryDeliveryWorkflowTests(unittest.TestCase):
    def test_windows_and_linux_consume_committed_runtime_without_proof_jobs(self):
        assert_ordinary_closure(self, load('build.yml'), load('native-validation.yml'))

    def test_capture_or_generator_reintroduction_is_detected(self):
        for command in ('python tools/build_walk_assets.py --sampler unused',
                        'python tools/run_dx12_smoke.py --root .',
                        './vector-range --capture-sequence=gameplay-reload'):
            build, linux = load('build.yml'), load('native-validation.yml')
            linux['jobs']['validate']['steps'].append({'run': command})
            with self.subTest(command=command), self.assertRaises(AssertionError):
                assert_ordinary_closure(self, build, linux)
        build, linux = load('build.yml'), load('native-validation.yml')
        build['jobs']['animation-assets'] = {'uses': './.github/workflows/blender-assets.yml'}
        with self.assertRaises(AssertionError):
            assert_ordinary_closure(self, build, linux)

    def test_existing_compile_test_and_packaging_commands_remain_fatal(self):
        lanes = ci_quality_checks.pipelines('python')
        self.assertEqual(lanes['game'], [
            ['cargo', 'clippy', '--locked', '--all-targets', '--', '-D', 'warnings'],
            ['cargo', 'test', '--locked'],
            ['cargo', 'build', '--locked', '--release', '--features', 'wgpu-runtime'],
        ])
        self.assertEqual(lanes['python'], [['python', '-m', 'unittest', 'discover', '-s', 'tools', '-p', 'test_*.py', '-v']])
        self.assertEqual(ci_quality_checks.pipelines(native_validation=True)['game'], lanes['game'])
        build = load('build.yml')['jobs']['build']
        commands = [step.get('run', '') for step in build['steps']]
        quality = commands.index('python tools/ci_quality_checks.py')
        stage = commands.index('python tools/package_game.py stage --root . --binary target/release/vector-range.exe --output dist/game --require-generated')
        self.assertLess(quality, stage)
        self.assertIn('git diff --exit-code -- build.rs src tests examples benches', commands)

    def test_release_permissions_and_concurrency_are_unchanged(self):
        build = load('build.yml')
        self.assertEqual(build['permissions'], {'contents': 'read'})
        publisher = build['jobs']['publish-game-update']
        self.assertEqual(publisher['needs'], ['build'])
        self.assertIn("github.ref == 'refs/heads/aella/automatic-game-updates-r1'", publisher['if'])
        self.assertEqual(publisher['permissions'], {'contents': 'write'})
        self.assertEqual(publisher['concurrency'], {'group': 'rust-duty-release-channel', 'cancel-in-progress': 'false'})
        self.assertEqual(build['on']['workflow_dispatch'], '')
        self.assertNotIn('inputs', build['on'])


if __name__ == '__main__':
    unittest.main()
