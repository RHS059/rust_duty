"""Source-free verifier regressions. Synthetic fixtures are never parity evidence."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import verify_prone_r15_runtime as v


def translation(x=0, y=0, z=0):
    result = np.eye(4)
    result[:3, 3] = [x, y, z]
    return result


def columns(value):
    return np.asarray(value).T.reshape(16).tolist()


def fixture(frame=1, depth=0):
    time = (frame - 1) / 60
    source_camera = translation(z=-1.26 * depth)
    delta = source_camera
    world_bone = delta @ translation(.03 * (frame - 1), 0, 0)
    actor_world = {name: delta @ translation(i * .1, 0, -.2) for i, name in enumerate(v.ACTORS)}
    local = np.array([[0., 0., 0.], [.02, .01, 0], [0, .03, .01]])
    skin_world = v.transformed(local, world_bone)
    normalize = v.BASIS @ np.linalg.inv(delta)
    rigid = [v.transformed(local, v.BASIS) for _ in v.ACTORS]
    pack = {"bones": [("root", -1)], "actors": [
        {"name": name, "meshes": [i], "inverse_rest_global": columns(np.eye(4))}
        for i, name in enumerate(v.ACTORS)]}
    bones = [("root", -1, v.BASIS.copy(), v.BASIS.T.copy())]
    witness = {"source_rest_world": {"root": np.eye(4).tolist()}}
    camera = {"initial_camera_world": np.eye(4).tolist()}
    source = {"source_frame": frame, "time_seconds": time, "camera_world": source_camera.tolist(),
              "camera_world_delta_from_frame1": delta.tolist(), "bone_world": {"root": world_bone.tolist()},
              "bone_deformation_world": {"root": world_bone.tolist()},
              "actors_world": {n: w.tolist() for n, w in actor_world.items()},
              "actors_camera_relative": {n: (np.linalg.inv(source_camera) @ w).tolist() for n, w in actor_world.items()}}
    actors, meshes = [], []
    for i, name in enumerate(v.ACTORS):
        transform = normalize @ actor_world[name] @ v.BASIS.T
        actors.append({"name": name, "mesh_indices": [i], "visible": True,
                       "global": columns(transform), "matrix": columns(transform)})
        meshes.append({"mesh": i, "actor": i, "visible": True,
                       "positions": v.transformed(rigid[i], transform).tolist()})
    result = {"clip": v.ACTION, "game_axis": False, "time": float(np.float32(time)),
              "sample_time": float(np.float32(time)), "bones": [{"name": "root", "global": columns(normalize @ world_bone)}],
              "skin_meshes": [{"mesh": 0, "positions": v.transformed(skin_world, normalize).tolist()}],
              "actors": actors, "rigid_meshes": meshes}
    eye = float(np.float32(1.016))
    sampled_camera = {"requested_seconds": time, "seconds": time, "weapon_sample_seconds": float(np.float32(time)),
                      "source_frame": frame, "entry_eye_height": eye,
                      "eye_height": eye + depth * (float(np.float32(.2794)) - eye), "normalized_depth_fraction": depth,
                      "camera_local_orientation_xyzw": [0, 0, 0, 1],
                      "camera_local_forward": [0, 0, -1], "camera_local_up": [0, 1, 0]}
    checker_args = (pack, bones, [3], rigid, witness, camera)
    return checker_args, {name: local for name in v.ACTORS}, result, sampled_camera, source, skin_world


class PrimitiveTests(unittest.TestCase):
    def test_nonfinite_and_duplicate_json_rejected(self):
        for text in ('{"x":NaN}', '{"x":Infinity}', '{"x":1,"x":2}'):
            with self.subTest(text=text), self.assertRaises(v.VerificationError):
                v.json_loads(text)
        with self.assertRaises(v.VerificationError):
            v.finite([[float("nan"), 0, 0]], (1, 3), "vertices")

    def test_column_major_matrix_and_affine_rejection(self):
        m = translation(1, 2, 3)
        np.testing.assert_array_equal(v.matrix(columns(m), "test", columns=True), m)
        m[3, 0] = .1
        with self.assertRaises(v.VerificationError):
            v.matrix(m.tolist(), "nonaffine")

    def test_correspondence_is_bidirectional_and_frozen(self):
        points = np.array([[0., 0, 0], [1., 0, 0], [0., 1, 0]])
        mapping = v.FixedCorrespondence(points[[1, 2, 0]], points)
        self.assertEqual(mapping.error(points[[1, 2, 0]] + 2, points + 2), 0)
        self.assertGreater(mapping.error(points, points), 1)
        with self.assertRaises(v.VerificationError):
            v.FixedCorrespondence(points[:2], points)
        with self.assertRaises(v.VerificationError):
            mapping.error(points[:2], points)

    def test_spatial_correspondence_matches_exact_numpy_oracle(self):
        rng = np.random.default_rng(1944)
        reference = rng.uniform(-2, 2, (150, 3))
        reference = np.concatenate([reference, reference[:20]])
        query = reference[rng.permutation(len(reference))] + rng.uniform(-.00003, .00003, reference.shape)
        distance, indices = v.nearest_indices(query, reference)
        bounded_distance, bounded_indices = v.bounded_nearest_indices(query, reference)
        np.testing.assert_array_equal(bounded_indices, indices)
        np.testing.assert_allclose(bounded_distance, distance, rtol=1e-15, atol=1e-20)
        # Adjacent cells and exact duplicate ties retain deterministic indices.
        reference = np.array([[.000099, 0, 0], [.000099, 0, 0]])
        self.assertEqual(v.bounded_nearest_indices(np.array([[.000101, 0, 0]]), reference)[1].tolist(), [0])

    def test_threshold_is_point_one_millimeter(self):
        points = np.array([[0., 0, 0]])
        v.FixedCorrespondence(points, points + [.00009, 0, 0])
        with self.assertRaises(v.VerificationError):
            v.FixedCorrespondence(points, points + [.00011, 0, 0])
        self.assertEqual(v.POSITION_LIMIT, 1e-4)
        self.assertEqual(v.MATRIX_LIMIT, 1e-4)

    def test_oracle_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(v.bounded_path(root, "sample-rows/0000.json", "row"),
                             root.resolve() / "sample-rows/0000.json")
            with self.assertRaises(v.VerificationError):
                v.bounded_path(root, "../outside.json", "row")

    def test_hash_is_checked_before_parsing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.json"
            path.write_text('{"value": 1}')
            digest = v.sha256(path)
            self.assertEqual(v.load_hashed_json(path, digest), {"value": 1})
            path.write_text('{"value": 2}')
            with self.assertRaises(v.VerificationError):
                v.load_hashed_json(path, digest)

    def test_nonrigid_camera_quaternion_rejected(self):
        with self.assertRaises(v.VerificationError):
            v.quaternion_matrix([0, 0, 0, 2])

    def test_stream_nonzero_exit_is_not_success(self):
        with self.assertRaisesRegex(v.VerificationError, "failed"):
            list(v.rust_samples([sys.executable, "-c", 'print("{}", flush=True); raise SystemExit(7)']))

    def test_stream_non_json_is_rejected(self):
        with self.assertRaises(ValueError):
            list(v.rust_samples([sys.executable, "-c", 'print("progress")']))


class CheckerTests(unittest.TestCase):
    def test_independent_skin_rigid_and_camera_pair_pass(self):
        args, geometry, pose, camera, source, skin = fixture()
        checker = v.ParityChecker(*args, rigid_source=geometry)
        checker.check(pose, camera, source, skin)
        _, _, pose, camera, source, skin = fixture(frame=2, depth=.6)
        checker.check(pose, camera, source, skin)
        self.assertTrue(all(row["passed"] for row in checker.records))
        with patch.object(v, "SAMPLE_COUNT", 2):
            summary = checker.summary()
        self.assertTrue(summary["passed"])
        self.assertTrue(summary["complete"])
        self.assertFalse(summary["correspondence"]["per_frame_remapping"])

    def test_missing_rigid_witness_cannot_pass(self):
        args, _, pose, camera, source, skin = fixture()
        checker = v.ParityChecker(*args)
        checker.check(pose, camera, source, skin)
        with patch.object(v, "SAMPLE_COUNT", 1):
            summary = checker.summary()
        self.assertTrue(summary["measured_checks_passed"])
        self.assertFalse(summary["complete"])
        self.assertFalse(summary["passed"])

    def test_camera_mismatch_is_measured_independently(self):
        args, geometry, pose, camera, source, skin = fixture()
        checker = v.ParityChecker(*args, rigid_source=geometry)
        camera["normalized_depth_fraction"] = .02
        camera["eye_height"] = camera["entry_eye_height"] + .02 * (float(np.float32(.2794)) - camera["entry_eye_height"])
        checker.check(pose, camera, source, skin)
        self.assertFalse(checker.records[-1]["passed"])
        self.assertGreater(checker.records[-1]["camera_world_matrix_error"], .02)
        self.assertGreater(checker.records[-1]["skin_world_error_m"], .02)

    def test_double_descent_is_detected(self):
        args, geometry, pose, camera, source, skin = fixture()
        checker = v.ParityChecker(*args, rigid_source=geometry)
        checker.check(pose, camera, source, skin)
        _, _, pose, camera, source, skin = fixture(frame=2, depth=.5)
        points = np.array(pose["skin_meshes"][0]["positions"])
        points[:, 1] -= .63  # Incorrectly retained common camera descent.
        pose["skin_meshes"][0]["positions"] = points.tolist()
        checker.check(pose, camera, source, skin)
        self.assertFalse(checker.records[-1]["passed"])
        self.assertGreater(checker.records[-1]["skin_normalized_error_m"], .6)

    def test_swapped_mesh_or_bone_identity_is_rejected(self):
        for kind in ("skin", "bone", "actor", "rigid_owner"):
            args, geometry, pose, camera, source, skin = fixture()
            if kind == "skin": pose["skin_meshes"][0]["mesh"] = 1
            elif kind == "bone": pose["bones"][0]["name"] = "different"
            elif kind == "actor": pose["actors"].reverse()
            else: pose["rigid_meshes"][0]["actor"] = 2
            with self.subTest(kind=kind), self.assertRaises(v.VerificationError):
                v.ParityChecker(*args, rigid_source=geometry).check(pose, camera, source, skin)

    def test_bad_rigid_geometry_is_detected_without_pose_self_reference(self):
        args, geometry, pose, camera, source, skin = fixture()
        geometry[v.ACTORS[0]] = geometry[v.ACTORS[0]] + [.001, 0, 0]
        with self.assertRaises(v.VerificationError):
            v.ParityChecker(*args, rigid_source=geometry)

    def test_runtime_rigid_position_corruption_is_detected(self):
        args, geometry, pose, camera, source, skin = fixture()
        checker = v.ParityChecker(*args, rigid_source=geometry)
        pose["rigid_meshes"][0]["positions"][1][0] += .001
        checker.check(pose, camera, source, skin)
        self.assertFalse(checker.records[-1]["passed"])
        self.assertGreater(checker.records[-1]["rigid_world_error_m"], .0009)

    def test_hidden_frame1_actor_still_has_independent_local_geometry_gate(self):
        args, geometry, pose, camera, source, skin = fixture()
        hidden = v.ACTORS[-1]
        zero = np.eye(4)
        zero[:3, :3] = 0
        source["actors_world"][hidden] = zero.tolist()
        source["actors_camera_relative"][hidden] = zero.tolist()
        pose["actors"][-1]["visible"] = False
        pose["actors"][-1]["global"] = columns(np.eye(4))
        pose["actors"][-1]["matrix"] = columns(np.eye(4))
        pose["rigid_meshes"][-1]["visible"] = False
        checker = v.ParityChecker(*args, rigid_source=geometry)
        checker.check(pose, camera, source, skin)
        self.assertTrue(checker.records[-1]["passed"])
        geometry[hidden] = geometry[hidden] + [.001, 0, 0]
        with self.assertRaises(v.VerificationError):
            v.ParityChecker(*args, rigid_source=geometry)

    def test_missing_sample_and_nonframe1_anchor_rejected(self):
        args, geometry, *_ = fixture()
        checker = v.ParityChecker(*args, rigid_source=geometry)
        with self.assertRaises(v.VerificationError):
            checker.summary()
        _, _, pose, camera, source, skin = fixture(frame=2)
        with self.assertRaises(v.VerificationError):
            checker.check(pose, camera, source, skin)

    def test_visibility_boolean_and_applied_matrix_are_validated(self):
        for kind in ("visible", "applied"):
            args, geometry, pose, camera, source, skin = fixture()
            if kind == "visible": pose["actors"][0]["visible"] = 1
            else: pose["actors"][0]["matrix"][12] += .01
            with self.subTest(kind=kind), self.assertRaises(v.VerificationError):
                v.ParityChecker(*args, rigid_source=geometry).check(pose, camera, source, skin)

class AdmissionTests(unittest.TestCase):
    def source_fixture(self):
        grid = [1.0, 69.0]
        source = {"source_sha256": v.SOURCE_SHA, "rig_action": v.ACTION, "camera_action": v.CAMERA_ACTION,
                  "rig_action_fingerprint": v.FINGERPRINTS[v.ACTION], "camera_action_fingerprint": v.FINGERPRINTS[v.CAMERA_ACTION],
                  "source_rest_world": {f"b{i}": np.eye(4).tolist() for i in range(148)},
                  "hierarchy": {f"b{i}": None for i in range(148)},
                  "topology": {f"Actual arms mesh {i}": {"vertices": count} for i, count in enumerate(v.VERTEX_COUNTS)},
                  "projection": {"type": "PERSP", "ray_directions": [[0, 0, -1]] * 4},
                  "frames": {str(frame): {"source_frame": frame, "row_path": f"sample-rows/{i:04d}.json", "row_sha256": "a"*64,
                                         "skin_path": f"skin-rows/{i:04d}.npz", "skin_sha256": "b"*64} for i, frame in enumerate(grid)}}
        return source, hashlib.sha256((json.dumps(grid) + "\n").encode()).hexdigest()

    def test_exact_grid_identity_and_hash(self):
        source, grid_sha = self.source_fixture()
        with patch.object(v, "SAMPLE_COUNT", 2), patch.object(v, "GRID_SHA", grid_sha):
            self.assertEqual(v.validate_source(source, [("b0", -1)]), [1., 69.])
            changed = copy.deepcopy(source)
            changed["frames"]["69.0"]["source_frame"] = 68.
            with self.assertRaises(v.VerificationError):
                v.validate_source(changed, [("b0", -1)])
            changed = copy.deepcopy(source)
            changed["frames"]["69.0"]["row_path"] = "sample-rows/0000.json"
            with self.assertRaises(v.VerificationError):
                v.validate_source(changed, [("b0", -1)])

    def test_foreign_action_or_source_is_rejected(self):
        for field in ("source_sha256", "rig_action", "camera_action", "rig_action_fingerprint", "camera_action_fingerprint"):
            source, grid_sha = self.source_fixture()
            source[field] = "foreign"
            with self.subTest(field=field), self.assertRaises(v.VerificationError):
                v.validate_source(source, [("b0", -1)])

    def test_changed_canonical_parent_is_rejected(self):
        source, grid_sha = self.source_fixture()
        source["hierarchy"]["b0"] = "b1"
        with patch.object(v, "SAMPLE_COUNT", 2), patch.object(v, "GRID_SHA", grid_sha), self.assertRaises(v.VerificationError):
            v.validate_source(source, [("b0", -1)])

    def test_runtime_key_grid_is_float32_exact(self):
        bones = [(f"b{i}", -1) for i in range(72)]
        blobs = {"asset.vra": b"synthetic"}
        pack = {"bones": bones, "actors": [{"name": n} for n in v.ACTORS],
                "clips": [{"name": v.ACTION, "loop": False, "frames": [{"time": 0.}, {"time": float(np.float32(1/3840))}]}]}
        manifest = {"schema": "rust-duty-fbx-segment-diagnostic/v1", "status": "diagnostic",
                    "source_fbx_sha256": v.FBX_SHA, "authoring_master_sha256": v.SOURCE_SHA,
                    "native_crop": [0, 68], "native_fps": [60, 1], "source_take": v.ACTION,
                    "imported_frame_offset": 1, "bones": 72, "actors": list(v.ACTORS),
                    "timing_policy": {"kind": "explicit-rational-resampling", "subdivisions": 64, "switches": [],
                                      "samples": 2, "float32_collision_policy": "reject"},
                    "files": {"asset.vra": {"sha256": hashlib.sha256(blobs["asset.vra"]).hexdigest(), "bytes": 9}},
                    "prone_camera_pair": {"receipt": "asset.prone-pair.json", "sidecar": "asset.prone-camera.json",
                                          "common_motion_removal": v.pair.REMOVAL,
                                          "rest_geometry": "canonical initial armature and skin object worlds restored before encoding"},
                    "source_action_ranges": [{"name": n+"|"+v.ACTION, "frame_range": [1, 69]} for n in ("Arms",)+v.ACTORS]}
        with patch.object(v, "RUNTIME_KEYS", 2):
            v.validate_manifest(manifest, pack, blobs, bones)
            pack["clips"][0]["frames"][1]["time"] = 1/3840
            with self.assertRaises(v.VerificationError):
                v.validate_manifest(manifest, pack, blobs, bones)


if __name__ == "__main__":
    unittest.main()
