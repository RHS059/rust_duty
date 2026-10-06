#!/usr/bin/env python3
"""Original synthetic controls for the source/native binding boundary only."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
import zlib

import ads_source_visibility_binding as binding


def encoded(value):
    return (json.dumps(value, default=float, sort_keys=True) + '\n').encode()


def digest(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.packet_path = self.root / 'packet.json'
        self.recorded = 'C:/original/source-replay'
        self.native = {
            'source_commit': '1' * 40, 'run_id': '1234', 'run_attempt': '2',
            **{key: 'a' * 64 for key in binding.shared._HASH_FIELDS},
            'runtime_and_manifest_sha256': {},
        }
        self.files = {}
        self.before = {}
        self.inputs = {}
        for name in sorted(binding.INPUTS):
            key = 'inputs/' + name
            if name == 'settings.cfg':
                data = b'fire_rpm = 700\r\n'
            elif name == 'ads-offset.cfg':
                data = ('fire_rpm = 700\n' + binding.OFFSET_SUFFIX).replace('\n', '\r\n').encode()
            elif name == 'assets/animations.cfg':
                data = ('\n'.join(f'{k} = {v}' for k, v in binding.MANIFEST_ASSETS.items())
                        + '\nreload.empty = unavailable\n').encode()
            else:
                data = ('original companion bytes ' + name).encode()
            self.add_file(key, data)
            self.inputs[name] = key
            if name != 'ads-offset.cfg':
                self.native['runtime_and_manifest_sha256'][name] = digest(data)['sha256']
        for name in ('Cargo.toml', 'Cargo.lock', 'src/authored_viewmodel.rs',
                     'src/weapon_model.rs', 'examples/source_visibility_certificate_telemetry.rs',
                     'run_bound_certificates.py'):
            self.add_file(name, f'original test implementation {name}'.encode())
        self.add_file('Cargo.toml', b'[package]\nname = "source-oracle-test"\nversion = "0.0.0"\n'
                                  b'[profile.release]\nlto = "thin"\ncodegen-units = 1\nstrip = true\n')
        self.exe = 'C:/original/build/source_visibility_certificate_telemetry.exe'
        self.add_file(self.exe, b'original source replay executable')
        self.invocations, self.frame_dirs, self.outputs, reports = {}, {}, {}, {}
        sources = []
        for family in ('locomotion', 'reload'):
            sources.append({'vra': self.recorded + '/' + self.inputs[f'assets/{family}/asset.vra'],
                            'companion_crc32': [zlib.crc32((self.root / self.files[self.inputs[f'assets/{family}/asset.{ext}']]).read_bytes())
                                                for ext in ('vrs', 'vrm')],
                            'rigid_meshes': 1, 'skin_meshes': 1})
        for role in binding.ROLES:
            backend, native_backend, renderer = binding.BACKENDS[role]
            folder = self.root / 'native' / role
            folder.mkdir(parents=True)
            self.frame_dirs[role] = folder
            command = ['C:\\app\\game.exe', f'--renderer={renderer}', '--no-update', '--reference-viewport',
                       '--animation-manifest=C:\\assets\\animations.cfg', '--capture-sequence=gameplay-ads',
                       f'--output=C:\\capture\\{role}', '--settings=C:\\capture\\ads-offset.cfg',
                       '--capture-frame-witness=' + binding.role_witness_identity(self.native, 'ads-offset', role)]
            if role == 'dx12':
                command.append('--force-fallback-adapter')
            self.invocations[role] = {'command': command, 'cwd': 'C:\\app',
                                     'timeout_seconds': 900 if role == 'windows-legacy' else 3000}
            header = {**binding.HEADER_FIELDS, **binding.PROFILE_FIELDS,
                      'backend_profile': binding.BACKEND_PROFILES[role], 'sources': sources,
                      'profile_native_verified': False}
            rows = []
            for index in range(binding.FRAME_COUNT):
                gameplay = {
                    'simulation_time': index, 'segment': 'complete_cycle', 'route': 'ready', 'clip': '',
                    'native_clip_seconds': None, 'clip_duration': None, 'direction': 0,
                    'ads_requested': False, 'simulation_ads': 0, 'speed': 0, 'grounded': True,
                    'sprinting': False, 'mantling': False, 'ammo': 12, 'reserve': 90, 'shots': 0,
                    'reload_left': 0, 'reload_credit_at': 0, 'reload_ready_at': 0,
                    'renderer_failed': False, 'walk_weight': 0, 'walk_seconds': None,
                    'run_weight': 0, 'walk_min_rate': 0.8,
                }
                time = {'elapsed_seconds': index, 'normalized_phase': 0,
                        'visual_duration_seconds': 9.2, 'simulation_ready_seconds': 0.2,
                        'sampling_hz': 59.940063}
                row = {'frame': index, 'native_gameplay': gameplay, 'native_time': time,
                       'companion_catalog_vra': sources[0]['vra'], 'companion_crc32': sources[0]['companion_crc32'],
                       'required_contrast_samples': 0, 'possible_samples': 0,
                       'required_contrast_runs': [], 'possible_support_runs': [],
                       'source_triangles': 1, 'unclassified_triangles': 0,
                       'outside_bottom': 1, 'hidden_source_triangles': 0,
                       'classification': 'expected_empty_under_profile',
                       'unsupported_clip_triangles': 0, 'possible_support_complete': True}
                rows.append(row)
                image = folder / f'{index:04}.png'
                image.write_bytes(b'fixture image bytes; rendering is tested by caller')
                for suffix, content in (('.json', {'backend': native_backend, 'requested': renderer,
                                                   'width': 960, 'height': 540}),
                                        ('.gameplay.json', gameplay), ('.time.json', time)):
                    Path(str(image) + suffix).write_bytes(encoded(content))
            output = f'frames-{backend}.jsonl'
            self.outputs[role] = output
            data = b''.join(encoded(record) for record in (header, *rows))
            (self.root / output).write_bytes(data)
            reports[backend] = {'command': [self.exe, self.recorded + '/' + self.inputs['assets/animations.cfg'],
                                            self.recorded + '/' + self.inputs['ads-offset.cfg'], backend,
                                            self.recorded + '/' + output], 'exit_code': 0,
                                'output': digest(data), 'header': header}
        compiler = b'rustc 1.94.0 (synthetic-test-compiler)\r\nbinary: rustc\r\nhost: x86_64-pc-windows-msvc\r\nrelease: 1.94.0\r\n'
        self.expected_compiler_sha256 = digest(compiler)['sha256']
        self.add_file('oracle/rustc-vv.txt', compiler)
        self.build = {'command': ['C:\\toolchain\\bin\\cargo.exe', 'build', '--locked', '--release',
                                   '--no-default-features', '--features', 'legacy-macroquad,wgpu-runtime',
                                   '--target', binding.ORACLE_TARGET, '--example', 'source_visibility_certificate_telemetry'],
                       'cwd': self.recorded, 'exit_code': 0, 'environment': deepcopy(binding.ORACLE_ENVIRONMENT)}
        self.add_file('oracle/build.json', encoded(self.build))
        self.oracle = {'schema': 'rust-duty-native-source-oracle/v1', 'platform': 'win32', 'machine': 'AMD64',
                       'host': binding.ORACLE_TARGET, 'target': binding.ORACLE_TARGET, 'profile': 'release',
                       'features': binding.ORACLE_FEATURES, 'rustc_vv': 'oracle/rustc-vv.txt',
                       'build_receipt': 'oracle/build.json', 'executable': self.exe,
                       'execution_receipts': {backend: {'command': report['command'], 'cwd': self.recorded,
                                                        'exit_code': 0, 'environment': deepcopy(binding.ORACLE_ENVIRONMENT)}
                                              for backend, report in reports.items()}}
        self.receipt = {'schema': 'rust-duty-source-visibility-certificates-binding/v1',
                        'source_base_commit': '1' * 40,
                        'reviewed_manifest_dependency_mapping': binding.MANIFEST_ASSETS,
                        'inputs_and_implementation_before': deepcopy(self.before),
                        'inputs_and_implementation_after': deepcopy(self.before),
                        'backend_reports': reports, 'oracle_execution': self.oracle}
        self.packet = {'schema': binding.SCHEMA, 'capture_binding': deepcopy(self.native),
                       'original_invocations': deepcopy(self.invocations), 'receipt': 'receipt.json',
                       'recorded_root': self.recorded, 'files': self.files,
                       'source_outputs': self.outputs, 'input_files': self.inputs}
        self.native_offset = self.root / 'original-ads-offset.cfg'
        self.native_offset.write_bytes((self.root / self.files[self.inputs['ads-offset.cfg']]).read_bytes())
        self.save()

    def add_file(self, key, data):
        relative = 'portable/' + (key.replace(':', '') if PureWindowsPath(key).is_absolute() else key)
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.files[key] = relative
        self.before[key] = digest(data)

    def save(self):
        self.packet_path.write_bytes(encoded(self.packet))
        raw = encoded(self.receipt)
        (self.root / 'receipt.json').write_bytes(raw)
        # The test producer independently authorizes its freshly constructed
        # receipt; negative semantic controls therefore reach the intended check.
        self.expected_receipt_sha256 = digest(raw)['sha256']

    def bind(self):
        return binding.bind_source_packet(self.packet_path, native_binding=self.native,
                                          original_invocations=self.invocations,
                                          native_frame_dirs=self.frame_dirs,
                                          native_offset_settings=self.native_offset,
                                          expected_receipt_sha256=self.expected_receipt_sha256,
                                          expected_compiler_sha256=self.expected_compiler_sha256)

    def alter_source(self, change, role='dx12', refresh_receipt=True):
        path = self.root / self.outputs[role]
        records = [json.loads(line) for line in path.read_bytes().splitlines()]
        change(records)
        raw = b''.join(encoded(row) for row in records)
        path.write_bytes(raw)
        if refresh_receipt:
            report = self.receipt['backend_reports'][binding.BACKENDS[role][0]]
            report['output'] = digest(raw)
            report['header'] = records[0]
            self.save()

    def test_complete_binding_retains_production_capture_and_source_identities(self):
        context = self.bind()
        self.assertEqual(context.capture_binding['source_commit'], '1' * 40)
        self.assertEqual(context.source_base_commit, '1' * 40)
        self.assertEqual([len(context.rows_by_role[role]) for role in binding.ROLES], [553, 553])
        context.verify_frame_binding(self.frame_dirs['dx12'] / '0552.png', 'dx12', 552)
        context.verify_unchanged()

    def test_changed_source_production_commit(self):
        self.receipt['source_base_commit'] = '2' * 40
        self.save()
        with self.assertRaisesRegex(ValueError, 'source replay production commit differs'):
            self.bind()

    def test_complete_example_binds_its_named_executable(self):
        self.select_example('source_visibility_certificate_complete')
        self.assertEqual(len(self.bind().rows_by_role['dx12']), 553)

    def test_unadorned_repository_example_binds_its_named_executable(self):
        self.select_example('source_visibility_certificate')
        self.assertEqual(len(self.bind().rows_by_role['dx12']), 553)

    def select_example(self, name):
        old_key = self.exe
        self.exe = f'C:/original/build/{name}.exe'
        self.files[self.exe] = self.files.pop(old_key)
        example = 'examples/source_visibility_certificate_telemetry.rs'
        new_example = f'examples/{name}.rs'
        self.files[new_example] = self.files.pop(example)
        for field in ('inputs_and_implementation_before', 'inputs_and_implementation_after'):
            self.receipt[field][self.exe] = self.receipt[field].pop(old_key)
            self.receipt[field][new_example] = self.receipt[field].pop(example)
        for report in self.receipt['backend_reports'].values():
            report['command'][0] = self.exe
        self.oracle['executable'] = self.exe
        self.build['command'][-1] = name
        self.update_bound_file('oracle/build.json', encoded(self.build))
        self.save()

    def update_bound_file(self, key, data):
        (self.root / self.files[key]).write_bytes(data)
        for field in ('inputs_and_implementation_before', 'inputs_and_implementation_after'):
            self.receipt[field][key] = digest(data)

    def test_linux_source_oracle_cannot_be_promoted(self):
        self.oracle['platform'] = 'linux'
        self.save()
        with self.assertRaisesRegex(ValueError, 'oracle platform'):
            self.bind()

    def test_source_compiler_must_match_independently_captured_bytes(self):
        key = self.oracle['rustc_vv']
        data = (self.root / self.files[key]).read_bytes().replace(b'1.94.0', b'1.95.0')
        self.update_bound_file(key, data)
        self.save()
        with self.assertRaisesRegex(ValueError, 'compiler bytes differ from independently captured compiler SHA-256'):
            self.bind()

    def test_compiler_receipt_requires_windows_host(self):
        key = self.oracle['rustc_vv']
        data = (self.root / self.files[key]).read_bytes().replace(b'x86_64-pc-windows-msvc', b'x86_64-unknown-linux-gnu')
        self.update_bound_file(key, data)
        self.expected_compiler_sha256 = digest(data)['sha256']
        self.save()
        with self.assertRaisesRegex(ValueError, 'rustc -Vv must identify the native Windows host'):
            self.bind()

    def test_nonrelease_source_build_rejected(self):
        self.build['command'].remove('--release')
        self.update_bound_file('oracle/build.json', encoded(self.build))
        self.save()
        with self.assertRaisesRegex(ValueError, 'locked release without default features'):
            self.bind()

    def test_wrapper_release_profile_must_match_captured_settings(self):
        data = (self.root / self.files['Cargo.toml']).read_bytes().replace(b'codegen-units = 1', b'codegen-units = 16')
        self.update_bound_file('Cargo.toml', data)
        self.save()
        with self.assertRaisesRegex(ValueError, 'oracle Cargo release profile'):
            self.bind()

    def test_release_flag_does_not_allow_extra_profile_overrides(self):
        data = (self.root / self.files['Cargo.toml']).read_bytes() + b'opt-level = 0\n'
        self.update_bound_file('Cargo.toml', data)
        self.save()
        with self.assertRaisesRegex(ValueError, 'oracle Cargo release profile'):
            self.bind()

    def test_different_native_features_rejected(self):
        self.build['command'][self.build['command'].index('--features') + 1] = 'wgpu-runtime'
        self.update_bound_file('oracle/build.json', encoded(self.build))
        self.save()
        with self.assertRaisesRegex(ValueError, 'exactly the native production features'):
            self.bind()

    def test_cpu_math_override_rejected(self):
        self.oracle['execution_receipts']['dx12']['environment']['RUSTFLAGS'] = '-C target-cpu=native'
        self.save()
        with self.assertRaisesRegex(ValueError, 'default compiler environment'):
            self.bind()

    def test_missing_explicit_environment_observation_rejected(self):
        self.build['environment'].pop('RUSTC_WRAPPER')
        self.update_bound_file('oracle/build.json', encoded(self.build))
        self.save()
        with self.assertRaisesRegex(ValueError, 'default compiler environment'):
            self.bind()

    def test_execution_receipt_must_match_source_command(self):
        self.oracle['execution_receipts']['dx12']['command'] = ['different.exe']
        self.save()
        with self.assertRaisesRegex(ValueError, 'original execution command'):
            self.bind()

    def test_native_oracle_metadata_is_mandatory(self):
        del self.receipt['oracle_execution']
        self.save()
        with self.assertRaisesRegex(ValueError, 'native Windows source oracle'):
            self.bind()

    def test_windows_relocation_and_new_producer_with_forwarded_features(self):
        self.packet['recorded_root'] = self.recorded.replace('/', '\\')
        old = 'run_bound_certificates.py'
        new = 'tools/build_ads_source_packet.py'
        self.files[new] = self.files.pop(old)
        for field in ('inputs_and_implementation_before', 'inputs_and_implementation_after'):
            self.receipt[field][new] = self.receipt[field].pop(old)
        for report in self.receipt['backend_reports'].values():
            for index in (0, 1, 2, 4):
                report['command'][index] = report['command'][index].replace('/', '\\')
        self.build['command'][self.build['command'].index('--features') + 1] = 'vector-range/legacy-macroquad,vector-range/wgpu-runtime'
        self.build['cwd'] = self.packet['recorded_root']
        self.update_bound_file('oracle/build.json', encoded(self.build))
        for receipt in self.oracle['execution_receipts'].values():
            receipt['cwd'] = self.packet['recorded_root']

        def use_windows_paths(rows):
            for source in rows[0]['sources']:
                source['vra'] = source['vra'].replace('/', '\\')
            for row in rows[1:]:
                row['companion_catalog_vra'] = row['companion_catalog_vra'].replace('/', '\\')

        for role in binding.ROLES:
            self.alter_source(use_windows_paths, role=role)
        self.save()
        self.assertEqual(len(self.bind().rows_by_role['dx12']), 553)

    def test_regenerated_reload_not_native_even_when_receipt_consistent(self):
        key = self.inputs['assets/reload/asset.vrs']
        data = b'regenerated different skeleton'
        (self.root / self.files[key]).write_bytes(data)
        for field in ('inputs_and_implementation_before', 'inputs_and_implementation_after'):
            self.receipt[field][key] = digest(data)
        self.save()
        with self.assertRaisesRegex(ValueError, 'native/source input mismatch: assets/reload/asset.vrs'):
            self.bind()

    def test_absent_companion(self):
        del self.packet['input_files']['assets/walk/asset.vrm']
        self.save()
        with self.assertRaisesRegex(ValueError, 'consumed inputs'):
            self.bind()

    def test_changed_base_settings(self):
        key = self.inputs['settings.cfg']
        data = b'fire_rpm = 800\n'
        (self.root / self.files[key]).write_bytes(data)
        for field in ('inputs_and_implementation_before', 'inputs_and_implementation_after'):
            self.receipt[field][key] = digest(data)
        self.save()
        with self.assertRaisesRegex(ValueError, 'native/source input mismatch: settings.cfg'):
            self.bind()

    def test_changed_native_offset(self):
        self.native_offset.write_bytes(b'changed offset settings')
        with self.assertRaisesRegex(ValueError, 'original native offset settings'):
            self.bind()

    def test_wrong_backend_profile_even_with_fresh_output_receipt(self):
        self.alter_source(lambda rows: rows[0].update(backend_profile=binding.BACKEND_PROFILES['windows-legacy']))
        with self.assertRaisesRegex(ValueError, 'source header backend_profile'):
            self.bind()

    def test_executable_native_binding_mismatch(self):
        self.packet['capture_binding']['executable_sha256'] = 'f' * 64
        self.save()
        with self.assertRaisesRegex(ValueError, 'binaries or common inputs differ'):
            self.bind()

    def test_exact_original_invocation_change(self):
        self.packet['original_invocations']['dx12']['command'].append('--capture-hz=60')
        self.save()
        with self.assertRaisesRegex(ValueError, 'original native invocation'):
            self.bind()

    def test_source_executable_changed(self):
        (self.root / self.files[self.exe]).write_bytes(b'changed executable')
        with self.assertRaisesRegex(ValueError, 'source bytes'):
            self.bind()

    def test_before_after_disagreement(self):
        self.receipt['inputs_and_implementation_after'][self.exe]['sha256'] = 'f' * 64
        self.save()
        with self.assertRaisesRegex(ValueError, 'before and after'):
            self.bind()

    def test_changed_source_output(self):
        self.alter_source(lambda rows: rows[12].update(required_contrast_samples=3), refresh_receipt=False)
        with self.assertRaisesRegex(ValueError, 'source output bytes'):
            self.bind()

    def test_refreshed_self_reported_output_hash_does_not_replace_trusted_receipt(self):
        original_receipt_sha256 = self.expected_receipt_sha256
        self.alter_source(lambda rows: rows[12].update(
            required_contrast_samples=3, possible_samples=3,
            required_contrast_runs=[[23040, 3]], possible_support_runs=[[23040, 3]],
            unclassified_triangles=1, outside_bottom=0,
            classification='potentially_visible_unresolved'))
        self.expected_receipt_sha256 = original_receipt_sha256
        with self.assertRaisesRegex(ValueError, 'source receipt differs from independently retained SHA-256'):
            self.bind()

    def test_trusted_receipt_hash_requires_canonical_sha256(self):
        self.expected_receipt_sha256 = 'A' * 64
        with self.assertRaisesRegex(ValueError, 'expected source receipt SHA-256 must be independently supplied'):
            self.bind()

    def test_missing_time_is_not_a_source_binding(self):
        self.alter_source(lambda rows: rows[1].pop('native_time'))
        with self.assertRaisesRegex(ValueError, 'missing complete native_time'):
            self.bind()

    def test_last_frame_timing_difference(self):
        self.alter_source(lambda rows: rows[-1]['native_time'].update(sampling_hz=60))
        with self.assertRaisesRegex(ValueError, 'dx12/552/native_time'):
            self.bind()

    def test_gameplay_type_and_value_changes(self):
        self.alter_source(lambda rows: rows[172]['native_gameplay'].update(ammo=12.0))
        with self.assertRaisesRegex(ValueError, 'native_gameplay/ammo: expected capture integer'):
            self.bind()

    def test_matching_gameplay_omission_is_rejected(self):
        self.alter_source(lambda rows: rows[172]['native_gameplay'].pop('walk_min_rate'))
        path = self.frame_dirs['dx12'] / '0171.png.gameplay.json'
        native = json.loads(path.read_bytes())
        native.pop('walk_min_rate')
        path.write_bytes(encoded(native))
        with self.assertRaisesRegex(ValueError, 'dx12/171/native_gameplay: expected exactly'):
            self.bind()

    def test_matching_time_omission_is_rejected(self):
        self.alter_source(lambda rows: rows[172]['native_time'].pop('sampling_hz'))
        path = self.frame_dirs['dx12'] / '0171.png.time.json'
        native = json.loads(path.read_bytes())
        native.pop('sampling_hz')
        path.write_bytes(encoded(native))
        with self.assertRaisesRegex(ValueError, 'dx12/171/native_time: expected exactly'):
            self.bind()

    def test_matching_wrong_boolean_type_is_rejected(self):
        self.alter_source(lambda rows: rows[172]['native_gameplay'].update(ads_requested=0))
        path = self.frame_dirs['dx12'] / '0171.png.gameplay.json'
        native = json.loads(path.read_bytes())
        native['ads_requested'] = 0
        path.write_bytes(encoded(native))
        with self.assertRaisesRegex(ValueError, 'native_gameplay/ads_requested: expected boolean'):
            self.bind()

    def test_matching_wrong_time_type_is_rejected(self):
        self.alter_source(lambda rows: rows[172]['native_time'].update(sampling_hz=True))
        path = self.frame_dirs['dx12'] / '0171.png.time.json'
        native = json.loads(path.read_bytes())
        native['sampling_hz'] = True
        path.write_bytes(encoded(native))
        with self.assertRaisesRegex(ValueError, 'native_time/sampling_hz: expected finite number'):
            self.bind()

    def test_late_native_mutation(self):
        context = self.bind()
        (self.frame_dirs['dx12'] / '0552.png.time.json').write_bytes(encoded({'changed': True}))
        with self.assertRaisesRegex(ValueError, 'late mutation'):
            context.verify_unchanged()

    def test_late_source_mutation(self):
        context = self.bind()
        (self.root / self.outputs['windows-legacy']).write_bytes(b'changed after initial verification')
        with self.assertRaisesRegex(ValueError, 'late mutation'):
            context.verify_unchanged()

    def test_late_frame_inventory_addition(self):
        context = self.bind()
        (self.frame_dirs['dx12'] / 'extra.png').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'bound file set changed'):
            context.verify_unchanged()

    def test_existing_validator_can_write_derived_report_on_fresh_copy(self):
        context = self.bind()
        (self.frame_dirs['dx12'] / 'verification.json').write_bytes(encoded({'passed': True}))
        context.verify_unchanged()

    def test_portable_mapping_rejects_escape(self):
        self.files[self.exe] = '../outside'
        self.save()
        with self.assertRaisesRegex(ValueError, 'unsafe relative path'):
            self.bind()

    def test_source_diagnostic_receipt_alone_is_not_bindable(self):
        self.packet_path.write_bytes(encoded(self.receipt))
        with self.assertRaisesRegex(ValueError, 'source packet'):
            self.bind()


if __name__ == '__main__':
    unittest.main()
