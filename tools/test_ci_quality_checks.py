from pathlib import Path
import tempfile
import threading
import unittest
import ci_quality_checks as checks


class QualityChecksTests(unittest.TestCase):
    def test_all_existing_required_commands_remain(self):
        lanes = checks.pipelines('python-test')
        self.assertEqual(len(lanes['python']), 1)
        self.assertEqual([c[1] for c in lanes['game']], ['clippy', 'test', 'build'])
        self.assertEqual([c[1] for c in lanes['updater']], ['fmt', 'clippy', 'test'])
        self.assertIn('--locked', lanes['game'][0])
        self.assertIn('--all-targets', lanes['game'][0])
        self.assertEqual(lanes['game'][0][-2:], ['-D', 'warnings'])
        self.assertIn('--release', lanes['game'][2])

    def test_native_validation_retains_game_and_python_without_duplicate_updater(self):
        lanes = checks.pipelines(native_validation=True)
        self.assertEqual(set(lanes), {'game', 'python'})
        self.assertEqual(lanes['game'], checks.pipelines()['game'])
        self.assertEqual(lanes['python'], checks.pipelines()['python'])

    def test_lanes_are_parallel_but_each_lane_is_ordered(self):
        barrier = threading.Barrier(3, timeout=5)
        seen = []
        def run(command):
            if command[1] == 'first':
                barrier.wait()
            seen.append(tuple(command))
            return 0
        lanes = {name: [[name, 'first'], [name, 'second']] for name in ('a', 'b', 'c')}
        with tempfile.TemporaryDirectory() as folder:
            result = checks.run_all(Path(folder), Path(folder), lanes, run)
            self.assertTrue(result['passed'])
            self.assertEqual(len(result['lanes']), 3)
            self.assertTrue((Path(folder) / 'timings.json').exists())
        for name in lanes:
            self.assertLess(seen.index((name, 'first')), seen.index((name, 'second')))

    def test_failure_blocks_success_and_other_lanes_still_finish(self):
        seen = []
        def run(command):
            seen.append(command[0])
            return 7 if command[0] == 'fail' else 0
        with tempfile.TemporaryDirectory() as folder:
            result = checks.run_all(Path(folder), Path(folder),
                {'bad': [['fail'], ['must-not-build']], 'good': [['check'], ['finish']]}, run)
        self.assertFalse(result['passed'])
        self.assertNotIn('must-not-build', seen)
        self.assertIn('finish', seen)

    def test_spawn_exception_is_recorded_and_fails_closed(self):
        def run(_):
            raise FileNotFoundError('missing executable')
        with tempfile.TemporaryDirectory() as folder:
            result = checks.run_all(Path(folder), Path(folder), {'bad': [['missing']]}, run)
        self.assertFalse(result['passed'])
        self.assertIn('missing executable', result['lanes'][0]['error'])
