"""Windows publication gates and retained non-distribution native coverage."""
import copy
from pathlib import Path
import unittest
import json
import tempfile
import select_windows_build as selection

ROOT = Path(__file__).resolve().parents[1]


class WindowsSelectionTests(unittest.TestCase):
    def setUp(self):
        self.run = {'id': 42, 'head_sha': 'a'*40, 'event': 'push', 'status': 'in_progress',
                    'conclusion': None, 'html_url': 'https://github.com/example/run/42',
                    'head_repository': {'full_name': selection.REPOSITORY}, 'run_attempt': 2}
        self.jobs = [{'id': 71, 'name': 'windows-latest', 'status': 'completed',
                      'conclusion': 'success', 'run_attempt': 1, 'html_url': 'https://github.com/example/job/71'},
                     {'id': 72, 'name': 'native-validation / validate', 'status': 'in_progress',
                      'conclusion': None}]

    def read(self, endpoint):
        return {'jobs': self.jobs} if '/jobs?' in endpoint else {'workflow_runs': [self.run]}

    def test_windows_ready_does_not_wait_for_linux_or_workflow_success(self):
        for conclusion in (None, 'failure', 'success'):
            self.run['conclusion'] = conclusion
            result = selection.select('game', 'a'*40, self.read)
            self.assertEqual(result['windows_job_id'], 71)
            self.assertEqual(result['run_attempt'], 1)
            self.assertEqual(result['workflow_run_attempt'], 2)

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

    def test_artifact_must_match_actual_windows_job_attempt(self):
        selected = selection.select('game', 'a'*40, self.read)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'BUILD_IDENTITY.json'
            identity = {'repository': selection.REPOSITORY, 'version': '0.1.11',
                        'display_version': '0.1.11+build.42.1',
                        'source': {'commit': 'a'*40, 'run_id': 42, 'run_attempt': 1}}
            path.write_text(json.dumps(identity))
            selection.verify_game_artifact(directory, selected, '0.1.11')
            for key, bad in [('commit', 'b'*40), ('run_id', 99), ('run_attempt', 2)]:
                changed = copy.deepcopy(identity)
                changed['source'][key] = bad
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError): selection.verify_game_artifact(directory, selected, '0.1.11')

    def test_launcher_requires_its_own_successful_windows_job(self):
        with self.assertRaises(ValueError): selection.select('launcher', 'a'*40, self.read)
        self.jobs[0]['name'] = 'Updater - windows-latest'
        self.assertEqual(selection.select('launcher', 'a'*40, self.read)['run_id'], 42)


if __name__ == '__main__': unittest.main()
