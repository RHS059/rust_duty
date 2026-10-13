"""Synthetic current-source build controls; these are not native execution proof."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import prepare_current_ads_profile as prepare
import test_dx12_authored_shards as fixtures
from test_build_ads_source_packet import COMPILER, COMPILER_SHA


class CurrentProfilePreparationTests(unittest.TestCase):
    def setUp(self):
        process_environment = {key: os.environ[key] for key in
            ('PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP') if key in os.environ}
        self.fixture = fixtures.SyntheticInputTests()
        self.fixture.setUp()
        os.environ.update(process_environment)
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        with (self.root / 'Cargo.toml').open('ab') as stream:
            stream.write(b'[profile.release]\nlto = "thin"\ncodegen-units = 1\nstrip = true\n')
        names = set(prepare.REQUIRED_IMPLEMENTATION) - {'Cargo.toml', 'Cargo.lock'}
        names.update(('src/lib.rs', 'src/render/finite_warp_probe.rs', 'src/render/shader.wgsl',
                      'updater/src/lib.rs', 'tools/dependent_diagnostic.py'))
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('synthetic current implementation ' + name + '\n').encode())
        self.git('init', '-q')
        self.git('config', 'core.autocrlf', 'false')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'synthetic source')
        os.environ['GITHUB_SHA'] = self.git('rev-parse', 'HEAD').decode().strip()
        self.manifest = self.fixture.manifest()
        self.manifest_path = self.root.parent / 'native-input-manifest.json'
        self.manifest_path.write_bytes((json.dumps(self.manifest) + '\n').encode())
        self.package = self.root.parent / 'current-profile-package'
        self.package.mkdir()
        self.builds = {}
        for example in prepare.EXAMPLES:
            (self.package / prepare.EXECUTABLES[example]).write_bytes(b'SYNTHETIC NOT EXECUTABLE ' + example.encode())
            self.builds[example] = {'command': prepare.build_command('C:/toolchain/cargo.exe', example),
                                   'cwd': 'C:/original/repo', 'exit_code': 0,
                                   'environment': prepare.binding.ORACLE_ENVIRONMENT}
            self.write_json(self.package / prepare.BUILD_RECEIPTS[example], self.builds[example])
        (self.package / 'rustc-Vv.txt').write_bytes(COMPILER)
        (self.package / 'input-manifest.json').write_bytes(self.manifest_path.read_bytes())
        inventory = prepare.producer.inventory(prepare.implementation_paths(self.root))
        self.receipt = {'schema': prepare.SCHEMA, 'capture_context': prepare.shared.context(),
            'capture_binding': deepcopy(self.manifest['binding']),
            'input_manifest_sha256': prepare.shared._read_regular(self.manifest_path),
            'platform': 'win32', 'machine': 'AMD64', 'host': prepare.TARGET, 'target': prepare.TARGET,
            'profile': 'release', 'features': prepare.producer.FEATURES, 'recorded_root': 'C:/original/repo',
            'executables': {name: f'target/{prepare.TARGET}/release/examples/{name}.exe' for name in prepare.EXAMPLES},
            'compiler_sha256': COMPILER_SHA, 'toolchain': prepare.compiler_identity(COMPILER, COMPILER_SHA),
            'active_toolchain_alias': 'stable-x86_64-pc-windows-msvc',
            'implementation_before': inventory, 'implementation_after': deepcopy(inventory),
            'files': {name: prepare.producer.digest(self.package / name) for name in prepare.FILES}}
        self.seal()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE)

    @staticmethod
    def write_json(path, value):
        path.write_bytes((json.dumps(value) + '\n').encode())

    def seal(self):
        self.write_json(self.package / 'receipt.json', self.receipt)
        self.anchor = prepare.shared._read_regular(self.package / 'receipt.json')

    def refresh_file(self, name):
        self.receipt['files'][name] = prepare.producer.digest(self.package / name)
        self.seal()

    def verify(self, *, anchor=None, compiler=None):
        return prepare.verify_precompiled(self.package, self.root, self.manifest_path,
            self.anchor if anchor is None else anchor, COMPILER_SHA if compiler is None else compiler)

    def test_two_exact_current_tools_and_original_build_receipts_are_bound(self):
        result = self.verify()
        self.assertEqual(result['executables'], {name: self.package / prepare.EXECUTABLES[name] for name in prepare.EXAMPLES})
        self.assertEqual(result['build_receipts'], {name: self.package / prepare.BUILD_RECEIPTS[name] for name in prepare.EXAMPLES})
        self.assertEqual(set(path.name for path in self.package.iterdir()), set(prepare.FILES) | {'receipt.json'})
        self.assertEqual(result['receipt']['capture_context']['source_commit'], self.git('rev-parse', 'HEAD').decode().strip())
        with self.assertRaises(TypeError):
            result['receipt']['compiler_sha256'] = '0' * 64
        with self.assertRaises(TypeError):
            result['receipt']['implementation_before']['src/lib.rs']['bytes'] = 0
        with self.assertRaises(TypeError):
            result['receipt']['features'][0] = 'unexpected'

    def test_both_independent_anchors_are_required(self):
        for name in ('anchor', 'compiler'):
            for invalid in ('', 'f' * 64, 'F' * 64, 'a' * 63, True):
                with self.subTest(name=name, invalid=invalid), self.assertRaises(ValueError):
                    self.verify(**{name: invalid})
        previous = self.anchor
        self.receipt['active_toolchain_alias'] = 'changed-alias'
        self.seal()
        with self.assertRaisesRegex(ValueError, 'job output'):
            self.verify(anchor=previous)

    def test_every_packaged_file_is_hash_bound(self):
        for name in prepare.FILES:
            path = self.package / name
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(original)

    def test_package_inventory_is_closed_including_empty_directories(self):
        extra = self.package / 'extra'
        extra.write_bytes(b'extra')
        with self.assertRaises(ValueError):
            self.verify()
        extra.unlink()
        extra.mkdir()
        with self.assertRaises(ValueError):
            self.verify()
        extra.rmdir()
        for name in prepare.FILES:
            path = self.package / name
            raw = path.read_bytes()
            path.unlink()
            with self.subTest(missing=name), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(raw)

    def test_symlinked_artifact_is_rejected(self):
        path = self.package / prepare.EXECUTABLES[prepare.EXAMPLES[0]]
        original = path.read_bytes()
        target = self.package.parent / 'linked-binary'
        target.write_bytes(original)
        path.unlink()
        try:
            path.symlink_to(target)
        except OSError:
            self.skipTest('host does not permit symlink creation')
        with self.assertRaisesRegex(ValueError, 'symlink|reparse'):
            self.verify()

    def test_source_identity_and_all_build_metadata_are_exact(self):
        changes = [('schema', 'other'), ('capture_context', {**prepare.shared.context(), 'run_attempt': '9'}),
                   ('platform', 'linux'), ('machine', 'ARM64'), ('target', 'other'), ('host', 'other'),
                   ('profile', 'dev'), ('features', ['wgpu-runtime']), ('toolchain', 'stable'),
                   ('executables', {name: f'target/release/examples/{name}.exe' for name in prepare.EXAMPLES}),
                   ('active_toolchain_alias', '--bad')]
        original = deepcopy(self.receipt)
        for key, value in changes:
            self.receipt = deepcopy(original)
            self.receipt[key] = value
            self.seal()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
        self.receipt = original
        self.seal()
        for change in ({'GITHUB_SHA': 'a' * 40}, {'GITHUB_RUN_ID': '999'}, {'GITHUB_RUN_ATTEMPT': '999'}):
            with patch.dict(os.environ, change), self.assertRaises(ValueError):
                self.verify()

    def test_complete_source_and_transitive_diagnostic_implementation_is_bound(self):
        names = ('src/lib.rs', 'src/render/finite_warp_probe.rs', 'src/render/shader.wgsl',
                 'updater/src/lib.rs', 'updater/build.rs', 'Cargo.toml', 'Cargo.lock',
                 'examples/source_visibility_geometry_probe.rs', 'examples/source_visibility_geometry/domain.rs',
                 'examples/finite_warp_probe.rs', 'tools/current_ads_profile_proof.py',
                 'tools/prepare_current_ads_profile.py', 'tools/dependent_diagnostic.py', 'rust-toolchain.toml')
        for name in names:
            self.assertIn(name, self.receipt['implementation_before'])
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(original)

    def test_untracked_or_ignored_implementation_injection_is_rejected(self):
        # Discover actual files even when Git's ordinary untracked listing
        # would hide them behind excludes.
        (self.root / '.git/info/exclude').write_text('injected.*\nTHIRD_PARTY_UPDATER_LICENSES.txt\n')
        for name in ('src/injected.rs', 'updater/src/injected.rs', 'examples/source_visibility_geometry/injected.rs',
                     'tools/injected.py', 'updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('untracked source\n')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'not tracked'):
                self.verify()
            path.unlink()

    def test_staged_source_change_cannot_be_relabelled_clean(self):
        (self.root / 'src/lib.rs').write_text('changed source\n')
        self.git('add', 'src/lib.rs')
        inventory = prepare.producer.inventory(prepare.implementation_paths(self.root))
        self.receipt['implementation_before'] = self.receipt['implementation_after'] = inventory
        self.seal()
        with self.assertRaisesRegex(ValueError, 'tracked modifications'):
            self.verify()

    def test_source_and_manifest_mutations_during_build_fail_closed(self):
        self.receipt['implementation_after']['src/lib.rs']['sha256'] = '0' * 64
        self.seal()
        with self.assertRaisesRegex(ValueError, 'changed source'):
            self.verify()
        self.receipt['implementation_after'] = deepcopy(self.receipt['implementation_before'])
        self.seal()
        self.manifest_path.write_bytes(self.manifest_path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            self.verify()

    def test_native_runtime_inputs_are_closed_and_unchanged(self):
        for name in ('settings.cfg', 'assets/locomotion/asset.vrs', 'assets/animations.cfg',
                     'assets/authoring/ads/sight_alignment.json'):
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(original)
        path = self.root / 'assets/injected.cfg'
        path.write_bytes(b'extra input')
        with self.assertRaisesRegex(ValueError, 'runtime inputs'):
            self.verify()

    def test_both_build_receipts_reject_wrong_example_flags_cwd_environment_and_failure(self):
        for example in prepare.EXAMPLES:
            original = deepcopy(self.builds[example])
            alternate = next(name for name in prepare.EXAMPLES if name != example)
            changes = ({'exit_code': 1}, {'exit_code': True}, {'cwd': 'C:/other/repo'},
                {'command': original['command'] + ['--bin', 'vector-range']},
                {'command': [part for part in original['command'] if part != '--release']},
                {'command': prepare.build_command('C:/toolchain/cargo.exe', alternate)},
                {'environment': {**prepare.binding.ORACLE_ENVIRONMENT, 'RUSTFLAGS': '-Copt-level=0'}})
            name = prepare.BUILD_RECEIPTS[example]
            for change in changes:
                self.write_json(self.package / name, {**original, **change})
                self.refresh_file(name)
                with self.subTest(example=example, change=change), self.assertRaises(ValueError):
                    self.verify()
            self.write_json(self.package / name, original)
            self.refresh_file(name)

    def test_receipt_schema_and_each_inventory_are_closed(self):
        for location in ('receipt', 'files', 'implementation_before'):
            original = deepcopy(self.receipt)
            target = self.receipt if location == 'receipt' else self.receipt[location]
            target['injected'] = {'bytes': 1, 'sha256': '0' * 64}
            self.seal()
            with self.subTest(location=location), self.assertRaises(ValueError):
                self.verify()
            self.receipt = original
            self.seal()

    def test_zero_length_executable_is_rejected_even_with_refreshed_hashes(self):
        for name in prepare.EXECUTABLES.values():
            path = self.package / name
            original = path.read_bytes()
            path.write_bytes(b'')
            self.refresh_file(name)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'missing or oversized'):
                self.verify()
            path.write_bytes(original)
            self.refresh_file(name)

    def test_compiler_environment_rejects_overrides_without_mutation(self):
        for environment in ({'RUSTFLAGS': ''}, {'CARGO_ENCODED_RUSTFLAGS': '-Copt-level=0'},
                            {'CARGO_PROFILE_RELEASE_OPT_LEVEL': '0'}, {'RUSTC_WRAPPER': 'wrapper'},
                            {'CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS': '-Copt-level=0'}):
            with self.subTest(environment=environment), self.assertRaisesRegex(ValueError, 'overrides'):
                prepare.producer.execution_environment(self.root, 'stable', environment)

    def test_header_release_must_agree_even_if_hash_is_anchored(self):
        malformed = COMPILER.replace(b'release: 1.90.0', b'release: 1.91.0')
        with self.assertRaisesRegex(ValueError, 'header/release'):
            prepare.compiler_identity(malformed, hashlib.sha256(malformed).hexdigest())

    def test_preparation_requires_native_windows_and_retains_failure_summary(self):
        evidence = self.root.parent / 'failure-evidence'
        with patch.object(prepare.sys, 'platform', 'linux'), self.assertRaisesRegex(ValueError, 'native Windows'):
            prepare.prepare(self.root, self.manifest_path, evidence, COMPILER_SHA)
        summary = json.loads((evidence / 'prepare-summary.json').read_text())
        self.assertFalse(summary['passed'])
        self.assertFalse(summary['acceptance_complete'])
        self.assertIn('native Windows', summary['failure'])
        self.assertFalse((evidence / 'independent-receipt.sha256').exists())

    def mock_build_preparation(self, *, mutate=None):
        actual_check_output = subprocess.check_output
        commands = []
        def check_output(command, **kwargs):
            if command == ['rustc', '-Vv']:
                return COMPILER
            if command == ['rustup', 'show', 'active-toolchain']:
                return 'stable-x86_64-pc-windows-msvc (default)\n'
            return actual_check_output(command, **kwargs)
        def build(command, root, env, logs, timeout):
            commands.append(command)
            example = command[command.index('--example') + 1]
            path = root / f'target/{prepare.TARGET}/release/examples/{example}.exe'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'SYNTHETIC MOCK COMPILER OUTPUT ' + example.encode())
            if mutate:
                mutate()
            return {'command': command, 'cwd': root.as_posix(), 'exit_code': 0,
                    'environment': prepare.binding.ORACLE_ENVIRONMENT}
        for patcher in (patch.object(prepare.sys, 'platform', 'win32'),
                        patch.object(prepare.platform, 'machine', return_value='AMD64'),
                        patch.object(prepare.subprocess, 'check_output', side_effect=check_output),
                        patch.object(prepare.producer, 'execution_environment', side_effect=lambda root, active, environment=None: dict(os.environ if environment is None else environment)),
                        patch.object(prepare.shutil, 'which', return_value='C:/toolchain/cargo.exe'),
                        patch.object(prepare.producer, 'process', side_effect=build)):
            patcher.start()
            self.addCleanup(patcher.stop)
        return commands

    def test_preparation_builds_exactly_two_tools_without_execution_or_source_changes(self):
        commands = self.mock_build_preparation()
        evidence = self.root.parent / 'prepared-evidence'
        output = self.root.parent / 'job-output'
        # The host is not Windows: verify the real package API separately above.
        # Only the producer's final native-path verification is mocked here.
        with patch.object(prepare, 'verify_precompiled') as verified, patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}):
            report = prepare.prepare(self.root, self.manifest_path, evidence, COMPILER_SHA)
        self.assertTrue(report['passed'])
        self.assertFalse(report['acceptance_complete'])
        self.assertEqual(commands, [prepare.build_command('C:/toolchain/cargo.exe', example) for example in prepare.EXAMPLES])
        self.assertEqual(set(path.name for path in (evidence / 'package').iterdir()), set(prepare.FILES) | {'receipt.json'})
        receipt_hash = prepare.shared._read_regular(evidence / 'package/receipt.json')
        self.assertEqual(report['receipt_sha256'], receipt_hash)
        self.assertEqual((evidence / 'independent-receipt.sha256').read_text(), receipt_hash + '\n')
        self.assertEqual(output.read_text(), f'receipt_sha256={receipt_hash}\ncompiler_sha256={COMPILER_SHA}\n')
        verified.assert_called_once_with(evidence / 'package', self.root, self.manifest_path, receipt_hash, COMPILER_SHA)

    def test_preparation_stops_before_second_build_when_native_inputs_change(self):
        commands = self.mock_build_preparation(mutate=lambda: (self.root / 'settings.cfg').write_text('changed\n'))
        evidence = self.root.parent / 'mutated-native-evidence'
        with self.assertRaisesRegex(ValueError, 'native runtime input differs'):
            prepare.prepare(self.root, self.manifest_path, evidence, COMPILER_SHA)
        self.assertEqual(len(commands), 1)
        self.assertFalse((evidence / 'package').exists())
        self.assertFalse(json.loads((evidence / 'prepare-summary.json').read_text())['passed'])

    def test_preparation_stops_before_second_build_when_first_changes_source(self):
        commands = self.mock_build_preparation(mutate=lambda: (self.root / 'src/lib.rs').write_text('changed\n'))
        evidence = self.root.parent / 'mutated-evidence'
        with self.assertRaisesRegex(ValueError, 'tracked modifications'):
            prepare.prepare(self.root, self.manifest_path, evidence, COMPILER_SHA)
        self.assertEqual(len(commands), 1)
        self.assertFalse((evidence / 'package').exists())
        self.assertFalse(json.loads((evidence / 'prepare-summary.json').read_text())['passed'])


if __name__ == '__main__':
    unittest.main()
