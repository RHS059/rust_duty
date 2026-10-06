"""Synthetic native-build receipt controls; no test claims Windows execution."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import prepare_ads_source_oracle as prepare
import test_dx12_authored_shards as fixtures
from test_build_ads_source_packet import COMPILER, COMPILER_SHA


class PrecompiledOracleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SyntheticInputTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        with (self.root / 'Cargo.toml').open('ab') as out:
            out.write(b'[profile.release]\nlto = "thin"\ncodegen-units = 1\nstrip = true\n')
        for name in ('src/lib.rs', 'src/authored_viewmodel.rs', 'src/weapon_model.rs',
                     'examples/source_visibility_certificate.rs', 'tools/build_ads_source_packet.py',
                     'tools/prepare_ads_source_oracle.py'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('original synthetic implementation ' + name + '\n').encode())
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE)
        git('init', '-q')
        git('config', 'core.autocrlf', 'false')
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic source')
        os.environ['GITHUB_SHA'] = git('rev-parse', 'HEAD').decode().strip()
        self.manifest = self.fixture.manifest()
        self.manifest_path = self.root.parent / 'native-input-manifest.json'
        self.manifest_path.write_bytes((json.dumps(self.manifest) + '\n').encode())
        self.package = self.root.parent / 'oracle-package'
        self.package.mkdir()
        (self.package / prepare.FILES[0]).write_bytes(b'SYNTHETIC NOT AN EXECUTABLE')
        (self.package / prepare.FILES[1]).write_bytes(COMPILER)
        self.build = {'command': prepare.build_command('C:/toolchain/cargo.exe'), 'cwd': 'C:/original/repo',
                      'exit_code': 0, 'environment': prepare.binding.ORACLE_ENVIRONMENT}
        (self.package / prepare.FILES[2]).write_bytes((json.dumps(self.build) + '\n').encode())
        (self.package / prepare.FILES[3]).write_bytes(self.manifest_path.read_bytes())
        inventory = prepare.producer.inventory(prepare.implementation_paths(self.root))
        self.receipt = {'schema': prepare.SCHEMA, 'capture_context': prepare.shared.context(),
            'capture_binding': deepcopy(self.manifest['binding']),
            'input_manifest_sha256': prepare.shared._read_regular(self.manifest_path),
            'platform': 'win32', 'machine': 'AMD64', 'host': prepare.TARGET, 'target': prepare.TARGET,
            'profile': 'release', 'features': prepare.producer.FEATURES, 'recorded_root': 'C:/original/repo',
            'executable': f'target/{prepare.TARGET}/release/examples/{prepare.EXAMPLE}.exe',
            'compiler_sha256': COMPILER_SHA,
            'toolchain': prepare.compiler_identity(COMPILER, COMPILER_SHA),
            'active_toolchain_alias': 'stable-x86_64-pc-windows-msvc',
            'implementation_before': inventory, 'implementation_after': deepcopy(inventory),
            'files': {name: prepare.producer.digest(self.package / name) for name in prepare.FILES}}
        self.seal()

    def seal(self):
        (self.package / 'receipt.json').write_bytes((json.dumps(self.receipt) + '\n').encode())
        self.anchor = prepare.shared._read_regular(self.package / 'receipt.json')

    def verify(self, anchor=None, compiler=None):
        return prepare.verify_precompiled(self.package, self.root, self.manifest_path,
                                          self.anchor if anchor is None else anchor,
                                          COMPILER_SHA if compiler is None else compiler)

    def test_thin_positive_packet_uses_all_real_hashes_without_companion_copies(self):
        result = self.verify()
        self.assertEqual(result['executable'], self.package / prepare.FILES[0])
        self.assertEqual({p.name for p in self.package.iterdir()}, set(prepare.FILES) | {'receipt.json'})
        self.assertFalse(any('asset.vra' in name for name in self.receipt['files']))

    def test_receipt_cannot_supply_or_refresh_its_own_anchor(self):
        for anchor in ('', 'f' * 64):
            with self.subTest(anchor=anchor), self.assertRaises(ValueError):
                self.verify(anchor=anchor)
        original = self.anchor
        self.receipt['active_toolchain_alias'] = 'different'
        self.seal()
        with self.assertRaisesRegex(ValueError, 'job output'):
            self.verify(anchor=original)

    def test_every_packaged_file_is_hash_bound(self):
        for name in prepare.FILES:
            path = self.package / name
            raw = path.read_bytes()
            path.write_bytes(raw + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(raw)

    def test_extra_missing_and_symlinked_files_are_rejected(self):
        extra = self.package / 'extra'
        extra.write_bytes(b'not allowed')
        with self.assertRaises(ValueError):
            self.verify()
        extra.unlink()
        path = self.package / prepare.FILES[0]
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.verify()
        path.write_bytes(raw)

    def test_context_platform_profile_and_build_selection_cannot_change(self):
        changes = [('capture_context', {**prepare.shared.context(), 'run_attempt': '9'}),
                   ('platform', 'linux'), ('machine', 'ARM64'), ('target', 'other'),
                   ('profile', 'dev'), ('features', ['wgpu-runtime'])]
        for key, value in changes:
            before = deepcopy(self.receipt)
            self.receipt[key] = value
            self.seal()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
            self.receipt = before
            self.seal()

    def test_same_source_cannot_be_relabelled_as_another_run(self):
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '999'}), self.assertRaises(ValueError):
            self.verify()

    def test_source_runtime_and_full_metadata_changes_are_rejected(self):
        for name in ('src/authored_viewmodel.rs', 'examples/source_visibility_certificate.rs',
                     'Cargo.toml', 'settings.cfg', 'assets/locomotion/asset.vrs',
                     'assets/authoring/ads/sight_alignment.json'):
            path = self.root / name
            raw = path.read_bytes()
            path.write_bytes(raw + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(raw)

    def test_compiler_hash_and_its_canonical_version_must_match(self):
        with self.assertRaisesRegex(ValueError, 'compiler differs'):
            self.verify(compiler='0' * 64)
        self.receipt['toolchain'] = 'stable'
        self.seal()
        with self.assertRaises(ValueError):
            self.verify()

    def test_source_changes_during_build_are_rejected(self):
        name = 'src/authored_viewmodel.rs'
        self.receipt['implementation_after'][name]['sha256'] = '0' * 64
        self.seal()
        with self.assertRaisesRegex(ValueError, 'changed source'):
            self.verify()

    def test_build_receipt_rejects_unrelated_targets_flags_or_failed_compilation(self):
        path = self.package / 'build-receipt.json'
        original = deepcopy(self.build)
        for change in ({'exit_code': 1}, {'command': original['command'] + ['--bin', 'vector-range']},
                       {'command': [x for x in original['command'] if x != '--release']},
                       {'environment': {**prepare.binding.ORACLE_ENVIRONMENT, 'RUSTFLAGS': '-Copt-level=0'}}):
            value = {**original, **change}
            path.write_bytes((json.dumps(value) + '\n').encode())
            self.receipt['files']['build-receipt.json'] = prepare.producer.digest(path)
            self.seal()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify()

    def test_compiler_header_and_release_are_checked_after_hash_validation(self):
        malformed = COMPILER.replace(b'release: 1.90.0', b'release: 1.91.0')
        with self.assertRaisesRegex(ValueError, 'header/release'):
            prepare.compiler_identity(malformed, hashlib.sha256(malformed).hexdigest())


if __name__ == '__main__':
    unittest.main()
