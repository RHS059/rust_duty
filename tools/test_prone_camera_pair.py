"""Original source-free fixtures for the actual paired-import functions."""
import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import import_fbx_viewmodel as importer
import prone_camera_pair as pair
import vrpack
import vrview


IDENTITY = vrpack.IDENTITY
CANDIDATE = b'original synthetic candidate bytes'
CANDIDATE_HASH = hashlib.sha256(CANDIDATE).hexdigest()
FINGERPRINTS = {pair.RIG_ACTION: 'a' * 64, pair.CAMERA_ACTION: 'b' * 64}


def translation(x, y, z):
    return (1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1)


def rows(matrix):
    return [list(matrix[i:i+4]) for i in range(0, 16, 4)]


def fixture():
    # C0 is translated and rotated: multiplication order matters. The camera
    # follows a simple independently constructed world-Z drop, with no assets.
    initial = (0, -1, 0, 3, 1, 0, 0, 2, 0, 0, 1, 5, 0, 0, 0, 1)
    samples = []
    for i in range(545):
        camera = list(initial)
        camera[11] = 5 - i/544
        samples.append({
            'candidate_frame': 1 + i/8,
            'time_seconds': i/480,
            'camera_world': rows(camera),
            'common_world_delta': rows(translation(0, 0, -i/544)),
        })
    return {
        'schema': pair.SIDECAR_SCHEMA,
        'candidate_sha256': CANDIDATE_HASH,
        'action_fingerprints': FINGERPRINTS.copy(),
        'units': 'metres and radians; Blender world +Z up',
        'camera_local_axes': '+X right, +Y up, -Z forward',
        'initial_camera_world': rows(initial),
        'sample_hz': 480, 'fps': 60,
        'duration_key_span_seconds': 68/60,
        'rows': samples,
    }


def load(document=None, **changes):
    data = json.dumps(fixture() if document is None else document).encode()
    kwargs = dict(expected_sidecar_sha256=hashlib.sha256(data).hexdigest(),
                  candidate_sha256=CANDIDATE_HASH, action_fingerprints=FINGERPRINTS.copy(),
                  native_start=0, native_end=68, fps=Fraction(60),
                  candidate_frame_offset=1, frames=importer.sample_grid(0, 68, 8, fps=Fraction(60))[0])
    kwargs.update(changes)
    return pair.load_camera_pair(data, **kwargs)


