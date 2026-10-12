"""Synthetic callbacks/process mocks only; never native Windows renderer proof.

The POSIX subprocess tests execute tiny generated Python fixtures, not a GPU
renderer. All DX12/Fxc log lines in this suite are deliberately synthetic.
"""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import dx12_contract_process as runner


IDENTITY = 'renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver'
COMPILER = 'renderer dx12_shader_compiler=Fxc'
GOOD_LOG = (IDENTITY + '\n' + COMPILER + '\n').encode()


class ContractProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='contract process ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.executable = Path(sys.executable).resolve()
        self.evidence = self.root / 'evidence'
        self.output = self.root / 'output'
        self.validator = Mock(return_value={'passed': True, 'custom_report': {'count': 3}})
        self.process = Mock(pid=123456789, returncode=0)
        self.process.wait.return_value = 0

    def run_fixture(self, **overrides):
        values = {'executable': self.executable, 'root': self.root,
                  'evidence': self.evidence, 'output': self.output,
                  'timeout': 1, 'fixture': 'synthetic-fixture',
                  'validate_outputs': self.validator}
        values.update(overrides)
        return runner.run(**values)

    def launch(self, argv, **kwargs):
        kwargs['stderr'].write(GOOD_LOG)
        return self.process

    def failure(self):
        self.assertFalse((self.evidence / 'summary.json').exists())
        self.assertFalse((self.evidence / 'summary.json.tmp').exists())
        result = json.loads((self.evidence / 'failure.json').read_text())
        self.assertIs(result['passed'], False)
        return result

    def fresh_paths(self, index):
        self.evidence = self.root / f'evidence-{index}'
        self.output = self.root / f'output-{index}'

    def test_command_runs_exact_executable_without_cargo_or_shell(self):
        self.assertEqual(runner.command(self.executable, self.output), [
            str(self.executable), '--renderer=dx12', '--force-fallback-adapter',
            '--output-dir', str(self.output)])

    def test_fxc_initialization_must_be_in_actual_stderr(self):
        def stdout_only(argv, **kwargs):
            kwargs['stdout'].write(GOOD_LOG)
            return self.process
        with patch.object(runner.subprocess, 'Popen', side_effect=stdout_only):
            with self.assertRaisesRegex(ValueError, 'FXC initialization in stderr'):
                self.run_fixture()
        self.validator.assert_not_called()
        self.failure()

    def test_success_preserves_summary_and_records_identity(self):
        summary = {'passed': True, 'custom_report': {'count': 3},
                   'build_version': 'synthetic', 'build_number': '41'}

        def validate(output):
            self.assertEqual(output, self.output)
            self.assertFalse((self.evidence / 'summary.json').exists())
            self.assertTrue(output.is_dir())
            # Final provenance must use the launch record, not a later env read.
            os.environ.update(GITHUB_SHA='changed', GITHUB_RUN_ID='changed', GITHUB_RUN_ATTEMPT='changed')
            return summary

        environment = {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}
        with patch.dict(os.environ, environment), patch.object(runner.subprocess, 'Popen', side_effect=self.launch) as process:
            report = self.run_fixture(validate_outputs=validate)
        self.assertEqual(report['custom_report'], {'count': 3})
        self.assertEqual(report['build_number'], '41')
        self.assertEqual(report['fixture'], 'synthetic-fixture')
        self.assertEqual(report['renderer_logs'], [IDENTITY])
        self.assertEqual(report['dx12_shader_compiler'], 'Fxc')
        self.assertEqual(report['exit_code'], 0)
        self.assertNotIn('exit_code', summary)
        self.assertEqual(json.loads((self.evidence / 'summary.json').read_text()), report)
        self.assertFalse((self.evidence / 'failure.json').exists())
        invocation = json.loads((self.evidence / 'invocation.json').read_text())
        self.assertEqual(invocation['executable_sha256'], hashlib.sha256(self.executable.read_bytes()).hexdigest())
        self.assertEqual(report['executable_sha256'], invocation['executable_sha256'])
        self.assertEqual(invocation['source_commit'], 'a' * 40)
        self.assertEqual(invocation['run_id'], '123')
        self.assertEqual(invocation['run_attempt'], '2')
        for key in ('source_commit', 'run_id', 'run_attempt'):
            self.assertEqual(report[key], invocation[key])
        self.assertEqual(invocation['command'], runner.command(self.executable, self.output))
        self.assertEqual(invocation['cwd'], str(self.root))
        self.assertEqual(invocation['timeout_seconds'], 1)
        self.assertEqual(process.call_args.kwargs['cwd'], self.root)
        self.assertIs(process.call_args.kwargs['shell'], False)
        self.assertEqual(process.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.process.wait.assert_called_once_with(timeout=1)
        self.assertEqual((self.evidence / 'stderr.log').read_bytes(), GOOD_LOG)
        self.assertEqual((self.evidence / 'stdout.log').read_bytes(), b'')

    def test_invalid_timeout_never_launches_or_creates_evidence(self):
        for timeout in (0, -1, float('nan'), float('inf'), -float('inf'), True, None, '1', 10 ** 1000):
            with self.subTest(timeout=timeout), patch.object(runner.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(ValueError, 'timeout'):
                    self.run_fixture(timeout=timeout)
                process.assert_not_called()
                self.assertFalse(self.evidence.exists())

    def test_missing_executable_and_working_directory_fail_preflight(self):
        for overrides in ({'executable': self.root / 'missing'}, {'executable': self.root},
                          {'root': self.root / 'missing'}, {'root': self.executable}):
            with self.subTest(overrides=overrides), patch.object(runner.subprocess, 'Popen') as process:
                with self.assertRaises(ValueError):
                    self.run_fixture(**overrides)
                process.assert_not_called()
                self.assertFalse(self.evidence.exists())

    @unittest.skipIf(sys.platform == 'win32', 'POSIX executable permission check')
    def test_nonexecutable_file_fails_preflight(self):
        file = self.root / 'not-executable'
        file.write_bytes(b'not an executable')
        with self.assertRaisesRegex(ValueError, 'not executable'):
            self.run_fixture(executable=file)
        self.assertFalse(self.evidence.exists())

    def test_invalid_fixture_or_callback_fails_preflight(self):
        for overrides in ({'fixture': ''}, {'fixture': ' '}, {'fixture': None},
                          {'validate_outputs': None}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.run_fixture(**overrides)
        self.assertFalse(self.evidence.exists())

    def test_existing_file_or_directory_is_not_changed(self):
        for index, (target, as_file) in enumerate((('evidence', False), ('output', False),
                                                  ('evidence', True), ('output', True))):
            self.fresh_paths(index)
            path = getattr(self, target)
            if as_file:
                path.write_bytes(b'keep this')
            else:
                path.mkdir()
                (path / 'summary.json').write_bytes(b'keep this')
            with self.subTest(target=target, as_file=as_file), patch.object(runner.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(ValueError, 'stale'):
                    self.run_fixture()
                process.assert_not_called()
                self.assertEqual((path if as_file else path / 'summary.json').read_bytes(), b'keep this')

    def test_resolved_overlapping_paths_are_rejected(self):
        for output in (self.evidence, self.evidence / 'child',
                       self.evidence / 'unused' / '..', self.evidence.parent):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'nonoverlapping'):
                self.run_fixture(output=output)
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            self.run_fixture(evidence=self.output / 'child')
        self.assertFalse(self.evidence.exists())

    @unittest.skipIf(sys.platform == 'win32', 'symlink privileges are not assumed on Windows')
    def test_broken_symlink_is_not_a_fresh_directory(self):
        for index, target in enumerate(('evidence', 'output')):
            self.fresh_paths(index)
            path = getattr(self, target)
            destination = self.root / f'missing-{index}'
            path.symlink_to(destination, target_is_directory=True)
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'stale'):
                self.run_fixture()
            self.assertTrue(path.is_symlink())
            self.assertFalse(destination.exists())

    def test_nonzero_exit_retains_failure_and_never_validates(self):
        self.process.returncode = 7
        self.process.wait.return_value = 7
        with patch.object(runner.subprocess, 'Popen', side_effect=self.launch):
            with self.assertRaisesRegex(ValueError, 'code 7'):
                self.run_fixture()
        self.assertEqual(self.failure()['exit_code'], 7)
        self.validator.assert_not_called()

    def test_launch_error_retains_failure_and_both_logs(self):
        with patch.object(runner.subprocess, 'Popen', side_effect=OSError('launch failed')):
            with self.assertRaisesRegex(OSError, 'launch failed'):
                self.run_fixture()
        self.assertEqual(self.failure()['error_type'], 'OSError')
        for filename in ('invocation.json', 'stdout.log', 'stderr.log'):
            self.assertTrue((self.evidence / filename).is_file())
        self.validator.assert_not_called()

    def test_hash_error_retains_failure(self):
        with patch.object(runner.hashlib, 'file_digest', side_effect=OSError('hash failed')):
            with self.assertRaisesRegex(OSError, 'hash failed'):
                self.run_fixture()
        self.assertEqual(self.failure()['error'], 'hash failed')

    def test_executable_change_during_process_or_validation_rejects_success(self):
        for index, stage in enumerate(('process', 'validation')):
            self.fresh_paths(index)
            executable = self.root / f'mocked-example-{index}'
            executable.write_bytes(b'synthetic process mock executable bytes')
            executable.chmod(0o700)
            original_hash = hashlib.sha256(executable.read_bytes()).hexdigest()

            def launch(argv, **kwargs):
                process = self.launch(argv, **kwargs)
                if stage == 'process':
                    executable.write_bytes(b'changed while process ran')
                return process

            def validate(output):
                if stage == 'validation':
                    executable.write_bytes(b'changed while validation ran')
                return {'passed': True}

            with self.subTest(stage=stage), patch.object(runner.subprocess, 'Popen', side_effect=launch):
                with self.assertRaisesRegex(ValueError, 'executable changed'):
                    self.run_fixture(executable=executable, validate_outputs=validate)
                self.failure()
                invocation = json.loads((self.evidence / 'invocation.json').read_text())
                self.assertEqual(invocation['executable_sha256'], original_hash)

    def test_output_creation_error_is_recorded_after_evidence_claim(self):
        original_mkdir = Path.mkdir

        def mkdir(path, *args, **kwargs):
            if path == self.output:
                raise PermissionError('output creation blocked')
            return original_mkdir(path, *args, **kwargs)

        with patch.object(Path, 'mkdir', new=mkdir), patch.object(runner.subprocess, 'Popen') as process:
            with self.assertRaisesRegex(PermissionError, 'output creation blocked'):
                self.run_fixture()
        process.assert_not_called()
        self.assertEqual(self.failure()['error_type'], 'PermissionError')

    def test_failed_summary_publication_retains_failure_without_partial_summary(self):
        original_replace = Path.replace

        def replace(path, destination):
            if path.name == 'summary.json.tmp':
                raise OSError('summary publication failed')
            return original_replace(path, destination)

        with patch.object(Path, 'replace', new=replace), patch.object(runner.subprocess, 'Popen', side_effect=self.launch):
            with self.assertRaisesRegex(OSError, 'summary publication failed'):
                self.run_fixture()
        self.assertEqual(self.failure()['error_type'], 'OSError')

    def test_wrong_or_missing_renderer_or_compiler_logs_fail(self):
        invalid = [b'', GOOD_LOG.replace(b'requested=dx12', b'requested=auto'),
                   GOOD_LOG.replace(b'backend=Dx12', b'backend=Vulkan'),
                   GOOD_LOG.replace(b'Microsoft Basic Render Driver', b'hardware adapter'),
                   (IDENTITY + '\n').encode(),
                   GOOD_LOG.replace(b'=Fxc', b'=fxc'), GOOD_LOG.replace(b'=Fxc', b'=Auto'),
                   GOOD_LOG + b'renderer dx12_shader_compiler=DynamicDxc\n',
                   GOOD_LOG + b'renderer requested=gl backend=Gl adapter=other\n']
        for index, log in enumerate(invalid):
            self.fresh_paths(index)

            def launch(argv, **kwargs):
                kwargs['stdout'].write(log)
                return self.process

            with self.subTest(log=log), patch.object(runner.subprocess, 'Popen', side_effect=launch):
                with self.assertRaises(ValueError):
                    self.run_fixture()
                self.failure()
        self.validator.assert_not_called()

    def test_callback_exception_retains_failure(self):
        for index, error in enumerate((ValueError('bad report'), RuntimeError('bad callback'), AssertionError('bad assertion'))):
            self.fresh_paths(index)
            self.validator.side_effect = error
            with self.subTest(error=error), patch.object(runner.subprocess, 'Popen', side_effect=self.launch):
                with self.assertRaises(type(error)):
                    self.run_fixture()
                self.assertEqual(self.failure()['error'], str(error))

    def test_callback_must_return_dict_with_passed_strictly_true(self):
        for index, report in enumerate((None, [], {}, {'passed': False}, {'passed': 1}, {'passed': 'true'})):
            self.fresh_paths(index)
            self.validator.return_value = report
            with self.subTest(report=report), patch.object(runner.subprocess, 'Popen', side_effect=self.launch):
                with self.assertRaises(ValueError):
                    self.run_fixture()
                self.failure()

    def test_callback_cannot_supply_process_owned_fields(self):
        fields = ('fixture', 'exit_code', 'renderer_logs', 'dx12_shader_compiler',
                  'executable_sha256', 'source_commit', 'run_id', 'run_attempt',
                  'command', 'cwd', 'timeout_seconds')
        for index, field in enumerate(fields):
            self.fresh_paths(index)
            self.validator.return_value = {'passed': True, field: 'forged'}
            with self.subTest(field=field), patch.object(runner.subprocess, 'Popen', side_effect=self.launch):
                with self.assertRaisesRegex(ValueError, 'process-owned fields'):
                    self.run_fixture()
                self.failure()

    def test_unserializable_callback_never_leaves_partial_summary(self):
        for index, value in enumerate((object(), float('nan'), float('inf'))):
            self.fresh_paths(index)
            self.validator.return_value = {'passed': True, 'custom': value}
            with self.subTest(value=value), patch.object(runner.subprocess, 'Popen', side_effect=self.launch):
                with self.assertRaises((ValueError, TypeError)):
                    self.run_fixture()
                self.failure()

    @unittest.skipIf(sys.platform == 'win32', 'POSIX tree-cleanup branch')
    def test_posix_timeout_kills_process_session_and_preserves_timeout(self):
        self.process.wait.side_effect = [subprocess.TimeoutExpired(['synthetic'], 1), -9]
        self.process.returncode = -9
        with patch.object(runner.subprocess, 'Popen', side_effect=self.launch) as process, patch.object(runner.os, 'killpg') as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_fixture()
        self.assertIs(process.call_args.kwargs['start_new_session'], True)
        kill.assert_called_once_with(self.process.pid, signal.SIGKILL)
        self.assertTrue(self.failure()['cleanup']['succeeded'])
        self.validator.assert_not_called()

    @unittest.skipIf(sys.platform == 'win32', 'POSIX tree-cleanup branch')
    def test_posix_cleanup_error_remains_visible_after_root_kill(self):
        self.process.wait.side_effect = [subprocess.TimeoutExpired(['synthetic'], 1), -9]
        self.process.returncode = -9
        with patch.object(runner.subprocess, 'Popen', side_effect=self.launch), patch.object(runner.os, 'killpg', side_effect=OSError('tree kill failed')):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_fixture()
        self.process.kill.assert_called_once_with()
        cleanup = self.failure()['cleanup']
        self.assertFalse(cleanup['succeeded'])
        self.assertIn('tree kill failed', cleanup['errors'][0])

    @unittest.skipIf(sys.platform == 'win32', 'POSIX tree-cleanup branch')
    def test_interrupted_wait_still_stops_process_tree(self):
        self.process.wait.side_effect = [KeyboardInterrupt(), -9]
        self.process.returncode = -9
        with patch.object(runner.subprocess, 'Popen', side_effect=self.launch), patch.object(runner.os, 'killpg') as kill:
            with self.assertRaises(KeyboardInterrupt):
                self.run_fixture()
        kill.assert_called_once_with(self.process.pid, signal.SIGKILL)
        self.assertEqual(self.failure()['error_type'], 'KeyboardInterrupt')

    @unittest.skipIf(sys.platform == 'win32', 'POSIX tree-cleanup branch')
    def test_timeout_racing_with_tree_exit_is_still_a_failed_run(self):
        self.process.wait.side_effect = [subprocess.TimeoutExpired(['synthetic'], 1), 0]
        self.process.returncode = 0
        with patch.object(runner.subprocess, 'Popen', side_effect=self.launch), patch.object(runner.os, 'killpg', side_effect=ProcessLookupError()):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_fixture()
        failure = self.failure()
        self.assertTrue(failure['cleanup']['already_exited'])
        self.assertTrue(failure['cleanup']['succeeded'])
        self.assertEqual(failure['error_type'], 'TimeoutExpired')

    def test_windows_timeout_uses_taskkill_tree_force_without_shell(self):
        self.process.wait.side_effect = [subprocess.TimeoutExpired(['synthetic'], 1), 1]
        self.process.returncode = 1
        killed = subprocess.CompletedProcess([], 0, b'tree terminated', b'')
        with patch.object(runner.sys, 'platform', 'win32'), patch.object(runner.subprocess, 'Popen', side_effect=self.launch) as process, patch.object(runner.subprocess, 'run', return_value=killed) as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_fixture()
        self.assertIs(process.call_args.kwargs['shell'], False)
        self.assertNotIn('start_new_session', process.call_args.kwargs)
        self.assertEqual(process.call_args.kwargs['creationflags'], 0x00000200)
        self.assertEqual(kill.call_args.args[0], ['taskkill', '/PID', str(self.process.pid), '/T', '/F'])
        self.assertFalse(kill.call_args.kwargs['check'])
        self.assertEqual(kill.call_args.kwargs['timeout'], runner.CLEANUP_TIMEOUT)
        self.assertTrue(self.failure()['cleanup']['succeeded'])

    def test_windows_cleanup_failure_is_preserved(self):
        for index, result in enumerate((subprocess.CompletedProcess([], 5, b'', b'access denied'),
                                        OSError('taskkill missing'),
                                        subprocess.TimeoutExpired(['taskkill'], 10))):
            self.fresh_paths(index)
            self.process.wait.side_effect = [subprocess.TimeoutExpired(['synthetic'], 1), -9]
            self.process.returncode = -9
            kwargs = {'side_effect': result} if isinstance(result, BaseException) else {'return_value': result}
            with self.subTest(result=result), patch.object(runner.sys, 'platform', 'win32'), patch.object(runner.subprocess, 'Popen', side_effect=self.launch), patch.object(runner.subprocess, 'run', **kwargs):
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.run_fixture()
                failure = self.failure()
                self.assertEqual(failure['error_type'], 'TimeoutExpired')
                self.assertFalse(failure['cleanup']['succeeded'])
                self.assertTrue(failure['cleanup']['errors'])
        self.assertEqual(self.process.kill.call_count, 3)

    def test_reap_timeout_is_recorded_without_a_summary(self):
        self.process.returncode = None
        self.process.wait.side_effect = subprocess.TimeoutExpired(['synthetic'], 1)
        with patch.object(runner.sys, 'platform', 'win32'), patch.object(runner.subprocess, 'Popen', side_effect=self.launch), patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_fixture()
        self.assertIn('process reap failed', self.failure()['cleanup']['errors'][0])

    def make_script(self, source):
        path = self.root / 'synthetic subprocess'
        path.write_text(f'#!{sys.executable}\n' + source, encoding='utf-8')
        path.chmod(0o700)
        return path

    @unittest.skipIf(sys.platform == 'win32', 'generated executable uses a POSIX shebang')
    def test_real_python_subprocess_is_only_synthetic_process_proof(self):
        executable = self.make_script(
            'import json, pathlib, sys\n'
            "out = pathlib.Path(sys.argv[sys.argv.index('--output-dir') + 1])\n"
            "(out / 'arguments.json').write_text(json.dumps(sys.argv[1:]))\n"
            f'print({IDENTITY!r})\nprint({COMPILER!r}, file=sys.stderr)\n')

        def validate(output):
            self.assertEqual(json.loads((output / 'arguments.json').read_text()), [
                '--renderer=dx12', '--force-fallback-adapter', '--output-dir', str(output)])
            return {'passed': True, 'scope': 'synthetic Python subprocess only'}

        result = self.run_fixture(executable=executable, validate_outputs=validate)
        self.assertEqual(result['scope'], 'synthetic Python subprocess only')
        self.assertEqual(result['renderer_logs'], [IDENTITY])

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux /proc distinguishes terminated zombies from live children')
    def test_real_timeout_stops_spawned_python_child(self):
        executable = self.make_script(
            'import pathlib, subprocess, sys, time\n'
            "out = pathlib.Path(sys.argv[sys.argv.index('--output-dir') + 1])\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "(out / 'child.pid').write_text(str(child.pid))\n"
            f'print({IDENTITY!r}, flush=True)\nprint({COMPILER!r}, flush=True)\n'
            'time.sleep(60)\n')
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_fixture(executable=executable, timeout=0.5)
        failure = self.failure()
        self.assertTrue(failure['cleanup']['succeeded'])
        pid = int((self.output / 'child.pid').read_text())
        stat = Path(f'/proc/{pid}/stat')
        deadline = time.monotonic() + 2
        while stat.exists() and time.monotonic() < deadline:
            if stat.read_text().split(') ', 1)[1].split()[0] == 'Z':
                break
            time.sleep(0.01)
        if stat.exists():
            self.assertEqual(stat.read_text().split(') ', 1)[1].split()[0], 'Z')


if __name__ == '__main__':
    unittest.main()
