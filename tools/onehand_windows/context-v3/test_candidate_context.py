"""Synthetic metadata only. No held Action payload, source transform or private geometry."""
import atexit
import builtins
import shutil
import copy
from dataclasses import replace
import hashlib
import importlib.machinery
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock
import candidate_context as c
import addon_resolver as addons
import production_assembler as production
from pinned_assembler import load_assembler, PINS
from pinned_transport import load_verifier, load_integrity_reader
HERE = Path(__file__).absolute().parent
PUBLISHED = HERE.parent / 'published-pr77/tools/onehand_windows'
WORKSPACE = PUBLISHED / 'audited'
ASSEMBLER = WORKSPACE / 'onehand-runtime-20261016-r2/runtime-conversion-v2'
TOOLS = WORKSPACE / 'onehand-runtime-20261016/importer-patch/tools'
TEST_ROOT = HERE / 'fixture-results'
TEST_ROOT.mkdir(exist_ok=True)
atexit.register(lambda: shutil.rmtree(TEST_ROOT) if TEST_ROOT.exists() else None)
ORIGINAL_MKDTEMP = tempfile.mkdtemp

def tmp():
    return Path(ORIGINAL_MKDTEMP(prefix='fixture-', dir=TEST_ROOT))

def synthetic_context(root):
    private = root / 'private'; candidate = private / 'session-one' / 'candidates' / 'candidate-one'
    roots = {name: str(root / ('root-' + name)) for name in c.ROOT_ROLES}
    files = {}
    for role in c.ALL_FILES:
        path = candidate / (role + '.bin') if role in c.OUTPUT_INPUT_ROLES | c.BLOCK_ROLES else root / (role + '.bin')
        if role.startswith('reference_'): path = Path(roots['reference']) / (role + '.json')
        if role.startswith('block_'):
            index = role.split('_')[1]
            path = candidate / ('block-' + index) / ('frames.bin' if role.endswith('_frames') else 'receipt.json')
        files[role] = {'path': str(path), 'sha256': hashlib.sha256(role.encode()).hexdigest()}
    for role, expected in {'baseline': c.BASE_SHA, 'original_delta': c.DELTA_SHA,
                            'canonical': c.CANONICAL_SHA, 'source_grid': c.GRID_SHA}.items(): files[role]['sha256'] = expected
    return {'schema': c.SCHEMA, 'mode': c.MODE, 'candidate_id': 'candidate-one', 'session_id': 'session-one',
            'private_root': str(private), 'roots': roots, 'files': files,
            'host': {'runner_id': 'fixture-runner', 'run_id': 'fixture-run', 'system': 'Windows',
                     'release': 'fixture-release', 'version': 'fixture-build', 'machine': 'AMD64',
                     'build_sha256': files['host_binding']['sha256']},
            'lineage': {'approved_source_sha256': c.APPROVED_SHA, 'source_package_pins_sha256': c.SOURCE_PINS_SHA,
                        'action_hashes': {name: hashlib.sha256(name.encode()).hexdigest()
                                          for name in ('legacy', 'complete', 'metadata', 'auxiliary')},
                        'static_state_sha256': 'd' * 64}, 'invariants': copy.deepcopy(c.INVARIANTS)}

