"""Synthetic fixtures/process mocks only; these tests never claim Windows execution."""

import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import run_dx12_smoke as smoke


class Dx12SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image = Image.new('RGBA', (960, 540), (36, 48, 61, 255))
        ImageDraw.Draw(image).rectangle((200, 100, 700, 400), fill=(90, 100, 110, 255))
        data = io.BytesIO()
        image.save(data, format='PNG')
        cls.png_bytes = data.getvalue()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.captures = self.root / 'captures'
        self.captures.mkdir()
        # An independent fixed fixture: 4 seconds plus 0.2-second tail,
        # inclusive zero-based samples at 30 Hz, three sidecars per image.
        for index in range(127):
            png = self.captures / f'{index:04}.png'
            png.write_bytes(self.png_bytes)
            Path(f'{png}.json').write_text(json.dumps({
                'backend': 'Dx12', 'adapter': 'Microsoft Basic Render Driver',
                'requested': 'dx12',
                'width': 960, 'height': 540}), encoding='utf-8')
            Path(f'{png}.time.json').write_text(json.dumps({
                'elapsed_seconds': index / 30, 'sampling_hz': 30,
                'normalized_phase': min(index / 120, 1),
                'simulation_ready_seconds': 2.4, 'visual_duration_seconds': 4}), encoding='utf-8')
            Path(f'{png}.gameplay.json').write_text(json.dumps({
                'simulation_time': index / 30, 'segment': 'fixture',
                'slot': None, 'phase': 'Inactive', 'normalized': 0, 'weight': 0,
                'placeholder': False, 'left_hand': None, 'right_hand': None,
                'left_owner': 'Base', 'right_owner': 'Base', 'obstruction': 0,
                'obstruction_raw': 0, 'fire_blocked': False, 'mounted': False,
                'position': [0, 0, 9], 'eye_height': 1.7, 'speed': 0,
                'grounded': True, 'look_sway_degrees': [0, 0], 'shots': 0}), encoding='utf-8')

    def edit(self, suffix, field, value):
        path = self.captures / f'0000.png{suffix}'
        record = json.loads(path.read_text(encoding='utf-8'))
        record[field] = value
        path.write_text(json.dumps(record), encoding='utf-8')

    def test_complete_synthetic_capture(self):
        result = smoke.validate_captures(self.captures)
        self.assertTrue(result['passed'])
        self.assertEqual(result['frames'], 127)
        self.assertEqual(result['backend'], 'Dx12')
        self.assertEqual(result['telemetry']['files'], 381)

    def test_missing_each_required_file(self):
        for suffix in ('', '.json', '.time.json', '.gameplay.json'):
            path = self.captures / f'0126.png{suffix}'
            data = path.read_bytes()
            path.unlink()
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                smoke.validate_captures(self.captures)
            path.write_bytes(data)

    def test_wrong_backend(self):
        for value in ('Vulkan', 'Gl', 'DX12', '', None):
            self.edit('.json', 'backend', value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                smoke.validate_captures(self.captures)

    def test_wrong_requested_renderer(self):
        for value in ('auto', 'vulkan', 'gl', None):
            self.edit('.json', 'requested', value)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'requested dx12'):
                smoke.validate_captures(self.captures)

    def test_wrong_adapter(self):
        for value in ('', ' ', 'unknown', 'NVIDIA GeForce', 'Microsoft Basic Render Driver\n', None):
            self.edit('.json', 'adapter', value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                smoke.validate_captures(self.captures)

    def test_bad_json(self):
        path = self.captures / '0000.png.json'
        for text in ('{', '{}', '{"backend":"Dx12","backend":"Dx12"}',
                     '{"value":NaN}', '{"value":1e9999}'):
            path.write_text(text, encoding='utf-8')
            with self.subTest(text=text), self.assertRaises(ValueError):
                smoke.validate_captures(self.captures)

    def test_bad_png(self):
        (self.captures / '0000.png').write_bytes(self.png_bytes[:64])
        with self.assertRaises(ValueError):
            smoke.validate_captures(self.captures)

    def test_wrong_extent(self):
        Image.new('RGBA', (20, 20)).save(self.captures / '0000.png')
        with self.assertRaisesRegex(ValueError, 'extent'):
            smoke.validate_captures(self.captures)

    def test_uniform_png(self):
        for color in ((36, 48, 61, 255), (168, 194, 199, 255), (30, 40, 50, 255)):
            Image.new('RGBA', (960, 540), color).save(self.captures / '0001.png')
            with self.subTest(color=color), self.assertRaisesRegex(ValueError, 'uniform'):
                smoke.validate_captures(self.captures)

    def test_non_sampled_invisible_frame_fails(self):
        with Image.open(io.BytesIO(self.png_bytes)) as image:
            image.putalpha(0)
            image.save(self.captures / '0001.png')
        with self.assertRaisesRegex(ValueError, 'foreground coverage'):
            smoke.validate_captures(self.captures)

    def test_near_uniform_wrong_background_fails(self):
        image = Image.new('RGBA', (960, 540), (168, 194, 199, 255))
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.save(self.captures / '0001.png')
        with self.assertRaisesRegex(ValueError, 'near-uniform'):
            smoke.validate_captures(self.captures)

    def test_incomplete_png_trailer_fails(self):
        (self.captures / '0001.png').write_bytes(self.png_bytes[:-1])
        with self.assertRaisesRegex(ValueError, 'truncated PNG'):
            smoke.validate_captures(self.captures)

    def test_extra_frame(self):
        (self.captures / '0127.png').write_bytes(self.png_bytes)
        with self.assertRaisesRegex(ValueError, 'unexpected capture set'):
            smoke.validate_captures(self.captures)

    def test_bad_timing(self):
        for field, value in [('elapsed_seconds', 0.1), ('sampling_hz', 60),
                             ('visual_duration_seconds', 3), ('elapsed_seconds', '0'),
                             ('elapsed_seconds', True)]:
            original = (self.captures / '0000.png.time.json').read_bytes()
            self.edit('.time.json', field, value)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                smoke.validate_captures(self.captures)
            (self.captures / '0000.png.time.json').write_bytes(original)

    def test_bad_gameplay(self):
        self.edit('.gameplay.json', 'simulation_time', None)
        with self.assertRaisesRegex(ValueError, 'simulation_time'):
            smoke.validate_captures(self.captures)

    def test_frozen_simulation_time_fails(self):
        path = self.captures / '0001.png.gameplay.json'
        record = json.loads(path.read_text())
        record['simulation_time'] = 0
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'incorrect simulation_time'):
            smoke.validate_captures(self.captures)

    def test_incomplete_or_polluted_telemetry_fields_fail(self):
        for suffix, field in (('.time.json', 'normalized_phase'), ('.gameplay.json', 'shots')):
            path = self.captures / f'0000.png{suffix}'
            original = path.read_text()
            record = json.loads(original)
            del record[field]
            path.write_text(json.dumps(record))
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'fields changed or incomplete'):
                smoke.validate_captures(self.captures)
            path.write_text(original)
            self.edit(suffix, 'backend', 'Dx12')
            with self.assertRaisesRegex(ValueError, 'fields changed or incomplete'):
                smoke.validate_captures(self.captures)
            path.write_text(original)

    def test_missing_or_contradictory_renderer_logs_fail(self):
        (self.root / 'stdout.log').write_text('')
        for log in ('', 'renderer requested=dx12 backend=Vulkan adapter=llvmpipe',
                    'renderer requested=dx12 backend=Dx12 adapter=NVIDIA GeForce',
                    'renderer requested=auto backend=Dx12 adapter=Microsoft Basic Render Driver'):
            (self.root / 'stderr.log').write_text(log)
            with self.subTest(log=log), self.assertRaisesRegex(ValueError, 'renderer identity'):
                smoke.validate_renderer_log(self.root)
        good = 'renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver'
        (self.root / 'stderr.log').write_text(good + '\n')
        self.assertEqual(smoke.validate_renderer_log(self.root), [good])
        (self.root / 'stdout.log').write_text('renderer requested=gl backend=Gl adapter=other')
        with self.assertRaises(ValueError):
            smoke.validate_renderer_log(self.root)

    def executable(self):
        path = self.root / 'vector-range.exe'
        path.write_bytes(b'synthetic process mock, not an executable')
        return path

    def test_missing_executable_never_launches(self):
        with patch.object(smoke.subprocess, 'run') as process:
            with self.assertRaisesRegex(ValueError, 'executable missing'):
                smoke.run(self.root / 'missing.exe', self.root, self.root / 'evidence', 1)
            process.assert_not_called()

    def test_stale_evidence_never_launches(self):
        with patch.object(smoke.subprocess, 'run') as process:
            with self.assertRaises(FileExistsError):
                smoke.run(self.executable(), self.root, self.captures, 1)
            process.assert_not_called()

    def test_nonzero_exit_preserves_failure(self):
        evidence = self.root / 'evidence'
        with patch.object(smoke.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7)):
            with self.assertRaisesRegex(ValueError, 'code 7'):
                smoke.run(self.executable(), self.root, evidence, 1)
        self.assertFalse(json.loads((evidence / 'failure.json').read_text())['passed'])
        self.assertFalse((evidence / 'summary.json').exists())

    def test_timeout_preserves_failure(self):
        evidence = self.root / 'evidence'
        with patch.object(smoke.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['game'], 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                smoke.run(self.executable(), self.root, evidence, 1)
        self.assertTrue((evidence / 'failure.json').is_file())
        self.assertFalse((evidence / 'summary.json').exists())

    def test_zero_exit_without_captures_fails(self):
        with patch.object(smoke.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaises(ValueError):
                smoke.run(self.executable(), self.root, self.root / 'evidence', 1)

    def test_command_is_actual_game_with_explicit_fallback(self):
        command = smoke.game_command(Path('vector-range.exe'), Path('captures'))
        self.assertEqual(command, [
            'vector-range.exe', '--renderer=dx12', '--force-fallback-adapter',
            '--no-update', '--procedural-weapon', '--reference-viewport',
            '--capture-sequence=gameplay-sway', '--capture-hz=30', '--output=captures'])

    def test_process_success_requires_validation(self):
        evidence = self.root / 'evidence'
        with patch.object(smoke.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as process:
            with patch.object(smoke, 'validate_captures', return_value={'passed': True}) as validate:
                with patch.object(smoke, 'validate_renderer_log', return_value=['synthetic']):
                    smoke.run(self.executable(), self.root, evidence, 123)
        validate.assert_called_once_with(evidence / 'captures')
        self.assertEqual(process.call_args.kwargs['timeout'], 123)
        self.assertEqual(process.call_args.kwargs['cwd'], self.root)
        self.assertTrue((evidence / 'summary.json').is_file())

    def test_actual_python_entry_point_success_and_wrong_api_with_mock_process(self):
        def process(command, **kwargs):
            destination = Path(next(arg.removeprefix('--output=') for arg in command if arg.startswith('--output=')))
            shutil.copytree(self.captures, destination)
            kwargs['stderr'].write(b'renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver\n')
            return subprocess.CompletedProcess(command, 0)

        executable = self.executable()
        for fail in (False, True):
            evidence = self.root / ('wrong-api' if fail else 'valid')
            if fail:
                self.edit('.json', 'backend', 'Vulkan')
            with patch.object(smoke.sys, 'platform', 'win32'), patch.object(smoke.subprocess, 'run', side_effect=process):
                with patch.object(smoke.sys, 'stdout', io.StringIO()), patch.object(smoke.sys, 'stderr', io.StringIO()):
                    status = smoke.main(['--executable', str(executable), '--root', str(self.root),
                                         '--evidence', str(evidence), '--timeout', '60'])
            self.assertEqual(status, 1 if fail else 0)
            self.assertEqual((evidence / 'summary.json').exists(), not fail)
            self.assertEqual((evidence / 'failure.json').exists(), fail)
            invocation = json.loads((evidence / 'invocation.json').read_text())
            self.assertRegex(invocation['executable_sha256'], r'^[0-9a-f]{64}$')

    def test_non_windows_entry_point_fails_without_launch(self):
        with patch.object(smoke.sys, 'platform', 'linux'), patch.object(smoke.subprocess, 'run') as process:
            with patch.object(smoke.sys, 'stderr', io.StringIO()):
                status = smoke.main(['--executable', str(self.executable()), '--evidence', str(self.root / 'evidence')])
        self.assertEqual(status, 1)
        process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
