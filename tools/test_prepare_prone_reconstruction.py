"""Source-free fixtures only. No test imports bpy or starts a subprocess.

Synthetic BLEND bytes and caller process attestations test the acceptance gates;
they are deliberately not evidence of actual Blender reconstruction.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

import prepare_prone_reconstruction as guard

ROOT = Path(__file__).resolve().parent.parent
SOURCE_BYTES = b'SOURCE-FREE TEST INPUT; NOT A PRIVATE BLEND'
CANDIDATE_BYTES = b'SOURCE-FREE TEST CANDIDATE; NOT A BLEND'


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


class ProductionIdentityTests(unittest.TestCase):
    def test_exact_production_identity_constants(self):
        self.assertEqual(guard.MANIFEST_SHA256,
                         '6e8cc99c5f5e607facaa2f0f49ea63d467cdb4da68feca86c770a7885fe667e0')
        self.assertEqual(guard.INPUT_SHA256,
                         '67cf025fc31d9804cb0259432a91e496d7d8f84d1d4ac6be2b1914a6a98510ad')
        self.assertEqual(guard.HISTORICAL_SIDECAR,
                         '19098b693b94a5a0b2421cff9dd25f5dda949506be87bc76eb84dfe23499fbfa')
        self.assertEqual(guard.CONTRACT_COMMIT, '659fd15ec77a7b4df5018bc7c86a54deace5333e')
        self.assertEqual(guard.INPUT_COMMIT, '9c5da4a2bb9920ce65390abfd7c287116d369e8a')
        self.assertEqual(guard.EXPECTED_ACTIONS, {
            'prone_crawl_enter_r6': '2a860a55decb8f0fa06226f55a2ace85e9629a21b54ff827cb275b244da8d41f',
            'prone_crawl_enter_camera_r6': '7006eeec2a3a9c83ca6eec27290692db81554ecb219afc656f8da413aa311c82'})


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'input.blend'
        self.source.write_bytes(SOURCE_BYTES)
        self.work = self.root / 'private-work'
        self.config = self.root / 'historical.json'
        config = json.loads((ROOT / 'tools' / 'prone_pair_r6_export.json').read_text())
        config['camera_sidecar_sha256'] = guard.HISTORICAL_SIDECAR
        write(self.config, config)
        self.real_hash = guard.file_hash
        patcher = mock.patch.object(guard, 'INPUT_SHA256', self.real_hash(self.source))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.contract = self.root / 'synthetic-contract'
        self.build_contract()
        patcher = mock.patch.object(guard, 'MANIFEST_SHA256',
                                    self.real_hash(self.contract / 'SHA256SUMS'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def build_contract(self):
        """Original synthetic rigid matrices/reports; no external snapshot needed."""
        self.contract.mkdir()

        def matrix(z):
            return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, z], [0, 0, 0, 1]]

        rows = []
        for i in range(545):
            depth = 1.3 * i / 544
            rows.append({'candidate_frame': 1 + i / 8, 'time_seconds': i / 480,
                         'camera_world': matrix(1.6 - depth),
                         'common_world_delta': matrix(-depth),
                         'height_above_source_ground_m': 1.6 - depth,
                         'normalized_depth_fraction': depth / 1.26})
        write(self.contract / 'camera_motion_samples.json', {
            'schema': 'prone-entry-r6-camera-motion/v1',
            'candidate_sha256': guard.HISTORICAL_CANDIDATE,
            'action_fingerprints': guard.EXPECTED_ACTIONS,
            'units': 'metres and radians; Blender world +Z up',
            'camera_local_axes': '+X right, +Y up, -Z forward',
            'initial_camera_world': matrix(1.6), 'sample_hz': 480, 'fps': 60,
            'duration_key_span_seconds': 68 / 60, 'rows': rows})
        write(self.contract / 'frame_map.json', {
            'source_commit': guard.INPUT_COMMIT, 'blend_sha256': guard.HISTORICAL_CANDIDATE,
            'actions': guard.EXPECTED_ACTIONS, 'required_bindings': {
                'Arms': 'prone_crawl_enter_r6', 'RD First Person Review': 'prone_crawl_enter_camera_r6'},
            'fps': 60, 'capture_status': 'Not captured', 'reference_sha256': 'b' * 64,
            'rows': [{'output_index': i, 'candidate_frame': i + 1, 'reference_native_frame': 2241 + i}
                     for i in range(69)]})
        write(self.contract / 'correction_design.json', {
            'source_sha256': guard.INPUT_SHA256, 'source_commit': guard.INPUT_COMMIT})
        write(self.contract / 'fresh_reopen_checks.json', {'summary': {
            'candidate_sha256': guard.HISTORICAL_CANDIDATE, 'actions': guard.EXPECTED_ACTIONS,
            'action_count': 114, 'sample_count': 545,
            'fresh_reopen_preservation': {k: True for k in guard.PRESERVATION},
            'protected_f1_to_11_all_bone_max_difference': 0,
            'all_bone_matrices_finite': True, 'all_drivers_valid': True,
            'contact_480hz_max_m': {'l': .000002, 'r': .000001},
            'old_wrist_guard_max_deg': {'l': 6.5, 'r': 0},
            'new_wrist_guard_max_deg': {'l': .76, 'r': 0},
            'strict_wrist_guard_threshold_deg': .08, 'strict_wrist_guard_pass': False,
            'wrist_guard_non_regression_pass': True, 'max_wrist_guard_increase_deg': {'l': 0, 'r': 0},
            'min_camera_height_above_ground_m': min(r['height_above_source_ground_m'] for r in rows),
            'max_optic_projection_error_px': .0008, 'finite_evaluated_vertex_samples': 1046760,
            'ground_intersection_probes': [{'frame': f, 'counts': {n: 0 for n in guard.PROBE_OBJECTS}}
                                           for f in guard.PROBE_FRAMES],
            'no_render': True, 'visual_pass': None}})
        write(self.contract / 'capture_pair_checks.json', {
            'checks': {k: True for k in guard.CAPTURE_CHECKS}, 'rendered': False, 'frames_exercised': 69})
        for name in ('revise_entry.py', 'verify_revision.py', 'test_capture_pair.py', 'capture_pair.py'):
            (self.contract / name).write_text('# Original synthetic fixture. Never execute.\n')
        (self.contract / 'SHA256SUMS').write_text(''.join(
            self.real_hash(p) + '  ' + p.name + '\n' for p in sorted(self.contract.iterdir())))

    def prepare(self):
        return guard.prepare(self.contract, self.source, self.work, self.config,
                             '/local/Blender 4.3.2/blender')

    def fixture(self):
        # Give synthetic process intervals room in the past; no sleeps and no
        # assumption that Windows/filesystem mtimes retain single nanoseconds.
        now = time.time_ns()
        with mock.patch.object(guard.time, 'time_ns', return_value=now - 60_000_000_000):
            plan = self.prepare()
        recipe = self.work / 'execution'
        candidate = hashlib.sha256(CANDIDATE_BYTES).hexdigest()
        (recipe / guard.CANDIDATE).write_bytes(CANDIDATE_BYTES)
        fm = guard.read_json(self.contract / 'frame_map.json')
        fm['blend_sha256'] = candidate
        write(recipe / 'frame_map.json', fm)
        sidecar = guard.read_json(self.contract / 'camera_motion_samples.json')
        sidecar['candidate_sha256'] = candidate
        write(recipe / 'camera_motion_samples.json', sidecar)
        summary = guard.read_json(self.contract / 'fresh_reopen_checks.json')['summary']
        summary['candidate_sha256'] = candidate
        rows, author, contact = [], [], []
        for i, motion in enumerate(sidecar['rows']):
            frame = 1 + i / 8
            row = {'frame': frame, 'camera_world': motion['camera_world'],
                   'common_world_delta': motion['common_world_delta'],
                   'camera_height_above_ground': motion['height_above_source_ground_m'],
                   'camera_z': motion['camera_world'][2][3],
                   'wrist_guard_degrees': summary['new_wrist_guard_max_deg'],
                   'optic_target_error_px': summary['max_optic_projection_error_px'],
                   'projected_guides': {'optic': [0, 0]}}
            if frame in guard.PROBE_FRAMES:
                row['onscreen_vertices_below_ground'] = {n: 0 for n in guard.PROBE_OBJECTS}
            rows.append(row)
            author.append({'frame': frame, 'camera_world': motion['camera_world'], 'optic_target_pixels': [0, 0]})
            contact.append({'frame': frame, 'error_m': summary['contact_480hz_max_m']})
        write(recipe / 'fresh_reopen_checks.json', {'summary': summary, 'rows': rows})
        snapshot = {k: {} for k in guard.SNAPSHOT}
        snapshot['actions'] = {f'fixture_prior_{i}': 'a' * 64 for i in range(112)}
        write(recipe / 'baseline_preservation.json', {'snapshot': snapshot,
              'extra': {k: {} for k in guard.EXTRA}, 'scene': {'frame_start': 1},
              'object_defaults': {'fixture_object': {}}})
        write(recipe / 'revision_report.json', {'source_sha256': guard.INPUT_SHA256,
              'candidate_sha256': candidate, 'actions': list(guard.EXPECTED_ACTIONS),
              'rendered': False, 'visual_pass': None, 'protected_f1_to_11_all_bone_difference': 0,
              'checks': {k: True for k in guard.AUTHOR_CHECKS}, 'rows': author,
              'contact_maxima_480hz_m': summary['contact_480hz_max_m']})
        write(recipe / 'contact_precheck.json', {'rows': contact, 'maxima_m': summary['contact_480hz_max_m']})
        (recipe / 'capture_pair_checks.json').write_bytes((self.contract / 'capture_pair_checks.json').read_bytes())
        evidence = guard.read_json(self.work / 'process_results.template.json')
        for i, stage in enumerate(evidence['stages']):
            log = Path(stage['log'])
            log.write_text('SOURCE-FREE SYNTHETIC PROCESS ATTESTATION; NO BLENDER EXECUTED\n')
            stage['returncode'] = 0
            stage['log_sha256'] = self.real_hash(log)
            for name in stage['artifacts']:
                stage['artifacts'][name] = self.real_hash(recipe / name)
            paths = [log] + [recipe / name for name in stage['artifacts']]
            stamp = ((now // 1_000_000_000) - 30 + 5 * i) * 1_000_000_000
            for path in paths:
                os.utime(path, ns=(stamp, stamp))
            observed = [path.stat().st_mtime_ns for path in paths]
            stage['started_at_ns'] = min(observed) - 1
            stage['finished_at_ns'] = max(observed) + 1
        self.evidence = self.work / 'process_results.json'
        write(self.evidence, evidence)
        return plan, evidence

    def accept(self):
        return guard.accept(self.work, self.evidence)

    def alter_report(self, name, mutate):
        path = self.work / 'execution' / name
        value = guard.read_json(path)
        mutate(value)
        write(path, value)
        # Re-sign this synthetic stage's artifact so the semantic gate is tested.
        evidence = guard.read_json(self.evidence)
        stage = next(s for s in evidence['stages'] if name in s['artifacts'])
        stage['artifacts'][name] = self.real_hash(path)
        stamp = stage['finished_at_ns'] - 1
        os.utime(path, ns=(stamp, stamp))
        write(self.evidence, evidence)

    def test_manifest_byte_exact_and_source_not_copied(self):
        self.prepare()
        self.assertEqual(guard.verify_manifest(self.contract), guard.verify_manifest(self.work / 'immutable'))
        for p in self.contract.iterdir():
            self.assertEqual(p.read_bytes(), (self.work / 'immutable' / p.name).read_bytes())
        for name in guard.GENERATED:
            self.assertFalse((self.work / 'execution' / name).exists())
        self.assertFalse(list(self.work.rglob('*.blend')))
        if os.name == 'posix':
            self.assertEqual(self.work.stat().st_mode & 0o777, 0o700)

    def test_manifest_newline_drift_rejected(self):
        contract = self.root / 'changed-contract'
        shutil.copytree(self.contract, contract)
        p = contract / 'camera_motion_samples.json'
        p.write_bytes(p.read_bytes() + b'\n')
        with self.assertRaisesRegex(guard.ReconstructionError, 'Immutable contract bytes changed'):
            guard.verify_manifest(contract)

    def test_rewritten_manifest_cannot_repin_contract(self):
        contract = self.root / 'changed-contract'
        shutil.copytree(self.contract, contract)
        p = contract / 'SHA256SUMS'
        p.write_bytes(p.read_bytes() + b'\n')
        with self.assertRaisesRegex(guard.ReconstructionError, 'Manifest anchor mismatch'):
            guard.verify_manifest(contract)

    def test_unmanifested_or_symlink_contract_rejected(self):
        contract = self.root / 'changed-contract'
        shutil.copytree(self.contract, contract)
        (contract / 'unexpected.blend').write_bytes(b'no private source')
        with self.assertRaises(guard.ReconstructionError):
            guard.verify_manifest(contract)
        (contract / 'unexpected.blend').unlink()
        p = contract / 'frame_map.json'
        original = Path.is_symlink
        # Windows may require elevated privileges to create actual symlinks.
        with mock.patch.object(Path, 'is_symlink', lambda path: path == p or original(path)):
            with self.assertRaises(guard.ReconstructionError):
                guard.verify_manifest(contract)

    def test_source_hash_and_existing_work_rejected(self):
        self.source.write_bytes(b'wrong input')
        with self.assertRaisesRegex(guard.ReconstructionError, 'r5 input hash'):
            self.prepare()
        self.source.write_bytes(SOURCE_BYTES)
        self.prepare()
        with self.assertRaisesRegex(guard.ReconstructionError, 'already exists'):
            self.prepare()

    def test_exact_commands_disable_autoexec_before_source(self):
        plan = self.prepare()
        self.assertEqual([x['stage'] for x in plan['commands']], list(guard.STAGES))
        for command in plan['commands']:
            argv = command['argv']
            self.assertEqual(argv[1:4], ['--background', '--factory-startup', '--disable-autoexec'])
            self.assertEqual(argv[5:8], ['--python-exit-code', '1', '--python'])
            self.assertEqual(command['cwd'], str(self.work / 'execution'))
        self.assertIn("'/local/Blender 4.3.2/blender'", (self.work / 'commands.txt').read_text())

    def test_missing_and_template_process_receipts_rejected(self):
        self.prepare()
        with self.assertRaises(guard.ReconstructionError):
            guard.accept(self.work, self.work / 'missing.json')
        with self.assertRaisesRegex(guard.ReconstructionError, 'did not succeed'):
            guard.accept(self.work, self.work / 'process_results.template.json')

    def test_failed_exit_despite_written_reports_rejected(self):
        _, evidence = self.fixture()
        evidence['stages'][1]['returncode'] = 1
        write(self.evidence, evidence)
        with self.assertRaisesRegex(guard.ReconstructionError, 'did not succeed'):
            self.accept()
        self.assertFalse((self.work / 'accepted').exists())

    def test_stale_run_and_missing_stage_rejected(self):
        _, evidence = self.fixture()
        for bad in [dict(evidence, run_id='different-run'), dict(evidence, stages=evidence['stages'][:-1])]:
            write(self.evidence, bad)
            with self.assertRaises(guard.ReconstructionError):
                self.accept()

    def test_wrong_command_or_log_hash_rejected(self):
        _, evidence = self.fixture()
        bad = copy.deepcopy(evidence)
        bad['stages'][0]['argv'].remove('--disable-autoexec')
        write(self.evidence, bad)
        with self.assertRaisesRegex(guard.ReconstructionError, 'command/cwd/log'):
            self.accept()
        evidence['stages'][1]['log_sha256'] = '0' * 64
        write(self.evidence, evidence)
        with self.assertRaisesRegex(guard.ReconstructionError, 'process log'):
            self.accept()

    def test_stale_artifact_and_process_times_rejected(self):
        plan, evidence = self.fixture()
        p = self.work / 'execution' / 'fresh_reopen_checks.json'
        os.utime(p, ns=(plan['prepared_at_ns'] - 1, plan['prepared_at_ns'] - 1))
        with self.assertRaisesRegex(guard.ReconstructionError, 'process output'):
            self.accept()
        evidence['stages'][0]['started_at_ns'] = plan['prepared_at_ns'] - 1
        write(self.evidence, evidence)
        with self.assertRaisesRegex(guard.ReconstructionError, 'process times'):
            self.accept()

    def test_wrong_expected_pair_rejected_even_consistently_replaced(self):
        self.fixture()
        self.alter_report('frame_map.json', lambda v: v['actions'].update(prone_crawl_enter_r6='f' * 64))
        self.alter_report('camera_motion_samples.json', lambda v: v['action_fingerprints'].update(prone_crawl_enter_r6='f' * 64))
        with self.assertRaisesRegex(guard.ReconstructionError, 'expected Action pair'):
            self.accept()

    def test_changed_frame_map_rejected(self):
        self.fixture()
        self.alter_report('frame_map.json', lambda v: v['rows'][5].update(reference_native_frame=999))
        with self.assertRaisesRegex(guard.ReconstructionError, 'Frame map differs'):
            self.accept()

    def test_boolean_cannot_replace_historical_frame_number(self):
        self.fixture()
        self.alter_report('frame_map.json', lambda v: v['rows'][0].update(candidate_frame=True, output_index=False))
        with self.assertRaisesRegex(guard.ReconstructionError, 'Frame map differs'):
            self.accept()

    def test_changed_motion_rejected(self):
        self.fixture()
        self.alter_report('camera_motion_samples.json', lambda v: v['rows'][200].update(normalized_depth_fraction=0))
        with self.assertRaisesRegex(guard.ReconstructionError, 'Camera sidecar differs'):
            self.accept()

    def test_partial_preservation_is_not_a_pass(self):
        self.fixture()
        self.alter_report('fresh_reopen_checks.json', lambda v: v['summary']['fresh_reopen_preservation'].pop('extra.meshes'))
        with self.assertRaisesRegex(guard.ReconstructionError, 'preservation'):
            self.accept()

    def test_missing_source_and_capture_restoration_checks_rejected(self):
        self.fixture()
        original = guard.read_json(self.work / 'execution' / 'revision_report.json')
        self.alter_report('revision_report.json', lambda v: v['checks'].pop('scene_fields'))
        with self.assertRaisesRegex(guard.ReconstructionError, 'author/source preservation'):
            self.accept()
        self.alter_report('revision_report.json', lambda v: v.update(original))
        self.alter_report('capture_pair_checks.json', lambda v: v['checks'].pop('camera_unbound'))
        with self.assertRaisesRegex(guard.ReconstructionError, 'capture/restoration'):
            self.accept()

    def test_strict_wrist_failure_cannot_be_hidden(self):
        self.fixture()
        self.alter_report('fresh_reopen_checks.json', lambda v: v['summary'].update(strict_wrist_guard_pass=True))
        with self.assertRaisesRegex(guard.ReconstructionError, 'strict wrist failure'):
            self.accept()

    def test_full_samples_and_actions_required(self):
        self.fixture()
        self.alter_report('fresh_reopen_checks.json', lambda v: v['rows'].pop())
        with self.assertRaisesRegex(guard.ReconstructionError, '545 fresh samples'):
            self.accept()

    def test_changed_recipe_input_and_candidate_bytes_rejected(self):
        self.fixture()
        path = self.work / 'execution' / 'verify_revision.py'
        original = path.read_bytes()
        path.write_bytes(original + b'\n')
        with self.assertRaisesRegex(guard.ReconstructionError, 'Execution recipe changed'):
            self.accept()
        path.write_bytes(original)
        self.source.write_bytes(b'changed original')
        with self.assertRaisesRegex(guard.ReconstructionError, 'Original input changed'):
            self.accept()
        self.source.write_bytes(SOURCE_BYTES)
        (self.work / 'execution' / guard.CANDIDATE).write_bytes(b'changed candidate')
        with self.assertRaisesRegex(guard.ReconstructionError, 'process output'):
            self.accept()

    def test_invalid_contact_driver_and_protected_pose_rejected(self):
        self.fixture()
        original = guard.read_json(self.work / 'execution' / 'fresh_reopen_checks.json')
        mutations = [lambda v: v['summary']['contact_480hz_max_m'].update(l=-.00001),
                     lambda v: v['summary'].update(all_drivers_valid=False),
                     lambda v: v['summary'].update(protected_f1_to_11_all_bone_max_difference=.001)]
        for mutation in mutations:
            self.alter_report('fresh_reopen_checks.json', lambda v: v.update(copy.deepcopy(original)))
            self.alter_report('fresh_reopen_checks.json', mutation)
            with self.assertRaises(guard.ReconstructionError):
                self.accept()

    def test_missing_source_baseline_sections_rejected(self):
        self.fixture()
        self.alter_report('baseline_preservation.json', lambda v: v['extra'].pop('meshes'))
        with self.assertRaisesRegex(guard.ReconstructionError, 'source baseline'):
            self.accept()

    def test_capture_must_exercise_all_69_frames(self):
        self.fixture()
        self.alter_report('capture_pair_checks.json', lambda v: v.update(frames_exercised=68))
        with self.assertRaisesRegex(guard.ReconstructionError, 'all 69'):
            self.accept()

    def test_private_work_directory_permission_check_is_posix_only(self):
        # Exercise both policy branches on every OS without creating WindowsPath
        # instances on POSIX or changing receipt/identity validation.
        for name, mode, expected in [('posix', 0o700, True), ('posix', 0o755, False),
                                     ('nt', 0o700, True), ('nt', 0o755, True)]:
            with mock.patch.object(guard.os, 'name', name):
                self.assertEqual(guard.private_mode_ok(mode), expected)
        self.fixture()
        self.work.chmod(0o755)
        if os.name == 'posix':
            with self.assertRaisesRegex(guard.ReconstructionError, 'remain private'):
                self.accept()
        else:
            self.assertEqual(self.accept()['status'], 'numerical_reconstruction_only')

    def test_success_separate_repin_keeps_historical_motion_and_wrist_failure(self):
        self.fixture()
        before = self.config.read_bytes()
        historical = guard.read_json(self.work / 'historical_export_config.json')
        receipt = self.accept()
        output = self.work / 'accepted'
        local = guard.read_json(output / 'prone_pair_r6_export.local.json')
        self.assertEqual({k for k in local if local[k] != historical[k]},
                         {'source_sha256', 'camera_sidecar_sha256'})
        self.assertEqual(local['action_fingerprints'], guard.EXPECTED_ACTIONS)
        self.assertEqual(local['source_contract_commit'], guard.CONTRACT_COMMIT)
        self.assertEqual((output / 'camera_motion_samples.json').read_bytes(),
                         (self.work / 'execution' / 'camera_motion_samples.json').read_bytes())
        self.assertEqual(before, self.config.read_bytes())
        self.assertFalse(receipt['strict_wrist_guard_pass'])
        self.assertGreater(receipt['new_wrist_guard_max_deg']['l'], .08)
        for key in ('rendered', 'art_approved', 'runtime_approved', 'export_approved'):
            self.assertIs(receipt[key], False)
        with self.assertRaisesRegex(guard.ReconstructionError, 'already exists'):
            self.accept()


if __name__ == '__main__':
    unittest.main()
