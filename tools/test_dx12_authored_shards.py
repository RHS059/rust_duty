#!/usr/bin/env python3
"""CPU-only synthetic tests. No test runs or claims native renderer execution."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import dx12_authored_shards as shards


CI = {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123456', 'GITHUB_RUN_ATTEMPT': '2'}
EXPECTED_CONTEXT = {'source_commit': 'a' * 40, 'run_id': '123456', 'run_attempt': '2'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ProfilesAndPathsTests(unittest.TestCase):
    def test_exact_closed_scenarios_and_profiles(self):
        values = {
            'jump-gameplay': (403, 2100, 3300, 60, 75),
            'reload-gameplay': (214, 1200, 2400, 45, 60),
            'walk-gameplay': (223, 1500, 2700, 50, 65),
            'ads-gameplay': (553, 3000, 4200, 75, 90),
            'ads-offset': (553, 3000, 4200, 75, 90),
            'layered-30': (337, 2100, 3300, 60, 75),
            'layered-60': (673, 3900, 5100, 90, 105),
            'reload-return': (391, 1800, 3000, 55, 70),
            'lighting-orientation': (None, 900, 1800, 35, 50),
        }
        self.assertEqual(shards.SCENARIOS, tuple(values))
        self.assertEqual(shards.SCENARIOS[:-1], tuple(case.name for case in shards.authored.CASES))
        self.assertEqual(set(shards.PROFILES), set(values))
        keys = ('expected_frames', 'capture_timeout_seconds', 'run_timeout_seconds',
                'step_timeout_minutes', 'job_timeout_minutes')
        for name, row in values.items():
            self.assertEqual(shards.PROFILES[name], dict(zip(keys, row)))
            profile = shards.PROFILES[name]
            self.assertLess(profile['run_timeout_seconds'], profile['step_timeout_minutes'] * 60)
            self.assertLess(profile['step_timeout_minutes'], profile['job_timeout_minutes'])
            for key, value in profile.items():
                self.assertTrue(type(value) is int or (key == 'expected_frames' and value is None))

    def test_real_case_paths_and_auxiliary_has_no_legacy_claim(self):
        for case in shards.authored.CASES:
            self.assertEqual(shards.capture_paths(case.name), {
                'windows-legacy': 'captures/windows-legacy/' + case.baseline,
                'dx12': 'captures/dx12/' + case.name,
            })
        self.assertEqual(shards.capture_paths('lighting-orientation'), {
            'dx12': 'captures/dx12/lighting', 'orientation': 'renderer-contract'})
        self.assertEqual(shards.capture_paths('ads-offset')['windows-legacy'],
                         'captures/windows-legacy/ads-placement/ads-offset')
        for unknown in ('layered', 'lighting', '', '../ads-gameplay', True, None):
            with self.subTest(unknown=unknown), self.assertRaises(ValueError):
                shards.capture_paths(unknown)


class ContextTests(unittest.TestCase):
    def test_context_has_exact_fields_and_string_types(self):
        with mock.patch.dict(os.environ, CI, clear=True):
            self.assertEqual(shards.context(), EXPECTED_CONTEXT)

    def test_no_implicit_identity(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            shards.context()
        for key in CI:
            env = dict(CI)
            del env[key]
            with self.subTest(missing=key), mock.patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                shards.context()

    def test_invalid_commit(self):
        for value in ('main', 'a' * 39, 'a' * 41, 'g' * 40, 'A' * 40, ' ' + 'a' * 40, 'a' * 40 + '\n'):
            with self.subTest(value=value), mock.patch.dict(os.environ, {**CI, 'GITHUB_SHA': value}, clear=True), self.assertRaises(ValueError):
                shards.context()

    def test_positive_canonical_ascii_decimal_run_identity(self):
        for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
            for value in ('', '0', '-1', '+1', '1.0', '01', ' 1', '1\n', '１２', '1e3'):
                with self.subTest(key=key, value=value), mock.patch.dict(os.environ, {**CI, key: value}, clear=True), self.assertRaises(ValueError):
                    shards.context()


class SyntheticInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'repo'
        self.root.mkdir()
        self.executable = self.root / 'vector-range.exe'
        self.fixture = self.root / 'renderer-contract.exe'
        self.files = {
            'vector-range.exe': b'synthetic dual runtime, not an executable\x00',
            'renderer-contract.exe': b'synthetic fixture, not an executable\xff',
            'Cargo.toml': b'[package]\nname = "synthetic"\n',
            'Cargo.lock': b'version = 4\n',
            'settings.cfg': b'viewmodel_offset_x=0\n',
            'assets/animations.cfg': b'normal_ready=synthetic\n',
            'assets/locomotion/asset.vra': b'not a real asset\x00\x01',
            'assets/locomotion/asset.vrs': b'synthetic skin',
            'assets/locomotion/asset.vrm': b'synthetic mesh',
            'assets/authoring/ads/sight_alignment.json': b'{"synthetic":true}\n',
            'assets/README.md': b'ordinary file, not a runtime manifest',
        }
        for name, contents in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, CI, clear=True).start()
        # Keep the real asset_evidence collection and real hash computations;
        # replace only the expensive authored source-generation verifier.
        self.generated = mock.patch.object(shards.authored, 'verify_generated', return_value={
            'walk': {'synthetic': True}, 'ads': {'synthetic': True},
            'directional': {'synthetic': True}, 'jump': {'synthetic': True},
        }).start()

    def manifest(self):
        return shards.make_input_manifest(self.executable, self.fixture, self.root)

    def test_exact_manifest_and_real_hashes(self):
        manifest = self.manifest()
        expected_assets = {name: digest(data) for name, data in self.files.items()
                           if name == 'settings.cfg' or (name.startswith('assets/') and Path(name).suffix in ('.vra', '.vrs', '.vrm', '.json', '.cfg'))}
        expected = {
            'schema': 'rust-duty-dx12-authored-inputs/v1',
            'platform': 'win32',
            'build_selection': {'default_enabled': False, 'features': ['legacy-macroquad', 'wgpu-runtime']},
            'binding': {
                **EXPECTED_CONTEXT,
                'executable_sha256': digest(self.files['vector-range.exe']),
                'renderer_contract_sha256': digest(self.files['renderer-contract.exe']),
                'cargo_manifest_sha256': digest(self.files['Cargo.toml']),
                'cargo_lock_sha256': digest(self.files['Cargo.lock']),
                'runtime_and_manifest_sha256': expected_assets,
            },
            'expected_scenarios': list(shards.SCENARIOS),
        }
        self.assertEqual(manifest, expected)
        self.generated.assert_called_once_with(self.root)
        self.assertNotIn(str(self.root), json.dumps(manifest))
        self.assertEqual(shards.verify_input_manifest(manifest, self.executable, self.fixture, self.root), expected['binding'])

    def test_cargo_hashes_canonicalize_only_line_endings(self):
        before = self.manifest()
        for name in ('Cargo.toml', 'Cargo.lock'):
            (self.root / name).write_bytes(self.files[name].replace(b'\n', b'\r\n'))
        self.assertEqual(self.manifest(), before)
        for name in ('Cargo.toml', 'Cargo.lock'):
            (self.root / name).write_bytes(self.files[name].replace(b'\n', b'\r'))
        self.assertEqual(self.manifest(), before)
        (self.root / 'Cargo.toml').write_bytes(self.files['Cargo.toml'] + b' ')
        self.assertNotEqual(self.manifest()['binding']['cargo_manifest_sha256'], before['binding']['cargo_manifest_sha256'])

    def test_binary_and_runtime_bytes_are_not_line_normalized(self):
        before = self.manifest()
        self.executable.write_bytes(self.files['vector-range.exe'] + b'\r\n')
        (self.root / 'settings.cfg').write_bytes(self.files['settings.cfg'].replace(b'\n', b'\r\n'))
        after = self.manifest()
        self.assertEqual(after['binding']['executable_sha256'], digest(self.executable.read_bytes()))
        self.assertNotEqual(after['binding']['executable_sha256'], before['binding']['executable_sha256'])
        self.assertNotEqual(after['binding']['runtime_and_manifest_sha256'], before['binding']['runtime_and_manifest_sha256'])

    def test_manifest_rejects_every_changed_input(self):
        before = self.manifest()
        for name in self.files:
            if name == 'assets/README.md':
                continue
            path = self.root / name
            path.write_bytes(self.files[name] + b'tamper')
            with self.subTest(name=name), self.assertRaises(ValueError):
                shards.verify_input_manifest(before, self.executable, self.fixture, self.root)
            path.write_bytes(self.files[name])

    def test_full_manifest_typed_shape_and_order_are_required(self):
        original = self.manifest()
        changes = [
            lambda m: m.update(extra=True),
            lambda m: m.pop('platform'),
            lambda m: m.update(schema='other/v1'),
            lambda m: m.update(platform='linux'),
            lambda m: m['build_selection'].update(default_enabled=0),
            lambda m: m['build_selection'].update(default_enabled=True),
            lambda m: m['build_selection'].update(features=['wgpu-runtime', 'legacy-macroquad']),
            lambda m: m['build_selection'].update(features=['wgpu-runtime']),
            lambda m: m['build_selection'].update(extra=False),
            lambda m: m.update(expected_scenarios=list(reversed(shards.SCENARIOS))),
            lambda m: m.update(expected_scenarios=tuple(shards.SCENARIOS)),
            lambda m: m['expected_scenarios'].pop(),
            lambda m: m['binding'].update(run_attempt=2),
            lambda m: m['binding'].update(source_commit='b' * 40),
            lambda m: m['binding'].update(executable_sha256='0' * 64),
        ]
        for index, change in enumerate(changes):
            candidate = copy.deepcopy(original)
            change(candidate)
            with self.subTest(change=index), self.assertRaises(ValueError):
                shards.verify_input_manifest(candidate, self.executable, self.fixture, self.root)
        for bad in ([], None, False):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                shards.verify_input_manifest(bad, self.executable, self.fixture, self.root)

    def test_reject_other_source_run_and_attempt(self):
        manifest = self.manifest()
        for key, value in (('GITHUB_SHA', 'b' * 40), ('GITHUB_RUN_ID', '654321'), ('GITHUB_RUN_ATTEMPT', '3')):
            with self.subTest(key=key), mock.patch.dict(os.environ, {key: value}), self.assertRaises(ValueError):
                shards.verify_input_manifest(manifest, self.executable, self.fixture, self.root)

    def test_source_verifier_failure_is_not_hidden(self):
        self.generated.side_effect = ValueError('synthetic source validation failed')
        with self.assertRaisesRegex(ValueError, 'synthetic source validation failed'):
            self.manifest()

    def test_source_companion_requirement_is_retained(self):
        for missing in ('walk', 'ads', 'directional', 'jump'):
            self.generated.return_value = {name: {} for name in ('walk', 'ads', 'directional', 'jump') if name != missing}
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'source-validated'):
                self.manifest()

    def test_inconsistent_asset_map_is_rejected(self):
        original = self.manifest()['binding']['runtime_and_manifest_sha256']
        for change in ('missing', 'changed', 'unexpected', 'unsafe', 'boolean'):
            candidate = dict(original)
            if change == 'missing':
                del candidate['assets/animations.cfg']
            elif change == 'changed':
                candidate['assets/animations.cfg'] = '0' * 64
            elif change == 'unexpected':
                candidate['assets/invented.cfg'] = '0' * 64
            elif change == 'unsafe':
                candidate['../outside'] = '0' * 64
            else:
                candidate['settings.cfg'] = True
            with self.subTest(change=change), mock.patch.object(shards.authored, 'asset_evidence', return_value={'runtime_and_manifest_sha256': candidate}), self.assertRaises(ValueError):
                self.manifest()

    def test_missing_binary_fixture_cargo_settings_or_assets_fails(self):
        for name in ('vector-range.exe', 'renderer-contract.exe', 'Cargo.toml', 'Cargo.lock', 'settings.cfg'):
            path = self.root / name
            path.unlink()
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.manifest()
            path.write_bytes(self.files[name])
        with self.assertRaises(ValueError):
            shards.make_input_manifest(self.executable, self.fixture, self.root / 'missing')

    def test_symlinked_build_and_input_files_are_rejected(self):
        target = self.root / 'target'
        target.write_bytes(b'target')
        for name in ('vector-range.exe', 'renderer-contract.exe', 'Cargo.toml', 'Cargo.lock', 'settings.cfg', 'assets/animations.cfg', 'assets/README.md'):
            path = self.root / name
            path.unlink()
            try:
                path.symlink_to(target)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f'symlink creation unavailable: {error}')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'symlink|reparse'):
                self.manifest()
            path.unlink()
            path.write_bytes(self.files[name])

    def test_new_runtime_file_breaks_existing_manifest(self):
        manifest = self.manifest()
        (self.root / 'assets/unexpected.cfg').write_bytes(b'new runtime input')
        with self.assertRaises(ValueError):
            shards.verify_input_manifest(manifest, self.executable, self.fixture, self.root)

    def test_binding_exact_keys_types_and_default_context(self):
        binding = self.manifest()['binding']
        self.assertEqual(shards.validate_binding(binding), binding)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(shards.validate_binding(binding, EXPECTED_CONTEXT), binding)
            self.assertEqual(shards.compare_binding(binding, copy.deepcopy(binding)), binding)
            with self.assertRaises(ValueError):
                shards.validate_binding(binding)
        for key in binding:
            candidate = copy.deepcopy(binding)
            del candidate[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                shards.validate_binding(candidate)
        for changes in ({'extra': 'x'}, {'run_id': 123456}, {'run_attempt': True}, {'run_id': 123456.0},
                        {'executable_sha256': 'A' * 64}, {'cargo_lock_sha256': 'a' * 63},
                        {'runtime_and_manifest_sha256': {}}, {'runtime_and_manifest_sha256': []},
                        {'runtime_and_manifest_sha256': {'settings.cfg': True}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                shards.validate_binding({**binding, **changes})
        with self.assertRaises(ValueError):
            shards.validate_binding(binding, {**EXPECTED_CONTEXT, 'extra': True})
        for changes in ({'source_commit': 'b' * 40}, {'run_id': '654321'}, {'run_attempt': '3'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                shards.validate_binding(binding, {**EXPECTED_CONTEXT, **changes})

    def test_compare_binding_rejects_changes_to_every_field(self):
        binding = self.manifest()['binding']
        for key in binding:
            candidate = copy.deepcopy(binding)
            if key == 'runtime_and_manifest_sha256':
                candidate[key]['settings.cfg'] = '0' * 64
            elif key in ('run_id', 'run_attempt'):
                candidate[key] = '999'
            elif key == 'source_commit':
                candidate[key] = 'b' * 40
            else:
                candidate[key] = '0' * 64
            with self.subTest(key=key), self.assertRaises(ValueError):
                shards.compare_binding(binding, candidate)
        with self.assertRaises(ValueError):
            shards.compare_binding({'run_id': '1'}, {'run_id': '1'})

    def test_unsafe_asset_keys_and_case_aliases_fail(self):
        binding = self.manifest()['binding']
        unsafe = ('../outside', '/absolute', './relative', 'a//b', 'a/../b', 'a/',
                  'C:/outside', 'C:relative', 'a\\b', 'a\x00b', 'a\nb', 'a:b',
                  'a/CON.txt', 'a/nul', 'aux', 'COM1.bin', 'a/trailing.', 'a/trailing ', '', 'a\ud800b')
        for key in unsafe:
            candidate = copy.deepcopy(binding)
            candidate['runtime_and_manifest_sha256'][key] = '0' * 64
            with self.subTest(key=key), self.assertRaises(ValueError):
                shards.validate_binding(candidate)
        candidate = copy.deepcopy(binding)
        candidate['runtime_and_manifest_sha256']['SETTINGS.cfg'] = '0' * 64
        with self.assertRaises(ValueError):
            shards.validate_binding(candidate)


    def test_binding_rejects_ancestor_case_aliases_and_file_directory_conflicts(self):
        binding = self.manifest()['binding']
        for additions in ({'ASSETS/other.cfg': '0' * 64}, {'assets': '0' * 64},
                          {'settings.cfg/child': '0' * 64}):
            candidate = copy.deepcopy(binding)
            candidate['runtime_and_manifest_sha256'].update(additions)
            with self.subTest(additions=additions), self.assertRaises(ValueError):
                shards.validate_binding(candidate)

    def test_source_root_and_asset_directory_symlinks_are_rejected(self):
        alias = self.root.parent / 'repo-alias'
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f'symlink creation unavailable: {error}')
        with self.assertRaisesRegex(ValueError, 'symlink|reparse'):
            shards.make_input_manifest(self.executable, self.fixture, alias)
        assets = self.root / 'assets'
        moved = self.root / 'original-assets'
        assets.rename(moved)
        assets.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink|reparse'):
            self.manifest()


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'evidence'
        self.root.mkdir()
        self.files = {
            'summary.json': b'{"passed":false}\n',
            'input-manifest.json': b'{"synthetic":true}\n',
            'logs/stdout.log': b'raw renderer log\n',
            'logs/stderr.log': b'',
            'captures/frame.png': b'synthetic png bytes',
            'captures/frame.png.json': b'{"backend":"Dx12"}\n',
            'captures/frame.png.gameplay.json': b'{"tick":1}\n',
            'nested/summary.json': b'{"nested":true}\n',
        }
        for name, data in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def test_real_file_inventory_binds_all_evidence_and_only_skips_root_summary(self):
        expected = {key: digest(value) for key, value in self.files.items() if key != 'summary.json'}
        self.assertEqual(shards.inventory_files(self.root), expected)
        self.assertEqual(shards.verify_files(self.root, expected), expected)
        self.assertEqual(shards.inventory_files(self.root, exclude=()),
                         {key: digest(value) for key, value in self.files.items()})
        (self.root / 'summary.json').write_text('{"new":"progress"}')
        self.assertEqual(shards.verify_files(self.root, expected), expected)

    def test_full_inventory_verification_can_bind_historical_root_summary(self):
        recorded = shards.inventory_files(self.root, exclude=())
        self.assertIn('summary.json', recorded)
        self.assertEqual(shards.verify_files(self.root, recorded, exclude=()), recorded)
        (self.root / 'summary.json').write_bytes(b'changed historical summary')
        with self.assertRaisesRegex(ValueError, 'changed'):
            shards.verify_files(self.root, recorded, exclude=())
        with self.assertRaises(ValueError):
            shards.verify_files(self.root, recorded, exclude=('logs/stdout.log',))

    def test_added_removed_changed_evidence_fails(self):
        recorded = shards.inventory_files(self.root)
        extra = self.root / 'unexpected.log'
        extra.write_bytes(b'unrecorded')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            shards.verify_files(self.root, recorded)
        extra.unlink()
        for name in recorded:
            path = self.root / name
            original = path.read_bytes()
            path.unlink()
            with self.subTest(name=name, tamper='missing'), self.assertRaisesRegex(ValueError, 'missing'):
                shards.verify_files(self.root, recorded)
            path.write_bytes(original + b'tamper')
            with self.subTest(name=name, tamper='changed'), self.assertRaisesRegex(ValueError, 'changed'):
                shards.verify_files(self.root, recorded)
            path.write_bytes(original)

    def test_reject_untrusted_recorded_map(self):
        recorded = shards.inventory_files(self.root)
        for bad in (None, [], True, {'../outside': '0' * 64}, {'/absolute': '0' * 64},
                    {'input-manifest.json': True}, {'input-manifest.json': 'A' * 64},
                    {'input-manifest.json': 'bad'}, {**recorded, 'summary.json': digest(self.files['summary.json'])}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                shards.verify_files(self.root, bad)

    def test_no_arbitrary_inventory_exclusions(self):
        for excluded in (('logs',), ('logs/stdout.log',), ('summary.json', 'input-manifest.json'), 'summary.json', None):
            with self.subTest(excluded=excluded), self.assertRaises(ValueError):
                shards.inventory_files(self.root, excluded)

    def symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f'symlink creation unavailable: {error}')

    def test_root_symlink_rejected(self):
        link = self.root.parent / 'alias'
        self.symlink(link, self.root, directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink|reparse'):
            shards.inventory_files(link)

    def test_file_internal_external_and_dangling_symlinks_rejected(self):
        outside = self.root.parent / 'outside'
        outside.write_bytes(b'outside')
        for target in (outside, self.root / 'logs/stdout.log', self.root.parent / 'missing'):
            link = self.root / 'linked.log'
            self.symlink(link, target)
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'symlink|reparse'):
                shards.inventory_files(self.root)
            link.unlink()

    def test_directory_symlinks_and_cycles_rejected(self):
        for target in (self.root.parent, self.root, self.root / 'logs'):
            link = self.root / 'linked-dir'
            self.symlink(link, target, directory=True)
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'symlink|reparse'):
                shards.inventory_files(self.root)
            link.unlink()

    def test_excluded_summary_symlink_still_rejected(self):
        summary = self.root / 'summary.json'
        summary.unlink()
        self.symlink(summary, self.root / 'input-manifest.json')
        with self.assertRaisesRegex(ValueError, 'symlink|reparse'):
            shards.inventory_files(self.root)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO requires POSIX')
    def test_special_file_rejected_even_if_named_summary(self):
        for name in ('pipe', 'summary.json'):
            path = self.root / name
            path.unlink(missing_ok=True)
            os.mkfifo(path)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'special'):
                shards.inventory_files(self.root)
            path.unlink()

    def test_missing_root_and_regular_file_root_fail(self):
        for root in (self.root / 'missing', self.root / 'input-manifest.json'):
            with self.subTest(root=root), self.assertRaises(ValueError):
                shards.inventory_files(root)

    @unittest.skipIf(os.name == 'nt', 'unsafe Windows filenames cannot be created on Windows')
    def test_actual_unsafe_names_and_case_aliases_fail(self):
        for name in ('a\\b', 'a:b', 'CON.txt', 'a\nb', 'trailing.', 'trailing '):
            path = self.root / name
            path.write_bytes(b'unsafe')
            with self.subTest(name=name), self.assertRaises(ValueError):
                shards.inventory_files(self.root)
            path.unlink()
        (self.root / 'INPUT-MANIFEST.json').write_bytes(b'alias')
        with self.assertRaisesRegex(ValueError, 'aliases'):
            shards.inventory_files(self.root)

    def test_mutation_during_hashing_is_rejected(self):
        path = self.root / 'logs/stdout.log'
        real_digest = hashlib.file_digest

        def mutate(stream, algorithm):
            result = real_digest(stream, algorithm)
            path.write_bytes(b'changed during inventory')
            return result

        with mock.patch.object(shards.hashlib, 'file_digest', side_effect=mutate), self.assertRaisesRegex(ValueError, 'changed'):
            shards._read_regular(path)

    def test_empty_inventory_is_not_itself_a_native_pass(self):
        empty = self.root / 'empty'
        empty.mkdir()
        self.assertEqual(shards.inventory_files(empty), {})
        self.assertEqual(shards.verify_files(empty, {}), {})


if __name__ == '__main__':
    unittest.main()
