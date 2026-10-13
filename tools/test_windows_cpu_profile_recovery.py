import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import recover_windows_cpu_profile as recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.trace_pin = patch.object(recovery, 'TRACE_SHA256', hashlib.sha256(b'ETL fixture').hexdigest())
        self.trace_pin.start()
        self.addCleanup(self.trace_pin.stop)

    def fixture(self, root):
        original = root / 'original'
        original.mkdir()
        data = {name: b'fixture\n' for name in recovery.PINNED_REPORTS}
        exe, pdb = b'exe fixture', b'pdb fixture'
        hashes = {'exe_sha256': hashlib.sha256(exe).hexdigest(), 'pdb_sha256': hashlib.sha256(pdb).hexdigest()}
        capture = dict(source_commit=recovery.SOURCE, passed=False, exit_code=1,
                       initial_settings_sha256=hashlib.sha256(b'settings').hexdigest(),
                       pid=12, renderer_window_thread_id=34, error='20-second exit timeout', cleanup_errors=[], **hashes)
        data['capture.json'] = json.dumps(capture).encode()
        data['build.json'] = json.dumps(dict(source_commit=recovery.SOURCE, **hashes)).encode()
        data['source.json'] = json.dumps({'commit': recovery.SOURCE}).encode()
        data['game.log'] = (b'renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver\n'
                            b'window physical_extent_verified=1920x1080\nLoaded Blender-authored viewmodel: fixture\n')
        for name, raw in dict(data, **{'vector-range.exe': exe, 'vector_range.pdb': pdb,
                                      'cpu.etl': b'ETL fixture', 'runtime/settings.cfg': b'settings'}).items():
            path = original / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        pins = {name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()}
        return original, pins

    def test_exact_reports_binaries_and_complete_inventory_required(self):
        with tempfile.TemporaryDirectory() as directory:
            original, pins = self.fixture(Path(directory))
            with patch.object(recovery, 'PINNED_REPORTS', pins):
                recovery.checked_inputs(original)
                for name in ('capture.json', 'source.json', 'vector-range.exe', 'vector_range.pdb', 'runtime/settings.cfg'):
                    path = original / name
                    prior = path.read_bytes()
                    path.write_bytes(prior + b'x')
                    with self.assertRaises(ValueError):
                        recovery.checked_inputs(original)
                    path.write_bytes(prior)
                (original / 'extra').write_bytes(b'no')
                with self.assertRaisesRegex(ValueError, 'Unexpected'):
                    recovery.checked_inputs(original)

    def test_substituted_nonempty_trace_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original, pins = self.fixture(Path(directory))
            with patch.object(recovery, 'PINNED_REPORTS', pins):
                recovery.checked_inputs(original)
                (original / 'cpu.etl').write_bytes(b'nonempty substituted trace')
                with self.assertRaisesRegex(ValueError, 'Original trace bytes differ'):
                    recovery.checked_inputs(original)

    def test_failed_original_is_never_upgraded(self):
        with tempfile.TemporaryDirectory() as directory:
            original, pins = self.fixture(Path(directory))
            capture = json.loads((original / 'capture.json').read_text())
            capture['passed'] = True
            (original / 'capture.json').write_text(json.dumps(capture))
            pins['capture.json'] = recovery.digest(original / 'capture.json')
            with patch.object(recovery, 'PINNED_REPORTS', pins):
                with self.assertRaisesRegex(ValueError, 'remain failed'):
                    recovery.checked_inputs(original)

    def test_exports_only_read_trace_and_filter_original_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = []
            def run(command, cwd, log, **kwargs):
                commands.append(command)
                Path(command[5]).write_bytes(b'export')
            with patch.object(recovery, 'command_log', side_effect=run):
                result = recovery.exports('xperf.exe', root, root, {'pid': 12, 'renderer_window_thread_id': 34})
            self.assertEqual(len(result), 5)
            self.assertTrue(all(command[0] == 'xperf.exe' and '-i' in command for command in commands))
            self.assertIn('-event', commands[-1])
            self.assertEqual(commands[-1][-6:], ['-event', 'Profile', '-pid', '12', '-tid', '34'])
            self.assertNotIn('-tle', repr(commands))

    def test_later_export_cannot_silently_change_an_earlier_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def run(command, cwd, log, **kwargs):
                Path(command[5]).write_bytes(b'export')
                if Path(command[5]).name == 'renderer-stack.txt':
                    (root / 'profile.txt').write_bytes(b'changed after export')
            with patch.object(recovery, 'command_log', side_effect=run):
                with self.assertRaisesRegex(ValueError, 'Report changed'):
                    recovery.exports('xperf.exe', root, root, {'pid': 12, 'renderer_window_thread_id': 34})

    def test_receipt_keeps_failure_and_input_bytes_even_when_exports_fail(self):
        for fails in (False, True):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                original, pins = self.fixture(root)
                before = recovery.inventory(original)
                exporter = root / 'xperf.exe'
                exporter.write_bytes(b'installed fixture')
                env = {'RECOVERY_RUN_ID': recovery.RUN_ID, 'RECOVERY_ARTIFACT_ID': recovery.ARTIFACT_ID,
                       'GITHUB_SHA': 'a' * 40}
                with patch.object(recovery, 'PINNED_REPORTS', pins), patch.object(recovery, 'require_host'), \
                        patch.dict(os.environ, env), patch.object(recovery, 'installed_tools', return_value={'xperf': exporter}), \
                        patch.object(recovery, 'exports', side_effect=ValueError('export failed') if fails else None,
                                     return_value={'profile.txt': 'b' * 64}):
                    if fails:
                        with self.assertRaisesRegex(ValueError, 'export failed'):
                            recovery.recover(original, root / 'output')
                    else:
                        recovery.recover(original, root / 'output')
                receipt = json.loads((root / 'output/recovery.json').read_text())
                self.assertIs(receipt['exports_completed'], not fails)
                self.assertFalse(receipt['original_capture_passed'])
                self.assertEqual(receipt['original_exit_code'], 1)
                self.assertTrue(receipt['original_inputs_unchanged'])
                self.assertFalse(receipt['top_functions_reviewed'])
                self.assertEqual(before, recovery.inventory(original))

    def test_final_input_inventory_failure_retains_original_error_and_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, pins = self.fixture(root)
            before = recovery.inventory(original)
            exporter = root / 'xperf.exe'
            exporter.write_bytes(b'installed fixture')
            first = ValueError('original export error')
            env = {'RECOVERY_RUN_ID': recovery.RUN_ID, 'RECOVERY_ARTIFACT_ID': recovery.ARTIFACT_ID}
            with patch.object(recovery, 'PINNED_REPORTS', pins), patch.object(recovery, 'require_host'), \
                    patch.dict(os.environ, env), patch.object(recovery, 'installed_tools', return_value={'xperf': exporter}), \
                    patch.object(recovery, 'exports', side_effect=first), \
                    patch.object(recovery, 'inventory', side_effect=[before, ValueError('unsafe new input')]):
                with self.assertRaises(ValueError) as caught:
                    recovery.recover(original, root / 'output')
            self.assertIs(caught.exception, first)
            receipt = json.loads((root / 'output/recovery.json').read_text())
            self.assertFalse(receipt['exports_completed'])
            self.assertFalse(receipt['original_inputs_unchanged'])
            self.assertEqual(receipt['error'], 'original export error')
            self.assertEqual(receipt['input_recheck_error'], 'unsafe new input')

    def test_workflow_is_one_fixed_read_only_artifact(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / '.github/workflows/windows-cpu-profile-recovery.yml').read_text()
        self.assertIn("artifact-ids: '" + recovery.ARTIFACT_ID + "'", workflow)
        self.assertIn("run-id: '" + recovery.RUN_ID + "'", workflow)
        self.assertIn('actions: read', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertIn('branches: [aella/wgpu-1080p-diagnostics]', workflow)
        self.assertIn('timeout-minutes: 20', workflow)
        self.assertNotIn('workflow_dispatch', workflow)
        self.assertNotIn('secrets:', workflow)
        self.assertNotIn('Popen', Path(recovery.__file__).read_text())
        self.assertEqual(len(recovery.PINNED_REPORTS), 15)


if __name__ == '__main__':
    unittest.main()
