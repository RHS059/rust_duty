"""Producer guard and CI contract tests. No native source execution is claimed."""
from copy import deepcopy
import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

import build_ads_source_packet as producer


CAPTURE = dict(producer.CAPTURE_CONTEXT)
TOOLCHAIN = '1.90.0-x86_64-pc-windows-msvc'
COMPILER = (b'rustc 1.90.0 (123456789 2026-10-01)\nbinary: rustc\ncommit-hash: '
            + b'1' * 40 + b'\ncommit-date: 2026-10-01\nhost: x86_64-pc-windows-msvc\n'
            b'release: 1.90.0\nLLVM version: 20.1.1\n')
COMPILER_SHA = hashlib.sha256(COMPILER).hexdigest()


def catalog():
    run = {'id': int(CAPTURE['run_id']), 'run_attempt': 1, 'head_sha': CAPTURE['source_commit'],
           'head_branch': 'main', 'path': '.github/workflows/build.yml',
           'repository': {'full_name': 'RHS059/rust_duty', 'id': 9},
           'head_repository': {'full_name': 'RHS059/rust_duty', 'id': 9},
           'status': 'completed', 'run_started_at': '2026-10-06T01:00:00Z', 'updated_at': '2026-10-06T04:00:00Z'}
    return {'attempt': run, 'complete': True, 'jobs_context': CAPTURE, 'jobs_complete': True,
            'jobs': [{'id': 112121396166, 'run_id': int(CAPTURE['run_id']), 'head_sha': CAPTURE['source_commit'],
                      'name': 'dx12-authored-validation / authored-inputs', 'status': 'completed',
                      'conclusion': 'success', 'labels': ['windows-latest']}], 'artifacts': [
        {'name': name, 'id': index + 1, 'expired': False, 'size_in_bytes': 1000,
         'created_at': '2026-10-06T02:00:00Z', 'workflow_run': {'id': int(CAPTURE['run_id']),
          'head_sha': CAPTURE['source_commit'], 'repository_id': 9, 'head_repository_id': 9}}
        for index, name in enumerate(producer.artifact_names('1').values())]}


class ProducerGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def select(self, value):
        return producer.select_artifacts(value, CAPTURE, 'RHS059/rust_duty')

    def test_exact_artifact_selection_has_eight_unique_ids(self):
        result = self.select(catalog())
        self.assertEqual(set(result), {'inputs', 'gameplay', 'offset', 'reload', 'walk', 'ads', 'directional', 'jump'})
        self.assertEqual(len({item['id'] for item in result.values()}), 8)

    def test_denied_artifact_never_reaches_download_selection(self):
        self.assertEqual(producer.DENIED_ARTIFACT_IDS, {11364272946, 11385711086, 11386835833, 11386227794})
        for artifact_id in producer.DENIED_ARTIFACT_IDS:
            value = catalog()
            value['artifacts'][3]['id'] = artifact_id
            with self.subTest(artifact_id=artifact_id), self.assertRaisesRegex(ValueError, 'authorized access scope'):
                self.select(value)

    def test_only_attempt_qualified_generated_artifacts_are_selected(self):
        value = catalog()
        for item in list(value['artifacts'][3:]):
            item = deepcopy(item)
            item['name'] = item['name'].removesuffix('-attempt-1')
            item['id'] += 100
            value['artifacts'].append(item)
        selected = self.select(value)
        for family in ('reload', 'walk', 'ads', 'directional', 'jump'):
            self.assertEqual(selected[family]['name'], f'generated-{family}-runtime-attempt-1')
        value['artifacts'] = [item for item in value['artifacts'] if item['name'] != 'generated-reload-runtime-attempt-1']
        with self.assertRaisesRegex(ValueError, 'generated-reload-runtime-attempt-1'):
            self.select(value)

    def test_capture_source_run_attempt_branch_and_workflow_are_pinned(self):
        for key, replacement in (('source_commit', '2' * 40), ('run_id', '1234'), ('run_attempt', '2')):
            wrong = {**CAPTURE, key: replacement}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'pinned 8f'):
                producer.select_artifacts(catalog(), wrong, 'RHS059/rust_duty')
        for key, replacement in (('head_branch', 'aella/wgpu-renderer-port'), ('path', '.github/workflows/other.yml')):
            value = catalog()
            value['attempt'][key] = replacement
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'main build workflow'):
                self.select(value)

    def test_capture_identity_cannot_be_satisfied_by_current_verifier_run(self):
        for key, replacement in [('id', 500), ('run_attempt', 3), ('head_sha', '2' * 40), ('status', 'in_progress')]:
            with self.subTest(key=key):
                value = catalog()
                value['attempt'][key] = replacement
                with self.assertRaises(ValueError):
                    self.select(value)

    def test_different_repository_and_fork_head_are_rejected(self):
        for key in ('repository', 'head_repository'):
            value = catalog()
            value['attempt'][key]['full_name'] = 'someone/rust_duty'
            with self.assertRaises(ValueError):
                self.select(value)

    def test_download_artifacts_must_match_every_native_identity_dimension(self):
        for key, replacement in [('id', 1235), ('head_sha', '2' * 40), ('repository_id', 10), ('head_repository_id', 10)]:
            with self.subTest(key=key):
                value = catalog()
                value['artifacts'][0]['workflow_run'][key] = replacement
                with self.assertRaises(ValueError):
                    self.select(value)

    def test_generated_runtime_from_other_attempt_cannot_be_reused(self):
        for timestamp in ('2026-10-05T23:59:59Z', '2026-10-06T04:00:01Z'):
            value = catalog()
            value['artifacts'][3]['created_at'] = timestamp
            with self.assertRaisesRegex(ValueError, 'selected attempt'):
                self.select(value)

    def test_incomplete_duplicate_expired_and_oversized_artifacts_fail_closed(self):
        variants = []
        value = catalog(); value['complete'] = False; variants.append(value)
        value = catalog(); value['artifacts'].append(deepcopy(value['artifacts'][0])); variants.append(value)
        value = catalog(); value['artifacts'].pop(); variants.append(value)
        value = catalog(); value['artifacts'][0]['expired'] = True; variants.append(value)
        value = catalog(); value['artifacts'][0]['size_in_bytes'] = 5 * 1024**3; variants.append(value)
        value = catalog(); value['artifacts'][0]['id'] = value['artifacts'][1]['id']; variants.append(value)
        for index, value in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.select(value)

    def test_moving_toolchains_and_missing_compiler_anchors_are_rejected(self):
        producer.validate_parameters(CAPTURE, TOOLCHAIN, COMPILER_SHA)
        for toolchain in ('stable', 'nightly', '1.90.0', '1.90.0-x86_64-unknown-linux-gnu', '--help'):
            with self.subTest(toolchain=toolchain), self.assertRaises(ValueError):
                producer.validate_parameters(CAPTURE, toolchain, COMPILER_SHA)
        with self.assertRaises(ValueError):
            producer.validate_parameters(CAPTURE, TOOLCHAIN, '')

    def test_actual_compiler_bytes_and_host_are_required(self):
        producer.checked_compiler(COMPILER, COMPILER_SHA)
        with self.assertRaisesRegex(ValueError, 'captured compiler'):
            producer.checked_compiler(COMPILER.replace(b'1.90', b'1.91'), COMPILER_SHA)
        wrong = COMPILER.replace(b'x86_64-pc-windows-msvc', b'x86_64-unknown-linux-gnu')
        with self.assertRaisesRegex(ValueError, 'host'):
            producer.checked_compiler(wrong, hashlib.sha256(wrong).hexdigest())

    def test_original_compiler_job_is_selected_from_exact_attempt_endpoint(self):
        self.assertEqual(producer.select_compiler_job(catalog(), CAPTURE)['id'], 112121396166)
        variants = []
        value = catalog(); value['jobs_context'] = {**CAPTURE, 'run_attempt': '3'}; variants.append(value)
        value = catalog(); value['jobs'][0]['conclusion'] = 'failure'; variants.append(value)
        value = catalog(); value['jobs'][0]['head_sha'] = '2' * 40; variants.append(value)
        value = catalog(); value['jobs'][0]['run_attempt'] = 3; variants.append(value)
        value = catalog(); value['jobs'][0]['labels'] = ['ubuntu-latest']; variants.append(value)
        value = catalog(); value['jobs'].append(deepcopy(value['jobs'][0])); variants.append(value)
        for index, value in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                producer.select_compiler_job(value, CAPTURE)

    def compiler_log(self):
        return (''.join('2026-10-06T02:00:00.123Z ' + line + '\n' for line in COMPILER.decode().splitlines())
                + f'Cache key: authored-dual-release-v1-Windows-X64-{COMPILER_SHA}-'
                + 'b' * 64 + '-' + CAPTURE['source_commit'] + '\n').encode()

    def test_compiler_anchor_is_recovered_from_original_source_bound_cache_key(self):
        result = producer.recover_compiler(self.compiler_log(), CAPTURE)
        self.assertEqual(result['rustc_sha256'], COMPILER_SHA)
        self.assertEqual(result['toolchain'], TOOLCHAIN)
        self.assertEqual(result['original_job_log_sha256'], hashlib.sha256(self.compiler_log()).hexdigest())

    def test_new_compiler_output_or_ambiguous_original_log_cannot_establish_anchor(self):
        for raw in (COMPILER, self.compiler_log().replace(CAPTURE['source_commit'].encode(), b'2' * 40),
                    self.compiler_log() + self.compiler_log().replace(COMPILER_SHA.encode(), b'c' * 64)):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                producer.recover_compiler(raw, CAPTURE)
        for kwargs in ({'claimed_toolchain': '1.91.0-' + producer.TARGET}, {'claimed_sha256': 'c' * 64}):
            with self.assertRaises(ValueError):
                producer.recover_compiler(self.compiler_log(), CAPTURE, **kwargs)

    def test_old_installed_rustc_version_does_not_override_verified_verbose_block(self):
        log = (b'2026-10-06T01:00:00.000Z rustc 1.98.1 (previously-installed)\n'
               + self.compiler_log() + b'rustc 1.91.0 (unrelated text)\n')
        result = producer.recover_compiler(log, CAPTURE)
        self.assertEqual(result['toolchain'], TOOLCHAIN)
        self.assertEqual(result['rustc_sha256'], COMPILER_SHA)

    def test_compiler_cli_retains_ansi_log_bytes_only_in_redirected_evidence(self):
        source = self.root / 'catalog.json'
        source.write_bytes((json.dumps(catalog()) + '\n').encode())
        output = self.root / 'compiler-recovery'
        original = b'\x1b[36moriginal ANSI-colored command\x1b[0m\n' + self.compiler_log()

        def github_cli(command, **kwargs):
            self.assertEqual(command, ['gh', 'api', '--allow-escape-sequences',
                '/repos/RHS059/rust_duty/actions/jobs/112121396166/logs'])
            self.assertNotIn('shell', kwargs)
            kwargs['stdout'].write(original)
            return SimpleNamespace(returncode=0)

        shown = io.StringIO()
        with patch.object(producer.subprocess, 'run', side_effect=github_cli) as call, \
                patch.dict(os.environ, {'GITHUB_OUTPUT': str(self.root / 'step-output')}, clear=True), contextlib.redirect_stdout(shown):
            producer.main(['recover-compiler', '--catalog', str(source), '--output', str(output),
                '--capture-source', CAPTURE['source_commit'], '--capture-run-id', CAPTURE['run_id'],
                '--capture-run-attempt', CAPTURE['run_attempt']])
        self.assertEqual(call.call_count, 1)
        self.assertEqual((output / 'original-authored-inputs.log').read_bytes(), original)
        self.assertNotIn('\x1b', shown.getvalue())
        self.assertEqual(json.loads((output / 'compiler-recovery.json').read_text())['rustc_sha256'], COMPILER_SHA)

    def test_verified_verbose_header_and_release_must_agree(self):
        changed = COMPILER.replace(b'release: 1.90.0', b'release: 1.91.0')
        replacement = hashlib.sha256(changed).hexdigest()
        log = self.compiler_log().replace(b'release: 1.90.0', b'release: 1.91.0').replace(COMPILER_SHA.encode(), replacement.encode())
        with self.assertRaisesRegex(ValueError, 'header, release line'):
            producer.recover_compiler(log, CAPTURE)

    def test_empty_or_nonempty_compiler_overrides_are_rejected(self):
        extras = ('CARGO_PROFILE_RELEASE_LTO', 'CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS',
                  'CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER')
        for key in producer.BLOCKED_ENVIRONMENT + extras:
            for value in ('', 'different'):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'overrides'):
                    producer.execution_environment(self.root, TOOLCHAIN, {key: value})

    def test_ancestor_and_cargo_home_configuration_are_rejected(self):
        source = self.root / 'repo'
        source.mkdir()
        cargo_home = self.root / 'cargo-home'
        cargo_home.mkdir()
        env = {'CARGO_HOME': str(cargo_home)}
        self.assertEqual(producer.execution_environment(source, TOOLCHAIN, env)['RUSTUP_TOOLCHAIN'], TOOLCHAIN)
        for directory in (self.root / '.cargo', cargo_home):
            directory.mkdir(exist_ok=True)
            path = directory / 'config.toml'
            path.write_text('[build]\nrustflags = ["-Ctarget-cpu=native"]\n')
            with self.assertRaisesRegex(ValueError, 'Cargo configuration'):
                producer.execution_environment(source, TOOLCHAIN, env)
            path.unlink()

    def test_explicit_cargo_home_works_without_a_user_home_and_remains_checked(self):
        cargo_home = self.root / 'cargo-home'
        cargo_home.mkdir()
        env = {'CARGO_HOME': str(cargo_home), 'RUSTUP_TOOLCHAIN': 'existing-toolchain'}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(producer.Path, 'home', side_effect=RuntimeError('Could not determine home directory.')):
            self.assertEqual(producer.execution_environment(self.root, TOOLCHAIN),
                             {**env, 'RUSTUP_TOOLCHAIN': TOOLCHAIN})
            self.assertEqual(dict(os.environ), env)
            for name in ('config', 'config.toml'):
                path = cargo_home / name
                path.write_text('[build]\nrustflags = ["-Ctarget-cpu=native"]\n')
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Cargo configuration'):
                    producer.execution_environment(self.root, TOOLCHAIN)
                path.unlink()

    def test_default_cargo_home_configuration_is_still_rejected(self):
        home = self.root / 'user-home'
        cargo_home = home / '.cargo'
        cargo_home.mkdir(parents=True)
        with patch.object(producer.Path, 'home', return_value=home):
            self.assertEqual(producer.execution_environment(self.root, TOOLCHAIN, {}),
                             {'RUSTUP_TOOLCHAIN': TOOLCHAIN})
            (cargo_home / 'config.toml').write_text('[build]\nrustflags = ["-Ctarget-cpu=native"]\n')
            with self.assertRaisesRegex(ValueError, 'Cargo configuration'):
                producer.execution_environment(self.root, TOOLCHAIN, {})

    def test_only_reviewed_additive_bridge_regions_can_replace_original(self):
        original = ('struct Model {}\nimpl AuthoredViewmodel {\n'
                    '    /// Loads CPU mesh and texture descriptors without requiring a render context.\n'
                    '    fn production() {}\n}\n#[cfg(test)]\nmod tests {\n    fn old_test() {}\n}\n').encode()
        overlay = original.decode().replace('impl AuthoredViewmodel {',
            '/// Read-only evaluated source pose for independent CPU diagnostics.\nstruct Snapshot {}\nimpl AuthoredViewmodel {')
        overlay = overlay.replace('    /// Loads CPU mesh',
            '    /// Snapshot the same effective pose selected by `draw_checked`, before\n    fn source_pose_snapshot() {}\n    /// Loads CPU mesh')
        overlay = overlay.rsplit('\n}', 1)[0] + '\n\n    fn layered_contact_fixture() -> AuthoredViewmodel {}\n}\n'
        self.assertEqual(producer.reviewed_bridge(original, overlay.encode()), overlay.encode())
        with self.assertRaisesRegex(ValueError, 'production code'):
            producer.reviewed_bridge(original, overlay.replace('fn production()', 'fn altered()').encode())
        with self.assertRaises(ValueError):
            producer.reviewed_bridge(original, overlay.replace('struct Model {}', 'struct Model {}\nfn injected() {}').encode())

    def input_fixture(self):
        inputs = producer.binding.INPUTS - {'ads-offset.cfg'}
        for name in inputs:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('original ' + name + '\n').encode())
        offset = self.root / 'native-offset.cfg'
        offset.write_bytes((self.root / 'settings.cfg').read_bytes() + producer.binding.OFFSET_SUFFIX.encode('utf-8'))
        manifest = {'binding': {'runtime_and_manifest_sha256': {name: producer.digest(self.root / name)['sha256'] for name in inputs}}}
        return manifest, offset

    def test_all_18_companions_and_manifest_base_are_compared_to_native_bytes(self):
        manifest, offset = self.input_fixture()
        producer.validate_consumed_inputs(self.root, manifest, offset)
        self.assertEqual(len(manifest['binding']['runtime_and_manifest_sha256']), 20)
        for name in producer.binding.INPUTS - {'ads-offset.cfg'}:
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'consumed native input differs'):
                producer.validate_consumed_inputs(self.root, manifest, offset)
            path.write_bytes(original)

    def test_offset_is_original_base_plus_exact_capture_transform(self):
        manifest, offset = self.input_fixture()
        offset.write_text(offset.read_text().replace('0.20', '0.21'))
        with self.assertRaisesRegex(ValueError, 'exact base-plus-offset'):
            producer.validate_consumed_inputs(self.root, manifest, offset)

    def test_exact_native_newline_bytes_are_recovered_only_when_the_hash_matches(self):
        manifest, offset = self.input_fixture()
        for name in ('settings.cfg', 'assets/animations.cfg'):
            expected = (self.root / name).read_bytes().replace(b'\n', b'\r\n')
            manifest['binding']['runtime_and_manifest_sha256'][name] = hashlib.sha256(expected).hexdigest()
        offset.write_bytes(offset.read_bytes().replace(b'\n', b'\r\n'))
        producer.recover_native_text_bytes(self.root, manifest, offset)
        producer.validate_consumed_inputs(self.root, manifest, offset)
        self.assertIn(b'\r\n', (self.root / 'settings.cfg').read_bytes())
        self.assertIn(b'\r\n', (self.root / 'assets/animations.cfg').read_bytes())
        manifest['binding']['runtime_and_manifest_sha256']['settings.cfg'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'exact native base'):
            producer.recover_native_text_bytes(self.root, manifest, offset)

    def test_portable_copy_cannot_refresh_a_mutated_input_hash(self):
        source = self.root / 'source'
        source.write_bytes(b'original')
        original = producer.digest(source)
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed before portable copy'):
            producer.copy_packet_file(source, self.root / 'portable', original)
        self.assertFalse((self.root / 'portable').exists())

    def test_timeout_retains_attempted_command_without_successful_exit_receipt(self):
        command = ['cargo.exe', 'build']
        with patch.object(producer.subprocess, 'run', side_effect=subprocess.TimeoutExpired(command, 5)):
            with self.assertRaises(subprocess.TimeoutExpired):
                producer.process(command, self.root, {}, self.root / 'logs', 5)
        record = json.loads((self.root / 'logs/invocation.json').read_text())
        self.assertEqual(record['command'], command)
        self.assertIsNone(record['exit_code'])
        self.assertEqual(record['environment'], {key: None for key in producer.ENVIRONMENT_KEYS})

    def test_nonwindows_fails_with_retained_failure_summary_and_no_anchor(self):
        for name in ('capture', 'verifier', 'downloads'):
            (self.root / name).mkdir()
        args = SimpleNamespace(capture_source=CAPTURE['source_commit'], capture_run_id=CAPTURE['run_id'],
                               capture_run_attempt=CAPTURE['run_attempt'], toolchain=TOOLCHAIN,
                               capture_rustc_sha256=COMPILER_SHA, capture_root=self.root / 'capture',
                               verifier_root=self.root / 'verifier', downloads=self.root / 'downloads',
                               evidence=self.root / 'evidence', receipt_anchor=self.root / 'anchor.sha256')
        with patch.object(producer.sys, 'platform', 'linux'), patch.object(producer.shared, 'context', return_value=CAPTURE):
            with self.assertRaisesRegex(ValueError, 'native Windows x86_64'):
                producer.build(args)
        report = json.loads((args.evidence / 'producer-summary.json').read_text())
        self.assertIs(report['passed'], False)
        self.assertIn('native Windows', report['failure'])
        self.assertFalse(args.receipt_anchor.exists())


