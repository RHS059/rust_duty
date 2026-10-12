"""Offline launcher bootstrap/clock/process tests; never launches or downloads."""
import importlib.util
import io
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('a100_launcher', ROOT / 'notebooks/public_a100_launcher.py')
launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_bootstrap_hashes_match_all_current_import_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in launcher.EXPECTED_FILES: shutil.copyfile(ROOT / 'tools' / name, root / name)
            launcher.verify_bootstrap(root)
            (root / 'prepare_public_a100.py').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'): launcher.verify_bootstrap(root)

    def test_public_download_flow_checks_bytes_before_any_launch(self):
        class Reply(io.BytesIO): status = 200
        opener = mock.Mock()
        opener.open.side_effect = lambda request, **kw: Reply((ROOT / 'tools' / request.full_url.rsplit('/', 1)[1]).read_bytes())
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(launcher.urllib.request, 'build_opener', return_value=opener), mock.patch.object(launcher.subprocess, 'Popen') as process:
            launcher.fetch_bootstrap(Path(temp) / 'tools', 'a' * 40)
            process.assert_not_called()
            self.assertEqual(opener.open.call_count, 5)

    def test_thirty_minute_allocation_cap_and_reserve(self):
        now = time.time()
        launcher.validate_clock(now - 870, now + 930, now)
        for start, deadline in ((now, now + 1801), (now + 1, now + 300), (now, now + 89)):
            with self.assertRaises(ValueError): launcher.validate_clock(start, deadline, now)

    def test_zombie_or_dead_process_is_terminal(self):
        fields = ['S'] + ['0'] * 20; fields[19] = '123'
        with mock.patch.object(Path, 'read_text', return_value='42 (controller) ' + ' '.join(fields)):
            self.assertEqual(launcher.process_start(42), '123')
        for state in ('Z', 'X'):
            fields[0] = state
            with mock.patch.object(Path, 'read_text', return_value='42 (controller) ' + ' '.join(fields)):
                self.assertIsNone(launcher.process_start(42))


if __name__ == '__main__': unittest.main()
