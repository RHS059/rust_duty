"""Fresh compact evidence wiring; no claim that native captures pass."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class CalibratedFeedbackWorkflowTests(unittest.TestCase):
    def test_bounded_read_only_caller_reuses_existing_renderer_checks(self):
        caller = yaml.load((ROOT / '.github/workflows/calibrated-presentation-feedback.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(caller['permissions'], {'contents': 'read'})
        self.assertEqual(caller['jobs'], {'renderer-evidence': {'uses': './.github/workflows/wgpu-renderer-contract.yml'}})
        self.assertEqual(caller['concurrency'], {'group': 'calibrated-native-feedback-${{ github.ref }}', 'cancel-in-progress': 'false'})
        self.assertEqual(set(caller['on']), {'push', 'workflow_dispatch'})
        self.assertEqual(caller['on']['push']['branches'], ['main'])
        self.assertIn('tools/run_calibrated_presentation.py', caller['on']['push']['paths'])
        self.assertNotIn('windows-source-bound-recovery', str(caller))
        self.assertNotIn('build.yml', str(caller))

    def test_compact_raw_output_preserves_the_full_packet_and_failure_evidence(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/wgpu-renderer-contract.yml').read_text())
        steps = workflow['jobs']['game-ui-gl-contract']['steps']
        uploads = {s['with']['name']: s for s in steps if s.get('uses') == 'actions/upload-artifact@v4'}
        full = uploads['calibrated-static-presentation-attempt-${{ github.run_attempt }}']
        raw = uploads['calibrated-static-raw-attempt-${{ github.run_attempt }}']
        self.assertEqual(full['with']['path'], 'evidence/calibrated-static/')
        self.assertEqual(raw['with']['path'].splitlines(), [
            'evidence/calibrated-static/captures/', 'evidence/calibrated-static/logs/',
            'evidence/calibrated-static/summary.json', 'evidence/calibrated-static/input-manifest.json',
            'evidence/calibrated-static/calibration-settings.cfg'])
        self.assertEqual(full['if'], 'always()')
        self.assertEqual(raw['if'], "always() && steps.calibrated-raw-budget.outcome == 'success'")
        budget = next(s for s in steps if s.get('id') == 'calibrated-raw-budget')
        self.assertEqual(budget['if'], 'always()')
        self.assertIn('total > 24 * 1024 * 1024', budget['run'])
        for step in (full, raw):
            self.assertEqual(step['with']['if-no-files-found'], 'error')
            self.assertNotIn('continue-on-error', step)
        self.assertFalse(any('download-artifact' in str(step.get('uses', '')) for step in steps))
        runner = next(s for s in steps if 'run_calibrated_presentation.py' in s.get('run', ''))
        self.assertLess(steps.index(runner), steps.index(full))
        self.assertLess(steps.index(full), steps.index(raw))

    def test_capture_neutrality_uses_same_pinned_runtime_and_retains_failures(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/wgpu-renderer-contract.yml').read_text())
        steps = workflow['jobs']['game-ui-gl-contract']['steps']
        build = next(s for s in steps if s.get('id') == 'gl-fixtures-build')
        stage = next(s for s in steps if s.get('id') == 'gl-runtime-stage')
        run = next(s for s in steps if 'run_windows_gl_capture_contract.py' in s.get('run', ''))
        upload = next(s for s in steps if s.get('with', {}).get('name', '').startswith('gl-capture-neutrality-'))
        self.assertIn('--example legacy_capture_contract', build['run'])
        self.assertIn('--example game_ui_contract', build['run'])
        self.assertIn('evidence/game-ui-gl-runtime', stage['run'])
        self.assertIn('--runtime evidence/game-ui-gl-runtime', run['run'])
        self.assertIn('--timeout 180', run['run'])
        self.assertEqual(run['if'], "${{ !cancelled() && steps.gl-fixtures-build.outcome == 'success' && steps.gl-runtime-stage.outcome == 'success' }}")
        # This regression does not suppress earlier UI/calibration evidence.
        calibrated = next(s for s in steps if 'run_calibrated_presentation.py' in s.get('run', ''))
        self.assertLess(steps.index(calibrated), steps.index(run))
        self.assertLess(steps.index(run), steps.index(upload))
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        self.assertEqual(upload['with']['path'].splitlines(), [
            'evidence/legacy-capture-contract/captures/',
            'evidence/legacy-capture-contract/process/',
            'evidence/legacy-capture-contract/summary.json',
            'evidence/legacy-capture-contract/runtime/staging-receipt.json'])
        for step in (run, upload):
            self.assertNotIn('continue-on-error', step)
        caller = yaml.load((ROOT / '.github/workflows/calibrated-presentation-feedback.yml').read_text(), Loader=yaml.BaseLoader)
        for path in ('examples/legacy_capture_contract.rs', 'tools/run_windows_gl_capture_contract.py',
                     'tools/test_windows_gl_capture_contract.py'):
            self.assertIn(path, caller['on']['push']['paths'])


if __name__ == '__main__':
    unittest.main()
