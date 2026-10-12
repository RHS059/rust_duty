"""Independent, offline registry fixtures for game notice provenance.

No real Cargo invocation, download, registry lookup, or repository notice change is
performed. Archives and lock checksums are constructed here, not by the collector.
"""

import contextlib
import copy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'collect_game_licenses', Path(__file__).with_name('collect_game_licenses.py'))
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

SOURCE = 'registry+https://github.com/rust-lang/crates.io-index'
FEATURES = ['audio', 'legacy-macroquad', 'wgpu-runtime']
BEGIN = b'\n\n========================================================================\nBEGIN GENERATED WINDOWS GAME DEPENDENCY NOTICES\n'
END = b'\nEND GENERATED WINDOWS GAME DEPENDENCY NOTICES\n'
BASELINE = (b'Existing project notices, kept exactly.\r\n\r\n'
            b'zeta 0.3.0\r\nDeclared license: MIT\r\n'
            b'Pre-existing attribution text; preserve spacing.  \r\n')


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


class CollectGameLicensesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.registry = self.root / 'registry'
        self.index = 'index.crates.io-fixture'
        self.packages = []
        self.nodes = []
        self.archives = {}
        self.members = {}
        self.locked = {}
        self.game = self.add_local('fixture-game')
        self.local = self.add_local('local-helper')
        self.alpha_text = 'Copyright (c) Alpha contributors\r\nOriginal UTF-8 café text.\r\n'.encode('utf-8')
        self.alpha = self.add_registry('alpha', '1.2.3', [
            ('LICENSE-MIT', self.alpha_text),
            ('legal/NOTICE', b'Original nested notice without terminal newline'),
            ('README.md', b'This is documentation, not notice text.'),
        ], features=['feature-z', 'feature-a'])
        self.zeta = self.add_registry('zeta', '0.3.0', [('COPYING', b'Original zeta text\n')])
        self.build = self.add_registry('build-helper', '2.0.1', [('LICENCE', b'Build/proc-macro notice\n')])
        # This archive intentionally has no license and must never be visited.
        self.unused = self.add_registry('unused', '9.9.9', [('README.md', b'Unreachable')])
        self.node(self.game)['features'] = list(FEATURES)
        self.connect(self.game, self.alpha)
        self.connect(self.game, self.local)
        self.connect(self.game, self.zeta)
        self.connect(self.local, self.zeta)
        self.connect(self.alpha, self.build, kind='build')
        self.metadata = {'packages': self.packages, 'resolve': {
            'root': self.game['id'], 'nodes': self.nodes}}
        self.notices = self.root / 'THIRD_PARTY_LICENSES.txt'
        self.inventory = self.root / 'game-dependency-notices.json'
        self.manifest = Path(self.game['manifest_path'])
        self.metadata_path = self.root / 'metadata.json'
        self.source_root = self.root / 'license-sources'
        self.supplements_path = self.source_root / 'manifest.json'
        self.notices.write_bytes(BASELINE)
        self.inventory.write_bytes(b'old inventory sentinel\n')
        # Any accidental metadata subprocess invocation is a hard test failure.
        subprocess_guard = patch.object(collector.subprocess, 'check_output',
                                        side_effect=AssertionError('Cargo must not run in fixture tests'))
        self.cargo = subprocess_guard.start()
        self.addCleanup(subprocess_guard.stop)

    def add_local(self, name):
        manifest = self.root / 'workspace' / name / 'Cargo.toml'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(f'[package]\nname = "{name}"\nversion = "0.1.0"\n', encoding='utf-8')
        package = {'id': f'path+file:///{name}#0.1.0', 'name': name,
                   'version': '0.1.0', 'source': None, 'manifest_path': str(manifest)}
        self.packages.append(package)
        self.nodes.append({'id': package['id'], 'features': [], 'deps': []})
        return package

    def add_registry(self, name, version, files, features=()):
        extracted = self.registry / 'src' / self.index / f'{name}-{version}'
        extracted.mkdir(parents=True)
        manifest = (f'[package]\nname = "{name}"\nversion = "{version}"\n'
                    'license = "MIT"\n').encode('utf-8')
        (extracted / 'Cargo.toml').write_bytes(manifest)
        # The collector must read original archive bytes, not these extracted copies.
        for relative, raw in files:
            path = extracted / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        package = {'id': f'{SOURCE}#{name}@{version}', 'name': name, 'version': version,
                   'source': SOURCE, 'manifest_path': str(extracted / 'Cargo.toml'),
                   'license': 'MIT', 'license_file': None, 'authors': [f'{name} contributors'],
                   'repository': f'https://example.invalid/{name}'}
        self.packages.append(package)
        self.nodes.append({'id': package['id'], 'features': list(features), 'deps': []})
        self.members[package['id']] = [('Cargo.toml', manifest), *files]
        self.repack(package)
        return package

    def repack(self, package, members=None, absolute_names=False):
        if members is not None:
            self.members[package['id']] = members
        name, version = package['name'], package['version']
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for relative, raw in self.members[package['id']]:
                path = relative if absolute_names else f'{name}-{version}/{relative}'
                entry = tarfile.TarInfo(path)
                entry.size = len(raw)
                entry.mtime = 0
                entry.mode = 0o644
                archive.addfile(entry, io.BytesIO(raw))
        # Fixed gzip mtime makes the fixture reproducible independently of wall time.
        compressed = gzip.compress(data.getvalue(), mtime=0)
        path = self.registry / 'cache' / self.index / f'{name}-{version}.crate'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(compressed)
        self.archives[package['id']] = path
        self.locked[package['id']] = {'name': name, 'version': version,
                                     'source': package['source'], 'checksum': digest(compressed)}

    def node(self, package):
        return next(node for node in self.nodes if node['id'] == package['id'])

    def connect(self, parent, child, kind=None):
        self.node(parent)['deps'].append({'name': child['name'], 'pkg': child['id'],
                                         'dep_kinds': [{'kind': kind, 'target': None}]})

    def lock_bytes(self):
        sections = ['version = 3\n']
        for package in [self.game, self.local, *self.locked.values()]:
            sections.append('[[package]]\n')
            for field in ('name', 'version', 'source', 'checksum'):
                if package.get(field) is not None:
                    sections.append(f'{field} = {json.dumps(package[field])}\n')
        return ''.join(sections).encode('utf-8')

    def generate(self, baseline=BASELINE, **kwargs):
        return collector.generate(self.metadata, self.lock_bytes(), baseline, **kwargs)

    def write_inputs(self):
        self.manifest.with_name('Cargo.lock').write_bytes(self.lock_bytes())
        self.metadata_path.write_text(json.dumps(self.metadata), encoding='utf-8')

    def cli(self, *extra):
        self.write_inputs()
        output, errors = io.StringIO(), io.StringIO()
        arguments = ['--manifest', str(self.manifest), '--metadata', str(self.metadata_path),
                     '--notices', str(self.notices), '--inventory', str(self.inventory),
                     '--supplements', str(self.supplements_path), *extra]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                status = collector.main(arguments)
            except SystemExit as error:
                status = error.code
        self.cargo.assert_not_called()
        return status, output.getvalue(), errors.getvalue()

    def assert_cli_failure_preserves_outputs(self, pattern, *extra):
        before = (self.notices.read_bytes(), self.inventory.read_bytes())
        status, output, errors = self.cli(*extra)
        self.assertEqual(status, 1, errors)
        self.assertEqual(output, '')
        self.assertRegex(errors, pattern)
        self.assertEqual((self.notices.read_bytes(), self.inventory.read_bytes()), before)

    def supplement(self, package=None, raw=b'Original upstream permission text\r\n', archive_slice=False):
        package = package or self.alpha
        manifest = self.members[package['id']][0]
        commit = 'a' * 40
        members = [manifest, ('Cargo.toml.orig', manifest[1]),
                   ('.cargo_vcs_info.json', json.dumps({'git': {'sha1': commit}}).encode('utf-8'))]
        source = b'// synthetic source prefix\n' + raw + b'fn example() {}\n'
        if archive_slice:
            members.append(('src/lib.rs', source))
        self.repack(package, members)
        self.source_root.mkdir(parents=True, exist_ok=True)
        relative = f"texts/{package['name']}.txt"
        path = self.source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        record = {'file': relative, 'label': 'LICENSE', 'bytes': len(raw), 'sha256': digest(raw),
                  'source_commit': commit,
                  'source_url': f'https://github.com/fixture/{package["name"]}/blob/{commit}/LICENSE'}
        if archive_slice:
            start = len(b'// synthetic source prefix\n')
            record.update({'archive_member': 'src/lib.rs', 'archive_source_sha256': digest(source),
                           'byte_range': [start, start + len(raw)]})
        entry = {'name': package['name'], 'version': package['version'],
                 'status': 'verified-upstream-supplement', 'notes': ['Synthetic fixture only'],
                 'archive_sha256': self.locked[package['id']]['checksum'],
                 'published_manifest_sha256': digest(manifest[1]), 'vcs_commit': commit,
                 'files': [record]}
        return {'schema': 'rust-duty-game-notice-supplements/v1', 'packages': [entry]}

    def generate_with_supplements(self, supplements, baseline=BASELINE):
        return self.generate(baseline, supplements=supplements, source_root=self.source_root)

    def unresolved(self, package):
        supplements = self.supplement(package)
        entry = supplements['packages'][0]
        entry.update({'status': 'preserved-baseline-unresolved', 'files': [],
                      'caveat': 'Synthetic inherited attribution gap; no original license text verified.',
                      'issue_url': 'https://github.com/fixture/quad-rand/issues/1'})
        return supplements

    def test_cli_check_utf8_json_is_independent_of_windows_locale(self):
        # Cargo emits UTF-8 even when Windows uses a legacy text locale.
        # Keep non-ASCII JSON literal so a CP1252 decoder produces valid JSON
        # with corrupted metadata, reproducing a stale-inventory check failure.
        self.alpha['authors'] = ['René Møller']
        supplements = self.supplement()
        supplements['packages'][0]['notes'] = ['Original café provenance']
        self.manifest.with_name('Cargo.lock').write_bytes(self.lock_bytes())
        metadata_bytes = json.dumps(self.metadata, ensure_ascii=False).encode('utf-8')
        self.metadata_path.write_bytes(metadata_bytes)
        self.supplements_path.write_bytes(
            json.dumps(supplements, ensure_ascii=False).encode('utf-8'))
        expected = self.generate_with_supplements(supplements)
        self.notices.write_bytes(expected[0])
        self.inventory.write_bytes(expected[1])
        record = next(package for package in json.loads(expected[1])['packages']
                      if package['name'] == 'alpha')
        self.assertEqual(record['authors'], ['René Møller'])
        self.assertEqual(record['supplement_notes'], ['Original café provenance'])

        def cargo_output(command, **kwargs):
            self.assertEqual(command[:2], ['cargo', 'metadata'])
            self.assertIn('--locked', command)
            self.assertIn('--offline', command)
            if kwargs.get('text') or kwargs.get('encoding'):
                return metadata_bytes.decode(kwargs.get('encoding') or 'cp1252',
                                             kwargs.get('errors') or 'strict')
            return metadata_bytes

        def legacy_locale_read_text(path, encoding=None, errors=None):
            return path.read_bytes().decode(encoding or 'cp1252', errors or 'strict')

        self.cargo.side_effect = cargo_output
        arguments = ['--manifest', str(self.manifest), '--notices', str(self.notices),
                     '--inventory', str(self.inventory), '--supplements',
                     str(self.supplements_path), '--check']
        for metadata_arguments in ([], ['--metadata', str(self.metadata_path)]):
            with self.subTest(metadata_arguments=metadata_arguments):
                before_calls = self.cargo.call_count
                with patch.object(Path, 'read_text', legacy_locale_read_text), \
                        patch.object(collector, 'atomic_write',
                                     side_effect=AssertionError('--check must not write')), \
                        contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    try:
                        status = collector.main(arguments + metadata_arguments)
                    except SystemExit as error:
                        status = error.code
                self.assertEqual(status, 0, errors.getvalue())
                self.assertEqual(self.cargo.call_count - before_calls,
                                 0 if metadata_arguments else 1)
                self.assertEqual((self.notices.read_bytes(), self.inventory.read_bytes()), expected)

    def test_original_bytes_and_baseline_are_preserved_exactly(self):
        (Path(self.alpha['manifest_path']).parent / 'LICENSE-MIT').write_bytes(b'edited extracted text')
        notices, inventory_bytes = self.generate()
        self.assertTrue(notices.startswith(BASELINE + BEGIN))
        self.assertTrue(notices.endswith(END))
        self.assertIn(self.alpha_text, notices)
        self.assertIn(b'Original nested notice without terminal newline\n', notices)
        self.assertNotIn(b'edited extracted text', notices)
        self.assertNotIn(b'This is documentation', notices)
        # Existing package attribution stays in the baseline without re-appending.
        self.assertEqual(notices.count(b'zeta 0.3.0'), 1)
        self.assertNotIn(b'Original zeta text', notices)
        report = json.loads(inventory_bytes)
        self.assertEqual(report['preserved_baseline_sha256'], digest(BASELINE))
        self.assertEqual(report['preserved_baseline_bytes'], len(BASELINE))
        self.assertEqual(report['notice_sha256'], digest(notices))
        self.assertEqual(report['notice_bytes'], len(notices))
        self.assertEqual(report['cargo_lock_sha256'], digest(self.lock_bytes()))

    def test_only_reachable_registry_closure_is_collected(self):
        # Including cycles exercises visited-node deduplication.
        self.connect(self.build, self.alpha)
        notices, inventory_bytes = self.generate()
        report = json.loads(inventory_bytes)
        self.assertEqual([package['name'] for package in report['packages']],
                         ['alpha', 'build-helper', 'zeta'])
        self.assertEqual(report['added_packages'], 2)
        self.assertNotIn(b'unused 9.9.9', notices)
        self.assertNotIn(b'local-helper 0.1.0', notices)
        self.assertIn(b'Build/proc-macro notice', notices)
        self.assertEqual(report['target'], 'x86_64-pc-windows-msvc')
        self.assertEqual(report['root_package'], {'name': 'fixture-game', 'version': '0.1.0'})
        self.assertEqual(report['cargo_features'], {'default_enabled': True, 'explicit': ['wgpu-runtime']})
        self.assertEqual(report['resolved_root_features'], sorted(FEATURES))

    def test_inventory_records_independently_verified_file_and_archive_hashes(self):
        _, inventory_bytes = self.generate()
        report = json.loads(inventory_bytes)
        alpha = report['packages'][0]
        self.assertEqual(alpha['archive_sha256'], digest(self.archives[self.alpha['id']].read_bytes()))
        self.assertEqual(alpha['files'], [
            {'path': 'LICENSE-MIT', 'bytes': len(self.alpha_text), 'sha256': digest(self.alpha_text)},
            {'path': 'legal/NOTICE', 'bytes': 47,
             'sha256': digest(b'Original nested notice without terminal newline')},
        ])
        self.assertEqual(alpha['enabled_features'], ['feature-a', 'feature-z'])
        self.assertEqual(alpha['source_package_url'], 'https://crates.io/crates/alpha/1.2.3')
        self.assertEqual(alpha['notice_location'], 'generated additions')
        self.assertEqual(report['packages'][-1]['notice_location'], 'preserved baseline')
        self.assertTrue(inventory_bytes.endswith(b'\n'))

    def test_regeneration_is_byte_identical_and_order_independent(self):
        expected = self.generate()
        self.assertEqual(self.generate(expected[0]), expected)
        self.metadata['packages'] = list(reversed(self.packages))
        self.metadata['resolve']['nodes'] = list(reversed(self.nodes))
        for node in self.nodes:
            node['deps'].reverse()
            node['features'].reverse()
        self.assertEqual(self.generate(expected[0]), expected)

    def test_declared_license_file_with_unconventional_name(self):
        raw = b'Verified custom-named permission text\n'
        manifest = self.members[self.alpha['id']][0]
        self.repack(self.alpha, [manifest, ('legal/terms.txt', raw)])
        for declared in ('legal/terms.txt', str(Path(self.alpha['manifest_path']).parent / 'legal/terms.txt')):
            with self.subTest(declared=declared):
                self.alpha['license_file'] = declared
                self.alpha['license'] = None
                notices, inventory_bytes = self.generate()
                self.assertIn(raw, notices)
                self.assertIn(b'Declared license: See original license_file below', notices)
                self.assertEqual(json.loads(inventory_bytes)['packages'][0]['files'][0]['path'], 'legal/terms.txt')

    def test_missing_or_outside_declared_license_file_fails(self):
        for declared in ('legal/missing.txt', str(self.root / 'outside.txt')):
            with self.subTest(declared=declared):
                self.alpha['license_file'] = declared
                with self.assertRaisesRegex(ValueError, 'license_file'):
                    self.generate()

    def test_missing_license_fails_before_outputs_change(self):
        self.repack(self.alpha, [self.members[self.alpha['id']][0]])
        self.assert_cli_failure_preserves_outputs('original license/notice text missing')

    def test_empty_and_non_utf8_license_fail_before_outputs_change(self):
        manifest = self.members[self.alpha['id']][0]
        for contents, pattern in [(b'', 'empty original license'), (b'Copyright\xff', 'non-UTF8')]:
            with self.subTest(contents=contents):
                self.repack(self.alpha, [manifest, ('LICENSE', contents)])
                self.assert_cli_failure_preserves_outputs(pattern)

    def test_oversized_license_fails(self):
        self.repack(self.alpha, [self.members[self.alpha['id']][0], ('LICENSE', b'x' * (4 * 1024**2 + 1))])
        with self.assertRaisesRegex(ValueError, 'oversized license'):
            self.generate()

    def test_archive_corruption_fails_before_outputs_change(self):
        archive = self.archives[self.alpha['id']]
        archive.write_bytes(archive.read_bytes() + b'corruption')
        self.assert_cli_failure_preserves_outputs('checksum mismatch')

    def test_checksummed_but_malformed_archive_fails_without_writing(self):
        contents = b'not a gzip tar archive'
        self.archives[self.alpha['id']].write_bytes(contents)
        self.locked[self.alpha['id']]['checksum'] = digest(contents)
        self.assert_cli_failure_preserves_outputs('Game license collection failed')

    def test_baseline_attribution_does_not_bypass_original_verification(self):
        self.repack(self.zeta, [self.members[self.zeta['id']][0]])
        self.assert_cli_failure_preserves_outputs('original license/notice text missing')

    def test_missing_archive_fails_before_outputs_change(self):
        self.archives[self.alpha['id']].unlink()
        self.assert_cli_failure_preserves_outputs('archive missing')

    def test_missing_invalid_or_wrong_source_lock_entries_fail(self):
        original = copy.deepcopy(self.locked[self.alpha['id']])
        for altered in (None, {**original, 'checksum': 'not-a-sha256'},
                        {**original, 'source': 'registry+https://example.invalid/index'}):
            with self.subTest(altered=altered):
                if altered is None:
                    self.locked.pop(self.alpha['id'], None)
                else:
                    self.locked[self.alpha['id']] = altered
                with self.assertRaisesRegex(ValueError, 'missing exact locked registry checksum'):
                    self.generate()

    def test_unsupported_registry_source_fails(self):
        self.alpha['source'] = 'git+https://example.invalid/project'
        with self.assertRaisesRegex(ValueError, 'unsupported source'):
            self.generate()

    def test_changed_extracted_manifest_fails_before_outputs_change(self):
        Path(self.alpha['manifest_path']).write_bytes(b'[package]\nname = "tampered"\n')
        self.assert_cli_failure_preserves_outputs('extracted package manifest differs')

    def test_missing_original_manifest_fails(self):
        self.repack(self.alpha, [('LICENSE', self.alpha_text)])
        with self.assertRaisesRegex(ValueError, 'original package manifest missing'):
            self.generate()

    def test_unsafe_archive_paths_fail(self):
        original = list(self.members[self.alpha['id']])
        for path in ('../escape', 'legal/../../escape'):
            with self.subTest(path=path):
                self.repack(self.alpha, [*original, (path, b'unsafe')])
                with self.assertRaisesRegex(ValueError, 'unsafe archive path'):
                    self.generate()
        for path in ('/alpha-1.2.3/LICENSE', 'other-1.2.3/LICENSE'):
            with self.subTest(path=path):
                self.repack(self.alpha, [(path, b'unsafe')], absolute_names=True)
                with self.assertRaisesRegex(ValueError, 'unsafe archive root'):
                    self.generate()

    def test_duplicate_archive_members_fail(self):
        self.repack(self.alpha, [*self.members[self.alpha['id']], ('LICENSE-MIT', b'duplicate')])
        with self.assertRaisesRegex(ValueError, 'duplicate archive member'):
            self.generate()

    def test_noncanonical_archive_paths_fail(self):
        original = list(self.members[self.alpha['id']])
        for path in ('/LICENSE-MIT', './LICENSE-MIT', 'legal//NOTICE', 'legal/./NOTICE'):
            with self.subTest(path=path):
                self.repack(self.alpha, [*original, (path, b'noncanonical duplicate')])
                with self.assertRaisesRegex(ValueError, 'unsafe|noncanonical'):
                    self.generate()

    def test_verified_upstream_supplement_preserves_bytes_and_provenance(self):
        raw = 'Original upstream copyright © fixture\r\n'.encode('utf-8')
        supplements = self.supplement(raw=raw)
        with self.assertRaisesRegex(ValueError, 'original license/notice text missing'):
            self.generate()
        notices, inventory = self.generate_with_supplements(supplements)
        self.assertTrue(notices.startswith(BASELINE + BEGIN))
        self.assertIn(raw, notices)
        record = supplements['packages'][0]['files'][0]
        self.assertIn(record['source_url'].encode(), notices)
        report = json.loads(inventory)
        package = report['packages'][0]
        self.assertEqual(package['supplement_status'], 'verified-upstream-supplement')
        self.assertEqual(package['supplemental_sources'], [record])
        self.assertEqual(package['files'][0]['sha256'], digest(raw))
        manifest_bytes = json.dumps(supplements, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(report['supplement_manifest_sha256'], digest(manifest_bytes))
        self.assertEqual(self.generate_with_supplements(supplements, notices), (notices, inventory))

    def test_verified_supplement_is_added_even_for_existing_baseline_package(self):
        raw = b'Original zeta upstream copyright and permission\n'
        supplements = self.supplement(self.zeta, raw=raw)
        notices, inventory = self.generate_with_supplements(supplements)
        self.assertTrue(notices.startswith(BASELINE + BEGIN))
        self.assertIn(raw, notices)
        self.assertEqual(json.loads(inventory)['packages'][-1]['notice_location'], 'generated additions')

    def test_verified_original_archive_slice(self):
        raw = b'// Copyright fixture contributors\n// Exact permission notice\n'
        supplements = self.supplement(raw=raw, archive_slice=True)
        notices, inventory = self.generate_with_supplements(supplements)
        self.assertIn(raw, notices)
        self.assertNotIn(b'fn example() {}', notices)
        self.assertEqual(json.loads(inventory)['packages'][0]['supplemental_sources'],
                         supplements['packages'][0]['files'])

    def test_supplement_pins_must_match_locked_package_evidence(self):
        supplements = self.supplement()
        for field, value, pattern in [
                ('archive_sha256', '0' * 64, 'archive pin mismatch'),
                ('vcs_commit', 'b' * 40, 'VCS pin mismatch'),
                ('published_manifest_sha256', '0' * 64, 'package manifest mismatch')]:
            altered = copy.deepcopy(supplements)
            altered['packages'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, pattern):
                self.generate_with_supplements(altered)

    def test_supplement_schema_duplicates_and_status_are_rejected(self):
        supplements = self.supplement()
        invalid_schema = {**supplements, 'schema': 'unrecognized/v1'}
        duplicates = {**supplements, 'packages': supplements['packages'] * 2}
        invalid_status = copy.deepcopy(supplements)
        invalid_status['packages'][0]['status'] = 'trust-me'
        for altered, pattern in [(invalid_schema, 'schema'), (duplicates, 'duplicate'),
                                 (invalid_status, 'status')]:
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ValueError, pattern):
                self.generate_with_supplements(altered)

    def test_supplement_requires_source_directory_and_original_text(self):
        supplements = self.supplement()
        with self.assertRaisesRegex(ValueError, 'source directory'):
            self.generate(supplements=supplements)
        supplements['packages'][0]['files'] = []
        with self.assertRaisesRegex(ValueError, 'no original notice text'):
            self.generate_with_supplements(supplements)

    def test_supplement_text_hash_size_and_encoding_are_verified(self):
        supplements = self.supplement()
        record = supplements['packages'][0]['files'][0]
        path = self.source_root / record['file']
        for field, value in [('sha256', '0' * 64), ('bytes', record['bytes'] + 1)]:
            altered = copy.deepcopy(supplements)
            altered['packages'][0]['files'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'text checksum mismatch'):
                self.generate_with_supplements(altered)
        for raw, pattern in [(b'', 'empty supplemental text'), (b'Invalid\xfftext', 'utf-8')]:
            path.write_bytes(raw)
            altered = copy.deepcopy(supplements)
            altered['packages'][0]['files'][0].update({'bytes': len(raw), 'sha256': digest(raw)})
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, pattern):
                self.generate_with_supplements(altered)

    def test_supplement_missing_source_file_fails(self):
        supplements = self.supplement()
        (self.source_root / supplements['packages'][0]['files'][0]['file']).unlink()
        with self.assertRaises(FileNotFoundError):
            self.generate_with_supplements(supplements)

    def test_supplement_source_path_cannot_escape_or_be_symlink(self):
        supplements = self.supplement()
        record = supplements['packages'][0]['files'][0]
        for path in ('../outside.txt', str(self.root / 'outside.txt')):
            altered = copy.deepcopy(supplements)
            altered['packages'][0]['files'][0]['file'] = path
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'unsafe supplemental'):
                self.generate_with_supplements(altered)
        path = self.source_root / record['file']
        target = self.root / 'original.txt'
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.generate_with_supplements(supplements)

    def test_supplement_requires_immutable_github_source_url(self):
        supplements = self.supplement()
        for url in ('https://github.com/fixture/alpha/blob/main/LICENSE',
                    'https://github.com/fixture/alpha/blob/' + 'b' * 40 + '/LICENSE',
                    'https://example.invalid/fixture/blob/' + 'a' * 40 + '/LICENSE',
                    'http://github.com/fixture/alpha/blob/' + 'a' * 40 + '/LICENSE'):
            altered = copy.deepcopy(supplements)
            altered['packages'][0]['files'][0]['source_url'] = url
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'immutable original source'):
                self.generate_with_supplements(altered)

    def test_supplement_archive_slice_hash_range_and_exact_bytes_are_verified(self):
        supplements = self.supplement(archive_slice=True)
        for field, value, pattern in [
                ('archive_source_sha256', '0' * 64, 'source member mismatch'),
                ('byte_range', [-1, 20], 'original byte slice'),
                ('byte_range', [0, 100000], 'original byte slice'),
                ('byte_range', [2, 2], 'original byte slice'),
                ('byte_range', [True, 10], 'original byte slice'),
                ('byte_range', [0, 10], 'original byte slice')]:
            altered = copy.deepcopy(supplements)
            altered['packages'][0]['files'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, pattern):
                self.generate_with_supplements(altered)

    def test_quad_rand_existing_baseline_requires_explicit_disclosed_caveat(self):
        quad = self.add_registry('quad-rand', '0.2.3', [])
        self.connect(self.game, quad)
        supplements = self.unresolved(quad)
        baseline = BASELINE + b'quad-rand 0.2.3\r\nDeclared license: MIT\r\nInherited wording.  \r\n'
        with self.assertRaisesRegex(ValueError, 'original license/notice text missing'):
            self.generate(baseline)
        notices, inventory = self.generate_with_supplements(supplements, baseline)
        self.assertTrue(notices.startswith(baseline + BEGIN))
        self.assertIn(b'Inherited attribution caveat: quad-rand 0.2.3', notices)
        self.assertIn(supplements['packages'][0]['caveat'].encode(), notices)
        report = json.loads(inventory)
        self.assertEqual(report['preserved_baseline_sha256'], digest(baseline))
        self.assertEqual(report['preserved_baseline_caveats'][0]['name'], 'quad-rand')
        self.assertEqual(report['preserved_baseline_caveats'][0]['issue_url'],
                         supplements['packages'][0]['issue_url'])
        package = next(item for item in report['packages'] if item['name'] == 'quad-rand')
        self.assertEqual(package['notice_location'], 'preserved baseline')
        self.assertEqual(package['files'], [])
        self.assertEqual(package['supplement_status'], 'preserved-baseline-unresolved')
        self.assertEqual(self.generate_with_supplements(supplements, notices), (notices, inventory))

    def test_quad_rand_exception_cannot_introduce_missing_notice_for_new_package(self):
        quad = self.add_registry('quad-rand', '0.2.3', [])
        self.connect(self.game, quad)
        supplements = self.unresolved(quad)
        with self.assertRaisesRegex(ValueError, 'only preserve the existing quad-rand'):
            self.generate_with_supplements(supplements)

    def test_unresolved_exception_rejects_other_packages_or_quad_rand_versions(self):
        for name, version in [('other-package', '0.2.3'), ('quad-rand', '0.2.4')]:
            with self.subTest(name=name, version=version):
                package = self.add_registry(name, version, [])
                self.connect(self.game, package)
                supplements = self.unresolved(package)
                baseline = BASELINE + f'{name} {version}\nDeclared license: MIT\nOld text\n'.encode()
                with self.assertRaisesRegex(ValueError, 'only preserve the existing quad-rand'):
                    self.generate_with_supplements(supplements, baseline)
                self.node(self.game)['deps'] = [dep for dep in self.node(self.game)['deps']
                                               if dep['pkg'] != package['id']]

    def test_cli_supplement_generation_check_and_corruption_fail_closed(self):
        supplements = self.supplement()
        self.supplements_path.write_text(json.dumps(supplements), encoding='utf-8')
        status, _, errors = self.cli()
        self.assertEqual(status, 0, errors)
        before = (self.notices.read_bytes(), self.inventory.read_bytes())
        status, _, errors = self.cli('--check')
        self.assertEqual(status, 0, errors)
        self.assertEqual((self.notices.read_bytes(), self.inventory.read_bytes()), before)
        record = supplements['packages'][0]['files'][0]
        (self.source_root / record['file']).write_bytes(b'corrupt source')
        self.assert_cli_failure_preserves_outputs('supplemental text checksum mismatch')
        self.assert_cli_failure_preserves_outputs('supplemental text checksum mismatch', '--check')

    def test_each_required_root_feature_is_enforced(self):
        for missing in FEATURES:
            with self.subTest(missing=missing):
                self.node(self.game)['features'] = [feature for feature in FEATURES if feature != missing]
                with self.assertRaisesRegex(ValueError, 'audio.*legacy.*wgpu-runtime'):
                    self.generate()
        self.node(self.game)['features'] = list(FEATURES)
        self.node(self.game)['features'].append('unrelated-feature')
        self.generate()

    def test_missing_resolved_root_fails(self):
        self.metadata['resolve']['root'] = None
        with self.assertRaisesRegex(ValueError, 'resolved game root'):
            self.generate()

    def test_incomplete_reachable_resolution_fails(self):
        self.node(self.game)['deps'].append({'pkg': 'missing-dependency'})
        with self.assertRaisesRegex(ValueError, 'incomplete dependency resolution'):
            self.generate()

    def test_ambiguous_generated_markers_fail(self):
        notices, _ = self.generate()
        for invalid in (BASELINE + END, notices + b'trailing edit',
                        notices + BEGIN + END, BASELINE + BEGIN + b'no end'):
            with self.subTest(invalid=invalid[-100:]):
                with self.assertRaisesRegex(ValueError, 'marker|ambiguous|trailing'):
                    self.generate(invalid)

    def test_cli_generates_and_checks_without_cargo_or_mutation(self):
        status, output, errors = self.cli()
        self.assertEqual(status, 0, errors)
        result = json.loads(output)
        self.assertEqual(result['notice_sha256'], digest(self.notices.read_bytes()))
        self.assertEqual(result['added_packages'], 2)
        expected = (self.notices.read_bytes(), self.inventory.read_bytes())
        with patch.object(collector, 'atomic_write', side_effect=AssertionError('--check must not write')):
            status, _, errors = self.cli('--check')
        self.assertEqual(status, 0, errors)
        self.assertEqual((self.notices.read_bytes(), self.inventory.read_bytes()), expected)
        status, _, errors = self.cli()
        self.assertEqual(status, 0, errors)
        self.assertEqual((self.notices.read_bytes(), self.inventory.read_bytes()), expected)

    def test_cli_check_rejects_stale_notices_without_writing(self):
        self.assert_cli_failure_preserves_outputs('stale', '--check')

    def test_cli_check_rejects_edited_generated_text_without_writing(self):
        notices, inventory = self.generate()
        self.notices.write_bytes(notices.replace(self.alpha_text, b'edited generated notice'))
        self.inventory.write_bytes(inventory)
        self.assert_cli_failure_preserves_outputs('stale', '--check')

    def test_cli_check_rejects_stale_inventory_without_writing(self):
        notices, _ = self.generate()
        self.notices.write_bytes(notices)
        self.assert_cli_failure_preserves_outputs('stale', '--check')

    def test_cli_check_missing_inventory_does_not_create_it(self):
        notices, _ = self.generate()
        self.notices.write_bytes(notices)
        self.inventory.unlink()
        status, _, errors = self.cli('--check')
        self.assertEqual(status, 1, errors)
        self.assertFalse(self.inventory.exists())
        self.assertEqual(self.notices.read_bytes(), notices)


if __name__ == '__main__':
    unittest.main()
