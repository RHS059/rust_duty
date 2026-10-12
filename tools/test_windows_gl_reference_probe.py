import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
import run_windows_gl_reference_probe as probe


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'process').mkdir()
        image = Image.new('RGBA', (960, 540), (36, 48, 61, 255))
        ImageDraw.Draw(image).rectangle((200, 200, 700, 450), fill=(180, 100, 40, 255))
        image.save(self.root / 'gl.png')
        self.metadata = {'requested': 'gl', 'backend': 'OpenGl', 'adapter': 'llvmpipe (LLVM 21.1.8, 256 bits)', 'width': 960, 'height': 540}
        self.write_metadata()
        self.log('renderer requested=gl backend=OpenGl adapter=' + self.metadata['adapter'])

    def write_metadata(self):
        (self.root / 'gl.png.json').write_text(json.dumps(self.metadata), encoding='utf-8')

    def log(self, text):
        (self.root / 'process/stdout.log').write_text(text + '\n', encoding='utf-8')
        (self.root / 'process/stderr.log').write_text('', encoding='utf-8')

    def test_valid_procedural_capture(self):
        self.assertEqual(probe.validate_capture(self.root)['backend'], 'OpenGl')

    def test_wrong_backend_request_adapter_and_extent_rejected(self):
        for key, value in [('backend', 'Dx12'), ('requested', 'auto'), ('adapter', 'Microsoft Basic Render Driver'), ('width', True), ('height', 541)]:
            with self.subTest(key=key):
                old = self.metadata[key]
                self.metadata[key] = value
                self.write_metadata()
                with self.assertRaises(ValueError):
                    probe.validate_capture(self.root)
                self.metadata[key] = old
        self.write_metadata()

    def test_missing_or_conflicting_renderer_logs_fail(self):
        for text in ['', 'renderer requested=gl backend=OpenGl adapter=other',
                     'renderer requested=gl backend=OpenGl adapter=' + self.metadata['adapter'] + '\nrenderer requested=dx12 backend=Dx12 adapter=other']:
            self.log(text)
            with self.assertRaises(ValueError):
                probe.validate_capture(self.root)

    def test_uniform_or_incomplete_capture_fails(self):
        Image.new('RGBA', (960, 540), (80, 80, 80, 255)).save(self.root / 'gl.png')
        with self.assertRaises(ValueError):
            probe.validate_capture(self.root)
        (self.root / 'gl.png').unlink()
        with self.assertRaises(ValueError):
            probe.validate_capture(self.root)

    def test_duplicate_json_fields_fail(self):
        (self.root / 'gl.png.json').write_text('{"backend":"OpenGl","backend":"Dx12"}')
        with self.assertRaises(ValueError):
            probe.validate_capture(self.root)

    def test_staging_receipt_and_pins(self):
        runtime = self.root / 'runtime'
        runtime.mkdir()
        dll = runtime / 'opengl32.dll'
        dll.write_bytes(b'original pinned bytes')
        manifest = self.root / 'lock.json'
        lock = {'schema': 'rust-duty-windows-gl-reference/v1', 'dlls': [{'dll': dll.name, 'size': dll.stat().st_size, 'sha256': probe.digest(dll)}]}
        manifest.write_text(json.dumps(lock))
        receipt = runtime / 'staging-receipt.json'
        receipt.write_text(json.dumps({'schema': 'rust-duty-windows-gl-reference-staging/v1', 'manifest_sha256': probe.digest(manifest)}))
        self.assertEqual(probe.validate_runtime(runtime, manifest)['dll_count'], 1)
        dll.write_bytes(b'tampered bytes')
        with self.assertRaises(ValueError):
            probe.validate_runtime(runtime, manifest)
        dll.write_bytes(b'original pinned bytes')
        (runtime / 'extra.dll').write_bytes(b'extra')
        with self.assertRaises(ValueError):
            probe.validate_runtime(runtime, manifest)
        (runtime / 'extra.dll').unlink()
        receipt.write_text('{}')
        with self.assertRaises(ValueError):
            probe.validate_runtime(runtime, manifest)

    def test_failed_capture_distinguishes_started_process_from_launch_failure(self):
        for pid in (123, None):
            with self.subTest(pid=pid):
                runtime = self.root / f'runtime-{pid}'
                runtime.mkdir()
                executable = self.root / f'game-{pid}.exe'
                executable.write_bytes(b'fixture executable')
                evidence = self.root / f'evidence-{pid}'
                def failed_process(command, root, logs, timeout):
                    logs.mkdir()
                    (logs / 'process.json').write_text(json.dumps({'pid': pid, 'status': 'failed'}))
                    raise ValueError('deliberate process failure')
                with patch.object(probe, 'os', SimpleNamespace(name='nt', environ={})), \
                     patch.object(probe, 'validate_runtime', return_value={'dll_count': 15}), \
                     patch.object(probe.subprocess, 'check_output', return_value='a' * 40), \
                     patch.object(probe, 'execute', side_effect=failed_process):
                    with self.assertRaisesRegex(ValueError, 'deliberate'):
                        probe.run(executable, runtime, self.root / 'manifest', self.root, evidence)
                report = json.loads((evidence / 'windows-gl-reference-report.json').read_text())
                self.assertTrue(report['execution_attempted'])
                self.assertEqual(report['native_execution'], pid is not None)
                self.assertFalse(report['capture_verified'])
                self.assertFalse(report['passed'])

    def test_non_windows_does_not_claim_native_execution(self):
        with patch.object(probe.os, 'name', 'posix'):
            with self.assertRaisesRegex(ValueError, 'Windows'):
                probe.run('missing', 'missing', 'missing', '.', 'missing')


if __name__ == '__main__':
    unittest.main()
