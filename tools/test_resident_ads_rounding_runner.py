"""Synthetic process flow only. No native rendering or compiler is invoked."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

from PIL import Image
import run_resident_ads_rounding as diagnostic
from test_capture_frame_witness import marker


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'evidence'
        self.output.mkdir()
        (self.output / 'materialize.json').write_text('{}')
        (self.root / 'settings.cfg').write_text('setting = 1\n')
        (self.root / 'assets/locomotion').mkdir(parents=True)
        (self.root / 'assets/animations.cfg').write_text('clip=ready')
        (self.root / 'assets/locomotion/asset.vrs').write_bytes(b'public fixture')
        self.source = {'commit': 'a'*40, 'files_sha256': {'settings.cfg': diagnostic.matrix.sha256(self.root/'settings.cfg')}}
        self.runtime = {'runtime_files_sha256': {}}
        self.compiler = {'rustc': 'release: 1.99.0\nhost: x86_64-pc-windows-msvc\n', 'cargo': 'cargo 1.99.0 test'}
        self.calls = []
        self.mutation = None
        self.patches = [patch.object(diagnostic, '__file__', str(self.root/'tools/run_resident_ads_rounding.py')),
            patch.object(diagnostic.sys, 'platform', 'win32'), patch.object(diagnostic, 'FRAMES', 1),
            patch.dict(os.environ, {'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_ACTIONS': 'true'}, clear=True),
            patch.object(diagnostic.pair, 'check_cargo_configuration'),
            patch.object(diagnostic.pair, 'toolchain_at', return_value=self.compiler),
            patch.object(diagnostic.profile, 'checked_source', side_effect=self.checked),
            patch.object(diagnostic.matrix, 'source_identity', return_value=self.runtime),
            patch.object(diagnostic.matrix, 'AUDITED_STAGING_CANDIDATE_MANIFEST', diagnostic.matrix.canonical_hash({})),
            patch.object(diagnostic.pair, 'read_sources', return_value={}),
            patch.object(diagnostic, 'source_pair', return_value={label: {'src/main.rs': label.encode()} for label in diagnostic.LABELS}),
            patch.object(diagnostic.native, 'logged', side_effect=self.logged),
            patch.object(diagnostic, 'device_evidence', side_effect=self.device)]
        for context in self.patches:
            context.start()
            self.addCleanup(context.stop)

    def checked(self, root):
        diagnostic.require(diagnostic.matrix.sha256(root/'settings.cfg') == self.source['files_sha256']['settings.cfg'], 'settings source changed')
        return self.source

    def logged(self, command, cwd, logs, env, timeout, executable_sha256=None):
        logs.mkdir()
        (logs/'invocation.json').write_text(json.dumps({'command': list(map(str,command)), 'cwd': str(cwd), 'timeout': timeout}))
        (logs/'result.json').write_text('{"exit_code":0}')
        (logs/'stdout.log').write_text('')
        (logs/'stderr.log').write_text(''.join('Loaded Blender-authored viewmodel: fixture, selected '+clip+'\n' for clip in ('normal_ready','reload_current_wip','normal_walk_r1','ads_entry_r1','jump_takeoff')))
        self.calls.append(command)
        if command[0] == 'cargo':
            self.assertEqual(command, diagnostic.BUILD)
            executable = Path(env['CARGO_TARGET_DIR'])/'release/vector-range.exe'
            executable.parent.mkdir(parents=True)
            executable.write_bytes(str(cwd).encode())
        else:
            self.assertEqual(diagnostic.matrix.sha256(Path(command[0])), executable_sha256)
            self.assertIn('--renderer=dx12', command)
            self.assertIn('--force-fallback-adapter', command)
            self.assertFalse(any(s.startswith('--capture-hz=') for s in command))
            capture = Path(next(s.split('=',1)[1] for s in command if s.startswith('--output=')))
            identity = next(s.split('=',1)[1] for s in command if s.startswith('--capture-frame-witness='))
            capture.mkdir()
            image = Image.new('RGBA', diagnostic.authored.EXTENT, diagnostic.authored.BACKGROUND)
            image.paste(marker(identity=identity).crop((0,0,64,22)),(0,0))
            image.save(capture/'0000.png')
            metadata = {'backend':'Dx12','requested':'dx12','adapter':diagnostic.authored.WARP,
                        'width':960,'height':540,'frame_witness':{'schema':diagnostic.witness.SCHEMA,'frame_index':0,'capture_identity':identity}}
            (capture/'0000.png.json').write_text(json.dumps(metadata))
            for suffix in ('time','gameplay'):
                (capture/f'0000.png.{suffix}.json').write_text('{"time":0.0}')
        if self.mutation:
            self.mutation(command)

    def device(self, logs):
        return {'adapter': 'synthetic same device'}

    def run_checked(self):
        return diagnostic.run(self.root, self.output)

    def test_two_fresh_builds_then_complete_controls_preserve_visibility_failure(self):
        result = self.run_checked()
        self.assertTrue(result['diagnostic_completed'])
        self.assertFalse(result['visibility_gate_passed'])
        self.assertEqual(result['differing_pixels'],0)
        self.assertEqual(len(self.calls),4)
        self.assertEqual([c[0] for c in self.calls[:2]],['cargo','cargo'])
        self.assertEqual(len(list((self.output/'executables').glob('*.exe'))),2)
        self.assertTrue(json.loads((self.output/'final-input-check.json').read_text())['passed'])
        self.assertIn('foreground coverage', result['visibility']['resident-off']['visibility'][0]['error'])

    def assert_failed(self):
        with self.assertRaises((ValueError, OSError, subprocess.SubprocessError)):
            self.run_checked()
        self.assertFalse((self.output/'summary.json').exists())
        self.assertTrue((self.output/'failure.json').exists())

    def test_later_build_cannot_mutate_prior_source_exe_receipt_or_logs(self):
        for relative in ('resident-off-source/src/main.rs','executables/resident-off.exe','resident-off-source.json','resident-off-build/result.json'):
            with self.subTest(relative=relative):
                # Separate temporary flow per mutation.
                case = RunnerTests('test_two_fresh_builds_then_complete_controls_preserve_visibility_failure')
                case.setUp()
                try:
                    def mutate(command):
                        if len(case.calls)==2:
                            (case.output/relative).write_bytes(b'changed')
                    case.mutation=mutate
                    case.assert_failed()
                finally:
                    case.doCleanups()

    def test_extra_capture_file_or_directory_during_device_read_is_rejected(self):
        for directory in (False, True):
            with self.subTest(directory=directory):
                case=RunnerTests(); case.setUp()
                try:
                    def device(logs):
                        path=case.output/'resident-off/extra'
                        path.mkdir() if directory else path.write_text('extra')
                        return {}
                    with patch.object(diagnostic,'device_evidence',side_effect=device):
                        case.assert_failed()
                finally:
                    case.doCleanups()

    def test_later_process_cannot_mutate_prior_capture(self):
        def mutate(command):
            if len(self.calls)==4:
                (self.output/'resident-off/0000.png.time.json').write_text('{"time":1.0}')
        self.mutation=mutate
        self.assert_failed()

    def test_asset_or_settings_mutation_during_capture_is_rejected(self):
        def mutate(command):
            if len(self.calls)==3:
                (self.root/'assets/locomotion/asset.vrs').write_bytes(b'changed')
        self.mutation=mutate
        self.assert_failed()

    def test_final_check_failure_cannot_leave_success_summary(self):
        original=diagnostic.compare_sequences
        def compare(*args):
            result=original(*args)
            (self.root/'settings.cfg').write_text('changed')
            return result
        with patch.object(diagnostic,'compare_sequences',side_effect=compare):
            self.assert_failed()
        self.assertFalse(json.loads((self.output/'final-input-check.json').read_text())['passed'])

    def test_private_asset_and_compiler_fail_before_build(self):
        (self.root/'assets/weapons').mkdir()
        with self.assertRaisesRegex(ValueError,'private weapon'):
            self.run_checked()
        self.assertFalse(self.calls)
        (self.root/'assets/weapons').rmdir()
        self.compiler['rustc']='release: 1.98.1\n'
        with self.assertRaisesRegex(ValueError,'actual Rust'):
            self.run_checked()
        self.assertFalse(self.calls)

    def test_original_process_error_survives_failed_final_checks(self):
        def mutate(command):
            if len(self.calls)==3:
                (self.root/'assets/locomotion/asset.vrs').write_bytes(b'changed')
                raise subprocess.TimeoutExpired(command,3000)
        self.mutation=mutate
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_checked()
        failure=json.loads((self.output/'failure.json').read_text())
        final=json.loads((self.output/'final-input-check.json').read_text())
        self.assertEqual(failure['type'],'TimeoutExpired')
        self.assertFalse(final['passed'])
        self.assertIn('assets changed',final['error'])
        self.assertFalse((self.output/'summary.json').exists())


class OwnedCleanupTests(unittest.TestCase):
    def test_timeout_and_interruption_retain_cleanup_and_original_exception(self):
        for error in (subprocess.TimeoutExpired(['owned'],1), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temp:
                child=Mock()
                child.wait.side_effect=error
                output=Path(temp)/'process'
                with patch.object(diagnostic.native.sys,'platform','linux'), \
                     patch.object(diagnostic.native.subprocess,'Popen',return_value=child), \
                     patch.object(diagnostic.native.process,'_terminate_process_tree',return_value={'error':'retained cleanup problem'}) as cleanup:
                    with self.assertRaises(type(error)):
                        diagnostic.native.logged(['owned'],Path(temp),output,{},1)
                cleanup.assert_called_once_with(child)
                self.assertEqual(json.loads((output/'cleanup.json').read_text())['error'],'retained cleanup problem')
                self.assertEqual(json.loads((output/'failure.json').read_text())['type'],type(error).__name__)


if __name__ == '__main__':
    unittest.main()
