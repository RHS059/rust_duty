import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import run_windows_gl_game_ui as runner
import test_dx12_game_ui_fixture as ui_fixture


class GlUiProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exe = self.root / 'fixture.exe'; self.exe.write_bytes(b'original-executable')
        self.runtime = self.root / 'runtime'; self.runtime.mkdir()
        self.manifest = self.root / 'lock.json'; self.manifest.write_text('{}')
        self.output = self.root / 'output'; self.evidence = self.root / 'evidence'
        self.adapter = 'llvmpipe (LLVM test)'

    def execute(self, argv, root, process, timeout):
        self.assertEqual(argv[1:], ['--renderer=gl', '--output-dir', str(self.output)])
        self.assertEqual(os.environ['GALLIUM_DRIVER'], 'llvmpipe')
        process.mkdir(parents=True)
        (process / 'stdout.log').write_text('')
        (process / 'stderr.log').write_text(f'renderer requested=gl backend=OpenGl adapter={self.adapter}\n')
        (process / 'process.json').write_text(json.dumps({'status':'passed','pid':123}))
        self.output.mkdir()
        (self.output / 'game-ui-contract-report.json').write_text(json.dumps({'requested':'gl','backend':'OpenGl','adapter':self.adapter,'platform':'windows'}))

    def run_mock(self, execute=None, validator=None):
        with patch.object(runner.sys, 'platform', 'win32'), patch.object(runner, 'validate_runtime', return_value={'pin':'same'}), patch.object(runner.subprocess, 'check_output', return_value='a'*40), patch.object(runner, 'execute', side_effect=execute or self.execute), patch.object(runner, 'validate_outputs', side_effect=validator or (lambda *_: {'passed':True})), patch.dict(os.environ, {'GITHUB_SHA':'a'*40, 'GALLIUM_DRIVER':'prior'}):
            return runner.run(self.exe, self.runtime, self.manifest, self.root, self.evidence, self.output)

    def test_bound_positive_and_environment_restored(self):
        before = os.environ.get('GALLIUM_DRIVER')
        report = self.run_mock()
        self.assertIs(report['passed'], True)
        self.assertEqual(report['source_commit'], 'a'*40)
        self.assertEqual(report['executable_sha256'], runner.digest(self.exe))
        self.assertIs(report['loaded_modules_verified'], False)
        self.assertEqual(os.environ.get('GALLIUM_DRIVER'), before)

    def full_fixture(self, platform):
        """Use all production pixel/schema checks; only native execution is mocked."""
        fixture = ui_fixture.GameUiFixtureTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for percent in ui_fixture.fixture.SCALES:
            for case in ui_fixture.fixture.CASES:
                fixture.edit(f'{case}-{percent}.png.json', requested='gl', backend='OpenGl', adapter=self.adapter)
        fixture.sync_report()
        fixture.edit(ui_fixture.fixture.REPORT, requested='gl', backend='OpenGl', adapter=self.adapter,
                     force_fallback_adapter=False, platform=platform)

        def execute(*args):
            self.execute(*args)
            for path in fixture.output.iterdir():
                shutil.copyfile(path, self.output / path.name)
        return fixture, execute

    def test_full_windows_fixture_passes_real_pixel_validator(self):
        _, execute = self.full_fixture('windows')
        result = self.run_mock(execute=execute, validator=runner.validate_outputs)
        self.assertIs(result['passed'], True)
        self.assertEqual(result['pixels']['captures'], 18)

    def test_linux_fixture_cannot_become_windows_native_evidence(self):
        fixture, execute = self.full_fixture('linux')
        # The generic GL validator intentionally accepts Linux. This wrapper
        # must still bind the emitted platform to its Windows-only process.
        self.assertIs(runner.validate_outputs(fixture.output, 'gl')['passed'], True)
        with self.assertRaisesRegex(ValueError, 'Windows fixture report'):
            self.run_mock(execute=execute, validator=runner.validate_outputs)
        report = json.loads((self.evidence / 'windows-gl-game-ui-report.json').read_text())
        self.assertIs(report['passed'], False)
        self.assertIs(report['pixel_checks_passed'], False)

    def test_wrong_startup_backend_rejected(self):
        def execute(*args):
            self.execute(*args)
            (self.evidence / 'process/stderr.log').write_text('renderer requested=dx12 backend=Dx12 adapter=wrong\n')
        with self.assertRaisesRegex(ValueError, 'startup renderer identity'):
            self.run_mock(execute)
        self.assertIs(json.loads((self.evidence / 'windows-gl-game-ui-report.json').read_text())['passed'], False)

    def test_named_hardware_adapter_does_not_replace_pinned_software(self):
        self.adapter = 'unverified hardware'
        with self.assertRaisesRegex(ValueError, 'llvmpipe UI identity'):
            self.run_mock()

    def test_failed_pixels_do_not_pass(self):
        with self.assertRaisesRegex(ValueError, 'pixel validator'):
            self.run_mock(validator=lambda *_: {'passed':False})

    def test_modified_executable_rejected(self):
        def validate(*args):
            self.exe.write_bytes(b'changed')
            return {'passed':True}
        with self.assertRaisesRegex(ValueError, 'executable changed'):
            self.run_mock(validator=validate)

    def test_stale_output_rejected_before_process(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'fresh separate'):
            self.run_mock()

    def test_dangling_staged_executable_link_is_preserved(self):
        staged = self.runtime / 'game_ui_contract.exe'
        target = self.root / 'must-not-create.exe'
        try:
            staged.symlink_to(target)
        except OSError as error:
            self.skipTest(f'host cannot create symlinks: {error}')
        original = staged.readlink()
        with self.assertRaises(FileExistsError):
            self.run_mock()
        self.assertTrue(staged.is_symlink())
        self.assertEqual(staged.readlink(), original)
        self.assertFalse(target.exists())
        self.assertFalse(self.output.exists())
        report = json.loads((self.evidence / 'windows-gl-game-ui-report.json').read_text())
        self.assertIs(report['passed'], False)
        self.assertIs(report['native_execution'], False)

    def test_oversized_executable_rejected_before_evidence_or_staging(self):
        with patch.object(runner, 'MAX_EXECUTABLE_BYTES', self.exe.stat().st_size - 1):
            with self.assertRaisesRegex(ValueError, 'executable size'):
                self.run_mock()
        self.assertFalse(self.evidence.exists())
        self.assertFalse((self.runtime / 'game_ui_contract.exe').exists())

    def test_executable_growth_after_preflight_is_bounded(self):
        original_digest = runner.digest
        original_size = self.exe.stat().st_size
        def grow_after_hash(path):
            result = original_digest(path)
            if Path(path) == self.exe:
                self.exe.write_bytes(self.exe.read_bytes() + b'x')
            return result
        with patch.object(runner, 'MAX_EXECUTABLE_BYTES', original_size), \
             patch.object(runner, 'digest', side_effect=grow_after_hash):
            with self.assertRaisesRegex(ValueError, 'size changed'):
                self.run_mock()
        self.assertFalse((self.runtime / 'game_ui_contract.exe').exists())
        self.assertFalse(self.output.exists())
        report = json.loads((self.evidence / 'windows-gl-game-ui-report.json').read_text())
        self.assertIs(report['passed'], False)
        self.assertIs(report['native_execution'], False)

    def test_nonwindows_is_not_a_native_pass(self):
        with patch.object(runner.sys, 'platform', 'linux'), self.assertRaisesRegex(ValueError, 'requires Windows'):
            runner.run(self.exe, self.runtime, self.manifest, self.root, self.evidence, self.output)
        self.assertFalse(self.evidence.exists())


if __name__ == '__main__':
    unittest.main()
