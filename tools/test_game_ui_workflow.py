"""Source-level wiring guards; actual UI acceptance requires Windows execution."""
from pathlib import Path
import unittest
import yaml


class GameUiWorkflowTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/wgpu-renderer-contract.yml'
        self.workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
        self.job = self.workflow['jobs']['game-ui-contract']

    def test_independent_windows_job_and_read_only_permissions(self):
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(self.job['runs-on'], 'windows-latest')
        self.assertNotIn('needs', self.job)
        self.assertEqual(self.job['timeout-minutes'], 30)
        checkout = self.job['steps'][0]
        self.assertIs(checkout['with']['persist-credentials'], False)

    def test_actual_current_source_build_and_native_verifier(self):
        commands = [s['run'] for s in self.job['steps'] if 'run' in s]
        self.assertIn('cargo build --locked --no-default-features --features wgpu-runtime --example game_ui_contract', commands)
        self.assertIn('python -m unittest -v test_dx12_game_ui_fixture', commands)
        native = next(x for x in commands if 'tools/run_dx12_game_ui_fixture.py' in x)
        self.assertIn('--executable target/debug/examples/game_ui_contract.exe', native)
        self.assertIn('--timeout 600', native)
        self.assertFalse(any('continue-on-error' in s for s in self.job['steps']))

    def test_retains_both_pixels_and_process_evidence_on_failure(self):
        upload = self.job['steps'][-1]
        self.assertEqual(upload['uses'], 'actions/upload-artifact@v4')
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        self.assertEqual(set(upload['with']['path'].split()), {'evidence/game-ui/', 'evidence/game-ui-run/'})

    def test_gl_uses_pinned_runtime_and_same_production_example(self):
        job = self.workflow['jobs']['game-ui-gl-contract']
        self.assertEqual(job['runs-on'], 'windows-latest')
        self.assertNotIn('needs', job)
        commands = [step.get('run', '') for step in job['steps']]
        self.assertIn('cargo build --locked --no-default-features --features legacy-macroquad,wgpu-runtime --example game_ui_contract --example legacy_capture_contract --bin vector-range', commands)
        self.assertIn('python -m pip install Pillow==11.3.0 PyYAML==6.0.3', commands)
        guards = next(command for command in commands if 'python -m unittest' in command)
        self.assertIn('test_game_ui_workflow', guards.split())
        self.assertTrue(any('stage_windows_gl_reference.ps1 -Manifest tools/windows_gl_reference_lock.json' in command for command in commands))
        native = next(command for command in commands if 'tools/run_windows_gl_game_ui.py' in command)
        self.assertIn('--runtime evidence/game-ui-gl-runtime', native)
        self.assertIn('--manifest tools/windows_gl_reference_lock.json', native)
        self.assertIn('--timeout 600', native)
        self.assertFalse(any('continue-on-error' in step for step in job['steps']))
        upload = next(step for step in job['steps'] if step.get('with', {}).get('name') == 'gl-game-ui-contract-attempt-${{ github.run_attempt }}')
        self.assertEqual(upload['if'], 'always()')
        self.assertNotIn('*.dll', upload['with']['path'])


    def test_static_calibration_reuses_current_dual_build_and_pinned_runtime(self):
        steps = self.workflow['jobs']['game-ui-gl-contract']['steps']
        builds = [step['run'] for step in steps if 'cargo build' in step.get('run', '')]
        self.assertEqual(len(builds), 1)
        self.assertIn('--example game_ui_contract --example legacy_capture_contract --bin vector-range', builds[0])
        runner = next(step for step in steps if 'run_calibrated_presentation.py' in step.get('run', ''))
        self.assertIn('--executable target/debug/vector-range.exe --root .', runner['run'])
        self.assertIn('--runtime evidence/game-ui-gl-runtime', runner['run'])
        self.assertIn('--evidence evidence/calibrated-static --timeout 180', runner['run'])
        self.assertNotIn('continue-on-error', runner)
        ui = next(step for step in steps if 'run_windows_gl_game_ui.py' in step.get('run', ''))
        self.assertLess(steps.index(ui), steps.index(runner))
        archive = next(step for step in steps if step.get('with', {}).get('name') == 'calibrated-static-presentation-attempt-${{ github.run_attempt }}')
        self.assertEqual(archive['if'], 'always()')
        self.assertEqual(archive['with']['name'], 'calibrated-static-presentation-attempt-${{ github.run_attempt }}')
        self.assertEqual(archive['with']['path'], 'evidence/calibrated-static/')
        self.assertEqual(archive['with']['if-no-files-found'], 'error')

if __name__ == '__main__':
    unittest.main()