class CameraMatrixTests(unittest.TestCase):
    def assertMatrix(self, actual, expected):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=8)

    def test_nonidentity_initial_camera_correct_world_delta_order(self):
        initial = (0, -1, 0, 3, 1, 0, 0, 2, 0, 0, 1, 5, 0, 0, 0, 1)
        # D is a world Z quarter-turn plus translation, C = D*C0.
        delta = (0, -1, 0, 10, 1, 0, 0, 20, 0, 0, 1, -2, 0, 0, 0, 1)
        current = (-1, 0, 0, 8, 0, -1, 0, 23, 0, 0, 1, 3, 0, 0, 0, 1)
        self.assertMatrix(pair.common_world_delta(current, initial), delta)
        self.assertMatrix(pair.common_world_delta(initial, initial), IDENTITY)

    def test_removes_one_world_delta_before_basis_for_bones_and_actors(self):
        delta = (0, -1, 0, 10, 1, 0, 0, 20, 0, 0, 1, -2, 0, 0, 0, 1)
        # W = D*local with local translation (2,3,4); independently calculated.
        evaluated = (0, -1, 0, 7, 1, 0, 0, 22, 0, 0, 1, 2, 0, 0, 0, 1)
        normalized = pair.remove_common_motion(evaluated, delta)
        self.assertMatrix(normalized, translation(2, 3, 4))
        basis = (1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1)
        inverse_basis = (1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1)
        bone = vrpack.matmul(basis, normalized)
        actor = vrpack.matmul(bone, inverse_basis)
        self.assertEqual((bone[3], bone[7], bone[11]), (2, 4, -3))
        self.assertMatrix(actor, translation(2, 4, -3))
        self.assertNotEqual(pair.remove_common_motion(normalized, delta), normalized)

    def test_hidden_actor_remains_hidden_after_removal(self):
        hidden = (0, 0, 0, 7, 0, 0, 0, 22, 0, 0, 0, 2, 0, 0, 0, 1)
        normalized = pair.remove_common_motion(hidden, translation(3, 4, -1))
        transform, visible = importer.rigid_transform(normalized)
        self.assertEqual(visible, 0)
        self.assertEqual(vrview.matrix(transform), IDENTITY)

    def test_preserves_foreground_scale(self):
        foreground = list(translation(2, 3, 4))
        foreground[0] = 2
        world = list(foreground)
        world[11] -= 9
        self.assertMatrix(pair.remove_common_motion(world, translation(0, 0, -9)), foreground)

    def test_bad_camera_matrices_fail(self):
        for index, value in ((0, 2), (1, .1), (0, -1), (0, 0), (12, .1), (3, float('nan')),
                             (3, float('inf'))):
            invalid = list(IDENTITY)
            invalid[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(vrpack.AssetError):
                pair.rigid_matrix(invalid)
        for invalid in (None, [], [[1] * 4] * 3, [True] * 16):
            with self.subTest(invalid=invalid), self.assertRaises(vrpack.AssetError):
                pair.rigid_matrix(invalid)

    def test_nonfinite_foreground_rejected_including_hidden(self):
        invalid = list(IDENTITY)
        invalid[3] = float('nan')
        with self.assertRaises(vrpack.AssetError):
            pair.remove_common_motion(invalid, IDENTITY)

    def test_common_armature_track_is_required_before_normalization(self):
        canonical = translation(2, 3, 4)
        delta = translation(0, 0, -1)
        pair.verify_armature_motion(translation(2, 3, 3), delta, canonical)
        with self.assertRaisesRegex(vrpack.AssetError, 'declared common world motion'):
            pair.verify_armature_motion(canonical, delta, canonical)

    def test_wrong_axis_or_double_armature_motion_is_rejected(self):
        for world in (translation(0, -1, 0), translation(0, 0, -2)):
            with self.assertRaisesRegex(vrpack.AssetError, 'declared common world motion'):
                pair.verify_armature_motion(world, translation(0, 0, -1), IDENTITY)


class PairContractTests(unittest.TestCase):
    def test_exact_grid_and_full_clip_are_accepted(self):
        contract = load()
        self.assertEqual(len(contract.deltas), 545)
        self.assertEqual(contract.delta_at(0), IDENTITY)
        self.assertEqual(contract.delta_at(68), translation(0, 0, -1))
        self.assertAlmostEqual(contract.delta_at(Fraction(1, 8))[11], -1/544, places=12)

    def test_native_one_based_mapping_is_explicit(self):
        contract = load(native_start=1, native_end=69, candidate_frame_offset=0,
                        frames=importer.sample_grid(1, 69, 8, fps=Fraction(60))[0])
        self.assertEqual(contract.delta_at(69), translation(0, 0, -1))

    def test_wrong_identity_pins_fail(self):
        for kwargs in ({'expected_sidecar_sha256': 'f' * 64},
                       {'candidate_sha256': 'f' * 64},
                       {'action_fingerprints': {pair.RIG_ACTION: 'a'*64}},
                       {'action_fingerprints': dict(FINGERPRINTS, **{pair.CAMERA_ACTION: 'c'*64})}):
            with self.subTest(kwargs=kwargs), self.assertRaises(vrpack.AssetError):
                load(**kwargs)

    def test_wrong_crop_fps_frame_mapping_or_sample_time_fail(self):
        for kwargs in ({'native_end': 67}, {'candidate_frame_offset': 0},
                       {'candidate_frame_offset': True}, {'fps': Fraction(60000, 1001)},
                       {'frames': [Fraction(0), Fraction(1, 64), Fraction(68)]},
                       {'frames': [Fraction(0), Fraction(68), Fraction(67)]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(vrpack.AssetError):
                load(**kwargs)
        for key, value in (('candidate_frame', 5), ('time_seconds', .333)):
            document = fixture()
            document['rows'][15][key] = value
            with self.assertRaises(vrpack.AssetError):
                load(document)

    def test_missing_duplicate_or_truncated_samples_fail(self):
        for mutate in (lambda d: d['rows'].pop(),
                       lambda d: d['rows'].__setitem__(10, d['rows'][9])):
            document = fixture()
            mutate(document)
            with self.assertRaises(vrpack.AssetError):
                load(document)

    def test_unrelated_rigid_delta_rejected_with_repaired_hash(self):
        document = fixture()
        document['rows'][7]['common_world_delta'][0][3] = .1
        with self.assertRaisesRegex(vrpack.AssetError, 'differs from'):
            load(document)

    def test_nonrigid_and_nonfinite_sidecar_matrices_fail(self):
        for key in ('camera_world', 'common_world_delta'):
            for value in (2, float('nan'), float('inf')):
                document = fixture()
                document['rows'][8][key][0][0] = value
                with self.subTest(key=key, value=value), self.assertRaises(vrpack.AssetError):
                    load(document)

    def test_receipt_binds_exact_vra_and_sidecar_bytes(self):
        contract = load()
        receipt = contract.receipt(b'original VRA fixture', 'c' * 64, pair.RIG_ACTION)
        self.assertEqual(receipt['schema'], pair.RECEIPT_SCHEMA)
        self.assertEqual(receipt['asset_vra_sha256'], hashlib.sha256(b'original VRA fixture').hexdigest())
        self.assertEqual(receipt['camera_sidecar_sha256'], hashlib.sha256(contract.sidecar_bytes).hexdigest())
        self.assertEqual(receipt['candidate_sha256'], CANDIDATE_HASH)
        self.assertEqual(receipt['action_fingerprints'], FINGERPRINTS)
        self.assertEqual(receipt['candidate_frame_range'], [1, 69])
        self.assertEqual(receipt['native_crop'], [0, 68])
        self.assertEqual(receipt['native_fps'], [60, 1])
        self.assertEqual(receipt['common_motion_removal'], pair.REMOVAL)
        self.assertEqual(receipt['canonical_rest_frame'], 1)
        changed = contract.receipt(b'changed VRA fixture', 'c' * 64, pair.RIG_ACTION)
        self.assertNotEqual(receipt['asset_vra_sha256'], changed['asset_vra_sha256'])


class RestGeometryTests(unittest.TestCase):
    def test_restores_initial_armature_and_skin_worlds_parent_first(self):
        arm = SimpleNamespace(name='Arms', parent=None, matrix_world=rows(translation(0, 0, -9)))
        skin = SimpleNamespace(name='Skin', parent=arm, matrix_world=rows(translation(1, 0, -9)))
        expected = {'Arms': translation(0, 0, 0), 'Skin': translation(1, 0, 0)}
        updates = []
        def update():
            updates.append(copy.deepcopy(arm.matrix_world))
        pair.restore_canonical_worlds([skin, arm], expected, lambda matrix: [list(r) for r in matrix], update)
        self.assertEqual(arm.matrix_world, rows(expected['Arms']))
        self.assertEqual(skin.matrix_world, rows(expected['Skin']))
        self.assertEqual(updates[0], rows(expected['Arms']))

    def test_changed_rest_world_or_missing_skin_is_not_silent(self):
        arm = SimpleNamespace(name='Arms', parent=None, matrix_world=rows(IDENTITY))
        with self.assertRaisesRegex(vrpack.AssetError, 'object set mismatch'):
            pair.restore_canonical_worlds([arm], {}, lambda matrix: matrix, lambda: None)
        def overwrite():
            arm.matrix_world = rows(translation(0, 0, -9))
        with self.assertRaisesRegex(vrpack.AssetError, 'was not restored'):
            pair.restore_canonical_worlds([arm], {'Arms': IDENTITY}, lambda matrix: matrix, overwrite)


class OptInTests(unittest.TestCase):
    def test_default_importer_does_not_read_a_camera_or_change_contract(self):
        self.assertIsNone(importer.paired_contract(SimpleNamespace(), [0, 68], Fraction(60)))

    def test_partial_arguments_rejected(self):
        with self.assertRaisesRegex(vrpack.AssetError, 'every --pair-'):
            importer.paired_contract(SimpleNamespace(pair_sidecar=Path('unused')), [0, 68], Fraction(60))

    def test_real_paired_argument_path_checks_source_bytes_and_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, sidecar = directory/'candidate.fixture', directory/'camera.json'
            source.write_bytes(CANDIDATE)
            data = json.dumps(fixture()).encode()
            sidecar.write_bytes(data)
            args = SimpleNamespace(
                pair_sidecar=sidecar, pair_sidecar_sha256=hashlib.sha256(data).hexdigest(),
                pair_candidate_source=source, pair_rig_action_fingerprint=FINGERPRINTS[pair.RIG_ACTION],
                pair_camera_action_fingerprint=FINGERPRINTS[pair.CAMERA_ACTION],
                pair_candidate_frame_offset=1, source_sha256=CANDIDATE_HASH,
                take='prone_crawl_enter', name=pair.RIG_ACTION, loop=False,
                subdivisions=8, switch=[], imported_frame_offset=1., native_start=0, native_end=68)
            frames = importer.sample_grid(0, 68, 8, fps=Fraction(60))[0]
            self.assertIsInstance(importer.paired_contract(args, frames, Fraction(60)), pair.CameraPair)
            for field, bad in (('subdivisions', 64), ('take', None), ('name', 'wrong'),
                               ('loop', True), ('switch', ['3']), ('imported_frame_offset', float('nan'))):
                altered = copy.copy(args)
                setattr(altered, field, bad)
                with self.subTest(field=field), self.assertRaises(vrpack.AssetError):
                    importer.paired_contract(altered, frames, Fraction(60))
            source.write_bytes(b'wrong candidate')
            with self.assertRaisesRegex(vrpack.AssetError, 'candidate source bytes'):
                importer.paired_contract(args, frames, Fraction(60))


if __name__ == '__main__':
    unittest.main()
