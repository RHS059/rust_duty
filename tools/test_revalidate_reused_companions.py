#!/usr/bin/env python3
"""Offline fail-closed unit tests. Fixtures are not gameplay/parity evidence."""
import argparse
import copy
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

import revalidate_reused_companions as reuse

LOCK_PATH = Path(__file__).with_name('source_bound_companion_reuse_lock.json')


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = reuse.read_json(LOCK_PATH)
        self.metadata = {'schema': 'rust-duty-companion-origin/v1', 'origin': self.lock['origin'],
                         'artifacts': [{k: a[k] for k in reuse.ARTIFACT_KEYS} for a in self.lock['artifacts']]}

    def archive(self, names=('asset.vra',), mutate=None):
        archive = self.root / 'input.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name in names:
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                if mutate:
                    mutate(info)
                z.writestr(info, b'fixture bytes')
        hashed = reuse.digest(archive)
        record = {'kind': 'reload', 'members': list(names), 'size_bytes': hashed['bytes'],
                  'zip_sha256': hashed['sha256']}
        return archive, record

    def extract(self, archive, record, limits=None):
        return reuse.extract_archive(archive, record, self.root / 'out', limits or self.lock['limits'])

    def test_production_lock_and_metadata(self):
        reuse.validate_lock(self.lock)
        reuse.validate_metadata(self.metadata, self.lock)
        self.assertEqual(62, len(self.lock['source_files']))
        self.assertEqual(58, sum('origin_sha256' in row for row in self.lock['source_files']))
        self.assertEqual(28, len(self.lock['artifacts'][0]['members']))
        self.assertEqual(75, sum(len(a['members']) for a in self.lock['artifacts']))

    def test_metadata_wrong_origin_and_artifact(self):
        for where, key, value in [('origin', 'run_id', 1), ('origin', 'run_attempt', 2),
                                  ('origin', 'repository', 'other/repo'), ('origin', 'tested_merge', '0'*40),
                                  ('artifact', 'artifact_id', 1), ('artifact', 'zip_sha256', '0'*64),
                                  ('artifact', 'head_sha', '0'*40)]:
            with self.subTest(where=where, key=key):
                metadata = copy.deepcopy(self.metadata)
                (metadata['origin'] if where == 'origin' else metadata['artifacts'][0])[key] = value
                with self.assertRaises(ValueError): reuse.validate_metadata(metadata, self.lock)

    def test_current_only_modules_do_not_claim_historical_bytes(self):
        current_only = {row['path']: row for row in self.lock['source_files']
                        if row.get('origin_absent') is True}
        self.assertEqual(set(current_only), {'src/graphics_device.rs', 'src/gpu_telemetry.rs',
            'src/gpu_telemetry/counters.rs', 'src/gpu_telemetry/windows.rs'})
        for row in current_only.values():
            self.assertNotIn('origin_sha256', row)
            self.assertTrue(row['reviewed_difference'])
        lib = next(row for row in self.lock['source_files'] if row['path'] == 'src/lib.rs')
        self.assertEqual(lib['origin_sha256'],
                         'b8be3461113a2967b93959878a744b8380cc296a1cb1b7eb770417edd0a5c551')

    def test_real_git_registration_refresh_keeps_source_guard_fail_closed(self):
        # Tiny original files exercise verify_source with real Git identities.
        # This is guard regression evidence, not asset or native parity proof.
        root = self.root / 'git-source'; root.mkdir()
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)

        def command(*args):
            return subprocess.check_output(['git', '-C', str(root),
                '-c', 'core.autocrlf=false', '-c', 'user.name=Companion guard test',
                '-c', 'user.email=companion-guard@example.invalid', *args], text=True).strip()

        def commit():
            command('add', '.')
            command('commit', '-qm', 'Original isolated guard fixture')
            return command('rev-parse', 'HEAD')

        paths = ('src/lib.rs', 'src/graphics_device.rs', 'src/gpu_telemetry.rs',
                 'src/gpu_telemetry/counters.rs', 'src/gpu_telemetry/windows.rs',
                 'examples/sample_viewmodel_clip.rs')
        for path in (*paths, 'assets/source.blend'):
            destination = root / path; destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(('original fixture for ' + path + '\n').encode())
        jump = self.root / 'git-jump.blend'; jump.write_bytes(b'original jump fixture')
        original_commit = commit()
        lock = copy.deepcopy(self.lock)
        lock['eligible_assets_tree'] = command('rev-parse', 'HEAD:assets')
        lock['jump_source'].update(reuse.digest(jump))
        lock['source_files'] = [{'path': path, **reuse.digest(root / path),
            'git_blob': command('rev-parse', 'HEAD:' + path)} for path in paths]
        lib = lock['source_files'][0]
        lib['origin_sha256'] = lib['sha256']
        reuse.verify_source(root, original_commit, jump, lock)

        path = root / paths[0]
        path.write_bytes(path.read_bytes() + b'pub mod graphics_device;\n')
        refreshed_commit = commit()
        with self.assertRaisesRegex(ValueError, 'current source Git identity mismatch: src/lib.rs'):
            reuse.verify_source(root, refreshed_commit, jump, lock)
        historical_hash = lib['origin_sha256']
        lib.update(reuse.digest(path), git_blob=command('rev-parse', 'HEAD:src/lib.rs'))
        reuse.verify_source(root, refreshed_commit, jump, lock)
        self.assertEqual(historical_hash, lib['origin_sha256'])

        for name in paths:
            with self.subTest(path=name):
                path = root / name
                clean = path.read_bytes()
                # Worktree-only edits fail even when HEAD is the reviewed blob.
                path.write_bytes(clean + b'changed\n')
                with self.assertRaisesRegex(ValueError, 'byte/hash mismatch'):
                    reuse.verify_source(root, command('rev-parse', 'HEAD'), jump, lock)
                changed_commit = commit()
                # Committed edits fail even if the worktree is restored to the
                # reviewed bytes. HEAD identity is an independent requirement.
                path.write_bytes(clean)
                with self.assertRaisesRegex(ValueError, 'current source Git identity mismatch'):
                    reuse.verify_source(root, changed_commit, jump, lock)
                clean_commit = commit()
                reuse.verify_source(root, clean_commit, jump, lock)

    def test_mandatory_source_omission_and_jump_relocation(self):
        for key in ('assets/source/reload/current.blend', 'tools/vrview.py',
                    'assets/authoring/locomotion_directional/r5/source_integrity.json',
                    'src/lib.rs', 'src/graphics_device.rs',
                    'src/gpu_telemetry.rs', 'src/gpu_telemetry/counters.rs',
                    'src/gpu_telemetry/windows.rs'):
            lock = copy.deepcopy(self.lock)
            lock['source_files'] = [r for r in lock['source_files'] if r['path'] != key]
            with self.subTest(path=key), self.assertRaises(ValueError): reuse.validate_lock(lock)
        lock = copy.deepcopy(self.lock); lock['jump_source']['path'] = 'elsewhere.blend'
        with self.assertRaises(ValueError): reuse.validate_lock(lock)

    def test_metadata_numeric_types_are_exact(self):
        for where, key, value in [('origin', 'run_attempt', True),
                                  ('origin', 'run_id', float(self.lock['origin']['run_id'])),
                                  ('artifact', 'artifact_id', float(self.lock['artifacts'][0]['artifact_id']))]:
            metadata = copy.deepcopy(self.metadata)
            (metadata['origin'] if where == 'origin' else metadata['artifacts'][0])[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): reuse.validate_metadata(metadata, self.lock)

    def test_missing_or_duplicate_metadata(self):
        for artifacts in [self.metadata['artifacts'][:-1], [self.metadata['artifacts'][0]]*5]:
            with self.assertRaises(ValueError):
                reuse.validate_metadata({**self.metadata, 'artifacts': artifacts}, self.lock)

    def test_duplicate_json_key(self):
        path = self.root / 'bad.json'
        path.write_text('{"schema":1,"schema":2}')
        with self.assertRaises(ValueError): reuse.read_json(path)

    def test_safe_zip_preserves_exact_bytes(self):
        archive, record = self.archive(('asset.vra', 'alternates/opening/source.json'))
        inventory = self.extract(archive, record)
        self.assertEqual(set(record['members']), set(inventory))
        for name in record['members']:
            self.assertEqual(b'fixture bytes', (self.root / 'out' / name).read_bytes())

    def test_bad_hash_writes_nothing(self):
        archive, record = self.archive()
        record['zip_sha256'] = '0'*64
        with self.assertRaises(ValueError): self.extract(archive, record)
        self.assertFalse((self.root / 'out').exists())

    def test_missing_full_reload_fails_before_extract(self):
        archive, record = self.archive()
        record['members'] = self.lock['artifacts'][0]['members']
        with self.assertRaisesRegex(ValueError, 'inventory'): self.extract(archive, record)
        self.assertFalse((self.root / 'out').exists())

    def test_extra_file_fails_before_extract(self):
        archive, record = self.archive(('asset.vra', 'surprise.py'))
        record['members'] = ['asset.vra']
        with self.assertRaises(ValueError): self.extract(archive, record)
        self.assertFalse((self.root / 'out').exists())

    def test_unsafe_portable_paths(self):
        for name in ('../escape', '/absolute', 'C:/drive', 'C:stream', 'a\\b', '//host/share',
                     'a//b', './dot', 'a/../b', 'trailing.', 'trailing ', 'NUL.txt', 'COM1.bin', 'a\x00b'):
            with self.subTest(name=name), self.assertRaises(ValueError): reuse.relative_path(name)

    def test_traversal_archive(self):
        archive, record = self.archive(('../escape',))
        with self.assertRaises(ValueError): self.extract(archive, record)
        self.assertFalse((self.root / 'out').exists())

    def test_embedded_nul_filename(self):
        # zipfile's writer strips NUL itself; replace a same-length safe name in
        # both headers so the central/local original names contain the byte.
        archive, record = self.archive(('asset.vraXevil',))
        archive.write_bytes(archive.read_bytes().replace(b'asset.vraXevil', b'asset.vra\0evil'))
        got = reuse.digest(archive)
        record.update(size_bytes=got['bytes'], zip_sha256=got['sha256'], members=['asset.vra'])
        with self.assertRaisesRegex(ValueError, 'NUL'): self.extract(archive, record)

    def test_case_collision(self):
        archive, record = self.archive(('asset.vra', 'ASSET.vra'))
        with self.assertRaisesRegex(ValueError, 'colliding'): self.extract(archive, record)

    def test_symlink_and_special_zip_entries(self):
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR):
            archive, record = self.archive(mutate=lambda i: setattr(i, 'external_attr', (kind | 0o644) << 16))
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.extract(archive, record)

    def test_zip_size_and_ratio_limits(self):
        for name in ('max_zip_bytes', 'max_member_bytes', 'max_uncompressed_bytes_per_zip'):
            archive, record = self.archive()
            limits = {**self.lock['limits'], name: 1}
            with self.subTest(limit=name), self.assertRaises(ValueError): self.extract(archive, record, limits)
        archive = self.root / 'input.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('asset.vra', b'0'*10000)
        got = reuse.digest(archive)
        record = {'kind': 'reload', 'members': ['asset.vra'], 'size_bytes': got['bytes'], 'zip_sha256': got['sha256']}
        with self.assertRaisesRegex(ValueError, 'ratio'):
            self.extract(archive, record, {**self.lock['limits'], 'max_compression_ratio': 2})

    def test_encrypted_and_unsupported_compression(self):
        archive, record = self.archive()
        raw = bytearray(archive.read_bytes())
        raw[raw.index(b'PK\x03\x04') + 6] |= 1
        raw[raw.index(b'PK\x01\x02') + 8] |= 1
        archive.write_bytes(raw)
        hashed = reuse.digest(archive)
        record.update(size_bytes=hashed['bytes'], zip_sha256=hashed['sha256'])
        with self.assertRaisesRegex(ValueError, 'encrypted'): self.extract(archive, record)
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_BZIP2) as z:
            z.writestr('asset.vra', b'fixture bytes')
        hashed = reuse.digest(archive)
        record.update(size_bytes=hashed['bytes'], zip_sha256=hashed['sha256'])
        with self.assertRaisesRegex(ValueError, 'compression'): self.extract(archive, record)

    def test_too_many_entries(self):
        archive, record = self.archive(('first', 'second'))
        with self.assertRaisesRegex(ValueError, 'too many'):
            self.extract(archive, record, {**self.lock['limits'], 'max_entries_per_zip': 1})

    def test_existing_pack_directory_preserved(self):
        archive, record = self.archive()
        out = self.root / 'out'; out.mkdir(); (out / 'keep').write_bytes(b'keep')
        with self.assertRaises(ValueError): self.extract(archive, record)
        self.assertEqual(b'keep', (out / 'keep').read_bytes())

    def test_filesystem_symlink_rejected(self):
        original = self.root / 'regular'; original.write_bytes(b'keep')
        link = self.root / 'link'
        try: link.symlink_to(original)
        except OSError: self.skipTest('symlink creation unavailable on this runner')
        with self.assertRaises(ValueError): reuse.digest(link)

    def source_fixture(self):
        root = self.root / 'source'; root.mkdir()
        source = root / 'source.blend'; source.write_bytes(b'actual blend fixture')
        jump = self.root / 'jump.blend'; jump.write_bytes(b'actual jump fixture')
        lock = copy.deepcopy(self.lock)
        lock['source_files'] = [{'path': 'source.blend', 'git_blob': '1'*40, **reuse.digest(source)}]
        lock['jump_source'] = {**lock['jump_source'], **reuse.digest(jump)}
        return root, jump, lock

    def test_source_worktree_hash_and_required_jump(self):
        root, jump, lock = self.source_fixture()
        answers = ['2'*40, lock['eligible_assets_tree'], '1'*40]
        with mock.patch.object(reuse, 'git', side_effect=answers): reuse.verify_source(root, '2'*40, jump, lock)
        (root / 'source.blend').write_bytes(b'changed')
        with mock.patch.object(reuse, 'git', side_effect=answers), self.assertRaisesRegex(ValueError, 'byte/hash'):
            reuse.verify_source(root, '2'*40, jump, lock)
        (root / 'source.blend').write_bytes(b'actual blend fixture')
        jump.unlink()
        with mock.patch.object(reuse, 'git', side_effect=answers), self.assertRaises(OSError):
            reuse.verify_source(root, '2'*40, jump, lock)

    def test_source_git_identity_mismatch(self):
        root, jump, lock = self.source_fixture()
        for answers in (['3'*40], ['2'*40, '0'*40], ['2'*40, lock['eligible_assets_tree'], '0'*40]):
            with mock.patch.object(reuse, 'git', side_effect=answers), self.assertRaises(ValueError):
                reuse.verify_source(root, '2'*40, jump, lock)

    def args_fixture(self):
        root, jump, _ = self.source_fixture()
        lock = copy.deepcopy(self.lock)
        lock['jump_source'].update(reuse.digest(jump))
        for row in lock['source_files']:
            path = root / row['path']; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('unit-test fixture: ' + row['path']).encode())
            row.update(reuse.digest(path))
        artifacts = []
        for row in lock['artifacts']:
            archive, data = self.archive(('asset.vra',))
            moved = self.root / (row['kind'] + '.zip'); archive.rename(moved)
            row.update({k: data[k] for k in ('members', 'size_bytes', 'zip_sha256')})
            artifacts.append(f"{row['kind']}={moved}")
        metadata = {'schema': 'rust-duty-companion-origin/v1', 'origin': lock['origin'],
                    'artifacts': [{k: a[k] for k in reuse.ARTIFACT_KEYS} for a in lock['artifacts']]}
        lock_path = self.root / 'lock.json'; lock_path.write_text(json.dumps(lock))
        meta_path = self.root / 'meta.json'; meta_path.write_text(json.dumps(metadata))
        args = argparse.Namespace(output=self.root/'output', lock=lock_path, origin_metadata=meta_path,
                                  artifact=artifacts, source_root=root, jump_source=jump, expected_source_commit='2'*40)
        return args

    def test_existing_output_preserved(self):
        args = self.args_fixture(); args.output.mkdir(); (args.output / 'keep').write_bytes(b'keep')
        with self.assertRaises(ValueError): reuse.revalidate(args)
        self.assertEqual(b'keep', (args.output / 'keep').read_bytes())

    def test_missing_archive_fails(self):
        args = self.args_fixture(); args.artifact = args.artifact[1:]
        with self.assertRaisesRegex(ValueError, 'all five'): reuse.revalidate(args)
        self.assertFalse(args.output.exists())

    def test_success_receipt_explicitly_reuses_generation(self):
        args = self.args_fixture()
        with mock.patch.object(reuse, 'verify_source'), mock.patch.object(reuse, 'run_validators', return_value=[{'fixture': True}]):
            result = reuse.revalidate(args)
        self.assertTrue(result['generation_reused'])
        for key in ('new_generation', 'new_asset_generation', 'fresh_source_oracle_parity', 'native_execution'):
            self.assertIs(result[key], False)
        self.assertTrue(result['historical_parity_reports_preserved'])
        self.assertEqual(5, len(result['artifact_members']))
        self.assertTrue((args.output / 'provenance.json').is_file())
        self.assertEqual(reuse.digest(args.origin_metadata), reuse.digest(args.output / 'origin-metadata.json'))

    def test_concurrent_output_preserved(self):
        args = self.args_fixture()
        def concurrent(root, reports):
            args.output.mkdir()
            (args.output / 'keep').write_bytes(b'other owner')
            return []
        with mock.patch.object(reuse, 'verify_source'), mock.patch.object(reuse, 'run_validators', side_effect=concurrent):
            with self.assertRaises(FileExistsError): reuse.revalidate(args)
        self.assertEqual(b'other owner', (args.output / 'keep').read_bytes())
        self.assertFalse((args.output / 'provenance.json').exists())

    def test_validator_failure_never_publishes_success(self):
        args = self.args_fixture()
        with mock.patch.object(reuse, 'verify_source'), mock.patch.object(reuse, 'run_validators', side_effect=ValueError('fixture failure')):
            with self.assertRaisesRegex(ValueError, 'fixture failure'): reuse.revalidate(args)
        self.assertFalse(args.output.exists())

    def test_validator_mutation_fails_closed(self):
        args = self.args_fixture()
        def mutate(root, reports):
            (root / 'assets/reload/asset.vra').write_bytes(b'modified')
            return []
        with mock.patch.object(reuse, 'verify_source'), mock.patch.object(reuse, 'run_validators', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'modified'): reuse.revalidate(args)
        self.assertFalse(args.output.exists())

    def test_late_current_only_source_edit_never_publishes_success(self):
        args = self.args_fixture()
        root = args.source_root
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(root), '-c', 'core.autocrlf=false',
                        'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(root), '-c', 'user.name=Companion guard test',
                        '-c', 'user.email=companion-guard@example.invalid', 'commit',
                        '-qm', 'Original isolated late source fixture'],
                       check=True, capture_output=True)
        args.expected_source_commit = reuse.git(root, 'rev-parse', 'HEAD')
        lock = reuse.read_json(args.lock)
        lock['eligible_assets_tree'] = reuse.git(root, 'rev-parse', 'HEAD:assets')
        for row in lock['source_files']:
            row['git_blob'] = reuse.git(root, 'rev-parse', 'HEAD:' + row['path'])
        args.lock.write_text(json.dumps(lock))

        def mutate_source(staged, reports):
            # Staged inputs remain intact: the late real source check must catch
            # this edit to the original current-only module before any receipt.
            path = root / 'src/graphics_device.rs'
            path.write_bytes(path.read_bytes() + b'late source edit\n')
            return [{'fixture': True}]

        with mock.patch.object(reuse, 'run_validators', side_effect=mutate_source) as validators:
            with self.assertRaisesRegex(ValueError, 'byte/hash mismatch: .*graphics_device.rs'):
                reuse.revalidate(args)
        validators.assert_called_once()
        self.assertFalse(args.output.exists())

    def test_all_six_validator_commands_and_failure(self):
        root = self.root / 'checked'; root.mkdir()
        ok = mock.Mock(returncode=0, stdout='{"passed":true}', stderr='')
        with mock.patch.object(reuse.subprocess, 'run', return_value=ok) as run:
            result = reuse.run_validators(root, self.root / 'reports')
        self.assertEqual(6, len(result))
        self.assertEqual(list(reuse.KINDS)+['all-generated'], [r['name'] for r in result])
        for call in run.call_args_list[:5]:
            self.assertEqual('assets/' + call.args[0][6], call.args[0][-1])
            self.assertEqual(300, call.kwargs['timeout'])
        bad = mock.Mock(returncode=1, stdout='{}', stderr='unchanged validator rejected fixture')
        with mock.patch.object(reuse.subprocess, 'run', return_value=bad), self.assertRaisesRegex(ValueError, 'validator failed'):
            reuse.run_validators(root, self.root / 'bad-reports')


if __name__ == '__main__':
    unittest.main()
