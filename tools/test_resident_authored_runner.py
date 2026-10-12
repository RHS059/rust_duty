"""Owned build/process and retained-input flow tests; no executable is launched."""
import contextlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import run_resident_authored_contract as resident


class ResidentAuthoredFlowTests(unittest.TestCase):
    def flow(self, mutation=None, host='win32'):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        root, output = base / 'source', base / 'evidence'
        root.mkdir(); output.mkdir()
        for name, raw in {'Cargo.toml': b'synthetic compile input', 'src/main.rs': b'original',
                          'assets/animations.cfg': b'public manifest',
                          'assets/locomotion/asset.vrs': b'synthetic nonexecutable asset'}.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        resident.matrix.write_json(output / 'materialize.json', {'synthetic': True})
        events, compiler_changed, compiler_calls = [], [], []
        self.last = root, output, events
        compiler = {'rustc': 'release: 1.99.0\nhost: ' + ('x86_64-pc-windows-msvc' if host == 'win32'
                    else 'x86_64-unknown-linux-gnu') + '\n', 'cargo': 'cargo 1.99.0 synthetic'}
        if mutation == 'private-assets': (root / 'assets/weapons').mkdir()
        if mutation == 'stale': (output / 'old.json').write_bytes(b'old')
        def checked_source(_):
            return {'commit': 'a' * 40, 'files_sha256': resident.profile.inventory(root)}
        def configuration(*_):
            if (root / '.cargo/config.toml').exists(): raise ValueError('unbound cargo config')
        def toolchain(_):
            compiler_calls.append(True)
            if len(compiler_calls) == 4 and mutation in ('final-capture-file','final-capture-directory'):
                path = output / 'captures/unexpected'
                if mutation.endswith('directory'): path.mkdir()
                else: path.write_bytes(b'after accepted retention')
            return {**compiler, 'changed': True} if compiler_changed else compiler.copy()
        def logged(command, cwd, directory, env, timeout, executable_sha256=None):
            self.assertEqual(cwd, root)
            self.assertEqual(env['PASS_SUBMISSION_SOURCE_SHA256'], resident.matrix.sha256(output / 'inputs.json'))
            directory.mkdir()
            (directory / 'stdout.log').write_bytes(b'synthetic stdout')
            (directory / 'stderr.log').write_bytes(b'synthetic stderr')
            resident.matrix.write_json(directory / 'result.json', {'exit_code': 0})
            if command[0] == 'cargo':
                events.append('build')
                self.assertEqual(command, ['cargo','build','--locked','--no-default-features','--features',
                                           'wgpu-runtime','--example',resident.EXAMPLE])
                binary = Path(env['CARGO_TARGET_DIR']) / 'debug/examples' / (resident.EXAMPLE + ('.exe' if host == 'win32' else ''))
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b'not an executable')
                if mutation == 'timeout': raise subprocess.TimeoutExpired(command, timeout)
                if mutation == 'build-source': (root / 'src/main.rs').write_bytes(b'changed')
                return
            events.append('process')
            self.assertEqual(command[1:], ['--manifest', str(root / 'assets/animations.cfg'), '--output-dir', str(output / 'captures')])
            self.assertEqual(resident.matrix.sha256(Path(command[0])), executable_sha256)
            captures = output / 'captures'; captures.mkdir()
            resident.matrix.write_json(captures / 'report.json', {'source_receipt_sha256': env['PASS_SUBMISSION_SOURCE_SHA256']})
            targets = {'source': root / 'src/main.rs', 'asset': root / 'assets/animations.cfg',
                       'input-receipt': output / 'inputs.json', 'materialize': output / 'materialize.json',
                       'executable': Path(command[0]), 'build-log': output / 'build/stdout.log',
                       'executable-receipt': output / 'executable.json'}
            if mutation in targets:
                path = targets[mutation]; path.write_bytes(path.read_bytes() + b'changed')
            if mutation == 'compiler': compiler_changed.append(True)
            if mutation == 'config':
                (root / '.cargo').mkdir(); (root / '.cargo/config.toml').write_bytes(b'config')
            if mutation == 'process-error': raise ValueError('synthetic native failure')
        def device(log, report):
            if mutation in ('extra-capture-file', 'extra-capture-directory', 'extra-process-file'):
                target = output / ('process' if mutation == 'extra-process-file' else 'captures') / 'unexpected'
                if mutation.endswith('directory'): target.mkdir()
                else: target.write_bytes(b'added after validation')
            return {'synthetic': True}
        def validate(directory, report, digest):
            self.assertEqual(report['source_receipt_sha256'], digest)
            if mutation == 'validation': raise ValueError('synthetic strict reader failure')
            return {'passed': True, 'exact_authored_pairs': 22}
        patches = [patch.object(resident, '__file__', str(root / 'tools/run_resident_authored_contract.py')),
                   patch.object(resident.sys, 'platform', host), patch.object(resident.pair, 'check_environment'),
                   patch.object(resident.pair, 'check_cargo_configuration', side_effect=configuration),
                   patch.object(resident.pair, 'toolchain_at', side_effect=toolchain),
                   patch.object(resident.profile, 'checked_source', side_effect=checked_source),
                   patch.object(resident.matrix, 'source_identity', return_value={'commit': 'a' * 40}),
                   patch.object(resident.pair, 'git', return_value=b''),
                   patch.object(resident, 'logged', side_effect=logged),
                   patch.object(resident, 'validate_outputs', side_effect=validate),
                   patch.object(resident, 'device_evidence', side_effect=device),
                   patch.object(subprocess, 'Popen', side_effect=AssertionError('real processes forbidden'))]
        with contextlib.ExitStack() as stack:
            for value in patches: stack.enter_context(value)
            return resident.run(root, output)

    def test_single_fresh_native_build_and_actual_loader_process_on_both_hosts(self):
        for host in ('win32','linux'):
            with self.subTest(host=host):
                result = self.flow(host=host)
                self.assertTrue(result['passed'])
                self.assertEqual(self.last[2], ['build','process'])
                self.assertTrue(resident.matrix.json_read(self.last[1] / 'final-input-check.json')['passed'])
                self.assertTrue((self.last[1] / 'summary.json').is_file())

    def test_source_build_asset_and_receipt_mutations_never_become_passed(self):
        for mutation in ('private-assets','stale','build-source','source','asset','input-receipt',
                         'materialize','executable','build-log','executable-receipt','compiler','config','validation','process-error',
                         'extra-capture-file','extra-capture-directory','extra-process-file'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertFalse((self.last[1] / 'summary.json').exists())

    def test_only_final_check_failure_retains_failed_overall_verdict(self):
        for mutation in ('final-capture-file','final-capture-directory'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.flow(mutation)
            output=self.last[1]
            self.assertFalse((output / 'summary.json').exists())
            self.assertIs(resident.matrix.json_read(output / 'failure.json')['passed'], False)
            self.assertEqual(resident.matrix.json_read(output / 'failure.json')['stage'], 'final-input-check')
            self.assertIs(resident.matrix.json_read(output / 'final-input-check.json')['passed'], False)

    def test_build_timeout_launches_no_fixture_and_preserves_input_check(self):
        with self.assertRaises(subprocess.TimeoutExpired): self.flow('timeout')
        self.assertEqual(self.last[2], ['build'])
        self.assertEqual(resident.matrix.json_read(self.last[1] / 'failure.json')['type'], 'TimeoutExpired')
        self.assertTrue(resident.matrix.json_read(self.last[1] / 'final-input-check.json')['passed'])

    def test_timeout_and_interrupt_retire_owned_process_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for host in ('win32','linux'):
                for index, error in enumerate((subprocess.TimeoutExpired('cargo', 3), KeyboardInterrupt())):
                    child = MagicMock(); child.wait.side_effect = error
                    directory = root / f'{host}-{index}'
                    cleanup = {'succeeded': False, 'errors': ['retained synthetic cleanup error']}
                    with patch.object(resident.sys, 'platform', host), \
                            patch.object(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, create=True), \
                            patch.object(subprocess, 'Popen', return_value=child) as launch, \
                            patch.object(resident.process, '_terminate_process_tree', return_value=cleanup) as retire:
                        with self.assertRaises(type(error)) as caught:
                            resident.logged(['cargo','build'], root, directory, dict(os.environ), 3)
                        self.assertIs(caught.exception, error)
                        retire.assert_called_once_with(child)
                        self.assertEqual(resident.matrix.json_read(directory / 'cleanup.json'), cleanup)
                        if host == 'win32': self.assertEqual(launch.call_args.kwargs['creationflags'], 512)
                        else: self.assertIs(launch.call_args.kwargs['start_new_session'], True)


if __name__ == '__main__':
    unittest.main()
