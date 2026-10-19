import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import contextlib
import warnings
from unittest import mock
import zipfile
import restore
import publish


class RecoveryTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory) / 'repo'
        root.mkdir()
        here = Path(directory) / 'code'
        here.mkdir()
        archive = Path(directory) / 'archive.zip'
        objects = []
        with zipfile.ZipFile(archive, 'w') as zipped:
            for number in range(14):
                data = ('runtime-' + str(number)).encode()
                member = 'objects/' + str(number)
                zipped.writestr(member, data)
                paths = [f'assets/pack{number}/file{n}.vra' for n in range(12 if number == 0 else 1)]
                objects.append({'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                                'git_sha': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
                                'archive': 'archive.zip', 'member': member,
                                'destinations': [{'path': p, 'operation': 'add', 'head_git_sha': None} for p in paths]})
        manifest = {'base_commit': 'base', 'branch': 'target', 'archives': [{'name': 'archive.zip'}], 'objects': objects}
        (here / 'manifest.json').write_text(json.dumps(manifest))
        return root, here, archive, manifest

    def restore_fixture(self, root, here, archive, git_results=None):
        with mock.patch.object(restore, 'HERE', here), mock.patch.object(restore, 'download', return_value=archive), \
                mock.patch.object(restore, 'git', side_effect=git_results or ['head', 'base', '', 'head refs/heads/target']), \
                contextlib.redirect_stdout(io.StringIO()):
            restore.restore(root, archive.parent, 'head')

    def test_successful_offline_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root, here, archive, manifest = self.fixture(directory)
            self.restore_fixture(root, here, archive)
            for row in manifest['objects']:
                for dest in row['destinations']:
                    restore.verify_file(root / dest['path'], row)
            self.assertEqual(len(list(root.rglob('*.vra'))), 25)

    def test_duplicate_zip_member_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, here, archive, _ = self.fixture(directory)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(archive, 'a') as zipped:
                    zipped.writestr('objects/0', b'runtime-0')
            with self.assertRaisesRegex(ValueError, 'inventory'):
                self.restore_fixture(root, here, archive)
            self.assertFalse((root / 'assets').exists())

    def test_missing_member_and_bad_hash_rejected_before_any_write(self):
        for mutation in ('member', 'sha256', 'git_sha'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root, here, archive, manifest = self.fixture(directory)
                manifest['objects'][-1][mutation] = 'missing' if mutation == 'member' else '0' * (40 if mutation == 'git_sha' else 64)
                (here / 'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    self.restore_fixture(root, here, archive)
                self.assertFalse((root / 'assets').exists())

    def test_destination_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, here, archive, _ = self.fixture(directory)
            (root / 'assets').symlink_to(here, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                self.restore_fixture(root, here, archive)

    def test_wrong_parent_remote_and_dirty_checkout_rejected(self):
        for results, message in [(['head', 'other'], 'pinned base'),
                                 (['head', 'base', 'dirty'], 'clean'),
                                 (['head', 'base', '', 'other refs/heads/target'], 'remote branch')]:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root, here, archive, _ = self.fixture(directory)
                with self.assertRaisesRegex(ValueError, message):
                    self.restore_fixture(root, here, archive, results)

    def test_extra_staged_path_rejected_before_commit_or_push(self):
        with tempfile.TemporaryDirectory() as directory:
            root, here, _, manifest = self.fixture(directory)
            hashes = {d['path']: r['git_sha'] for r in manifest['objects'] for d in r['destinations']}
            cached_reads = []
            def fake_git(_root, *args):
                if args == ('rev-parse', 'HEAD'): return 'head'
                if args == ('rev-parse', 'HEAD^'): return 'base'
                if args[0] == 'hash-object': return hashes[args[1]]
                if args[:2] == ('diff', '--cached'):
                    cached_reads.append(1)
                    return '' if len(cached_reads) == 1 else '\n'.join([*hashes, 'unexpected.txt'])
                if args[0] == 'add': return ''
                self.fail('unexpected git command')
            with mock.patch.object(publish, 'HERE', here), mock.patch.object(publish, 'git', side_effect=fake_git), \
                    mock.patch.object(publish, 'verify_file'), mock.patch.dict('os.environ', {'RECOVERY_PUSH_TOKEN': 'offline-test'}), \
                    mock.patch.object(publish.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'staged paths differ'):
                    publish.publish(root, 'head')
                run.assert_not_called()

    def test_stream_failure_cleans_temporary_file(self):
        response = io.BytesIO(b'too many bytes')
        response.headers = {'Content-Type': 'application/octet-stream'}
        with tempfile.TemporaryDirectory() as directory, mock.patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                restore.download({'name': 'x.zip', 'drive_id': 'x', 'bytes': 2}, Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_manifest_has_exact_fourteen_objects_and_twentyfive_paths(self):
        m = json.loads((restore.HERE / 'manifest.json').read_text())
        self.assertEqual(len(m['objects']), 14)
        paths = [d['path'] for r in m['objects'] for d in r['destinations']]
        self.assertEqual(len(paths), 25)
        self.assertEqual(len(set(paths)), 25)
        self.assertEqual(m['base_commit'], 'b6e9a4b819e1f53f1da0cb34abd0a9ca13f2ccfa')
        self.assertEqual({d['path'] for r in m['objects'] for d in r['destinations'] if d['operation'] == 'replace'}, {'assets/ads/asset.vra.gz'})

    def test_download_form_parses_only_named_form(self):
        form = restore.DownloadForm()
        form.feed('<input type="hidden" name="ignored" value="bad"><form id="download-form" method="get" action="https://drive.usercontent.google.com/download"><input type="hidden" name="id" value="expected"></form>')
        self.assertEqual(form.fields, {'id': 'expected'})

    def test_duplicate_fields_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            form = restore.DownloadForm()
            form.feed('<form id="download-form" method="get"><input type="hidden" name="id"><input type="hidden" name="id">')

    def test_post_form_rejected(self):
        with self.assertRaisesRegex(ValueError, 'method'):
            restore.DownloadForm().feed('<form id="download-form" method="post">')

    def test_hash_and_size_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'object'
            path.write_bytes(b'bytes')
            row = {'bytes': 5, 'sha256': hashlib.sha256(b'bytes').hexdigest()}
            restore.verify_file(path, row)
            with self.assertRaisesRegex(ValueError, 'size'):
                restore.verify_file(path, dict(row, bytes=4))
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                restore.verify_file(path, dict(row, sha256='0' * 64))

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_bytes(b'a')
            link = Path(directory) / 'link'
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'ordinary'):
                restore.verify_file(link, {'bytes': 1, 'sha256': hashlib.sha256(b'a').hexdigest()})

    def test_warning_requires_explicit_flag(self):
        response = io.BytesIO(b'<title>Google Drive - Virus scan warning</title>')
        response.headers = {'Content-Type': 'text/html'}
        with tempfile.TemporaryDirectory() as directory, mock.patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'explicit owner approval'):
                restore.download({'name': 'x.zip', 'drive_id': 'x'}, Path(directory))

    def test_unexpected_warning_is_rejected_even_when_approved(self):
        response = io.BytesIO(b'<title>Sign in</title>')
        response.headers = {'Content-Type': 'text/html'}
        with tempfile.TemporaryDirectory() as directory, mock.patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'unexpected HTML'):
                restore.download({'name': 'x.zip', 'drive_id': 'x'}, Path(directory), True)

    def test_head_guard_runs_before_network(self):
        with mock.patch.object(restore, 'git', return_value='different'), mock.patch.object(restore, 'download') as download:
            with self.assertRaisesRegex(ValueError, 'checkout differs'):
                restore.restore(Path('.'), Path('.'), 'expected')
            download.assert_not_called()

    def test_manifest_does_not_include_source_or_executable(self):
        manifest = json.loads((restore.HERE / 'manifest.json').read_text())
        for row in manifest['objects']:
            self.assertLess(row['bytes'], 100 * 1024 * 1024)
            for dest in row['destinations']:
                self.assertTrue(dest['path'].startswith('assets/'))
                self.assertNotIn('authoring', dest['path'])
                self.assertNotIn('.blend', dest['path'])
                self.assertNotIn('.exe', dest['path'])


if __name__ == '__main__':
    unittest.main()
