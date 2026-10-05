"""Synthetic stager/ZIP contracts; never proof of a runnable Windows game."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import tempfile
import unittest
import zipfile

import build_identity
import inventory_windows_preview as inventory
import package_game
import release_update
import test_dx12_preview as fixtures


class PreviewInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Real stager creates provenance/launcher. Existing fixture replaces
        # asset packaging/native stamping, so no private assets or EXE execute.
        fixture = fixtures.Dx12PreviewTests()
        fixture.setUp()
        try:
            def stamp(destination, platform, env):
                record = build_identity.context(env)
                record.update(schema='rust-duty-build-identity/v1', target=build_identity.TARGETS[platform][0],
                              executable=release_update.asset(destination / 'vector-range.exe'))
                (destination / 'BUILD_IDENTITY.json').write_text(json.dumps(record))
                return record
            fixture.stamper.side_effect = stamp
            fixture.run_stage()
            for name in (*package_game.NOTICES, *package_game.RUNTIME_FILES, *package_game.BUILD_FILES):
                path = fixture.output / name
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f'Original synthetic fixture: {name}\n')
            cls.control = {p.relative_to(fixture.output).as_posix(): p.read_bytes()
                           for p in fixture.output.rglob('*') if p.is_file()}
        finally:
            fixture.doCleanups()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'preview.zip'
        self.entries = dict(self.control)

    def archive(self, entries=None, descriptors=False):
        entries = self.entries.items() if entries is None else entries
        class Sequential(io.BytesIO):
            def seek(self, *args):
                raise OSError('nonseekable synthetic writer')
        if descriptors:
            destination = Sequential()
        else:
            destination = self.path
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, data in entries:
                archive.writestr(name, data)
        if descriptors:
            self.path.write_bytes(destination.getvalue())
        return self.path

    def mutate_json(self, name, mutate):
        value = json.loads(self.entries[name])
        mutate(value)
        self.entries[name] = json.dumps(value).encode()

    def invalid(self, expected=None):
        self.archive()
        before = self.path.read_bytes()
        result = inventory.validate_zip_archive(self.path, strict=True)
        self.assertFalse(result['valid'], result)
        if expected:
            self.assertIn(expected, result['error'])
        self.assertEqual(self.path.read_bytes(), before)
        return result

    def test_producer_flat_and_wrapped_controls_preserve_input(self):
        for prefix in ('', 'preview/'):
            with self.subTest(prefix=prefix):
                entries = [(prefix + name, value) for name, value in self.control.items()]
                if prefix:
                    entries.insert(0, (prefix, b''))
                self.archive(entries)
                before = self.path.read_bytes()
                report = inventory.validate_zip_archive(self.path, strict=True)
                self.assertTrue(report['valid'], report)
                self.assertEqual(report['package_root'], prefix)
                self.assertEqual(report['files'], sorted(self.control))
                self.assertEqual(report['executable_sha256'], hashlib.sha256(self.control['vector-range.exe']).hexdigest())
                self.assertIn('No executable was run', report['scope'])
                self.assertEqual(self.path.read_bytes(), before)

    def test_all_required_real_files_are_required_exactly(self):
        self.assertTrue(set(package_game.NOTICES) <= set(inventory.REQUIRED_FILES))
        self.assertTrue(set(package_game.RUNTIME_FILES) <= set(inventory.REQUIRED_FILES))
        for name in inventory.REQUIRED_FILES:
            with self.subTest(name=name):
                self.entries = {key: value for key, value in self.control.items() if key != name}
                self.invalid()
        self.entries = dict(self.control)
        self.entries['vector-range.exe.fake'] = self.entries.pop('vector-range.exe')
        self.invalid()

    def test_hash_size_source_and_notice_binding(self):
        mutations = [
            ('BUILD_IDENTITY.json', lambda r: r['executable'].update(sha256='0' * 64)),
            ('BUILD_IDENTITY.json', lambda r: r['executable'].update(size=True)),
            ('BUILD_IDENTITY.json', lambda r: r['source'].update(run_attempt=3)),
            ('BUILD_IDENTITY.json', lambda r: r.update(display_version='invented')),
            ('DX12_PREVIEW.json', lambda r: r.update(executable_sha256='0' * 64)),
            ('DX12_PREVIEW.json', lambda r: r.update(default_renderer='dx12')),
            ('DX12_PREVIEW.json', lambda r: r['smoke'].update(frames=True)),
            ('DX12_PREVIEW.json', lambda r: r['game_dependency_notices'].update(notice_sha256='0' * 64))]
        for name, mutate in mutations:
            with self.subTest(name=name, mutate=mutate):
                self.entries = dict(self.control)
                self.mutate_json(name, mutate)
                self.invalid()
        self.entries = dict(self.control)
        self.entries['vector-range.exe'] += b'changed'
        self.invalid('size mismatch')
        self.entries = dict(self.control)
        self.entries['THIRD_PARTY_LICENSES.txt'] += b'changed'
        self.invalid('notice SHA256 mismatch')

    def test_launcher_cannot_hide_missing_flags_or_extra_commands(self):
        for launcher in (b'@echo off\nvector-range.exe\n',
                         self.control['PLAYTEST_DX12.cmd'].replace(b'--no-update', b''),
                         self.control['PLAYTEST_DX12.cmd'] + b'echo injected command\n'):
            self.entries['PLAYTEST_DX12.cmd'] = launcher
            self.invalid('launcher differs')

    def test_malformed_duplicate_nonfinite_json_and_utf8_reject(self):
        original = self.control['DX12_PREVIEW.json']
        for data in (b'{', b'[]', b'null', b'\xff', b'{"x":NaN}', b'{"x":1e9999}',
                     original.rstrip()[:-1] + b',"schema":"duplicate"}'):
            self.entries['DX12_PREVIEW.json'] = data
            self.invalid()

    def test_windows_path_traversal_devices_aliases_and_controls_reject(self):
        names = ('../escape', '/absolute', 'C:/absolute', 'a\\b', 'a:b', 'a/../b', 'a//b', './x',
                 'a/NUL.txt', 'a/CON', 'a/x. ', 'a/x\x01', 'a/<bad>')
        for name in names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    inventory.normalize_zip_member(name)
                self.entries = {**self.control, name: b'x'}
                self.invalid()
        for name, expected in [('ui/theme.css', 'ui/theme.css'), ('preview/docs/', 'preview/docs')]:
            self.assertEqual(inventory.normalize_zip_member(name), expected)

    def test_case_collisions_file_directory_conflicts_and_split_roots_reject(self):
        for name in ('UI/THEME.CSS', 'ui'):
            self.entries = {**self.control, name: b'x'}
            self.invalid()
        self.archive([*self.control.items(), ('vector-range.exe', b'duplicate')])
        self.assertFalse(inventory.validate_zip_archive(self.path)['valid'])
        self.archive([('preview/' + k, v) for k, v in self.control.items()] + [('outside.txt', b'x')])
        self.assertFalse(inventory.validate_zip_archive(self.path)['valid'])

    def test_unix_symlink_and_special_file_modes_reject(self):
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600):
            info = zipfile.ZipInfo('ordinary-looking-name')
            info.create_system = 3
            info.external_attr = mode << 16
            self.archive([*self.control.items(), (info, b'vector-range.exe')])
            result = inventory.validate_zip_archive(self.path)
            self.assertFalse(result['valid'], result)
            self.assertTrue('symlink' in result['error'] or 'nonregular' in result['error'])

    def test_crc_checks_all_data_including_descriptor_entries(self):
        self.entries['extra-data.bin'] = b'x' * 4096
        for descriptors in (False, True):
            with self.subTest(descriptors=descriptors):
                self.archive(descriptors=descriptors)
                self.assertTrue(inventory.validate_zip_archive(self.path)['valid'])
                with zipfile.ZipFile(self.path) as archive:
                    info = archive.getinfo('extra-data.bin')
                    self.assertEqual(bool(info.flag_bits & 8), descriptors)
                data = bytearray(self.path.read_bytes())
                name_size, extra_size = struct.unpack_from('<HH', data, info.header_offset + 26)
                data[info.header_offset + 30 + name_size + extra_size + 2048] ^= 1
                self.path.write_bytes(data)
                result = inventory.validate_zip_archive(self.path)
                self.assertFalse(result['valid'])
                self.assertIn('CRC', result['error'])

    def test_cli_report_is_exclusive_even_for_source_and_dangling_links(self):
        self.archive()
        report = self.root / 'inventory.json'
        args = ['--zip-path', str(self.path), '--strict', '--report', str(report)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(inventory.main(args), 0)
        before = report.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(inventory.main(args), 1)
        self.assertEqual(report.read_bytes(), before)
        before = self.path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(inventory.main(['--zip-path', str(self.path), '--report', str(self.path)]), 1)
        self.assertEqual(self.path.read_bytes(), before)
        link = self.root / 'dangling'
        try:
            link.symlink_to(self.root / 'missing')
        except OSError as error:
            self.skipTest(str(error))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(inventory.main(['--zip-path', str(self.path), '--report', str(link)]), 1)
        self.assertFalse((self.root / 'missing').exists())


if __name__ == '__main__':
    unittest.main()
