"""Original synthetic fixtures exercise the real capture-verification CLI."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('verify_capture_telemetry.py')


class CaptureTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.legacy = self.root / 'legacy'
        self.candidate = self.root / 'candidate'
        for folder in (self.legacy, self.candidate):
            folder.mkdir()
            self.write(folder, 'sequence/0000.png.gameplay.json', {
                'tick': 0, 'position': [1.25, 0, -2], 'firing': False,
                'state': {'route': 'ready', 'owner': None},
            })
            self.write(folder, 'sequence/0000.png.time.json', {'elapsed': 0, 'hz': 30})
            self.write(folder, 'sequence/0001.png.gameplay.json', {'tick': 4})
            self.write(folder, 'sequence/0001.png.time.json', {'elapsed': 0.125, 'hz': 30})

    def write(self, folder, name, value, raw=False):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if raw else json.dumps(value), encoding='utf-8')
        return path

    def run_cli(self, *args, passes=True, message=None):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                                capture_output=True, text=True, check=False)
        if passes:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['passed'])
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('Traceback', result.stderr)
            if message:
                self.assertIn(message, result.stderr)
        return result

    def parity(self, **kwargs):
        return self.run_cli('compare', self.legacy, self.candidate, **kwargs)

    def test_equal_nested_records_pass_without_modifying_inputs(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*.json')}
        result = json.loads(self.parity().stdout)
        self.assertEqual(result['files'], 4)
        self.assertEqual(result['gameplay_files'], 2)
        self.assertEqual(result['time_files'], 2)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.json')})

    def test_order_and_formatting_do_not_change_parity(self):
        self.write(self.candidate, 'sequence/0000.png.time.json', ' {"hz":30, "elapsed":0}\n', raw=True)
        self.parity()

    def test_missing_extra_and_renamed_files_fail(self):
        path = self.candidate / 'sequence/0001.png.time.json'
        path.unlink()
        self.parity(passes=False, message='missing=')
        self.write(self.candidate, 'sequence/0001.png.time.json', {'elapsed': 0.125, 'hz': 30})
        self.write(self.candidate, 'other/0001.png.time.json', {'elapsed': 0.125, 'hz': 30})
        self.parity(passes=False, message="extra=['other/")
        path.unlink()
        self.parity(passes=False, message="missing=['sequence/")

    def test_missing_or_extra_fields_fail_including_nested(self):
        for value in ({'tick': 4, 'new': 1}, {'other': 4}):
            with self.subTest(value=value):
                self.write(self.candidate, 'sequence/0001.png.gameplay.json', value)
                self.parity(passes=False, message='fields differ')
        self.write(self.candidate, 'sequence/0001.png.gameplay.json', {'tick': 4})
        self.write(self.candidate, 'sequence/0000.png.gameplay.json', {
            'tick': 0, 'position': [1.25, 0, -2], 'firing': False,
            'state': {'route': 'ready'},
        })
        self.parity(passes=False, message="['state']")

    def test_value_array_and_type_changes_fail(self):
        for value in (5, True, 4.0, '4', None, [4], {'v': 4}):
            with self.subTest(value=value):
                self.write(self.candidate, 'sequence/0001.png.gameplay.json', {'tick': value})
                self.parity(passes=False, message='differs')
        for before, after in (([0, 1], [0]), ([0, 1], [1, 0])):
            self.write(self.legacy, 'sequence/0001.png.gameplay.json', {'tick': before})
            self.write(self.candidate, 'sequence/0001.png.gameplay.json', {'tick': after})
            self.parity(passes=False, message='differs')

    def test_sub_float_precision_changes_are_not_rounded_away(self):
        for before, after in (('0.100000000000000001', '0.100000000000000002'),
                              ('1e-9999', '2e-9999')):
            self.write(self.legacy, 'sequence/0001.png.gameplay.json', '{"x":' + before + '}', raw=True)
            self.write(self.candidate, 'sequence/0001.png.gameplay.json', '{"x":' + after + '}', raw=True)
            self.parity(passes=False, message='value differs')

    def test_renderer_metadata_is_never_ignored_by_parity(self):
        for folder, backend in ((self.legacy, 'Gl'), (self.candidate, 'Vulkan')):
            self.write(folder, 'sequence/0001.png.gameplay.json',
                       {'tick': 4, 'backend': backend, 'adapter': 'fixture'})
        self.parity(passes=False, message="['backend']")

    def test_invalid_json_and_roots_fail_even_when_identical(self):
        values = ('{', 'null', '[]', '"text"', '42', '{}', '{"x":1,"x":1}',
                  '{"nested":{"x":1,"x":2}}', '{"x":1} trailing')
        for raw in values:
            with self.subTest(raw=raw):
                for folder in (self.legacy, self.candidate):
                    self.write(folder, 'sequence/0001.png.gameplay.json', raw, raw=True)
                self.parity(passes=False)

    def test_nested_nonfinite_and_overflow_numbers_fail_on_both_sides(self):
        for folder in (self.legacy, self.candidate):
            for value in ('NaN', 'Infinity', '-Infinity', '1e9999', '-1e9999'):
                with self.subTest(folder=folder, value=value):
                    self.write(folder, 'sequence/0001.png.gameplay.json',
                               '{"state":[{"number":' + value + '}]}', raw=True)
                    self.parity(passes=False, message='non-finite')
                    self.run_cli('validate', folder, passes=False, message='non-finite')
            self.write(folder, 'sequence/0001.png.gameplay.json', {'tick': 4})

    def test_empty_missing_and_non_directory_inputs_fail(self):
        empty = self.root / 'empty'
        empty.mkdir()
        plain = self.root / 'file'
        plain.write_text('x')
        for path in (empty, self.root / 'absent', plain):
            self.run_cli('compare', path, path, passes=False)
            self.run_cli('validate', path, passes=False)
        self.run_cli('compare', passes=False)

    def test_metadata_validation_is_separate_and_glob_selectable(self):
        self.write(self.candidate, 'sequence/0000.png.json',
                   {'backend': 'Vulkan', 'adapter': 'software fixture'})
        self.run_cli('validate', self.candidate, '--expected-backend', 'Vulkan')
        self.run_cli('validate', self.candidate, '--expected-backend', 'Dx12', passes=False, message='backend')
        self.parity()  # Capture-only metadata is outside deterministic sidecars.
        self.run_cli('validate', self.candidate, '--require-renderer', '--renderer-glob', '*.time.json',
                     passes=False, message='backend')
        self.run_cli('validate', self.candidate, '--require-renderer', '--renderer-glob', 'missing*.json',
                     passes=False, message='at least one')

    def test_missing_and_malformed_metadata_fail(self):
        self.run_cli('validate', self.candidate, '--require-renderer', passes=False, message='at least one')
        for value in ({'width': 960}, {'backend': '', 'adapter': 'fixture'},
                      {'backend': 'Vulkan', 'adapter': '  '},
                      {'backend': 'Vulkan', 'adapter': 4}):
            self.write(self.candidate, 'sequence/0000.png.json', value)
            self.run_cli('validate', self.candidate, '--require-renderer', passes=False, message='nonblank')

    def test_finite_validation_inspects_other_json_too(self):
        self.write(self.candidate, 'pose.json', '{"position":[1e9999]}', raw=True)
        self.run_cli('validate', self.candidate, passes=False, message='non-finite')

    def test_invalid_encoding_and_extreme_nesting_fail_cleanly(self):
        path = self.candidate / 'sequence/0001.png.gameplay.json'
        path.write_bytes(b'\xff')
        self.parity(passes=False)
        path.write_text('{"x":' + '[' * 2000 + '0' + ']' * 2000 + '}')
        self.parity(passes=False)
        path.write_text('{"x":1e-999999999999999999999}')
        self.parity(passes=False, message='parser limits')

    def test_symlinks_and_json_directories_fail(self):
        link = self.candidate / 'linked'
        try:
            link.symlink_to(self.legacy, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable on this platform')
        self.parity(passes=False, message='symbolic link')
        link.unlink()
        (self.candidate / 'bad.time.json').mkdir()
        self.parity(passes=False, message='not a file')


if __name__ == '__main__':
    unittest.main()
