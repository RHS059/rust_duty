import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import run_preflight_case as runner


class Child:
    def __init__(self, done):
        self.done = done
        self.pid = 12345
        self.killed = False
    def poll(self): return 0 if self.done else None
    def wait(self, timeout): return 0
    def kill(self): self.killed = True


class PreflightRunnerTests(unittest.TestCase):
    def run_case(self, done):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        child = Child(done)
        with mock.patch.object(runner, '__file__', str(root/'tools/run_preflight_case.py')), \
             mock.patch.object(runner.sys, 'argv', ['run_preflight_case.py', '--case', 'full']), \
             mock.patch.object(runner.subprocess, 'Popen', return_value=child) as spawn, \
             mock.patch.object(runner.subprocess, 'run') as terminate, \
             mock.patch.object(runner.time, 'monotonic', side_effect=[0, 1] if done else [0, 661, 662]), \
             mock.patch.dict(os.environ, {}, clear=True):
            code = runner.main()
        result = json.loads((root/'evidence/preflight/full/result.json').read_text())
        self.assertEqual(spawn.call_args.kwargs['env']['RUST_DUTY_PREFLIGHT_CASE'], 'full')
        self.assertIn('--ignored', spawn.call_args.args[0])
        return code, result, child, terminate

    def test_success_records_real_case_and_elapsed(self):
        code, result, child, terminate = self.run_case(True)
        self.assertEqual(code, 0)
        self.assertTrue(result['passed'])
        self.assertEqual(result['elapsed_seconds'], 1)
        self.assertFalse(child.killed)
        terminate.assert_not_called()

    def test_deadline_fails_even_if_killed_child_reports_zero(self):
        code, result, child, terminate = self.run_case(False)
        self.assertEqual(code, 1)
        self.assertTrue(result['timed_out'])
        self.assertFalse(result['passed'])
        if os.name == 'nt':
            terminate.assert_called_once_with(['taskkill', '/PID', '12345', '/T', '/F'], check=False, timeout=30)
        else:
            self.assertTrue(child.killed)
