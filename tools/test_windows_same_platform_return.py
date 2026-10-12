"""Synthetic native-process mocks only; no Windows/GPU acceptance claim."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import run_windows_same_platform_return as runner
import verify_reload_return_capture as return_validator


class SamePlatformReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image = Image.new('RGBA', (960, 540), (36, 48, 61, 255))
        ImageDraw.Draw(image).rectangle((200, 100, 700, 420), fill=(120, 90, 60, 255))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        cls.png = buffer.getvalue()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.executable = self.root / 'built/vector-range.exe'
        self.executable.parent.mkdir()
        self.executable.write_bytes(b'MZ synthetic combined executable, never executed')
        self.runtime = self.root / 'mesa'
        self.runtime.mkdir()
        dll = self.runtime / 'opengl32.dll'
        dll.write_bytes(b'original synthetic pinned DLL')
        license = self.runtime / 'licenses/synthetic/COPYING'
        license.parent.mkdir(parents=True)
        license.write_bytes(b'original synthetic pinned license')
        self.manifest = self.root / 'runtime-lock.json'
        self.write(self.manifest, {'schema': 'rust-duty-windows-gl-reference/v1',
                    'architecture': 'x86_64', 'runtime_environment': runner.ENVIRONMENT,
                    'dlls': [{'dll': dll.name, 'size': dll.stat().st_size, 'sha256': runner.authored.sha256(dll)}],
                    'packages': [{'name': 'synthetic', 'licenses': [{'member': 'ucrt64/share/licenses/synthetic/COPYING',
                                  'size': license.stat().st_size, 'sha256': runner.authored.sha256(license)}]}]})
        self.write(self.runtime / 'staging-receipt.json',
                   {'schema': 'rust-duty-windows-gl-reference-staging/v1',
                    'manifest_sha256': runner.authored.sha256(self.manifest)})
        (self.root / 'settings.cfg').write_text('# unchanged synthetic settings\n')
        (self.root / 'assets').mkdir()
        (self.root / 'assets/animations.cfg').write_text('# synthetic five-pack bindings\n')
        for name in ('reload', 'walk', 'ads', 'directional', 'jump'):
            folder = self.root / 'assets' / name
            folder.mkdir()
            for suffix in ('vra', 'vrs', 'vrm'):
                (folder / f'asset.{suffix}').write_bytes(f'synthetic {name} {suffix}'.encode())
        validator = self.root / 'tools/verify_reload_return_capture.py'
        validator.parent.mkdir()
        validator.write_bytes(Path(return_validator.__file__).read_bytes())
        self.evidence = self.root / 'evidence'
        self.env = {'GITHUB_REPOSITORY': 'RHS059/rust_duty', 'GITHUB_SHA': 'a' * 40,
                    'GITHUB_RUN_ID': '80', 'GITHUB_RUN_NUMBER': '9', 'GITHUB_RUN_ATTEMPT': '2',
                    'GITHUB_REF_NAME': 'test/same-platform'}
        self.commands = []
        self.mutate_capture = None

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def sequence(self, folder, backend, count=391):
        folder.mkdir(parents=True)
        adapter = 'llvmpipe (LLVM 22.1.8, 256 bits)' if backend == 'OpenGl' else runner.authored.WARP
        for i in range(count):
            image = folder / f'{i:04}.png'
            image.write_bytes(self.png)
            self.write(Path(f'{image}.json'), {'backend': backend, 'requested': 'gl' if backend == 'OpenGl' else 'dx12',
                       'adapter': adapter, 'width': 960, 'height': 540, 'hfov': 90.0, 'ads': 0.0, 'reload_phase': None})
            self.write(Path(f'{image}.time.json'), {'elapsed_seconds': i / 60, 'sampling_hz': 60})
            start = next((a for a, b in ((100, 112), (200, 206), (250, 262)) if a <= i < b), None)
            active = next((a for a, b in ((10, 100), (170, 200), (206, 250)) if a <= i < b), None)
            weight = (i - start + 1) / 13 if start is not None else None
            self.write(Path(f'{image}.gameplay.json'), {
                'simulation_time': i / 60, 'route': 'reload.return' if start is not None else 'reload.tactical' if active is not None else 'ready',
                'return_weight': weight, 'extra_actor_opacity': 1 - weight if weight is not None else 1 if active is not None else 0,
                'anchor': [0, 0, -0.3], 'renderer_failed': False, 'walk_weight': 0.5, 'run_weight': 0.5, 'visual_ads': 0,
                'native_reload_seconds': (i - active + 1) / 60 if active is not None else None, 'native_reload_duration': 1.5,
                'ammo': 12, 'reserve': 90, 'shots': 0})
        return adapter

    def fake_execute(self, command, root, logs, timeout, **kwargs):
        self.commands.append((command, root, timeout, dict(runner.ENVIRONMENT)))
        logs.mkdir(parents=True, exist_ok=False)
        self.write(logs / 'invocation.json', {'command': command, 'cwd': str(root), 'timeout_seconds': timeout})
        self.write(logs / 'process.json', {'schema': 'rust-duty-capture-process/v1', 'status': 'passed', 'pid': 12345,
                                        'exit_code': 0, 'elapsed_seconds': 1, 'timeout_seconds': timeout})
        context = runner.build_identity.context()
        stdout, stderr = '', ''
        if command[-1] == '--build-version':
            stdout = context['version'] + '\n'
        elif command[-1] == '--build-label':
            stdout = context['display_version'] + '\n'
        elif command[0] == sys.executable:
            return_validator.verify(Path(command[-1]))  # The existing validator, unchanged.
        else:
            folder = Path(next(a.split('=', 1)[1] for a in command if a.startswith('--output=')))
            backend = 'OpenGl' if '--renderer=gl' in command else 'Dx12'
            adapter = self.sequence(folder, backend)
            request = 'gl' if backend == 'OpenGl' else 'dx12'
            stderr = f'renderer requested={request} backend={backend} adapter={adapter}\n'
            if backend == 'Dx12':
                stderr += runner.authored.FXC_LOG + '\n'
            if self.mutate_capture:
                self.mutate_capture(folder, backend)
        (logs / 'stdout.log').write_text(stdout)
        (logs / 'stderr.log').write_text(stderr)
        return {'exit_code': 0}

    def run_mock(self, *, images=False, **overrides):
        values = dict(executable=self.executable, runtime=self.runtime, manifest=self.manifest,
                      root=self.root, evidence=self.evidence, timeout=20, run_timeout=120)
        values.update(overrides)
        assets = {'generated_verification': {'synthetic': True}, 'runtime_and_manifest_sha256': runner.input_hashes(self.root)}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(runner.sys, 'platform', 'win32'))
            stack.enter_context(patch.dict(os.environ, self.env))
            stack.enter_context(patch.object(runner.subprocess, 'check_output', return_value='a' * 40 + '\n'))
            stack.enter_context(patch.object(runner.authored, 'asset_evidence', return_value=assets))
            stack.enter_context(patch.object(runner.authored, 'execute', side_effect=self.fake_execute))
            if not images:
                stack.enter_context(patch.object(runner.authored, 'verify_png', return_value={'foreground_coverage': 0.1}))
            return runner.run(**values)

    def test_one_binary_both_exact_commands_and_real_guard_control(self):
        before = runner.input_hashes(self.root)
        report = self.run_mock(images=True)
        self.assertTrue(report['passed'], report.get('error'))
        self.assertFalse(report['pixel_binding_proven'])
        self.assertFalse(report['acceptance_complete'])
        self.assertFalse(report['loaded_modules_verified'])
        captures = [c[0] for c in self.commands if '--capture-sequence=gameplay-return' in c[0]]
        self.assertEqual(len(captures), 2)
        self.assertEqual(captures[0][0], captures[1][0])
        for command in captures:
            self.assertIn('--capture-hz=60', command)
            self.assertIn(f'--settings={self.root / "settings.cfg"}', command)
            self.assertIn(f'--animation-manifest={self.root / "assets/animations.cfg"}', command)
            self.assertIn('--no-update', command)
        self.assertIn('--renderer=gl', captures[0])
        self.assertNotIn('--force-fallback-adapter', captures[0])
        self.assertIn('--renderer=dx12', captures[1])
        self.assertIn('--force-fallback-adapter', captures[1])
        self.assertEqual(report['parity']['gameplay_files'], 391)
        self.assertEqual(report['parity']['time_files'], 391)
        self.assertEqual(report['parity']['capture_metadata_files'], 391)
        for name in ('gl', 'dx12'):
            self.assertEqual(report['captures'][name]['frames'], 391)
            self.assertEqual(len(report['captures'][name]['files_sha256']), 391 * 4 + 1)
        self.assertEqual(runner.input_hashes(self.root), before)
        self.assertEqual((self.evidence / 'runtime/licenses/synthetic/COPYING').read_bytes(),
                         (self.runtime / 'licenses/synthetic/COPYING').read_bytes())

    def test_non_windows_and_existing_output_fail_before_native_action(self):
        with patch.object(runner.sys, 'platform', 'linux'), self.assertRaisesRegex(ValueError, 'Windows'):
            runner.run(self.executable, self.runtime, self.manifest, self.root, self.evidence)
        self.evidence.mkdir()
        sentinel = self.evidence / 'keep'
        sentinel.write_text('untouched')
        with self.assertRaisesRegex(ValueError, 'existing'):
            self.run_mock()
        self.assertEqual(sentinel.read_text(), 'untouched')
        self.assertFalse(self.commands)

    def test_invalid_timeout_fails_before_evidence(self):
        for field in ('timeout', 'run_timeout'):
            for value in (0, -1, True, float('nan'), float('inf')):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.run_mock(**{field: value})
        self.assertFalse(self.evidence.exists())
        self.assertFalse(self.commands)

    def test_runtime_pin_corruption_never_launches(self):
        (self.runtime / 'opengl32.dll').write_bytes(b'changed DLL')
        report = self.run_mock()
        self.assertFalse(report['passed'])
        self.assertIn('differs from pin', report['error'])
        self.assertFalse(self.commands)
        self.assertTrue((self.evidence / runner.REPORT).is_file())

    def test_runtime_license_corruption_never_launches(self):
        (self.runtime / 'licenses/synthetic/COPYING').write_bytes(b'changed notice')
        report = self.run_mock()
        self.assertFalse(report['passed'])
        self.assertIn('license differs from pin', report['error'])
        self.assertFalse(self.commands)

    def test_exact_backend_request_adapter_hz_and_compiler_guards(self):
        folder = self.root / 'standalone'
        adapter = self.sequence(folder, 'OpenGl')
        logs = self.root / 'standalone-logs'
        logs.mkdir()
        (logs / 'stdout.log').write_text('')
        (logs / 'stderr.log').write_text(f'renderer requested=gl backend=OpenGl adapter={adapter}\n')
        path = folder / '0000.png.json'
        original = path.read_bytes()
        with patch.object(runner.authored, 'verify_png', return_value={'foreground_coverage': 0.1}):
            runner.validate_capture(folder, 'OpenGl', logs)
            for field, value in [('requested', 'auto'), ('adapter', 'hardware'), ('backend', 'Dx12')]:
                row = json.loads(original)
                row[field] = value
                self.write(path, row)
                with self.subTest(field=field), self.assertRaises(ValueError):
                    runner.validate_capture(folder, 'OpenGl', logs)
            path.write_bytes(original)
            timing = folder / '0000.png.time.json'
            old_time = timing.read_bytes()
            row = json.loads(old_time)
            row['sampling_hz'] = 59
            self.write(timing, row)
            with self.assertRaisesRegex(ValueError, '60 Hz'):
                runner.validate_capture(folder, 'OpenGl', logs)
            timing.write_bytes(old_time)
            (logs / 'stderr.log').write_text('renderer requested=gl backend=OpenGl adapter=wrong\n')
            with self.assertRaisesRegex(ValueError, 'startup renderer identity'):
                runner.validate_capture(folder, 'OpenGl', logs)
            for path in folder.glob('*.png.json'):
                row = json.loads(path.read_text())
                row.update(backend='Dx12', requested='dx12', adapter=runner.authored.WARP)
                self.write(path, row)
            identity = f'renderer requested=dx12 backend=Dx12 adapter={runner.authored.WARP}\n'
            for compiler in ('', 'renderer dx12_shader_compiler=Dxc\n'):
                (logs / 'stderr.log').write_text(identity + compiler)
                with self.subTest(compiler=compiler), self.assertRaises(ValueError):
                    runner.validate_capture(folder, 'Dx12', logs)

    def test_wrong_frame_count_and_api_are_rejected(self):
        def truncate(folder, backend):
            if backend == 'OpenGl':
                for path in folder.glob('0390.png*'):
                    path.unlink()
        self.mutate_capture = truncate
        report = self.run_mock()
        self.assertFalse(report['passed'])
        self.assertIn('391', report['error'])

    def test_tiny_anchor_difference_remains_strict_failure(self):
        def drift(folder, backend):
            if backend == 'Dx12':
                path = folder / '0101.png.gameplay.json'
                row = json.loads(path.read_text())
                row['anchor'][0] = 0.000000000000000001
                self.write(path, row)
        self.mutate_capture = drift
        report = self.run_mock()
        self.assertFalse(report['passed'])
        self.assertIn('anchor', report['error'])
        self.assertTrue(report['captures']['gl']['passed'])
        self.assertTrue(report['captures']['dx12']['passed'])
        self.assertTrue((self.evidence / 'captures/dx12/0101.png.gameplay.json').is_file())

    def test_settings_mutation_stops_before_second_backend(self):
        def mutate(folder, backend):
            (self.root / 'settings.cfg').write_text('changed settings')
        self.mutate_capture = mutate
        report = self.run_mock()
        self.assertFalse(report['passed'])
        self.assertIn('assets/settings changed', report['error'])
        self.assertEqual(sum('--capture-sequence=gameplay-return' in c[0] for c in self.commands), 1)

    def test_environment_restored_on_process_failure(self):
        def fail(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 1)
        self.fake_execute = fail
        with patch.dict(os.environ, {'GALLIUM_DRIVER': 'previous', 'LIBGL_ALWAYS_SOFTWARE': 'previous'}):
            report = self.run_mock()
            self.assertEqual(os.environ['GALLIUM_DRIVER'], 'previous')
            self.assertEqual(os.environ['LIBGL_ALWAYS_SOFTWARE'], 'previous')
        self.assertFalse(report['passed'])
        self.assertIn('TimeoutExpired', report['error'])
        self.assertTrue((self.evidence / runner.REPORT).is_file())

    def test_whole_run_budget_stops_before_launch(self):
        with patch.object(runner.time, 'monotonic', side_effect=[0, 0, 2, 2, 2]):
            report = self.run_mock(run_timeout=1)
        self.assertFalse(report['passed'])
        self.assertIn('budget exhausted', report['error'])
        self.assertFalse(self.commands)


if __name__ == '__main__':
    unittest.main()