class GeneratedInputStaging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.downloads = self.root / 'source', self.root / 'downloads'
        self.source.mkdir()
        for family in ('reload', 'walk', 'ads', 'directional', 'jump'):
            (self.downloads / family).mkdir(parents=True)
        self.walk = self.downloads / 'walk'
        self.target = self.source / 'assets/walk'
        self.target.mkdir(parents=True)
        self.native = {'binding': {'runtime_and_manifest_sha256': {}}}
        self.hashes = self.native['binding']['runtime_and_manifest_sha256']
        # Exercise the real walk metadata layout with small runtime payloads.
        baseline = Path(__file__).resolve().parents[1] / 'assets/walk'
        self.family = json.loads((baseline / 'manifest.json').read_text())
        for name in ('asset.vra', 'asset.vrs', 'asset.vrm'):
            raw = ('captured native ' + name).encode()
            (self.walk / name).write_bytes(raw)
            self.family['files'][name] = producer.digest(self.walk / name)
            (self.target / name).write_bytes(b'committed fallback')
        packed = gzip.compress((self.walk / 'asset.vrs').read_bytes(), mtime=0)
        (self.walk / 'asset.vrs.gz').write_bytes(packed)
        self.family['repository_transport'] = {'asset.vrs': {
            'file': 'asset.vrs.gz', 'encoding': 'gzip', **producer.digest(self.walk / 'asset.vrs.gz'),
            'decoded_bytes': self.family['files']['asset.vrs']['bytes'],
            'decoded_sha256': self.family['files']['asset.vrs']['sha256']}}
        (self.target / 'asset.vrs.gz').write_bytes(b'committed compressed fallback')
        for name in ('conversion.json', 'parity.json'):
            original = (baseline / name).read_bytes()
            (self.target / name).write_bytes(original)
            # Whitespace changes still require the exact native metadata hash.
            (self.walk / name).write_bytes(original + b'\n')
        (self.target / 'manifest.json').write_bytes((baseline / 'manifest.json').read_bytes())
        self.save_family()
        for name, path in producer.shared._walk_files(self.walk):
            if not name.endswith('.gz'):
                self.hashes['assets/walk/' + name] = producer.digest(path)['sha256']
        self.original = producer.inventory(dict(producer.shared._walk_files(self.source)))

    def save_family(self):
        (self.walk / 'manifest.json').write_text(json.dumps(self.family) + '\n')
        self.hashes['assets/walk/manifest.json'] = producer.digest(self.walk / 'manifest.json')['sha256']

    def stage(self):
        producer.stage_generated_inputs(self.source, self.downloads, self.native)

    def assert_untouched(self):
        self.assertEqual(producer.inventory(dict(producer.shared._walk_files(self.source))), self.original)

    def test_native_runtime_metadata_and_bound_transport_replace_fallbacks(self):
        self.stage()
        for name, path in producer.shared._walk_files(self.walk):
            self.assertEqual((self.target / name).read_bytes(), path.read_bytes(), name)
        self.stage()  # Identical staging remains valid.

    def test_wrong_native_runtime_or_metadata_is_rejected_before_any_replacement(self):
        for name in ('asset.vra', 'conversion.json', 'manifest.json', 'parity.json'):
            path = self.walk / name
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'native input differs|native-bound family manifest'):
                self.stage()
            self.assert_untouched()
            path.write_bytes(original)

    def test_unbound_differing_overwrite_is_rejected_even_for_ancillary_files(self):
        (self.walk / 'README.md').write_bytes(b'incoming ancillary text')
        (self.target / 'README.md').write_bytes(b'committed ancillary text')
        self.original = producer.inventory(dict(producer.shared._walk_files(self.source)))
        with self.assertRaisesRegex(ValueError, 'not bound to native inputs'):
            self.stage()
        self.assert_untouched()

    def test_new_or_identical_readme_does_not_authorize_unbound_runtime_or_metadata(self):
        (self.walk / 'README.md').write_bytes(b'ancillary text')
        self.stage()
        self.stage()
        for name in ('asset.vra', 'conversion.json'):
            self.hashes.pop('assets/walk/' + name)
            (self.target / name).unlink()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'not bound to native inputs'):
                self.stage()
            self.hashes['assets/walk/' + name] = producer.digest(self.walk / name)['sha256']
            (self.target / name).write_bytes((self.walk / name).read_bytes())

    def test_compressed_only_input_is_native_bound_before_materialization(self):
        (self.walk / 'asset.vrs').unlink()
        (self.target / 'asset.vrs').unlink()
        self.stage()
        self.assertEqual(gzip.decompress((self.target / 'asset.vrs.gz').read_bytes()), b'captured native asset.vrs')
        self.assertFalse((self.target / 'asset.vrs').exists())

    def test_transport_requires_native_bound_manifest(self):
        self.hashes.pop('assets/walk/manifest.json')
        with self.assertRaisesRegex(ValueError, 'native-bound family manifest'):
            self.stage()
        self.assert_untouched()

    def test_transport_hash_and_size_must_match_even_when_decoded_bytes_are_native(self):
        path = self.walk / 'asset.vrs.gz'
        original = path.read_bytes()
        for replacement in (gzip.compress((self.walk / 'asset.vrs').read_bytes(), mtime=1), original + b'\0'):
            path.write_bytes(replacement)
            with self.subTest(packed=replacement), self.assertRaisesRegex(ValueError, 'transport differs from native-bound'):
                self.stage()
            self.assert_untouched()
        path.write_bytes(original)

    def test_transport_decoded_hash_is_anchored_to_native_input_not_only_family_manifest(self):
        self.family['files']['asset.vrs']['sha256'] = 'a' * 64
        self.family['repository_transport']['asset.vrs']['decoded_sha256'] = 'a' * 64
        self.save_family()
        with self.assertRaisesRegex(ValueError, 'transport differs from native-bound'):
            self.stage()
        self.assert_untouched()

    def test_verified_transport_metadata_cannot_hide_wrong_decoded_bytes(self):
        path = self.walk / 'asset.vrs.gz'
        wrong = b'x' * len((self.walk / 'asset.vrs').read_bytes())
        path.write_bytes(gzip.compress(wrong, mtime=0))
        self.family['repository_transport']['asset.vrs'].update(producer.digest(path))
        self.save_family()
        with self.assertRaisesRegex(ValueError, 'decoded transport differs from native input'):
            self.stage()
        self.assert_untouched()

    def test_invalid_gzip_with_bound_packed_hash_is_rejected_before_replacement(self):
        path = self.walk / 'asset.vrs.gz'
        path.write_bytes(b'not a gzip stream')
        self.family['repository_transport']['asset.vrs'].update(producer.digest(path))
        self.save_family()
        with self.assertRaisesRegex(ValueError, 'invalid generated transport'):
            self.stage()
        self.assert_untouched()

    def test_later_family_failure_does_not_partially_replace_walk(self):
        (self.downloads / 'jump/unbound.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'not bound to native inputs'):
            self.stage()
        self.assert_untouched()


class WorkflowContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / '.github/workflows/revalidate-ads-source.yml'
        cls.workflow = yaml.safe_load(cls.path.read_text())
        cls.job = cls.workflow['jobs']['windows-source-oracle']
        cls.steps = cls.job['steps']

    def test_windows_producer_preserves_separate_capture_and_verifier_checkouts(self):
        self.assertEqual(self.job['runs-on'], 'windows-latest')
        checkouts = [step['with'] for step in self.steps if step.get('uses') == 'actions/checkout@v4']
        self.assertEqual([(item['path'], item['ref']) for item in checkouts],
                         [('verifier', '${{ github.sha }}'), ('capture-source', '${{ env.CAPTURE_SOURCE }}')])
        self.assertTrue(all(item['persist-credentials'] is False for item in checkouts))
        self.assertEqual(self.workflow['permissions'], {'contents': 'read', 'actions': 'read'})

    def test_dispatch_cannot_change_capture_identity_or_run_on_another_ref(self):
        inputs = self.workflow.get('on', self.workflow.get(True))['workflow_dispatch']['inputs']
        self.assertEqual(set(inputs), {'capture_toolchain', 'capture_rustc_sha256'})
        self.assertTrue(all(value['type'] == 'string' and 'default' not in value for value in inputs.values()))
        for name in ('capture_toolchain', 'capture_rustc_sha256'):
            self.assertFalse(inputs[name]['required'])
        self.assertIn("github.ref == 'refs/heads/main'", self.job['if'])
        self.assertEqual(self.job['env']['CAPTURE_SOURCE'], CAPTURE['source_commit'])
        self.assertEqual(self.job['env']['CAPTURE_RUN_ID'], CAPTURE['run_id'])
        self.assertEqual(self.job['env']['CAPTURE_RUN_ATTEMPT'], CAPTURE['run_attempt'])

    def test_automatic_trigger_is_restricted_to_pinned_original_capture_on_main(self):
        triggers = self.workflow.get('on', self.workflow.get(True))
        self.assertEqual(triggers['workflow_run'], {'workflows': ['Rust prototype checks and playable builds'],
                                                  'types': ['completed'], 'branches': ['main']})
        guard = self.job['if']
        for pin in ('37415102452', "run_attempt == 1", '8f571464be706d0abde862e124582a188f633baf',
                    "head_branch == 'main'", "head_repository.full_name == 'RHS059/rust_duty'", '.github/workflows/build.yml'):
            self.assertIn(pin, guard)
        self.assertNotIn("conclusion == 'success'", guard)
        self.assertIn('paths', triggers['push'])
        self.assertEqual(triggers['push']['branches'], ['main'])

    def test_recovered_historical_compiler_outputs_drive_install_build_and_verifier(self):
        recovery = next(step for step in self.steps if step.get('id') == 'compiler')
        self.assertIn('recover-compiler', recovery['run'])
        self.assertNotIn('rustc -Vv', recovery['run'])
        oracle = next(step for step in self.steps if step.get('id') == 'oracle')
        self.assertEqual(oracle['env']['CAPTURE_TOOLCHAIN'], '${{ steps.compiler.outputs.toolchain }}')
        self.assertEqual(oracle['env']['CAPTURE_RUSTC_SHA256'], '${{ steps.compiler.outputs.rustc_sha256 }}')

    def test_incomplete_capture_is_pending_without_downloads_or_generation(self):
        metadata = next(step for step in self.steps if step.get('id') == 'eligibility')
        self.assertIn("identity.data.status === 'completed'", metadata['with']['script'])
        self.assertIn('validation_performed: false', metadata['with']['script'])
        first = self.steps.index(metadata) + 1
        for step in self.steps[first:]:
            if step.get('uses') != 'actions/upload-artifact@v4':
                self.assertEqual(step.get('if'), "steps.eligibility.outputs.eligible == 'true'")

    def test_all_downloads_use_guarded_ids_not_latest_names_or_patterns(self):
        selection = next(step for step in self.steps if step.get('id') == 'artifacts')
        downloads = [step for step in self.steps if step.get('uses') == 'actions/download-artifact@v4']
        self.assertEqual(len(downloads), 22)
        for step in downloads:
            value = step['with']
            self.assertLess(self.steps.index(selection), self.steps.index(step))
            self.assertTrue(value['artifact-ids'].startswith('${{ steps.artifacts.outputs.'))
            self.assertEqual(value['run-id'], '${{ env.CAPTURE_RUN_ID }}')
            self.assertEqual(value['repository'], 'RHS059/rust_duty')
            self.assertNotIn('name', value)
            self.assertNotIn('pattern', value)
        script = next(step['with']['script'] for step in self.steps if step.get('uses') == 'actions/github-script@v7')
        self.assertIn('page <= 20', script)
        self.assertIn('per_page: 100', script)
        self.assertIn('getWorkflowRunAttempt', script)
        self.assertNotIn('downloadArtifact', script)

    def test_receipt_anchor_is_direct_native_step_output_not_a_packet_rehash(self):
        oracle = next(step for step in self.steps if step.get('id') == 'oracle')
        check = next(step for step in self.steps if 'tools/revalidate_ads_offset.py' in step.get('run', ''))
        self.assertLess(self.steps.index(oracle), self.steps.index(check))
        self.assertEqual(check['env']['SOURCE_RECEIPT_SHA256'], '${{ steps.oracle.outputs.source_receipt_sha256 }}')
        self.assertIn('--receipt-anchor evidence/independent-source-receipt.sha256', oracle['run'])
        self.assertIn('--capture-rustc-sha256 "$env:CAPTURE_RUSTC_SHA256"', check['run'])
        self.assertIn('--verifier-source "$env:GITHUB_SHA"', check['run'])
        self.assertIn('--capture-source "$env:CAPTURE_SOURCE"', check['run'])
        self.assertNotIn('Get-FileHash', check['run'])

    def test_failed_evidence_and_original_verdicts_are_always_retained(self):
        uploads = [step for step in self.steps if step.get('uses') == 'actions/upload-artifact@v4']
        self.assertEqual(len(uploads), 2)
        self.assertTrue(all(step.get('if') == 'always()' for step in uploads))
        complete = uploads[0]['with']['path'].splitlines()
        self.assertIn('evidence/', complete)
        self.assertIn('downloaded/gameplay/summary.json', complete)
        self.assertIn('downloaded/offset/summary.json', complete)
        self.assertIn('downloaded/inputs/evidence/authored-inputs/input-manifest.json', complete)
        self.assertIn('evidence/independent-source-receipt.sha256', uploads[1]['with']['path'])

    def test_workflow_has_no_new_native_capture_render_or_override_command(self):
        text = self.path.read_text()
        self.assertNotIn('run_dx12_authored_shard.py run', text)
        self.assertNotIn('RUSTFLAGS:', text)
        self.assertNotIn('CARGO_ENCODED_RUSTFLAGS:', text)
        self.assertNotIn('RUSTC_WRAPPER:', text)
        self.assertNotIn('continue-on-error', text)
        self.assertNotIn('actions/cache', text)


if __name__ == '__main__':
    unittest.main()