def synthetic_authored(ctx):
    data = {'schema': 'rust-duty-onehand-authored-input-bridge/v2', 'authored_input_admitted': True,
            'source_relation': 'exact authored motion and structured state; explicit nine-key comment exclusion',
            'approved_source_sha256': c.APPROVED_SHA, 'generated_source_sha256': ctx.pin('generated_source').sha256,
            'baseline_sha256': c.BASE_SHA, 'delta_sha256': c.DELTA_SHA, 'canonical_sha256': c.CANONICAL_SHA,
            'source_package_pins_sha256': c.SOURCE_PINS_SHA, 'bridge_sha256': c.BRIDGE_SHA,
            'reference_replay_sha256': ctx.pin('reference_replay').sha256,
            'reference_witness_index_sha256': ctx.pin('reference_index').sha256,
            'reference_source_equivalence_sha256': ctx.pin('reference_equivalence').sha256,
            'reference_generated_source_sha256': '9' * 64, 'target_replay_sha256': ctx.pin('target_replay').sha256,
            'action_hashes': dict(ctx.action_hashes), 'static_state_sha256': ctx.static_state_sha256,
            'metadata_projection': c.metadata_projection_binding(dict(ctx.action_hashes)['metadata']),
            'prior_actions_preserved': 88, 'result_action_count': 89, 'original_scalar_corrections': 12,
            'unchanged_driven_outputs': 4, 'reference_samples': 4240, 'reference_chunk_pairs': 17,
            'required_next_gate': 'Explicit distinct-source runtime contract and actual Windows all-grid/offkey proof',
            'limits': ['Admission is conditional on authentic externally pinned native replay/reference evidence.',
                       'Receipts do not cryptographically attest the host or prove a native process ran.',
                       'Only preservation categories covered by the frozen source producer are asserted.',
                       'No cross-platform evaluated numeric equality follows from matching authored data.',
                       'Do not substitute this generated source into an approved-source receipt.',
                       'No current Linux FBX/VRA equivalence or art acceptance is inferred.']}
    data.update({name: False for name in ('source_byte_identity_with_approved',
        'target_evaluated_source_equivalence_proved', 'cross_platform_float64_equality_proved',
        'windows_execution_proved', 'runtime_equivalence_proved', 'activation_authorized', 'private_assets_copied_or_uploaded')})
    return data

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.root = tmp(); self.data = synthetic_context(self.root); self.ctx = c.ProofContext.parse(self.data)
    def reject(self, pattern='.'):
        with self.assertRaisesRegex(c.ContextError, pattern): c.ProofContext.parse(self.data)
    def test_round_trip_and_stable_binding(self):
        self.assertEqual(self.ctx.record(), self.data)
        self.assertEqual(c.ProofContext.parse(self.ctx.record()), self.ctx)
        self.assertEqual(self.ctx.context_sha256, c.digest(self.data))
        self.assertNotEqual(self.ctx.binding_sha256, self.ctx.context_sha256)
    def test_unknown_fields_fail(self):
        self.data['accepted'] = True; self.reject('unknown')
    def test_unknown_roles_fail(self):
        self.data['files']['approved_raw_source'] = self.data['files']['generated_source']; self.reject('unknown')
    def test_missing_admission_pin_fails(self):
        del self.data['files']['authored_admission']; self.reject('missing')
    def test_unsupported_candidate_mode_fails(self):
        self.data['mode'] = 'existing-current-bytes'; self.reject('mode')
    def test_generated_identity_cannot_be_approved(self):
        self.data['files']['generated_source']['sha256'] = c.APPROVED_SHA; self.reject('launder')
    def test_generated_identity_cannot_be_baseline(self):
        self.data['files']['generated_source']['sha256'] = c.BASE_SHA; self.reject('launder')
    def test_role_alias_fails(self):
        self.data['files']['actual_fbx']['path'] = self.data['files']['generated_source']['path']; self.reject('alias')
    def test_case_alias_fails(self):
        self.data['files']['actual_fbx']['path'] = self.data['files']['generated_source']['path'].upper(); self.reject('alias')
    def test_hardlink_alias_fails(self):
        a = Path(self.data['files']['generated_source']['path']); a.parent.mkdir(parents=True); a.write_bytes(b'not source geometry')
        Path(self.data['files']['actual_fbx']['path']).hardlink_to(a); self.reject('hardlinked')
    def test_foreign_candidate_fails(self):
        self.data['files']['actual_fbx']['path'] = self.data['files']['actual_fbx']['path'].replace('candidate-one', 'candidate-two'); self.reject('foreign candidate')
    def test_foreign_session_fails(self):
        self.data['session_id'] = 'another-session'; self.reject('foreign candidate')
    def test_unknown_host_field_fails(self):
        self.data['host']['windows_proved'] = True; self.reject('unknown')
    def test_linux_host_cannot_be_windows(self):
        self.data['host']['system'] = 'Linux'; self.reject('target host')
    def test_malformed_pin_fails(self):
        self.data['files']['authored_admission']['sha256'] = 'ABC' * 21; self.reject('SHA256')
    def test_relative_root_fails(self):
        self.data['roots']['tools'] = '../tools'; self.reject('absolute')
    def test_symlink_root_fails(self):
        target = self.root / 'target'; target.mkdir(); Path(self.data['roots']['tools']).symlink_to(target); self.reject('symlink/reparse')
    def test_reparse_point_fails(self):
        actual = Path.lstat; root = self.root
        def lstat(path):
            result = actual(path)
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400) if path == root else result
        with mock.patch.object(Path, 'lstat', lstat): self.reject('reparse')
    def test_block_pair_location_fails(self):
        self.data['files']['block_01_frames']['path'] += '.other'; self.reject('accompany')
    def test_original_invariants_cannot_change(self):
        for key, value in [('source_samples', 4239), ('subdivisions', 64), ('runtime_keys', 24320), ('block_count', 11), ('native_fps', 30), ('matrix_position_strict_max', .001)]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.data); changed['invariants'][key] = value
                with self.assertRaises(c.ContextError): c.ProofContext.parse(changed)
    def test_bool_does_not_impersonate_count(self):
        self.data['invariants']['native_first_frame'] = True; self.reject('differs')
    def test_absent_payloads_are_blocked(self):
        with self.assertRaises((c.ContextError, FileNotFoundError)): self.ctx.verify_files()
    def test_authored_schema_validation_is_not_execution(self):
        data = synthetic_authored(self.ctx); self.assertEqual(self.ctx.validate_authored_receipt(data), data)
        self.assertFalse(data['windows_execution_proved'])
        with self.assertRaises((c.ContextError, FileNotFoundError)): self.ctx.verify_files()
    def test_authored_cross_platform_claim_rejected(self):
        data = synthetic_authored(self.ctx); data['cross_platform_float64_equality_proved'] = True
        with self.assertRaisesRegex(c.ContextError, 'cross_platform'): self.ctx.validate_authored_receipt(data)
    def test_authored_mixed_candidate_rejected(self):
        data = synthetic_authored(self.ctx); data['generated_source_sha256'] = '5' * 64
        with self.assertRaisesRegex(c.ContextError, 'generated_source'): self.ctx.validate_authored_receipt(data)
    def test_authored_unknown_payload_rejected(self):
        data = synthetic_authored(self.ctx); data['private_geometry'] = []
        with self.assertRaisesRegex(c.ContextError, 'unknown'): self.ctx.validate_authored_receipt(data)
    def test_process_binding_identity(self):
        record = self.ctx.process_binding({'SystemRoot': 'C:\\Windows'})
        self.assertEqual(record['context_sha256'], self.ctx.context_sha256)
        self.assertEqual(record['expected_host']['system'], 'Windows')
        self.assertEqual(record['owner_lock'], str(self.ctx.owner_lock))
        self.assertNotIn('windows_execution_proved', record)
    def test_prerequisite_mixed_identity_fails_before_read(self):
        value = {'schema': 'rust-duty-windows-production-prerequisites/v1', 'candidate_binding_sha256': '0' * 64,
                 'same_platform_only': True, 'cross_platform_float64_equality_proved': False, 'control': {}, 'focus': {}}
        with self.assertRaisesRegex(c.ContextError, 'candidate binding'): production.verify_prerequisites(self.ctx, value)
    def test_production_rejects_current_non_windows_host(self):
        if sys.platform == 'win32': self.skipTest('not the non-Windows negative test')
        with self.assertRaisesRegex(c.ContextError, 'actual 64-bit Windows'): production.assemble_production(self.ctx)
        self.assertFalse(self.ctx.runtime_output.exists())
    def test_windows_alias_components_rejected(self):
        for suffix in ('CON', 'actual_fbx.bin:stream', 'actual_fbx.bin ', 'actual_fbx.bin.'):
            changed = copy.deepcopy(self.data)
            changed['files']['actual_fbx']['path'] = str(self.ctx.candidate_root / suffix)
            with self.subTest(suffix=suffix), self.assertRaisesRegex(c.ContextError, 'ambiguous Windows'):
                c.ProofContext.parse(changed)
    def test_context_record_cannot_mutate_original_invariants(self):
        data = self.ctx.record(); data['invariants']['focus_frames'][0] = 0
        self.assertEqual(c.INVARIANTS['focus_frames'][0], 55.65625)
    def test_exclusive_owner_keeps_foreign_lock(self):
        self.ctx.owner_lock.parent.mkdir(parents=True)
        self.ctx.owner_lock.write_bytes(b'foreign owner')
        with self.assertRaises(FileExistsError):
            with production.exclusive_owner(self.ctx): self.fail('entered foreign lock')
        self.assertEqual(self.ctx.owner_lock.read_bytes(), b'foreign owner')
    def test_exclusive_owner_releases_only_own_lock(self):
        self.ctx.owner_lock.parent.mkdir(parents=True)
        with production.exclusive_owner(self.ctx): self.assertTrue(self.ctx.owner_lock.is_file())
        self.assertFalse(self.ctx.owner_lock.exists())
    def test_exclusive_owner_preserves_changed_lock(self):
        self.ctx.owner_lock.parent.mkdir(parents=True)
        with self.assertRaisesRegex(c.ContextError, 'foreign replacement'):
            with production.exclusive_owner(self.ctx): self.ctx.owner_lock.write_bytes(b'replaced')
        self.assertEqual(self.ctx.owner_lock.read_bytes(), b'replaced')
    def test_transport_readonly_verifier_pin_and_missing_evidence(self):
        verifier = load_integrity_reader(HERE.parent / 'context-historical-test-inputs/process-v1')
        with self.assertRaises((FileNotFoundError, ValueError, RuntimeError)): verifier(self.root, require_completed=True)

    def test_focus_preserves_strict_bounds_and_coverage(self):
        report = {'source_sha256': self.ctx.pin('generated_source').sha256,
                  'fbx_sha256': self.ctx.pin('actual_fbx').sha256, 'sample_frames': list(c.FOCUS),
                  'samples': 9, 'skin_vertex_samples': 92106, 'passed': True,
                  'sample_grid_sha256': '5ca9e5d361df01ceb384450cf1ef5d3602aaae98a173d24a996ef5675fb37b11',
                  'independent_grid_sha256': c.GRID_SHA,
                  'checks': {key: True for key in production.FOCUS_CHECKS},
                  'maxima': {key: 0.0 for key in production.MAXIMA}, 'camera_projection_ray_error': 0.0}
        self.assertIs(production.verify_focus_report(self.ctx, report), report)
        for key, value in [('samples', 8), ('skin_vertex_samples', 92105),
                           ('camera_projection_ray_error', 1e-5), ('camera_projection_ray_error', float('nan'))]:
            changed = copy.deepcopy(report); changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(c.ContextError):
                production.verify_focus_report(self.ctx, changed)
        for maximum in (1e-4, -1e-8, float('inf')):
            changed = copy.deepcopy(report); changed['maxima']['bone_deformation_world_matrix'] = maximum
            with self.subTest(maximum=maximum), self.assertRaises(c.ContextError):
                production.verify_focus_report(self.ctx, changed)
        changed = copy.deepcopy(report); changed['checks']['single_native_clock'] = False
        with self.assertRaises(c.ContextError): production.verify_focus_report(self.ctx, changed)

    def test_review_denied_transport_cannot_admit_production(self):
        package = HERE.parent / 'context-historical-test-inputs/process-v1'
        with self.assertRaisesRegex(c.ContextError, 'transport v1 blocked'):
            load_verifier(package)
        with mock.patch.object(c.HostBuildBinding, 'require_current_host'), \
             mock.patch.object(production, 'exclusive_owner', side_effect=AssertionError('must not acquire')):
            with self.assertRaisesRegex(c.ContextError, 'transport v1 blocked'):
                production.assemble_production(self.ctx)

    def test_original_grid_is_hash_pinned_without_reconstruction(self):
        path = PUBLISHED / 'source-producer-privacy-v1/dense-times.json'
        self.assertEqual(c.file_sha(path), c.GRID_SHA); values = c.strict_json(path)
        self.assertEqual(len(values), 4240); self.assertTrue(all(a < b for a, b in zip(values, values[1:])))
        self.assertEqual((values[0], values[-1]), (1, 96))

