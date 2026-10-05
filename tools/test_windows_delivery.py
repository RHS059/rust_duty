"""Windows publication gates and retained non-distribution native coverage."""
import copy
from pathlib import Path
import unittest
import select_windows_build as selection

ROOT = Path(__file__).resolve().parents[1]


class WindowsSelectionTests(unittest.TestCase):
    def setUp(self):
        self.run = {'id': 42, 'head_sha': 'a'*40, 'event': 'push', 'status': 'in_progress',
                    'conclusion': None, 'html_url': 'https://github.com/example/run/42',
                    'head_repository': {'full_name': selection.REPOSITORY}, 'run_attempt': 2}
        self.jobs = [{'id': 71, 'name': 'windows-latest', 'status': 'completed',
                      'conclusion': 'success', 'html_url': 'https://github.com/example/job/71'},
                     {'id': 72, 'name': 'native-validation / validate', 'status': 'in_progress',
                      'conclusion': None}]

    def read(self, endpoint):
        return {'jobs': self.jobs} if '/jobs?' in endpoint else {'workflow_runs': [self.run]}

    def test_windows_ready_does_not_wait_for_linux_or_workflow_success(self):
        for conclusion in (None, 'failure', 'success'):
            self.run['conclusion'] = conclusion
            result = selection.select('game', 'a'*40, self.read)
            self.assertEqual(result['windows_job_id'], 71)
            self.assertEqual(result['run_attempt'], 2)

    def test_wrong_source_event_repository_or_cancelled_run_rejected(self):
        for field, bad in [('head_sha', 'b'*40), ('event', 'pull_request'),
                           ('head_repository', {'full_name': 'other/repo'}), ('conclusion', 'cancelled')]:
            old = copy.deepcopy(self.run)
            self.run[field] = bad
            with self.assertRaises(ValueError): selection.select('game', 'a'*40, self.read)
            self.run = old

    def test_windows_failed_running_absent_or_ambiguous_fails_closed(self):
        original = copy.deepcopy(self.jobs)
        for change in ('failed', 'running', 'missing', 'duplicate'):
            self.jobs = copy.deepcopy(original)
            if change == 'failed': self.jobs[0]['conclusion'] = 'failure'
            elif change == 'running': self.jobs[0]['status'] = 'in_progress'
            elif change == 'missing': self.jobs.pop(0)
            else: self.jobs.append(copy.deepcopy(self.jobs[0]))
            with self.assertRaises(ValueError): selection.select('game', 'a'*40, self.read)

    def test_launcher_requires_its_own_successful_windows_job(self):
        with self.assertRaises(ValueError): selection.select('launcher', 'a'*40, self.read)
        self.jobs[0]['name'] = 'Updater - windows-latest'
        self.assertEqual(selection.select('launcher', 'a'*40, self.read)['run_id'], 42)


class WindowsWorkflowTests(unittest.TestCase):
    def test_windows_build_is_independent_of_native_validation(self):
        text = (ROOT/'.github/workflows/build.yml').read_text()
        build = text.split('  build:\n')[1].split('  publish-game-update:')[0]
        self.assertIn('runs-on: windows-latest', build)
        self.assertNotIn('native-validation', build)
        self.assertNotIn('Linux', build)
        self.assertIn('vector-range-windows-x64', build)
        native = (ROOT/'.github/workflows/native-validation.yml').read_text()
        self.assertIn('runs-on: ubuntu-latest', native)
        for capture in ('verify_jump_capture', 'verify_gameplay_capture', 'verify_gameplay_walk_capture',
                        'verify_gameplay_ads_capture', 'verify_ads_placement_capture',
                        'verify_layered_locomotion_capture', 'verify_reload_return_capture', 'verify_lighting_capture'):
            self.assertIn(capture, native)
        self.assertNotIn('package_game.py stage', native)
        self.assertNotIn('path: dist/game/', native)
        self.assertNotIn('dist/game', native)

    def test_publisher_and_launcher_only_deliver_windows(self):
        for workflow in ('publish-updates', 'updater'):
            text = (ROOT/f'.github/workflows/{workflow}.yml').read_text()
            for token in ('vector-range-linux', 'launcher-linux', 'unknown-linux-gnu', 'windows linux'):
                self.assertNotIn(token, text)
        text = (ROOT/'.github/workflows/publish-updates.yml').read_text()
        self.assertIn('tools/select_windows_build.py', text)
        self.assertIn('tools/smoke_live_update.py', text)
        self.assertIn('tools/smoke_game_update.py', text)


if __name__ == '__main__': unittest.main()
