"""Static CI contracts; these tests do not establish native rendering success."""
from pathlib import Path
import unittest

import yaml

import dx12_authored_shards as shared


class AuthoredWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / '.github/workflows/wgpu-dx12-authored.yml'
        cls.workflow = yaml.safe_load(cls.path.read_text(encoding='utf-8'))
        cls.jobs = cls.workflow['jobs']

    def steps(self, job):
        return self.jobs[job]['steps']

    def downloads(self, job):
        return [step['with'] for step in self.steps(job)
                if step.get('uses') == 'actions/download-artifact@v4']

    def uploads(self, job):
        return [step for step in self.steps(job)
                if step.get('uses') == 'actions/upload-artifact@v4']

    def test_closed_nine_scenario_matrix_and_measured_budgets(self):
        strategy = self.jobs['authored-capture']['strategy']
        self.assertIs(strategy['fail-fast'], False)
        self.assertEqual(strategy['max-parallel'], 4)
        expected = [{'scenario': name, **{key: value for key, value in profile.items() if key != 'expected_frames'}}
                    for name, profile in shared.PROFILES.items()]
        self.assertEqual(strategy['matrix'], {'include': expected})
        self.assertEqual(sum(profile['expected_frames'] or 0 for profile in shared.PROFILES.values()), 3347)
        self.assertEqual(self.jobs['authored-capture']['timeout-minutes'], '${{ matrix.job_timeout_minutes }}')

    def test_single_dual_runtime_build_and_unchanged_binaries(self):
        builds = [(job, step['run']) for job in self.jobs for step in self.steps(job)
                  if 'cargo build' in step.get('run', '')]
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0][0], 'authored-inputs')
        self.assertEqual(builds[0][1].split(), ['cargo', 'build', '--locked', '--release', '--no-default-features',
                        '--features', 'legacy-macroquad,wgpu-runtime', '--bin', 'vector-range', '--example', 'renderer_contract'])
        executable_upload = self.uploads('authored-inputs')[0]['with']
        self.assertEqual(executable_upload['name'], 'dx12-authored-inputs-attempt-${{ github.run_attempt }}')
        self.assertEqual(executable_upload['if-no-files-found'], 'error')
        self.assertEqual(executable_upload['path'].splitlines(), [
            'target/release/vector-range.exe', 'target/release/examples/renderer_contract.exe',
            'evidence/authored-inputs/input-manifest.json', 'evidence/authored-inputs/historical-manifest.json'])
        for job in ('authored-capture', 'authored-aggregate'):
            self.assertIn({'name': executable_upload['name'], 'path': '.'}, self.downloads(job))

    def test_every_job_uses_same_run_validated_assets(self):
        for job in self.jobs:
            downloads = self.downloads(job)
            for name in ('reload', 'walk', 'ads', 'directional', 'jump'):
                self.assertIn({'name': f'generated-{name}-runtime', 'path': f'assets/{name}'}, downloads)
            materialize = [s['run'] for s in self.steps(job) if 'package_game.py materialize' in s.get('run', '')]
            self.assertEqual(len(materialize), 1)
            self.assertIn('--include-walk --include-ads --include-directional --include-jump --require-generated', materialize[0])
            for download in downloads:
                self.assertTrue(set(download) <= {'name', 'pattern', 'path', 'merge-multiple'})
                self.assertFalse(any(key in download for key in ('repository', 'run-id', 'github-token')))

    def test_historical_downloads_remain_exact_same_attempt(self):
        names = ['gameplay-jump', 'gameplay-reload', 'gameplay-walk', 'gameplay-ads', 'ads-placement', 'layered-locomotion', 'reload-return']
        folders = ['jump-gameplay', 'reload-gameplay', 'walk-gameplay', 'ads-gameplay', 'ads-placement', 'layered', 'reload-return']
        expected = [{'name': f'native-{name}-evidence-attempt-${{{{ github.run_attempt }}}}', 'path': f'evidence/legacy/{folder}'}
                    for name, folder in zip(names, folders)]
        for job in ('authored-inputs', 'authored-aggregate'):
            actual = [d for d in self.downloads(job) if d.get('name', '').startswith('native-')]
            self.assertEqual(actual, expected)
        self.assertFalse(any(d.get('name', '').startswith('native-') for d in self.downloads('authored-capture')))

    def test_failed_and_canceled_shards_cannot_skip_aggregate(self):
        self.assertEqual(self.jobs['authored-capture']['needs'], 'authored-inputs')
        aggregate = self.jobs['authored-aggregate']
        self.assertEqual(aggregate['needs'], ['authored-inputs', 'authored-capture'])
        self.assertEqual(aggregate['if'], 'always()')
        self.assertEqual(aggregate['timeout-minutes'], 60)
        steps = self.steps('authored-aggregate')
        downloads = [step for step in steps if step.get('with', {}).get('pattern')]
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0]['if'], 'always()')
        self.assertEqual(downloads[0]['with'], {
            'pattern': 'dx12-authored-shard-*-evidence-attempt-${{ github.run_attempt }}',
            'path': 'evidence/downloaded-authored-shards', 'merge-multiple': False})
        runner = next(step for step in steps if 'tools/aggregate_dx12_authored.py' in step.get('run', ''))
        self.assertEqual(runner['if'], 'always()')
        self.assertEqual(runner['timeout-minutes'], 45)
        self.assertIn('--timeout 900 --run-timeout 2400', runner['run'])
        self.assertIn('--historical-manifest evidence/authored-inputs/historical-manifest.json', runner['run'])

    def test_scoped_execution_and_always_artifacts(self):
        steps = self.steps('authored-capture')
        runner = next(step for step in steps if 'tools/run_dx12_authored_shard.py run' in step.get('run', ''))
        self.assertEqual(runner['timeout-minutes'], '${{ matrix.step_timeout_minutes }}')
        for flag in ('--scenario ${{ matrix.scenario }}', '--timeout ${{ matrix.capture_timeout_seconds }}',
                     '--run-timeout ${{ matrix.run_timeout_seconds }}'):
            self.assertIn(flag, runner['run'])
        for job in ('authored-capture', 'authored-aggregate'):
            for step in self.uploads(job):
                self.assertEqual(step['if'], 'always()')
                self.assertEqual(step['with']['retention-days'], 7)
        self.assertEqual(self.uploads('authored-aggregate')[0]['with']['name'],
                         'dx12-authored-evidence-attempt-${{ github.run_attempt }}')

    def test_all_existing_and_new_suites_remain_selected(self):
        steps = self.steps('authored-inputs')
        test = next(step for step in steps if 'python -m unittest' in step.get('run', ''))
        self.assertEqual(test['env'], {'PYTHONPATH': 'tools'})
        self.assertEqual(test['run'].split()[4:], [
            'test_dx12_authored', 'test_dx12_capture_progress', 'test_dx12_authored_adversarial',
            'test_dx12_authored_shards', 'test_run_dx12_authored_shard', 'test_aggregate_dx12_authored',
            'test_dx12_authored_workflow'])
        self.assertTrue(any(step.get('run') == 'python -m pip install PyYAML==6.0.3' for step in steps))

    def test_no_relaxed_failures_or_permissions_or_release_actions(self):
        self.assertEqual(set(self.jobs), {'authored-inputs', 'authored-capture', 'authored-aggregate'})
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        for job in self.jobs.values():
            self.assertEqual(job['runs-on'], 'windows-latest')
            self.assertNotIn('continue-on-error', job)
            self.assertNotIn('permissions', job)
            for step in job['steps']:
                self.assertNotIn('continue-on-error', step)
                if step.get('uses') == 'actions/checkout@v4':
                    self.assertEqual(step['with'], {'persist-credentials': False})
                if step.get('uses') == 'actions/upload-artifact@v4':
                    self.assertTrue(step['with']['name'].startswith('dx12-authored-'))
        text = self.path.read_text(encoding='utf-8')
        self.assertNotIn('run_dx12_authored.py\n', text)
        self.assertNotIn('workflow_dispatch', text)


if __name__ == '__main__':
    unittest.main()