class AddonTests(unittest.TestCase):
    def setUp(self):
        from test_windows_addon_profile import fixture, SOURCE
        self.bundle = tmp(); self.root, self.pins = fixture(self.bundle); self.source = SOURCE
    def test_synthetic_logical_resolution(self):
        result = addons._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)
        self.assertEqual(result['import_fbx.py'], self.root / 'import_fbx.py')
    def test_changed_newlines_fail_exact_bytes(self):
        (self.root / 'import_fbx.py').write_bytes(self.source.replace(b'\r\n', b'\n'))
        with self.assertRaisesRegex(c.ContextError, 'exact bytes'): addons._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)
    def test_function_hash_cannot_be_relaxed(self):
        self.pins['raw_functions_sha256']['import_fbx.py']['audited'] = '0' * 64
        with self.assertRaisesRegex(c.ContextError, 'function source'): addons._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)
    def test_path_escape_rejected(self):
        with self.assertRaisesRegex(c.ContextError, 'unsafe logical'): addons._resolve(self.bundle, '../io_scene_fbx', self.pins)
    def test_symlink_file_rejected(self):
        target = self.root / 'import_fbx.py'; moved = self.bundle / 'moved.py'; target.rename(moved); target.symlink_to(moved)
        with self.assertRaisesRegex(c.ContextError, 'symlink'): addons._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)
    def test_official_reconstructed_windows_bytes_and_function_pins(self):
        from test_reconstruction_and_preservation import reconstructed_bundle
        bundle, _ = reconstructed_bundle(self.bundle / 'official')
        result = addons.resolve_addon(bundle, 'scripts/io_scene_fbx')
        self.assertEqual(len(result), 10)
        self.assertEqual(len(addons.official_pins()['raw_functions_sha256']['import_fbx.py']), 2)
    def test_shadow_module_rejected_without_importing_blender(self):
        from test_reconstruction_and_preservation import reconstructed_bundle
        bundle, _ = reconstructed_bundle(self.bundle / 'official')
        files = addons.resolve_addon(bundle, 'scripts/io_scene_fbx')
        shadow = ModuleType('io_scene_fbx'); shadow.__file__ = str(self.root / 'import_fbx.py')
        shadow.__spec__ = importlib.machinery.ModuleSpec('io_scene_fbx', None, origin=shadow.__file__)
        with self.assertRaisesRegex(c.ContextError, 'shadow addon'): addons.verify_loaded_modules(files, {'io_scene_fbx': shadow})

class AssemblerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.assembler = load_assembler(ASSEMBLER, TOOLS)
    def test_generated_production_contract_keeps_original_layout(self):
        ctx = c.ProofContext.parse(synthetic_context(tmp())); old = self.assembler.PRODUCTION_CONTRACT
        contract = production.production_contract(ctx, self.assembler)
        self.assertEqual((contract.source_sha256, contract.fbx_sha256), (ctx.pin('generated_source').sha256, ctx.pin('actual_fbx').sha256))
        self.assertEqual((contract.bone_count, contract.actor_count, contract.last_tick, contract.ticks_per_second,
                          contract.block_count, contract.frame_bytes, contract.max_transforms, contract.max_file_bytes),
                         (72, 3, 24320, 15360, 12, 3007, 2000000, 128 * 1024**2))
        self.assertEqual(old.source_sha256, c.APPROVED_SHA); self.assertIs(old, self.assembler.PRODUCTION_CONTRACT)
    def test_untrusted_helper_environment_and_modules_cannot_shadow(self):
        hostile = ModuleType('vrview')
        with mock.patch.dict(sys.modules, {'vrview': hostile}), mock.patch.dict('os.environ', {'VRVIEW_TOOLS_PATH': '/missing/hostile'}):
            actual = load_assembler(ASSEMBLER, TOOLS)
        self.assertIsNot(actual.vrview, hostile); self.assertEqual(c.file_sha(actual.vrview.__file__), PINS['vrview'])
    def test_explicit_generated_identity_with_unchanged_small_stream(self):
        fixture = fixture_module().Fixture()
        assembler = fixture.run.__globals__['assembler']
        old = assembler.PRODUCTION_CONTRACT
        source, fbx = '3' * 64, '4' * 64
        fixture.contract = replace(fixture.contract, source_sha256=source, fbx_sha256=fbx)
        for record in [fixture.metadata, *fixture.receipts]:
            record['source_sha256'] = source; record['fbx_sha256'] = fbx
            admission = record['window_admission']; admission['fbx_sha256'] = fbx
            admission['full_raw_admission']['fbx_sha256'] = fbx
            admission['full_raw_admission_sha256'] = assembler._json_digest(admission['full_raw_admission'])
        fixture.sync_metadata()
        report = fixture.run()
        self.assertEqual((report['source_sha256'], report['fbx_sha256']), (source, fbx))
        self.assertEqual(fixture.output_path.read_bytes(), fixture.expected())
        self.assertIs(assembler.PRODUCTION_CONTRACT, old)
        self.assertEqual(old.source_sha256, c.APPROVED_SHA)
        self.assertFalse(report['rust_parity_verified'])

    def test_wrong_assembler_bytes_rejected(self):
        package = tmp(); (package / 'assemble_runtime.py').write_text('raise AssertionError("must never run")\n')
        with self.assertRaisesRegex(c.ContextError, 'pin differs'): load_assembler(package, TOOLS)

def fixture_module():
    """Load unchanged tiny fixtures in an isolated verified namespace."""
    path = HERE.parent / 'context-historical-test-inputs/test_assemble_runtime.py'
    c.require(c.file_sha(path) == '5b6dce136fac5d681b96d87be74c703ded58dfee2de20fe9c615aeb720b97159', 'original fixture bytes differ')
    assembler = load_assembler(ASSEMBLER, TOOLS); module = ModuleType('_unchanged_assembler_fixture_tests')
    def imports(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'assemble_runtime': return assembler
        if name == 'tempfile': return SimpleNamespace(mkdtemp=lambda **kw: ORIGINAL_MKDTEMP(dir=TEST_ROOT, **kw))
        return builtins.__import__(name, globals, locals, fromlist, level)
    module.__builtins__ = {**vars(builtins), '__import__': imports}
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromTestCase(fixture_module().StreamAssemblyTests)); return tests

if __name__ == '__main__': unittest.main(verbosity=2)
