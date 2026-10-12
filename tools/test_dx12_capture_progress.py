"""Real short-lived Python children and synthetic orchestration, not DX12 proof.

Exercise the authored harness's public execution/reporting boundary. These tests
cover timeout cleanup and retained progress, not renderer or asset acceptance.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stdout
import io
import itertools
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import run_dx12_authored as authored


class CaptureProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    @staticmethod
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))

    def command(self, source):
        return [sys.executable, '-u', '-c', source]

    def harness(self, evidence, execute, *, process_timeout=1, **kwargs):
        game, fixture = self.root / 'game.exe', self.root / 'fixture.exe'
        game.write_bytes(b'synthetic game, never executed')
        fixture.write_bytes(b'synthetic fixture, never executed')
        (self.root / 'settings.cfg').write_text('fov = 90\n', encoding='utf-8')
        legacy = self.root / 'legacy'
        legacy.mkdir(exist_ok=True)
        with ExitStack() as stack:
            stack.enter_context(patch.object(authored, 'asset_evidence', return_value={'synthetic': True}))
            stack.enter_context(patch.object(authored, 'execute', side_effect=execute))
            stack.enter_context(patch.object(authored, 'lighting_commands', return_value=[]))
            for name in ('validate_orientation', 'validate_sequence', 'compare_sequence', 'validate_lighting'):
                stack.enter_context(patch.object(authored, name, return_value={'synthetic': True}))
            return authored.run(game, fixture, self.root, evidence, legacy, process_timeout, **kwargs)

    def test_execute_rejects_invalid_timeout_before_launch_or_logs(self):
        for index, timeout in enumerate((0, -1, float('nan'), float('inf'), -float('inf'))):
            logs = self.root / f'invalid-{index}'
            with self.subTest(timeout=timeout), patch.object(authored.subprocess, 'Popen') as launch:
                with self.assertRaisesRegex(ValueError, 'timeout'):
                    authored.execute(['never-launch'], self.root, logs, timeout)
                launch.assert_not_called()
                self.assertFalse(logs.exists())

    def test_success_persists_pid_elapsed_and_terminal_status(self):
        logs = self.root / 'success'
        result = authored.execute(self.command('print("completed")'), self.root, logs, 5)
        self.assertEqual(result['exit_code'], 0)
        report = self.read(logs / 'process.json')
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['exit_code'], 0)
        self.assertGreater(report['pid'], 0)
        self.assertGreaterEqual(report['elapsed_seconds'], 0)
        self.assertEqual(report['timeout_seconds'], 5)
        self.assertIn('completed', (logs / 'stdout.log').read_text())

    def test_execute_rejects_invalid_progress_interval_before_launch(self):
        for index, interval in enumerate((0, -1, float('nan'), float('inf'))):
            logs = self.root / f'invalid-progress-{index}'
            with self.subTest(interval=interval), patch.object(authored.subprocess, 'Popen') as launch:
                with self.assertRaisesRegex(ValueError, 'progress interval'):
                    authored.execute(['never-launch'], self.root, logs, 5, progress_interval=interval)
                launch.assert_not_called()
                self.assertFalse(logs.exists())

    def test_nonzero_exit_persists_failure_and_both_streams(self):
        logs = self.root / 'nonzero'
        with self.assertRaisesRegex(ValueError, 'process exited 7'):
            authored.execute(self.command('import sys; print("partial"); '
                                          'print("diagnostic", file=sys.stderr); sys.exit(7)'),
                             self.root, logs, 5)
        report = self.read(logs / 'process.json')
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['exit_code'], 7)
        self.assertIn('partial', (logs / 'stdout.log').read_text())
        self.assertIn('diagnostic', (logs / 'stderr.log').read_text())

    def test_failed_spawn_persists_failed_status_without_fake_pid(self):
        logs = self.root / 'spawn'
        with self.assertRaises(OSError):
            authored.execute([str(self.root / 'absent-executable')], self.root, logs, 5)
        report = self.read(logs / 'process.json')
        self.assertEqual(report['status'], 'failed')
        self.assertIsNone(report['pid'])
        self.assertIsNone(report['exit_code'])
        self.assertIn('error', report)
        self.assertTrue((logs / 'invocation.json').is_file())

    def test_timeout_keeps_partial_files_and_reports_elapsed_failure(self):
        logs = self.root / 'timeout'
        output = self.root / 'partial'
        output.mkdir()
        frame = output / '0000.png'
        source = ('import sys,time; from pathlib import Path; '
                  f'Path({str(frame)!r}).write_bytes(b"partial-frame-evidence"); '
                  'print("capture started"); print("warning retained", file=sys.stderr); time.sleep(30)')
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            authored.execute(self.command(source), self.root, logs, 0.5)
        self.assertLess(time.monotonic() - start, 10, 'timeout cleanup must also be bounded')
        self.assertEqual(frame.read_bytes(), b'partial-frame-evidence')
        self.assertIn('capture started', (logs / 'stdout.log').read_text())
        self.assertIn('warning retained', (logs / 'stderr.log').read_text())
        report = self.read(logs / 'process.json')
        self.assertEqual(report['status'], 'timed_out')
        self.assertGreaterEqual(report['elapsed_seconds'], 0.5)
        self.assertIsNotNone(report['exit_code'])
        self.assertIn('timeout', report['error'].lower().replace('timed out', 'timeout'))

    def test_timeout_stops_descendant_before_returning(self):
        # The child stays idle until the test releases it AFTER execute returns.
        # Without tree cleanup it writes survived, which is the actual bug.
        ready = self.root / 'child-ready'
        release = self.root / 'release-child'
        survived = self.root / 'child-survived'
        child = ('import os,time; from pathlib import Path; '
                 f'Path({str(ready)!r}).write_text(str(os.getpid())); '
                 f'release=Path({str(release)!r}); stop=time.monotonic()+10\n'
                 'while not release.exists() and time.monotonic()<stop: time.sleep(.01)\n'
                 f'if release.exists(): Path({str(survived)!r}).write_text("survived timeout")\n')
        parent = ('import subprocess,sys,time; '
                  f'subprocess.Popen([sys.executable,"-u","-c",{child!r}]); time.sleep(30)')
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                authored.execute(self.command(parent), self.root, self.root / 'tree', 1)
            self.assertTrue(ready.is_file(), 'the real descendant must have started before timeout')
            release.touch()
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline and not survived.exists():
                time.sleep(0.01)
            self.assertFalse(survived.exists(), 'a timed-out process left a live descendant')
        finally:
            # Clean up the negative control on the old harness as well.
            if ready.is_file() and survived.exists():
                pid = int(ready.read_text())
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                                   capture_output=True, timeout=5, check=False)
                else:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_running_process_progress_is_readable_before_process_exits(self):
        logs, release = self.root / 'live', self.root / 'release'
        source = ('import time; from pathlib import Path; '
                  f'release=Path({str(release)!r}); stop=time.monotonic()+5\n'
                  'while not release.exists() and time.monotonic()<stop: time.sleep(.01)\n')
        # No renderer, subprocess, or JSON I/O mocks: observe the live artifact.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(authored.execute, self.command(source), self.root, logs, 5)
            try:
                deadline = time.monotonic() + 1
                report = None
                while time.monotonic() < deadline:
                    path = logs / 'process.json'
                    if path.exists():
                        report = self.read(path)
                        if report['status'] == 'running':
                            break
                    if future.done():
                        future.result()
                        break
                    time.sleep(0.01)
                self.assertIsNotNone(report, 'running state was not saved before process completion')
                self.assertEqual(report['status'], 'running')
                self.assertGreater(report['pid'], 0)
                self.assertFalse(future.done())
            finally:
                release.touch()
                future.result(timeout=10)
        self.assertEqual(self.read(logs / 'process.json')['status'], 'passed')

    def test_windows_timeout_attempts_tree_kill_before_bounded_root_reap(self):
        # Exercise public execute's Windows branch with controlled OS calls.
        # Actual Windows process-tree behavior still needs the native CI run.
        for cleanup_error in (False, True):
            with self.subTest(cleanup_timeout=cleanup_error):
                logs = self.root / f'windows-cleanup-{cleanup_error}'
                process = Mock(pid=1234, returncode=None)
                events = []
                process.poll.side_effect = lambda: process.returncode

                def wait(timeout):
                    if process.returncode is None:
                        raise subprocess.TimeoutExpired(['synthetic-child'], timeout)
                    events.append(('reap', timeout))
                    return process.returncode

                def kill():
                    events.append(('kill-root',))
                    process.returncode = -9

                def taskkill(command, **kwargs):
                    events.append(('taskkill',))
                    self.assertEqual(command, ['taskkill', '/PID', '1234', '/T', '/F'])
                    self.assertEqual(kwargs['timeout'], 10)
                    self.assertFalse(kwargs['check'])
                    if cleanup_error:
                        raise subprocess.TimeoutExpired(command, 10)
                    return subprocess.CompletedProcess(command, 0, 'tree cleanup', '')

                process.wait.side_effect = wait
                process.kill.side_effect = kill
                with patch.object(authored, 'os', SimpleNamespace(name='nt', replace=os.replace)), \
                        patch.object(authored.subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, create=True), \
                        patch.object(authored.subprocess, 'Popen', return_value=process) as launch, \
                        patch.object(authored.subprocess, 'run', side_effect=taskkill), \
                        patch.object(authored.time, 'monotonic', side_effect=itertools.count(0, 0.1)):
                    with self.assertRaises(subprocess.TimeoutExpired) as expired:
                        authored.execute(['synthetic-child'], self.root, logs, 1)
                self.assertEqual(expired.exception.timeout, 1, 'cleanup must not hide the original deadline')
                self.assertEqual(launch.call_args.kwargs['creationflags'], 512)
                self.assertNotIn('start_new_session', launch.call_args.kwargs)
                self.assertEqual(events, [('taskkill',), ('kill-root',), ('reap', 5)])
                saved = self.read(logs / 'process.json')
                self.assertEqual(saved['status'], 'timed_out')
                self.assertEqual(saved['cleanup']['method'], 'taskkill-tree')
                if cleanup_error:
                    self.assertIn('TimeoutExpired', saved['cleanup']['error'])
                else:
                    self.assertEqual(saved['cleanup']['exit_code'], 0)

    def test_periodic_progress_reports_retained_frame_count(self):
        logs, output = self.root / 'heartbeat', self.root / 'frames'
        output.mkdir()
        source = ('import time; from pathlib import Path; '
                  f'Path({str(output / "0000.png")!r}).write_bytes(b"partial"); time.sleep(.25)')
        console = io.StringIO()
        with redirect_stdout(console):
            authored.execute(self.command(source) + [f'--output={output}'], self.root, logs, 5,
                             progress_interval=0.05)
        self.assertIn('still running', console.getvalue())
        self.assertIn('png_files=1', console.getvalue())
        report = self.read(logs / 'process.json')
        self.assertEqual(report['png_files'], 1)
        self.assertEqual(report['output_path'], str(output))

    def test_run_persists_current_check_before_calling_it(self):
        evidence = self.root / 'run-live'
        observed = []

        def execute(command, root, logs, timeout, **kwargs):
            saved = self.read(evidence / 'summary.json')
            observed.append((logs.name, saved))
            raise ValueError('synthetic launch failure')

        result = self.harness(evidence, execute)
        self.assertFalse(result['passed'])
        first = observed[0][1]
        self.assertEqual(first['status'], 'running')
        self.assertEqual(first['current_check'], 'orientation-renderer-contract')
        self.assertTrue(first['checks'][0]['passed'])
        self.assertEqual(observed[1][1]['current_check'], 'jump-gameplay/capture')
        self.assertFalse(observed[1][1]['checks'][-1]['passed'])
        saved = self.read(evidence / 'summary.json')
        self.assertEqual(saved['status'], 'failed')
        self.assertIsNone(saved['current_check'])
        self.assertEqual(saved['checks'], result['checks'])
        self.assertTrue(all(check['elapsed_seconds'] >= 0 for check in saved['checks']))

    def test_run_timeout_stays_failed_and_later_cases_continue(self):
        evidence = self.root / 'run-timeout'
        attempted = []

        def execute(command, root, logs, timeout, **kwargs):
            attempted.append(logs.name)
            if logs.name == 'jump-gameplay':
                raise subprocess.TimeoutExpired(command, timeout)
            raise ValueError('synthetic independent failure')

        result = self.harness(evidence, execute)
        self.assertEqual(attempted, ['renderer-contract', *[case.name for case in authored.CASES]])
        saved = self.read(evidence / 'summary.json')
        self.assertFalse(saved['passed'])
        self.assertFalse(saved['acceptance_complete'])
        self.assertEqual(saved['automated_landmark_gate'], 'open')
        row = next(item for item in saved['checks'] if item['name'] == 'jump-gameplay/capture')
        self.assertFalse(row['passed'])
        self.assertIn('timed out', row['error'])
        self.assertEqual(saved, result)

    def test_interrupt_preserves_current_check_and_completed_evidence(self):
        evidence = self.root / 'interrupted'
        with self.assertRaises(KeyboardInterrupt):
            self.harness(evidence, lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
        saved = self.read(evidence / 'summary.json')
        self.assertEqual(saved['status'], 'interrupted')
        self.assertEqual(saved['current_check'], 'orientation-renderer-contract')
        self.assertFalse(saved['passed'])
        self.assertTrue(saved['checks'][0]['passed'])
        self.assertFalse(saved['checks'][-1]['passed'])
        self.assertIn('KeyboardInterrupt', saved['checks'][-1]['error'])

    def test_run_rejects_invalid_whole_run_budget_before_any_action(self):
        for index, budget in enumerate((0, -1, float('nan'), float('inf'))):
            evidence = self.root / f'invalid-budget-{index}'
            execute = Mock()
            with self.subTest(budget=budget), self.assertRaisesRegex(ValueError, 'run timeout'):
                self.harness(evidence, execute, run_timeout=budget)
            execute.assert_not_called()
            self.assertFalse(evidence.exists())

    def test_budget_exhausted_before_first_check_starts_no_work(self):
        evidence = self.root / 'budget-before-check'
        clock = [0.0]

        def hash_consumes_budget(path):
            clock[0] += 1
            return 'synthetic-hash'

        execute = Mock()
        with patch.object(authored.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(authored, 'sha256', side_effect=hash_consumes_budget):
            result = self.harness(evidence, execute, run_timeout=1)
        execute.assert_not_called()
        self.assertTrue(result['budget_exhausted'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(result['checks']), 1)
        self.assertIn('not attempted', result['checks'][0]['error'])
        self.assertEqual(self.read(evidence / 'summary.json'), result)

    def test_whole_run_budget_caps_process_and_stops_later_work(self):
        evidence = self.root / 'budget-after-capture'
        clock = [0.0]
        attempted = []

        def execute(command, root, logs, timeout, **kwargs):
            attempted.append((logs.name, timeout))
            clock[0] = 3.1
            return {'synthetic': True}

        with patch.object(authored.time, 'monotonic', side_effect=lambda: clock[0]):
            result = self.harness(evidence, execute, process_timeout=10, run_timeout=3)
        self.assertEqual(attempted, [('renderer-contract', 3)])
        self.assertTrue(result['budget_exhausted'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['run_timeout_seconds'], 3)
        self.assertEqual(result['elapsed_seconds'], 3.1)
        self.assertEqual(len(result['checks']), 2)
        self.assertFalse(result['checks'][-1]['passed'])
        self.assertIn('budget exhausted', result['checks'][-1]['error'])
        self.assertFalse((evidence / 'captures/lighting').exists())
        self.assertEqual(self.read(evidence / 'summary.json'), result)

    def test_real_child_timeout_exhausts_run_budget_and_saves_final_summary(self):
        evidence = self.root / 'budget-real-child'
        actual_execute = authored.execute
        attempted = []

        def execute(command, root, logs, timeout, **kwargs):
            attempted.append((logs, timeout))
            return actual_execute(self.command('import time; print("partial output"); time.sleep(30)'),
                                  root, logs, timeout)

        started = time.monotonic()
        result = self.harness(evidence, execute, process_timeout=10, run_timeout=0.3)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(len(attempted), 1)
        logs, timeout = attempted[0]
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 0.3)
        self.assertTrue(result['budget_exhausted'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['acceptance_complete'])
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['current_check'])
        self.assertEqual(self.read(logs / 'process.json')['status'], 'timed_out')
        self.assertIn('partial output', (logs / 'stdout.log').read_text())
        self.assertEqual(self.read(evidence / 'summary.json'), result)

    def test_remaining_budget_is_not_reset_for_the_next_capture(self):
        evidence = self.root / 'budget-not-reset'
        clock = [0.0]
        attempted = []

        def execute(command, root, logs, timeout, **kwargs):
            attempted.append((logs.name, timeout))
            if logs.name == 'renderer-contract':
                clock[0] = 1
                return {'synthetic': True}
            clock[0] = 3.1
            raise subprocess.TimeoutExpired(command, timeout)

        with patch.object(authored.time, 'monotonic', side_effect=lambda: clock[0]):
            result = self.harness(evidence, execute, process_timeout=10, run_timeout=3)
        self.assertEqual(attempted, [('renderer-contract', 3), ('jump-gameplay', 2)])
        self.assertTrue(result['budget_exhausted'])
        self.assertFalse(result['passed'])
        self.assertTrue(result['checks'][1]['passed'])
        self.assertEqual(result['checks'][-1]['name'], 'jump-gameplay/capture')
        self.assertFalse(result['checks'][-1]['passed'])
        self.assertIn('timed out after 2', result['checks'][-1]['error'])
        self.assertEqual(self.read(evidence / 'summary.json'), result)

    def test_failed_atomic_write_keeps_previous_valid_summary(self):
        path = self.root / 'summary.json'
        authored.write_json(path, {'status': 'running', 'current_check': 'jump-gameplay/capture'})
        before = path.read_bytes()
        with patch.object(authored.os, 'replace', side_effect=OSError('synthetic interrupted replace')):
            with self.assertRaises(OSError):
                authored.write_json(path, {'status': 'failed'})
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
