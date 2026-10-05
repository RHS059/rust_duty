"""Exercise exclusive output on the host and verify the Windows API contract."""

import ctypes
import errno
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import exclusive_output as exclusive


class ExclusiveOutputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'report.json'

    def symlink(self, target):
        try:
            self.path.symlink_to(target)
        except OSError as error:
            self.skipTest(f'host cannot create symlinks: {error}')

    def test_new_utf8_report_and_parent_policy(self):
        nested = self.root / 'nested/report.json'
        with self.assertRaises(FileNotFoundError):
            exclusive.write_text_exclusive(nested, 'text')
        exclusive.write_text_exclusive(nested, 'snowman ☃\n', create_parents=True)
        self.assertEqual(nested.read_bytes(), 'snowman ☃\n'.encode())
        with self.assertRaises(FileExistsError):
            exclusive.write_text_exclusive(nested, 'overwrite')
        self.assertEqual(nested.read_bytes(), 'snowman ☃\n'.encode())

    def test_existing_directory_is_preserved(self):
        self.path.mkdir()
        sentinel = self.path / 'keep'
        sentinel.write_text('unchanged')
        with self.assertRaises(FileExistsError):
            exclusive.write_text_exclusive(self.path, 'overwrite')
        self.assertEqual(sentinel.read_text(), 'unchanged')

    def test_binary_payloads_and_existing_bytes_are_preserved(self):
        for name, payload in (('empty', b''), ('binary', bytes(range(256)) + b'\x00\xff\x80\n')):
            with self.subTest(name=name):
                path = self.root / name / 'output.bin'
                exclusive.write_bytes_exclusive(path, payload, create_parents=True)
                self.assertEqual(path.read_bytes(), payload)
                with self.assertRaises(FileExistsError):
                    exclusive.write_bytes_exclusive(path, b'replacement')
                self.assertEqual(path.read_bytes(), payload)

    def test_binary_leaf_links_preserve_link_and_target(self):
        for live in (False, True):
            folder = self.root / str(live)
            folder.mkdir()
            path, target = folder / 'output.bin', folder / 'target.bin'
            if live:
                target.write_bytes(b'\x00\xff original target')
            try:
                path.symlink_to(target)
            except OSError as error:
                self.skipTest(f'host cannot create symlinks: {error}')
            original = path.readlink()
            with self.subTest(live=live), self.assertRaises(FileExistsError):
                exclusive.write_bytes_exclusive(path, b'new executable bytes')
            self.assertTrue(path.is_symlink())
            self.assertEqual(path.readlink(), original)
            if live:
                self.assertEqual(target.read_bytes(), b'\x00\xff original target')
            else:
                self.assertFalse(target.exists())

    def test_invalid_payloads_fail_before_creating_parents(self):
        path = self.root / 'absent/output'
        with self.assertRaises(TypeError):
            exclusive.write_bytes_exclusive(path, 'not bytes', create_parents=True)
        with self.assertRaises(UnicodeEncodeError):
            exclusive.write_text_exclusive(path, '\ud800', create_parents=True)
        self.assertFalse(path.parent.exists())

    def test_dangling_link_is_rejected_before_any_create_api(self):
        target = self.root / 'absent'
        self.symlink(target)
        original = self.path.readlink()
        with patch.object(exclusive, '_write_windows') as windows, patch.object(exclusive, '_write_posix') as posix:
            with self.assertRaises(FileExistsError):
                exclusive.write_text_exclusive(self.path, 'must not follow')
        windows.assert_not_called()
        posix.assert_not_called()
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(self.path.readlink(), original)
        self.assertFalse(target.exists())

    def test_live_link_and_target_are_preserved(self):
        target = self.root / 'existing'
        target.write_bytes(b'keep exactly')
        self.symlink(target)
        original = self.path.readlink()
        with self.assertRaises(FileExistsError):
            exclusive.write_text_exclusive(self.path, 'must not overwrite')
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(self.path.readlink(), original)
        self.assertEqual(target.read_bytes(), b'keep exactly')

    def test_link_appearing_after_lstat_is_not_followed_by_host_create(self):
        target = self.root / 'absent'
        name = '_write_windows' if exclusive._WINDOWS else '_write_posix'
        original = getattr(exclusive, name)
        def raced_create(path, data):
            self.symlink(target)
            return original(path, data)
        with patch.object(exclusive, name, side_effect=raced_create), self.assertRaises(FileExistsError):
            exclusive.write_text_exclusive(self.path, 'must not follow raced link')
        self.assertTrue(self.path.is_symlink())
        self.assertFalse(target.exists())

    def test_windows_create_new_uses_open_reparse_point_and_handles_partial_writes(self):
        emitted = bytearray()
        def write(handle, buffer, size, count, overlapped):
            data = ctypes.string_at(buffer, size)
            emitted.extend(data[:2])
            count._obj.value = min(2, size)
            return True
        api = SimpleNamespace(create=Mock(return_value=123), write=Mock(side_effect=write),
                              flush=Mock(return_value=True), close=Mock(return_value=True), error=lambda: 5)
        payload = b'\x00\xff\x80abcdefg'
        with patch.object(exclusive, '_windows_api', return_value=api), patch.object(exclusive, '_WINDOWS', True):
            exclusive.write_bytes_exclusive(self.path, payload)
        api.create.assert_called_once_with(str(self.path.absolute()), exclusive.GENERIC_WRITE, 0, None,
            exclusive.CREATE_NEW, exclusive.FILE_ATTRIBUTE_NORMAL | exclusive.FILE_FLAG_OPEN_REPARSE_POINT, None)
        self.assertEqual(emitted, payload)
        api.flush.assert_called_once_with(123)
        api.close.assert_called_once_with(123)

    def test_windows_collision_never_opens_or_writes_target(self):
        api = SimpleNamespace(create=Mock(return_value=exclusive.INVALID_HANDLE_VALUE),
                              write=Mock(), flush=Mock(), close=Mock(), error=lambda: 80)
        with patch.object(exclusive, '_windows_api', return_value=api), self.assertRaises(FileExistsError):
            exclusive._write_windows(self.path, b'not written')
        api.write.assert_not_called()
        api.close.assert_not_called()

    def test_windows_write_failure_closes_handle_and_never_reports_success(self):
        api = SimpleNamespace(create=Mock(return_value=123), write=Mock(return_value=False),
                              flush=Mock(return_value=True), close=Mock(return_value=True), error=lambda: 5)
        with patch.object(exclusive, '_windows_api', return_value=api), self.assertRaises(OSError) as raised:
            exclusive._write_windows(self.path, b'cannot write')
        self.assertEqual(raised.exception.errno, errno.EACCES)
        api.flush.assert_not_called()
        api.close.assert_called_once_with(123)


if __name__ == '__main__':
    unittest.main()
