"""Synthetic class reuse controls plus validation of the compact reviewed bundle.

Synthetic source objects model the already-completed source-packet trust boundary;
that binder and the PNG/witness validators have independent tests. No GPU, private
assets or successful native capture is fabricated by these tests.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import finite_ads_profile_binding as f


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


class ProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bound = f.source.BoundSourcePacket()
        self.bound.capture_binding = {'source_commit': '1' * 40, 'run_id': '456', 'run_attempt': '1',
            **{key: 'a' * 64 for key in f.source.shared._HASH_FIELDS}, 'runtime_and_manifest_sha256': {}}
        self.packet = {'recorded_root': 'C:/fresh/source', 'receipt': 'receipt.json',
                       'capture_binding': self.bound.capture_binding, 'files': {}, 'input_files': {}}
        self.receipt = {'capture_rustc_sha256': f._identity(b'compiler')['sha256'],
                        'oracle_execution': {'platform': 'win32', 'host': f.source.ORACLE_TARGET,
                        'target': f.source.ORACLE_TARGET, 'profile': 'release', 'features': f.source.ORACLE_FEATURES,
                        'rustc_vv': 'compiler.txt'}, 'inputs_and_implementation_before': {},
                        'inputs_and_implementation_after': {}}
        self.descriptor = {'schema': f.SCHEMA, 'status': 'reviewed', 'class_id': 'ads-offset-8f571464-finite-v1',
                           'acceptance_verdict': None, 'equivalence': {'inputs': {}, 'production': {},
                           'capture_configuration': {key: self.bound.capture_binding[key] for key in
                             ('gl_reference_sha256', 'cargo_manifest_sha256', 'cargo_lock_sha256')},
                           'compiler_sha256': self.receipt['capture_rustc_sha256'],
                           'oracle': {key: self.receipt['oracle_execution'][key] for key in
                                      ('platform', 'host', 'target', 'profile', 'features')}, 'state_sha256': {}}}
        for name in sorted(f.source.INPUTS):
            self.add_file(name, name.encode())
            self.packet['input_files'][name] = name
            self.descriptor['equivalence']['inputs'][name] = f._identity(name.encode())
        for name in ('src/authored_viewmodel.rs', 'src/render/device.rs', 'Cargo.toml', 'Cargo.lock'):
            raw = (name + '\n').encode()
            self.add_file(name, raw)
            self.descriptor['equivalence']['production'][name] = f._identity(raw)
        self.add_file('compiler.txt', b'compiler')
        source_path = self.packet['recorded_root'] + '/assets/locomotion/asset.vra'
        for role in f.source.ROLES:
            header = {**deepcopy(f.source.HEADER_FIELDS), **f.source.PROFILE_FIELDS,
                      **{name: False for name in f.gl.SOURCE_FALSE_FLAGS},
                      'sources': [{'vra': source_path}], 'backend_profile': f.source.BACKEND_PROFILES[role]}
            rows = [{'frame': index, 'companion_catalog_vra': source_path,
                     'native_gameplay': {'ammo': 12}, 'native_time': {'sampling_hz': Decimal('59.94')},
                     'required_contrast_runs': [], 'possible_support_runs': [], 'acceptance_verdict': None}
                    for index in range(553)]
            self.bound.headers_by_role[role], self.bound.rows_by_role[role] = header, rows
            self.descriptor['equivalence']['state_sha256'][role] = f._state_sha(header, rows, self.packet['recorded_root'])
        original_gl = {'schema': 'synthetic-reviewed-gl', 'manifest_sha256': 'c' * 64,
                       'files': {'windows_gl_reference_lock.json': 'c' * 64,
                                 'staging-receipt.json': 'd' * 64, 'opengl32.dll': 'e' * 64}}
        self.bound.capture_binding['gl_reference_sha256'] = f.source.shared.gl_reference_digest(original_gl)
        self.descriptor['equivalence']['capture_configuration']['gl_reference_sha256'] = self.bound.capture_binding['gl_reference_sha256']
        self.descriptor['equivalence'].update(original_gl_reference=original_gl,
            gl_metadata_pairs=[{'manifest_sha256': 'c' * 64, 'staging_receipt_sha256': 'd' * 64},
                               {'manifest_sha256': 'e' * 64, 'staging_receipt_sha256': 'f' * 64}])
        self.native_manifest = {'binding': self.bound.capture_binding, 'gl_reference': deepcopy(original_gl)}
        self.packet_path = self.root / 'packet.json'
        self.save()

    def add_file(self, name, raw):
        path = self.root / 'inventory' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.packet['files'][name] = path.relative_to(self.root).as_posix()
        for key in ('inputs_and_implementation_before', 'inputs_and_implementation_after'):
            self.receipt[key][name] = f._identity(raw)

    def save(self):
        self.add_file('native-input-manifest.json', encoded(self.native_manifest))
        self.packet_path.write_bytes(encoded(self.packet))
        (self.root / 'receipt.json').write_bytes(encoded(self.receipt))
        # A fresh synthetic source producer is explicitly separate from the
        # independent reviewed class, which these controls never refresh.
        self.bound._snapshots.clear()
        self.bound._remember(self.packet_path)

    def bind_class(self):
        return f._packet_class(self.bound, self.packet_path, self.descriptor)

    def test_equivalent_fresh_run_and_executable_are_not_original_identity(self):
        self.bind_class()
        for key in ('executable_sha256', 'renderer_contract_sha256'):
            self.bound.capture_binding[key] = 'b' * 64
        self.bound.capture_binding.update(source_commit='2' * 40, run_id='789')
        self.save()
        self.bind_class()

    def test_exact_inputs_and_production_reject_refreshed_candidate_inventory(self):
        for name in ('assets/ads/asset.vra', 'settings.cfg', 'src/render/device.rs', 'Cargo.lock'):
            old = (self.root / self.packet['files'][name]).read_bytes()
            self.add_file(name, old + b'changed')
            self.save()
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.bind_class()
            self.add_file(name, old)
            self.save()

    def test_missing_and_unreviewed_production_files_rejected(self):
        self.add_file('src/new_runtime.rs', b'new code')
        self.save()
        with self.assertRaisesRegex(ValueError, 'unreviewed production'):
            self.bind_class()

    def test_complete_state_comparison_includes_nonfallback_rows_and_number_precision(self):
        for field, value in (('native_gameplay', {'ammo': 11}), ('native_time', {'sampling_hz': Decimal('59.9400000000000000000000000000000001')}),
                             ('required_contrast_runs', [[2000, 1]]), ('new_source_field', True)):
            row = self.bound.rows_by_role['dx12'][552]
            old = deepcopy(row)
            row[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'complete reviewed masks'):
                self.bind_class()
            row.clear(); row.update(old)

    def test_only_exact_verified_root_mapping_and_source_line_endings(self):
        for role in f.source.ROLES:
            self.bound.headers_by_role[role]['sources'][0]['vra'] = 'D:/later/source/assets/locomotion/asset.vra'
            for row in self.bound.rows_by_role[role]:
                row['companion_catalog_vra'] = 'D:/later/source/assets/locomotion/asset.vra'
        self.packet['recorded_root'] = 'D:/later/source'
        self.add_file('src/render/device.rs', b'src/render/device.rs\r\n')
        self.save()
        self.bind_class()
        self.bound.rows_by_role['dx12'][0]['companion_catalog_vra'] = 'D:/outside/assets/locomotion/asset.vra'
        with self.assertRaisesRegex(ValueError, 'escapes verified'):
            self.bind_class()

    def test_lone_carriage_return_and_compiler_change_rejected(self):
        self.add_file('src/render/device.rs', b'src/render/device.rs\r')
        self.save()
        with self.assertRaisesRegex(ValueError, 'CRLF/LF'):
            self.bind_class()
        self.add_file('src/render/device.rs', b'src/render/device.rs\n')
        self.add_file('compiler.txt', b'changed compiler')
        self.save()
        with self.assertRaisesRegex(ValueError, 'actual compiler bytes'):
            self.bind_class()

    def test_pending_descriptor_and_self_refreshed_hash_rejected(self):
        path = self.root / 'class.json'
        self.descriptor['status'] = 'pending_independent_native_review'
        path.write_bytes(encoded(self.descriptor))
        kwargs = dict(source_packet=self.bound, source_packet_path=self.packet_path,
                      reviewed_class=path, native_runtime_logs={})
        with self.assertRaisesRegex(ValueError, 'independent SHA'):
            f.bind_finite_ads_profile(expected_class_sha256='0' * 64, **kwargs)
        with self.assertRaisesRegex(ValueError, 'review pending'):
            f.bind_finite_ads_profile(expected_class_sha256=f._identity(path.read_bytes())['sha256'], **kwargs)

    def test_source_flags_and_late_source_mutation_rejected(self):
        self.bound.headers_by_role['dx12']['profile_native_verified'] = True
        with self.assertRaisesRegex(ValueError, 'original source flag'):
            self.bind_class()
        self.bound.headers_by_role['dx12']['profile_native_verified'] = False
        self.bind_class()
        (self.root / self.packet['files']['src/render/device.rs']).write_bytes(b'late mutation')
        with self.assertRaisesRegex(ValueError, 'late mutation'):
            self.bind_class()

    def test_late_native_input_manifest_mutation_rejected(self):
        self.bind_class()
        path = self.root / self.packet['files']['native-input-manifest.json']
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'late mutation'):
            self.bind_class()

    def test_config_mapping_allows_only_whole_file_lf_and_crlf(self):
        name = 'settings.cfg'; lf = b'viewmodel_x = 0.20\nviewmodel_y = -0.20\n'
        crlf = lf.replace(b'\n', b'\r\n')
        expected = {'inputs': {name: f._identity(crlf)}, 'config_newlines': {name: {
            'original': f._identity(crlf), 'lf': f._identity(lf), 'crlf': f._identity(crlf),
            'transform': 'whole-file CRLF/LF only'}}}
        for raw in (lf, crlf):
            f._input_equivalent(name, raw, expected)
        for raw in (lf + b' ', lf.replace(b' = ', b'='), lf.replace(b'0.20', b'0.21'),
                    lf.replace(b'\n', b'\r'), lf.replace(b'\n', b'\r\n', 1)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                f._input_equivalent(name, raw, expected)

    def test_existing_reviewed_bridge_and_checked_overlays_are_the_only_exclusions(self):
        raw = (b'/// Read-only evaluated source pose for independent CPU diagnostics.\nstruct Probe;\n'
               b'impl AuthoredViewmodel {\n'
               b'    /// Snapshot the same effective pose selected by `draw_checked`, before\n'
               b'    fn snapshot() {}\n'
               b'    /// Loads CPU mesh and texture descriptors without requiring a render context.\n'
               b'    fn load() {}\n}\n#[cfg(test)]\nmod tests {\n'
               b'    fn retained() {}\n\n    fn layered_contact_fixture() -> AuthoredViewmodel { todo!() }\n}\n')
        base = f._bridge_base(raw)
        f.producer.reviewed_bridge(base, raw)
        self.assertNotEqual(raw, base)
        self.assertEqual(f._production_bytes('src/authored_viewmodel.rs', raw.replace(b'\n', b'\r\n')), base)
        original = b'impl Mesh {\n' + f.preparation.MESH_END + b' retained\n}\n'
        overlay = original.replace(f.preparation.MESH_END, f.preparation.MESH_START + b' helper\n' + f.preparation.MESH_END)
        self.assertEqual(f._production_bytes('src/render/mesh.rs', overlay), original)
        self.assertNotEqual(f._production_bytes('src/render/mesh.rs', overlay.replace(b'retained', b'changed')), original)

    def test_exact_asset_path_fixture_repair_preserves_historical_source_and_packet(self):
        name = 'src/asset_path.rs'
        # Normalize the checkout-derived fixture, not the raw packet bytes under test.
        raw = (Path(__file__).resolve().parents[1] / name).read_bytes().replace(b'\r\n', b'\n')
        original = f._asset_path_test_base(raw)
        self.assertEqual(f._identity(raw), f.ASSET_PATH_TEST_FIX['after'])
        self.assertEqual(f._identity(original), f.ASSET_PATH_TEST_FIX['before'])
        reviewed = json.loads(Path(__file__).with_name('finite_ads_reviewed_class.json').read_text())
        self.assertEqual(f._identity(original), reviewed['equivalence']['production'][name])
        start = b'#[cfg(test)]\nmod tests {\n'
        end = b'    #[test]\n    fn locomotion_pack_is_discovered_next_to_executable()'
        self.assertEqual(original[:original.index(start)], raw[:raw.index(start)])
        self.assertEqual(original[original.index(end):], raw[raw.index(end):])
        self.descriptor['equivalence']['production'][name] = f._identity(original)
        for current in (original, raw, raw.replace(b'\n', b'\r\n')):
            self.add_file(name, current)
            self.save()
            self.bind_class()
            self.assertEqual(self.bound._read(self.root / self.packet['files'][name]), current)

    def test_asset_path_fixture_mapping_rejects_refreshed_unreviewed_bytes(self):
        name = 'src/asset_path.rs'
        raw = (Path(__file__).resolve().parents[1] / name).read_bytes().replace(b'\r\n', b'\n')
        self.descriptor['equivalence']['production'][name] = f.ASSET_PATH_TEST_FIX['before']
        changes = (
            (b'return WeaponSource::Procedural;', b'return WeaponSource::Embedded;'),
            (b'#[cfg(test)]', b'#[cfg(not(test))]'),
            (b'NEXT_TEMP_ID', b'OTHER_TEMP_ID'),
            (b'fn locomotion_pack_is_discovered', b'fn changed_locomotion_pack_is_discovered'),
        )
        for before, after in changes:
            changed = raw.replace(before, after)
            self.assertNotEqual(changed, raw)
            self.add_file(name, changed)
            self.save()
            with self.subTest(change=before), self.assertRaisesRegex(ValueError, 'unreviewed additive/source'):
                self.bind_class()
        self.add_file(name, raw)
        self.save()
        # A descriptor with a different original source is not this mapping.
        self.descriptor['equivalence']['production'][name] = f._identity(b'another source')
        with self.assertRaisesRegex(ValueError, 'unreviewed additive/source'):
            self.bind_class()


class ReviewedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).with_name('finite_ads_reviewed_class.json')
        self.descriptor = f.source._parse(self.path.read_bytes(), 'reviewed descriptor')
        self.ledger = f.source.BoundSourcePacket()
        self.evidence = f._read_evidence(self.ledger, self.path, self.descriptor)

    def test_actual_bounded_native_build_and_four_domain_reports_bind(self):
        f._native_build(self.evidence, self.descriptor)
        for role in f.source.ROLES:
            backend = f.source.BACKENDS[role][0]
            for kind in ('empty', 'visible'):
                f._comparison(self.evidence[f'{backend}_{kind}'], role, self.descriptor[kind + '_frames'],
                              kind == 'empty', self.descriptor['original_outputs_sha256'][role])

    def test_missing_domain_frame_changed_compiler_and_executable_rejected(self):
        report = deepcopy(self.evidence['dx12_empty'])
        report['frames'].pop()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            f._comparison(report, 'dx12', self.descriptor['empty_frames'], True,
                          self.descriptor['original_outputs_sha256']['dx12'])
        for key in ('compiler_before', 'compiler_after'):
            e = deepcopy(self.evidence); e[key] += b'changed'
            with self.subTest(key=key), self.assertRaises(ValueError):
                f._native_build(e, self.descriptor)
        e = deepcopy(self.evidence); e['native']['executable_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'actual native executable'):
            f._native_build(e, self.descriptor)

    def test_unbound_gl_and_plan_only_native_rejected_before_rows(self):
        for key, value in (('reviewed_gl_hashes_match', False), ('status', 'failed')):
            e = deepcopy(self.evidence); e['runner'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                f._native_evidence(e, self.descriptor, None)
        e = deepcopy(self.evidence); e['native']['native_execution'] = False
        with self.assertRaisesRegex(ValueError, 'native execution required'):
            f._native_evidence(e, self.descriptor, None)

    def test_native_frame_triangle_and_negative_control_proof_required(self):
        e = deepcopy(self.evidence)
        # Explicit synthetic mask substitution exercises semantic controls after
        # the real native document's setup checks, without claiming native proof.
        mask = bytearray(960 * 540); mask[2000] = 1
        native_rows = [{'required_contrast_runs': [[2000, 1]]} for _ in range(553)]
        bound = f.source.BoundSourcePacket(); bound.rows_by_role['dx12'] = native_rows
        for row in e['native']['frames']:
            row['required_samples'] = 1
            row['checked_required_mask_sha256'] = hashlib.sha256(mask).hexdigest()
        f._native_evidence(e, self.descriptor, bound)
        for control in f.CONTROLS:
            changed = deepcopy(e)
            del changed['native']['frames'][0]['negative_controls'][control]
            with self.subTest(control=control), self.assertRaisesRegex(ValueError, 'negative controls'):
                f._native_evidence(changed, self.descriptor, bound)
        for key, value in (('source_triangles', 0), ('per_triangle_support_guard_passed', False),
                           ('production_alpha_blend_endpoints_verified', False)):
            changed = deepcopy(e); changed['native']['frames'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                f._native_evidence(changed, self.descriptor, bound)
        e['native']['frames'].pop()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            f._native_evidence(e, self.descriptor, bound)

    def test_missing_gl_fragment_frame_or_inventory_claim_rejected(self):
        for field, value in (('frames', self.descriptor['gl_export']['frames'][:-1]),
                             ('complete_triangle_fragment_inventory_checked', False)):
            d = deepcopy(self.descriptor); d['gl_export'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                f._gl_rows(d, self.evidence['gl_binding'], None)

    def test_gl_exact_metadata_pairs_and_all_runtime_components(self):
        expected = self.descriptor['equivalence']
        original = expected['original_gl_reference']
        fresh = deepcopy(original)
        pair = expected['gl_metadata_pairs'][1]
        fresh['manifest_sha256'] = pair['manifest_sha256']
        fresh['files']['windows_gl_reference_lock.json'] = pair['manifest_sha256']
        fresh['files']['staging-receipt.json'] = pair['staging_receipt_sha256']
        def check(reference):
            binding = {'gl_reference_sha256': f.source.shared.gl_reference_digest(reference)}
            f._gl_reference_equivalent({'binding': binding, 'gl_reference': reference}, binding, expected)
        check(original); check(fresh)
        bad = []
        for base, other in ((original, fresh), (fresh, original)):
            changed = deepcopy(base)
            changed['files']['staging-receipt.json'] = other['files']['staging-receipt.json']
            bad.append(changed)
        for member in (next(name for name in original['files'] if name.endswith('.dll')),
                       next(name for name in original['files'] if name.startswith('licenses/'))):
            changed = deepcopy(fresh); changed['files'][member] = '0' * 64; bad.append(changed)
        changed = deepcopy(fresh); changed['environment']['GALLIUM_DRIVER'] = 'changed'; bad.append(changed)
        changed = deepcopy(fresh); changed['loaded_modules_verified'] = True; bad.append(changed)
        for changed in bad:
            # Even a consistently refreshed candidate aggregate cannot authorize
            # changed members or an unreviewed pairing of genuine metadata.
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'components'):
                check(changed)

    def test_late_evidence_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'evidence.json'
            path.write_bytes(b'{}')
            ledger = f.source.BoundSourcePacket(); ledger._remember(path)
            path.write_bytes(b'{"mutated": true}')
            with self.assertRaisesRegex(ValueError, 'late mutation'):
                ledger.verify_unchanged()

    def test_native_runtime_changes_and_ambiguous_receipts_rejected(self):
        native = self.evidence['native']['native_identity']
        device = {key: native[key] for key in f.DEVICE_FIELDS}
        device.update(force_fallback_requested=True, present_mode='Fifo')
        lines = ['renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver',
                 'renderer dx12_shader_compiler=Fxc', 'renderer device_evidence=' + json.dumps(device)]
        with tempfile.TemporaryDirectory() as temporary:
            logs = {role: Path(temporary) / (role + '.log') for role in f.source.ROLES}
            logs['windows-legacy'].write_text('GL capture log\n')
            for value in ({**device, 'driver': 'different'}, {**device, 'vendor_id': 1},
                          {**device, 'device_type': 'DiscreteGpu'},
                          {**device, 'device_id': 1}, {**device, 'driver_info': 'different'}):
                logs['dx12'].write_text('\n'.join([*lines[:2], 'renderer device_evidence=' + json.dumps(value)]))
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'independent WARP'):
                    f._runtime_identity(f.source.BoundSourcePacket(), logs, native, None)
            logs['dx12'].write_text('\n'.join([*lines, lines[-1]]))
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                f._runtime_identity(f.source.BoundSourcePacket(), logs, native, None)

    def test_windowed_game_receipt_binds_without_using_headless_probe_mode(self):
        native = self.evidence['native']['native_identity']
        device = {key: native[key] for key in f.DEVICE_FIELDS}
        device.update(force_fallback_requested=True, present_mode='Fifo')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bound = f.source.BoundSourcePacket()
            bound.capture_binding = {'gl_reference_sha256': 'a' * 64}
            bound._frames = {role: [root / (role + '.png')] for role in f.source.ROLES}
            for role, frames in bound._frames.items():
                adapter = native['adapter'] if role == 'dx12' else 'llvmpipe (LLVM 22.1.8, 256 bits)'
                Path(str(frames[0]) + '.json').write_text(json.dumps({'adapter': adapter}))
            logs = {role: root / (role + '.log') for role in f.source.ROLES}
            logs['windows-legacy'].write_text('GL capture log\n')
            prefix = ['renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver',
                      'renderer dx12_shader_compiler=Fxc']
            def check(value):
                logs['dx12'].write_text('\n'.join([*prefix, 'renderer device_evidence=' + json.dumps(value)]))
                return f._runtime_identity(f.source.BoundSourcePacket(), logs, native, bound)
            self.assertEqual(check(device)['dx12']['adapter'], native['adapter'])
            for mode in (None, 'Immediate', 'Mailbox'):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'windowed fallback'):
                    check({**device, 'present_mode': mode})
            for fallback in (False, None, 1, 'true'):
                with self.subTest(fallback=fallback), self.assertRaisesRegex(ValueError, 'windowed fallback'):
                    check({**device, 'force_fallback_requested': fallback})
            for field in ('present_mode', 'force_fallback_requested'):
                incomplete = dict(device); del incomplete[field]
                with self.subTest(missing=field), self.assertRaisesRegex(ValueError, 'windowed fallback'):
                    check(incomplete)
            Path(str(bound._frames['dx12'][0]) + '.json').write_text(json.dumps({'adapter': 'different GPU'}))
            fresh = f.source.BoundSourcePacket()
            fresh.capture_binding, fresh._frames = bound.capture_binding, bound._frames
            bound = fresh
            with self.assertRaisesRegex(ValueError, 'capture/native adapter'):
                check(device)

    def test_finite_type_rejects_out_of_scope_and_boolean_coercion(self):
        profile = f.BoundFiniteAdsProfile(None, self.ledger, self.descriptor, 'a' * 64, {},
                                        {role: {} for role in f.source.ROLES}, {}, 'C:/source')
        with self.assertRaisesRegex(ValueError, 'outside reviewed'):
            profile.verify_frame_binding(Path('unbound.png'), 'dx12', 552)
        with self.assertRaises(TypeError):
            bool(profile)
        self.assertFalse(profile.native_profile_binding_verified)
        self.assertIsNone(profile.acceptance_verdict)


if __name__ == '__main__':
    unittest.main()
