import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import run_windows_gl_capture_contract as runner


class CaptureContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'captures'
        self.output.mkdir()
        for name, color in runner.EXPECTED.items():
            Image.new('RGBA', (64, 64), tuple(color)).save(self.output / name)
        self.report = {
            'schema': 'rust-duty-legacy-capture-neutrality/v1', 'status': 'passed',
            'backend': 'OpenGl', 'adapter': 'llvmpipe (test fixture)', 'extent': [64, 64],
            'channel_tolerance': 0, 'interior_pixels_per_capture': 3136,
            'captures': [str(self.output / name) for name in runner.EXPECTED],
        }
        self.save_report()

    def save_report(self):
        (self.output / 'report.json').write_text(json.dumps(self.report))

    def test_fixed_pixels_valid_control(self):
        result = runner.validate_outputs(self.output)
        self.assertIs(result['passed'], True)
        self.assertEqual(result['interior_pixels_checked'], 15680)
        self.assertEqual(len(result['png_sha256']), 5)

    def test_unrepaired_capture_modulation_fails(self):
        Image.new('RGBA', (64, 64), (102, 25, 13, 255)).save(self.output / 'warm-after.png')
        with self.assertRaisesRegex(ValueError, 'fixed expected'):
            runner.validate_outputs(self.output)

    def test_one_wrong_interior_channel_is_not_tolerated(self):
        path = self.output / 'cool-after.png'
        with Image.open(path) as image:
            image.putpixel((32, 32), (128, 127, 128, 255))
            image.save(path)
        with self.assertRaisesRegex(ValueError, 'fixed expected'):
            runner.validate_outputs(self.output)

    def test_wrong_extent_or_alpha_format_fails(self):
        path = self.output / 'baseline.png'
        for mode, size in [('RGBA', (1, 1)), ('RGB', (64, 64))]:
            with self.subTest(mode=mode, size=size):
                Image.new(mode, size).save(path)
                with self.assertRaisesRegex(ValueError, '64x64 RGBA PNG'):
                    runner.validate_outputs(self.output)

    def test_missing_or_extra_output_fails(self):
        (self.output / 'extra.txt').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'exactly five'):
            runner.validate_outputs(self.output)
        (self.output / 'extra.txt').unlink()
        (self.output / 'baseline.png').unlink()
        with self.assertRaisesRegex(ValueError, 'exactly five'):
            runner.validate_outputs(self.output)

    def test_wrong_identity_or_probe_contract_fails(self):
        for key, value in [('schema', 'other'), ('status', 'failed'), ('backend', 'Dx12'),
                           ('adapter', 'other GPU'), ('channel_tolerance', 1),
                           ('interior_pixels_per_capture', 1), ('extent', [65, 64])]:
            with self.subTest(key=key):
                original = self.report[key]
                self.report[key] = value
                self.save_report()
                with self.assertRaises(ValueError):
                    runner.validate_outputs(self.output)
                self.report[key] = original
        self.save_report()

    def test_stale_capture_paths_fail(self):
        self.report['captures'][0] = str(self.root / 'stale.png')
        self.save_report()
        with self.assertRaisesRegex(ValueError, 'paths or order'):
            runner.validate_outputs(self.output)

    def test_symlinked_png_is_rejected(self):
        path = self.output / 'baseline.png'
        other = self.root / 'outside.png'
        path.rename(other)
        try:
            path.symlink_to(other)
        except OSError as error:
            self.skipTest(f'host cannot create symlinks: {error}')
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            runner.validate_outputs(self.output)

    def test_nonwindows_fails_before_native_execution(self):
        with patch.object(runner.sys, 'platform', 'linux'), patch.object(runner.authored, 'execute') as execute:
            with self.assertRaisesRegex(ValueError, 'native Windows'):
                runner.run(self.root / 'fixture.exe', self.root, self.root, self.root / 'evidence')
            execute.assert_not_called()

    def run_mock(self, fail_process=False, change_executable=False):
        exe = self.root / 'fixture.exe'
        exe.write_bytes(b'test executable')
        runtime = self.root / 'mesa'
        runtime.mkdir()
        def stage(executable, _, manifest, destination):
            destination.mkdir()
            (destination / 'vector-range.exe').write_bytes(executable.read_bytes())
            return {'loaded_modules_verified': False}
        def execute(command, root, logs, timeout):
            self.assertEqual(command[1], '--output-dir')
            self.assertEqual(os.environ['GALLIUM_DRIVER'], 'llvmpipe')
            destination = Path(command[2])
            self.output.rename(destination)
            self.output = destination
            self.report['captures'] = [str(destination / name) for name in runner.EXPECTED]
            self.save_report()
            logs.mkdir()
            (logs / 'process.json').write_text(json.dumps({
                'status': 'failed' if fail_process else 'passed', 'pid': 123,
                'exit_code': 1 if fail_process else 0}))
            (logs / 'invocation.json').write_text(json.dumps({'command': command, 'cwd': str(root)}))
            (logs / 'stderr.log').write_text('')
            if change_executable:
                exe.write_bytes(b'changed executable')
            if fail_process:
                raise ValueError('process exited 1')
            (logs / 'stdout.log').write_text(f"Legacy capture neutrality passed on {self.report['adapter']}\n")
        evidence = self.root / 'evidence'
        with patch.object(runner.sys, 'platform', 'win32'), \
             patch.object(runner.subprocess, 'check_output', return_value='a'*40), \
             patch.object(runner.subprocess, 'run'), \
             patch.object(runner, 'stage_runtime', side_effect=stage), \
             patch.object(runner.authored, 'execute', side_effect=execute), \
             patch.object(runner, 'validate_runtime'), patch.dict(os.environ, {'GITHUB_SHA': 'a'*40}):
            return runner.run(exe, self.root, runtime, evidence)

    def test_bound_native_wrapper_checks_real_process_receipt(self):
        result = self.run_mock()
        self.assertIs(result['passed'], True)
        self.assertIs(result['native_execution'], True)
        self.assertIs(result['loaded_modules_verified'], False)
        self.assertEqual(result['source_commit'], 'a'*40)
        self.assertTrue((self.root / 'evidence/summary.json').is_file())

    def test_failed_native_process_retains_failure_and_executed_identity(self):
        with self.assertRaisesRegex(ValueError, 'process exited 1'):
            self.run_mock(fail_process=True)
        report = json.loads((self.root / 'evidence/summary.json').read_text())
        self.assertIs(report['passed'], False)
        self.assertIs(report['native_execution'], True)
        self.assertIs(report['pixel_checks_passed'], False)
        self.assertEqual(report['process_status'], 'failed')

    def test_changed_executable_is_not_a_native_pass(self):
        with self.assertRaisesRegex(ValueError, 'executable changed'):
            self.run_mock(change_executable=True)
        report = json.loads((self.root / 'evidence/summary.json').read_text())
        self.assertIs(report['passed'], False)
        self.assertIs(report['native_execution'], True)
        self.assertIs(report['pixel_checks_passed'], False)


if __name__ == '__main__':
    unittest.main()
