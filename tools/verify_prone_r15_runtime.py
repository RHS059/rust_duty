#!/usr/bin/env python3
"""Stream actual Rust CPU parity against the immutable approved prone r15 oracle.

No Blender, Python animation fallback, native graphics, asset activation or
artistic approval. The 1,944 independent source samples include fractional
1/128 and 1/512-frame neighborhoods; arbitrary continuous-time parity is not
claimed. Geometry inputs and detailed output are private and must not be
committed with this source-only verifier.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from fractions import Fraction
import hashlib
import io
from itertools import product
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

import numpy as np
import prone_camera_pair as pair
import vrpack
import vrskin
import vrview

ACTION = pair.R15_RIG_ACTION
CAMERA_ACTION = pair.R15_CAMERA_ACTION
SOURCE_SHA = pair.R15_SOURCE_SHA
FINGERPRINTS = pair.R15_FINGERPRINTS
FBX_SHA = "f025876ede4ec28098337ea645da679765678d75d94fdcf51965a92eba4e4a02"
CANONICAL_SHA = "d02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab"
ORACLE_SHA = "94195fd1f003a56711add86caf81a762ce9a392741c9de0c8e0cfdf0a948dcb9"
GRID_SHA = "f47bb34d734b7e5bf01806530c23367a45214e9037ea445c102e9405db9ff1e4"
CAMERA_SHA = "9b91331d264444fec48813a769f67d02273ba96d8d922d49e50f7497e6ee22f9"
EVIDENCE_PINS = {
    "export-receipt.json": "e79c1bf28cc3c2ace24e5048941d134932eeadc774c130df8b67b22718435fd6",
    "paired-camera-contract.json": "eba1b418f22613b9c2548e8f7aa11849b9f820edc346cdbdfcecd05cf0d19213",
    "fresh-import-parity.json": "423bb59c454cf15883001cdaad3ed39830261b094a76eae5d2250ca6325602a1",
    "fbx-take-contract.json": "0930ad10ad435a5591655cbe4b0a307f3393b3daf3179e8c9061be00a65f3e72",
}
ACTORS = ("hk416_weapon", "hk416_magazine", "hk416_magazine_outgoing")
VERTEX_COUNTS = (5710, 3954, 570)
BASIS = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=float)
POSITION_LIMIT = MATRIX_LIMIT = 0.0001
TIME_LIMIT = 0.0000001  # Float32 JSON spelling only; never a source frame tolerance.
SAMPLE_COUNT = 1944
RUNTIME_KEYS = 4353

class VerificationError(ValueError):
    """Missing, malformed, mismatched or unmeasured required evidence."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pinned(path, expected):
    actual = sha256(path)
    require(actual == expected, f"SHA-256 mismatch: {path}; expected {expected}, got {actual}")
    return actual


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def json_loads(text):
    return json.loads(text, object_pairs_hook=no_duplicate_keys,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          VerificationError(f"non-finite JSON number: {value}")))


def finite(value, shape, label):
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise VerificationError(f"invalid numeric {label}") from exc
    require(array.shape == shape and np.isfinite(array).all(), f"invalid shape/non-finite {label}")
    return array


def matrix(value, label, *, columns=False):
    array = finite(value, (16,) if columns else (4, 4), label)
    if columns:
        array = array.reshape(4, 4).T
    require(np.max(np.abs(array[3] - [0, 0, 0, 1])) <= 1e-6, f"non-affine {label}")
    return array


def skeleton_parents(bones):
    names = [bone[0] for bone in bones]
    require(len(set(names)) == len(names), "duplicate bone identity")
    vrskin.validate_parents([bone[1] for bone in bones])
    return {name: names[parent] if parent >= 0 else None for name, parent in bones}


def read_geometry(vrs, vrm):
    """Inspect validated companion bytes; retain VRS rests/counts and VRM positions."""
    vrskin.inspect_vrs(vrs)
    vrpack.inspect_vrm(vrm)

    def reader(data):
        cursor = 24
        def take(count):
            nonlocal cursor
            require(0 <= count <= len(data) - cursor, "truncated companion")
            value = data[cursor:cursor + count]
            cursor += count
            return value
        def unpack(fmt):
            return struct.unpack(fmt, take(struct.calcsize(fmt)))
        return take, unpack

    take, unpack = reader(vrs)
    bones = []
    for _ in range(unpack("<I")[0]):
        name = take(unpack("<H")[0]).decode("utf-8")
        parent = unpack("<i")[0]
        local = matrix(unpack("<16f"), f"VRS rest {name}", columns=True)
        inverse_bind = matrix(unpack("<16f"), f"VRS inverse bind {name}", columns=True)
        bones.append((name, parent, local, inverse_bind))
    counts = []
    for _ in range(unpack("<I")[0]):
        take(24)
        _, _, size = unpack("<III")
        take(size)
        vertices, indices = unpack("<II")
        counts.append(vertices)
        take(vertices * struct.calcsize("<8f8H8f") + indices * 4)
    take, unpack = reader(vrm)
    rigid = []
    for _ in range(unpack("<I")[0]):
        take(24)
        _, _, size = unpack("<III")
        take(size)
        vertices, indices = unpack("<II")
        values = np.frombuffer(take(vertices * 32), dtype="<f4").reshape(vertices, 8)[:, :3].astype(float)
        rigid.append(values)
        take(indices * 4)
    return bones, counts, rigid


def nearest_indices(query, reference):
    """Exact bounded-memory Euclidean NN; only the declared NumPy dependency.

    Direct coordinate differences avoid cancellation from squared-norm shortcuts.
    Equal-distance ties choose the first index, deterministically. The result is
    computed once for the first pose and never rematched on later frames.
    """
    require(query.ndim == reference.ndim == 2 and query.shape[1] == reference.shape[1] == 3,
            "nearest-neighbor points must be Nx3")
    require(len(query) > 0 and len(reference) > 0
            and np.isfinite(query).all() and np.isfinite(reference).all(),
            "invalid nearest-neighbor positions")
    indices = np.empty(len(query), dtype=np.int64)
    distances = np.empty(len(query), dtype=float)
    for begin in range(0, len(query), 32):
        difference = query[begin:begin + 32, None, :] - reference[None, :, :]
        squared = np.einsum("ijk,ijk->ij", difference, difference)
        selected = np.argmin(squared, axis=1)
        indices[begin:begin + len(selected)] = selected
        distances[begin:begin + len(selected)] = np.sqrt(squared[np.arange(len(selected)), selected])
    return distances, indices


def bounded_nearest_indices(query, reference, limit=POSITION_LIMIT):
    """Exact first-index NN inside the immutable acceptance radius.

    A point within ``limit`` must be in the same or an adjacent spatial cell
    along each axis. Inspect all 27 cells, retain every duplicate vertex, and
    choose the smallest original index on ties. If no accepted neighbor exists,
    fail closed rather than using an approximate or widening-radius match.
    The unrestricted NumPy implementation above is retained as a test oracle.
    """
    require(query.ndim == reference.ndim == 2 and query.shape[1] == reference.shape[1] == 3,
            "nearest-neighbor points must be Nx3")
    require(len(query) > 0 and len(reference) > 0 and np.isfinite(query).all() and np.isfinite(reference).all(),
            "invalid nearest-neighbor positions")
    require(math.isfinite(limit) and limit > 0, "invalid correspondence acceptance radius")
    scaled_query, scaled_reference = np.floor(query / limit), np.floor(reference / limit)
    require(np.max(np.abs(scaled_query)) < 2**62 and np.max(np.abs(scaled_reference)) < 2**62,
            "correspondence coordinates exceed safe spatial index range")
    cells = {}
    for index, cell in enumerate(scaled_reference.astype(np.int64)):
        cells.setdefault(tuple(cell), []).append(index)
    offsets = tuple(product((-1, 0, 1), repeat=3))
    indices, distances = np.empty(len(query), dtype=np.int64), np.empty(len(query), dtype=float)
    for row, (point, cell) in enumerate(zip(query, scaled_query.astype(np.int64))):
        x, y, z = (int(c) for c in cell)
        candidates = []
        for dx, dy, dz in offsets:
            candidates.extend(cells.get((x + dx, y + dy, z + dz), ()))
        require(candidates, "first-pose correspondence has no neighbor within 0.1 mm")
        candidates = np.asarray(sorted(candidates), dtype=np.int64)
        difference = point - reference[candidates]
        squared = np.einsum("ij,ij->i", difference, difference)
        selected = int(np.argmin(squared))
        distance = math.sqrt(float(squared[selected]))
        require(distance <= limit, "first-pose correspondence exceeds 0.1 mm")
        indices[row], distances[row] = candidates[selected], distance
    return distances, indices


class FixedCorrespondence:
    """Bidirectional first-pose NN correspondence, frozen for all later poses."""
    def __init__(self, actual, expected):
        require(len(actual) > 0 and len(expected) > 0, "empty skin correspondence")
        forward_distance, self.forward = bounded_nearest_indices(actual, expected)
        reverse_distance, self.reverse = bounded_nearest_indices(expected, actual)
        self.initial_error = max(float(forward_distance.max()), float(reverse_distance.max()))
        require(self.initial_error <= POSITION_LIMIT, "first-pose bidirectional skin correspondence exceeds 0.1 mm")
        self.actual_shape, self.expected_shape = actual.shape, expected.shape
        self.digest = hashlib.sha256(np.asarray(self.forward, dtype="<u8").tobytes()
                                     + np.asarray(self.reverse, dtype="<u8").tobytes()).hexdigest()

    def error(self, actual, expected):
        require(actual.shape == self.actual_shape and expected.shape == self.expected_shape,
                "skin vertex identity/count changed after first pose")
        require(np.isfinite(actual).all() and np.isfinite(expected).all(), "non-finite skin positions")
        return max(float(np.linalg.norm(actual - expected[self.forward], axis=1).max()),
                   float(np.linalg.norm(actual[self.reverse] - expected, axis=1).max()))


def max_position_error(actual, expected):
    return float(np.linalg.norm(actual - expected, axis=-1).max())


def transformed(vertices, transform):
    return vertices @ transform[:3, :3].T + transform[:3, 3]


def hashed_bytes(path, expected):
    data = Path(path).read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, f"SHA-256 mismatch: {path}")
    return data


def load_hashed_json(path, expected):
    return json_loads(hashed_bytes(path, expected).decode("utf-8"))


def bounded_path(root, relative, label):
    require(isinstance(relative, str) and relative, f"missing {label} path")
    result = (root / relative).resolve()
    require(result.is_relative_to(root.resolve()), f"{label} path escapes oracle directory")
    return result


def numeric(value, label):
    require(type(value) in (int, float) and math.isfinite(value), f"invalid/non-finite {label}")
    return value


def visible_matrix(value):
    magnitude = float(np.max(np.abs(value[:3, :3])))
    if magnitude < 1e-10:
        return False
    require(abs(np.linalg.det(value[:3, :3])) > 1e-8, "partially singular actor matrix")
    return True


def exact_time(value, time, label):
    require(abs(numeric(value, label) - float(np.float32(time))) <= TIME_LIMIT, f"{label} mismatch")


def validate_source(witness, canonical, *, source_sha256=SOURCE_SHA):
    for key, expected in {"source_sha256": source_sha256, "rig_action": ACTION,
                          "camera_action": CAMERA_ACTION,
                          "rig_action_fingerprint": FINGERPRINTS[ACTION],
                          "camera_action_fingerprint": FINGERPRINTS[CAMERA_ACTION]}.items():
        require(witness.get(key) == expected, f"source {key} mismatch")
    frames = witness.get("frames")
    require(isinstance(frames, dict) and len(frames) == SAMPLE_COUNT, "source oracle sample count mismatch")
    grid = [numeric(row.get("source_frame"), "source frame") for row in frames.values()]
    require(grid == sorted(set(grid)) and grid[0] == 1 and grid[-1] == 69, "source sample grid order/span mismatch")
    require(list(frames) == [str(float(frame)) for frame in grid], "source sample key/frame identity mismatch")
    require(hashlib.sha256((json.dumps(grid) + "\n").encode()).hexdigest() == GRID_SHA,
            "source sample grid does not match the exact approved 1,944 timestamps")
    rest, hierarchy = witness.get("source_rest_world", {}), witness.get("hierarchy", {})
    require(len(rest) == 148 and set(rest) == set(hierarchy), "source rest/hierarchy inventory mismatch")
    for name, parent in skeleton_parents(canonical).items():
        require(name in rest and hierarchy[name] == parent, f"canonical source parent mismatch: {name}")
    for name, value in rest.items():
        require(abs(np.linalg.det(matrix(value, f"source rest {name}")[:3, :3])) > 1e-8,
                f"singular source rest: {name}")
    topology = witness.get("topology", {})
    require(set(topology) == {f"Actual arms mesh {i}" for i in range(3)}, "source skin identity mismatch")
    for i, count in enumerate(VERTEX_COUNTS):
        require(topology[f"Actual arms mesh {i}"].get("vertices") == count, "source skin count mismatch")
    projection = witness.get("projection", {})
    require(projection.get("type") == "PERSP", "source projection must be perspective")
    finite(projection.get("ray_directions"), (4, 3), "source projection rays")
    paths = []
    for index, row in enumerate(frames.values()):
        for kind, suffix in (("row", "json"), ("skin", "npz")):
            require(row.get(f"{kind}_path") == f"{'sample' if kind == 'row' else 'skin'}-rows/{index:04d}.{suffix}",
                    "source sample file index/order mismatch")
            digest = row.get(f"{kind}_sha256")
            require(isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest),
                    "missing/invalid sample file digest")
            paths.append(row[f"{kind}_path"])
    require(len(set(paths)) == 2 * SAMPLE_COUNT, "reused source sample path")
    return grid


def load_source_row(root, descriptor, bone_names):
    row = load_hashed_json(bounded_path(root, descriptor["row_path"], "sample"), descriptor["row_sha256"])
    frame = descriptor["source_frame"]
    require(row.get("source_frame") == frame and row.get("time_seconds") == (frame - 1) / 60,
            "source row time/frame mismatch")
    require(row.get("reference_frame_position") == frame + 2240, "reference time mapping mismatch")
    for field in ("camera_world", "rig_world", "camera_world_delta_from_frame1", "rig_world_delta_from_frame1"):
        matrix(row.get(field), field)
    for field in ("bone_world", "bone_deformation_world"):
        require(set(row.get(field, {})) == set(bone_names), f"source {field} inventory mismatch")
        for name, value in row[field].items():
            matrix(value, f"source {field} {name}")
    for field in ("actors_world", "actors_camera_relative"):
        require(set(row.get(field, {})) == set(ACTORS), f"source {field} inventory mismatch")
        for name, value in row[field].items():
            matrix(value, f"source {field} {name}")
    data = hashed_bytes(bounded_path(root, descriptor["skin_path"], "skin"), descriptor["skin_sha256"])
    with np.load(io.BytesIO(data), allow_pickle=False) as npz:
        require(set(npz.files) == {"m0", "m1", "m2"}, "source skin NPZ identity mismatch")
        skin = np.concatenate([finite(npz[f"m{i}"], (count, 3), f"source skin m{i}")
                               for i, count in enumerate(VERTEX_COUNTS)])
    return row, skin


def validate_manifest(manifest, pack, blobs, canonical, *, source_sha256=SOURCE_SHA, fbx_sha256=FBX_SHA):
    for field, expected in {
        "schema": "rust-duty-fbx-segment-diagnostic/v1", "status": "diagnostic",
        "source_fbx_sha256": fbx_sha256, "authoring_master_sha256": source_sha256,
        "native_crop": [0, 68], "native_fps": [60, 1], "source_take": ACTION,
        "imported_frame_offset": 1, "bones": 72, "actors": list(ACTORS),
    }.items():
        require(manifest.get(field) == expected, f"manifest {field} mismatch")
    for field, expected in {"kind": "explicit-rational-resampling", "subdivisions": 64,
                            "switches": [], "samples": RUNTIME_KEYS,
                            "float32_collision_policy": "reject"}.items():
        require(manifest.get("timing_policy", {}).get(field) == expected, f"manifest timing {field} mismatch")
    require(len(canonical) == 72 and skeleton_parents(pack["bones"]) == skeleton_parents(canonical),
            "runtime canonical skeleton identity/hierarchy mismatch")
    require([actor["name"] for actor in pack["actors"]] == list(ACTORS), "runtime actor identity/order mismatch")
    require(len(pack["clips"]) == 1, "expected exactly one selected runtime clip")
    clip = pack["clips"][0]
    require(clip["name"] == ACTION and clip["loop"] is False, "runtime clip identity/loop mismatch")
    require([row["time"] for row in clip["frames"]] == [float(np.float32(i / 3840)) for i in range(RUNTIME_KEYS)],
            "runtime must contain exact float32 3840 Hz grid with 4,353 keys")
    files = manifest.get("files", {})
    require(set(files) == set(blobs), "manifest companion identity set mismatch")
    for name, data in blobs.items():
        require(files[name].get("sha256") == hashlib.sha256(data).hexdigest()
                and files[name].get("bytes") == len(data), f"manifest hash/size mismatch: {name}")
    contract = manifest.get("prone_camera_pair", {})
    for field, expected in {"receipt": "asset.prone-pair.json", "sidecar": "asset.prone-camera.json",
                            "common_motion_removal": pair.REMOVAL,
                            "rest_geometry": "canonical initial armature and skin object worlds restored before encoding"}.items():
        require(contract.get(field) == expected, f"pair manifest {field} mismatch")
    ranges = manifest.get("source_action_ranges", [])
    names = [row.get("name") for row in ranges]
    require(len(names) == len(set(names)), "duplicate imported Action identity")
    for owner in ("Arms",) + ACTORS:
        matches = [row for row in ranges if row.get("name") == owner + "|" + ACTION]
        require(len(matches) == 1 and matches[0].get("frame_range") == [1, 69], f"source take range mismatch: {owner}")


def validate_pair(blobs, provenance=None):
    source_sha = SOURCE_SHA if provenance is None else provenance["generated_source_sha256"]
    camera_sha = CAMERA_SHA if provenance is None else provenance["camera_sidecar_sha256"]
    fbx_sha = FBX_SHA if provenance is None else provenance["source_fbx_sha256"]
    receipt_schema = pair.R15_RECEIPT_SCHEMA if provenance is None else "rust-duty-prone-camera-pair/v3"
    camera_data = blobs["asset.prone-camera.json"]
    require(hashlib.sha256(camera_data).hexdigest() == camera_sha, "camera sidecar differs from exact approved source sample")
    camera = json_loads(camera_data.decode())
    pair.load_camera_pair(camera_data, expected_sidecar_sha256=camera_sha, candidate_sha256=source_sha,
                          action_fingerprints=FINGERPRINTS, native_start=0, native_end=68, fps=Fraction(60),
                          candidate_frame_offset=1, frames=[Fraction(i, 64) for i in range(RUNTIME_KEYS)])
    receipt = json_loads(blobs["asset.prone-pair.json"].decode())
    for field, expected in {
        "schema": receipt_schema, "asset_vra_sha256": hashlib.sha256(blobs["asset.vra"]).hexdigest(),
        "camera_sidecar_sha256": camera_sha, "candidate_sha256": source_sha,
        "action_fingerprints": FINGERPRINTS, "source_fbx_sha256": fbx_sha, "clip_name": ACTION,
        "native_crop": [0, 68], "native_fps": [60, 1], "candidate_frame_offset": 1,
        "candidate_frame_range": [1, 69], "common_motion_removal": pair.REMOVAL,
        "canonical_rest_frame": 1, "camera_sample_hz": 3840, "source_rig_action": ACTION,
        "source_camera_action": CAMERA_ACTION, "source_take": ACTION, "imported_frame_offset": 1,
    }.items():
        require(receipt.get(field) == expected, f"pair receipt {field} mismatch")
    if provenance is not None:
        require(camera.get("schema") == "prone-entry-r15-camera-motion/v2" and
                camera.get("source_equivalence") == receipt.get("source_equivalence") == provenance["source_equivalence_descriptor"],
                "regenerated camera/receipt proof identity differs")
    return camera


def validate_rigid(witness, grid, initial_source, *, source_sha256=SOURCE_SHA):
    for field, expected in {"schema": "rust-duty-private-prone-rigid-oracle/v1", "passed": True,
                            "source_sha256": source_sha256, "action_fingerprints": FINGERPRINTS,
                            "sample_grid_sha256": GRID_SHA, "source_frames": grid,
                            "sample_count": SAMPLE_COUNT,
                            "basis": "Blender evaluated mesh local; world_at_frame1 is Blender world"}.items():
        require(witness.get(field) == expected, f"rigid oracle {field} mismatch")
    actors, samples = witness.get("actors", {}), witness.get("samples", [])
    require(set(actors) == set(ACTORS), "rigid oracle actor identity mismatch")
    require(len(samples) == len(grid), "rigid oracle sample count mismatch")
    geometry = {}
    for name, actor in actors.items():
        count = actor.get("vertex_count")
        require(type(count) is int and count > 0, "invalid rigid vertex count")
        geometry[name] = finite(actor.get("vertices_local"), (count, 3), name + " local vertices")
        polygons = actor.get("polygons")
        require(isinstance(polygons, list) and len(polygons) == actor.get("polygon_count") and polygons,
                "invalid source rigid polygon count")
        for polygon in polygons:
            require(isinstance(polygon, list) and len(polygon) >= 3
                    and all(type(v) is int and 0 <= v < count for v in polygon), "invalid source rigid polygon")
        payload = {"vertices_local": actor["vertices_local"], "polygons": polygons}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        require(actor.get("geometry_sha256") == digest, "source local geometry digest mismatch")
        require(np.max(np.abs(matrix(actor.get("world_at_frame1"), "rigid frame1 world")
                              - matrix(initial_source["actors_world"][name], "source frame1 actor"))) <= MATRIX_LIMIT,
                "rigid/source frame1 matrix mismatch")
    for frame, sample in zip(grid, samples):
        require(sample.get("source_frame") == frame and set(sample.get("actors", {})) == set(ACTORS),
                "rigid sample frame/actor mismatch")
        for name, actor in sample["actors"].items():
            require(actor.get("geometry_sha256") == actors[name]["geometry_sha256"], "actor is not independently proven rigid")
            require(actor.get("hide_render") is False, "source hide_render unsupported by runtime visibility contract")
    return geometry


def quaternion_matrix(values):
    q = finite(values, (4,), "Rust camera quaternion")
    require(abs(float(q @ q) - 1) <= 1e-5, "Rust camera quaternion must be normalized")
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([[1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
                     [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
                     [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)]])


def runtime_camera(sample, time, initial):
    for field in ("requested_seconds", "seconds", "weapon_sample_seconds"):
        exact_time(sample.get(field), time, "Rust camera " + field)
    require(abs(numeric(sample.get("source_frame"), "Rust camera source frame")
                - (1 + 60 * float(np.float32(time)))) <= 1e-5, "Rust camera source frame mismatch")
    depth = numeric(sample.get("normalized_depth_fraction"), "Rust camera depth")
    eye = numeric(sample.get("entry_eye_height"), "Rust camera entry eye height")
    require(abs(eye - float(np.float32(1.016))) <= 1e-7, "unexpected camera probe entry height")
    require(abs(numeric(sample.get("eye_height"), "Rust camera eye height")
                - (eye + depth * (float(np.float32(.2794)) - eye))) <= 3e-7,
            "runtime camera applies stance descent more than once")
    rotation = quaternion_matrix(sample.get("camera_local_orientation_xyzw"))
    for field, direction in (("camera_local_forward", [0, 0, -1]), ("camera_local_up", [0, 1, 0])):
        require(max_position_error(finite(sample.get(field), (3,), field), rotation @ direction) <= MATRIX_LIMIT,
                "camera axes/quaternion mismatch")
    result = initial.copy()
    result[:3, :3] = initial[:3, :3] @ rotation
    result[2, 3] = initial[2, 3] - 1.26 * depth
    return result
class ParityChecker:
    def __init__(self, pack, bones, skin_counts, rigid, witness, camera, rigid_source=None):
        self.pack, self.bones, self.skin_counts, self.rigid = pack, bones, skin_counts, rigid
        self.witness, self.rigid_source = witness, rigid_source
        self.initial_camera = matrix(camera["initial_camera_world"], "initial camera")
        self.inverse_initial_camera = np.linalg.inv(self.initial_camera)
        require([(b[0], b[1]) for b in bones] == pack["bones"], "VRS/VRA bone identity/order mismatch")
        self.rest_globals, self.inverse_rests = [], []
        rest_errors = []
        for name, parent, local, _ in bones:
            require(parent < len(self.rest_globals), "runtime bones must be parent-first")
            world = self.rest_globals[parent] @ local if parent >= 0 else local
            self.rest_globals.append(world)
            self.inverse_rests.append(np.linalg.inv(world))
            rest_errors.append(max_position_error(world[:3, 3], (BASIS @ matrix(witness["source_rest_world"][name], name))[:3, 3]))
        self.rest_head_error = max(rest_errors)
        require(self.rest_head_error <= POSITION_LIMIT, "source/runtime rest head error exceeds 0.1 mm")
        self.actor_inverse_rest = [matrix(a["inverse_rest_global"], "actor inverse rest", columns=True) for a in pack["actors"]]
        self.mesh_actor = {}
        for index, actor in enumerate(pack["actors"]):
            require(actor["meshes"], "actor has no rigid geometry")
            for mesh in actor["meshes"]:
                require(mesh not in self.mesh_actor, "duplicate rigid mesh ownership")
                self.mesh_actor[mesh] = index
        require(set(self.mesh_actor) == set(range(len(rigid))), "rigid mesh ownership incomplete")
        self.skin_correspondence = None
        self.rigid_correspondence = {}
        if rigid_source is not None:
            for i, actor in enumerate(pack["actors"]):
                # This is geometry matching only, never a source oracle inferred
                # from VRM. The independently evaluated source-local frame-1
                # mesh also anchors actors whose frame-1 scale is zero.
                actual_local = transformed(np.concatenate([rigid[m] for m in actor["meshes"]]),
                                           BASIS.T @ self.actor_inverse_rest[i])
                self.rigid_correspondence[actor["name"]] = FixedCorrespondence(actual_local, rigid_source[actor["name"]])
        self.records = []

    def check(self, result, camera_sample, source, source_skin):
        index = len(self.records)
        require(index < SAMPLE_COUNT, "Rust sampler returned extra samples")
        frame, time = source["source_frame"], source["time_seconds"]
        require(result.get("clip") == ACTION and result.get("game_axis") is False, "Rust clip/basis mismatch")
        for field in ("time", "sample_time"):
            exact_time(result.get(field), time, "Rust pose " + field)
        source_camera = matrix(source["camera_world"], "source camera")
        camera = runtime_camera(camera_sample, time, self.initial_camera)
        source_delta = source_camera @ self.inverse_initial_camera
        runtime_delta = camera @ self.inverse_initial_camera
        require(np.max(np.abs(source_delta - matrix(source["camera_world_delta_from_frame1"], "declared source delta"))) <= 1e-5,
                "source common camera delta inconsistent")
        normalization = BASIS @ np.linalg.inv(source_delta)
        reconstruction = runtime_delta @ BASIS.T
        camera_relative = np.linalg.inv(camera) @ reconstruction
        inverse_source_camera = np.linalg.inv(source_camera)
        skin_samples = result.get("skin_meshes", [])
        require([s.get("mesh") for s in skin_samples] == list(range(len(self.skin_counts))), "Rust skin mesh identity/order mismatch")
        actual_skin = np.concatenate([finite(s.get("positions"), (count, 3), "Rust skin positions")
                                      for s, count in zip(skin_samples, self.skin_counts)])
        expected_skin = transformed(source_skin, normalization)
        if self.skin_correspondence is None:
            require(frame == 1, "skin correspondence must anchor at source frame 1")
            self.skin_correspondence = FixedCorrespondence(actual_skin, expected_skin)
        errors = {
            "skin_normalized_error_m": self.skin_correspondence.error(actual_skin, expected_skin),
            "skin_world_error_m": self.skin_correspondence.error(transformed(actual_skin, reconstruction), source_skin),
            "skin_camera_relative_error_m": self.skin_correspondence.error(transformed(actual_skin, camera_relative),
                                                                            transformed(source_skin, inverse_source_camera)),
            "camera_world_matrix_error": float(np.max(np.abs(camera - source_camera))),
            "camera_position_error_m": max_position_error(camera[:3, 3], source_camera[:3, 3]),
        }
        samples = result.get("bones", [])
        require([s.get("name") for s in samples] == [b[0] for b in self.bones], "Rust bone identity/order mismatch")
        bone_deformation, bone_heads, world_heads, camera_heads = [], [], [], []
        for i, sample in enumerate(samples):
            name = sample["name"]
            actual = matrix(sample.get("global"), "Rust bone " + name, columns=True)
            expected = normalization @ matrix(source["bone_deformation_world"][name], "source bone deformation") @ BASIS.T
            bone_deformation.append(float(np.max(np.abs(actual @ self.inverse_rests[i] - expected))))
            source_head = matrix(source["bone_world"][name], "source bone world")[:3, 3]
            bone_heads.append(max_position_error(actual[:3, 3], transformed(source_head, normalization)))
            world_heads.append(max_position_error(transformed(actual[:3, 3], reconstruction), source_head))
            camera_heads.append(max_position_error(transformed(actual[:3, 3], camera_relative), transformed(source_head, inverse_source_camera)))
        errors.update(bone_deformation_matrix_error=max(bone_deformation), bone_head_normalized_error_m=max(bone_heads),
                      bone_head_world_error_m=max(world_heads), bone_head_camera_relative_error_m=max(camera_heads))
        samples = result.get("actors", [])
        require([s.get("name") for s in samples] == list(ACTORS), "Rust actor identity/order mismatch")
        actual_visible, expected_visible, actor_errors, actor_world_errors, actor_camera_errors, actor_origins = [], [], [], [], [], []
        for i, sample in enumerate(samples):
            name, actor = sample["name"], self.pack["actors"][i]
            require(sample.get("mesh_indices") == actor["meshes"], "Rust actor mesh ownership mismatch")
            require(type(sample.get("visible")) is bool, "non-boolean Rust actor visibility")
            actual = matrix(sample.get("global"), "Rust actor global", columns=True)
            applied = matrix(sample.get("matrix"), "Rust actor applied", columns=True)
            require(np.max(np.abs(applied - actual @ self.actor_inverse_rest[i])) <= MATRIX_LIMIT,
                    "Rust applied actor matrix inconsistent with global/rest")
            source_world = matrix(source["actors_world"][name], "source actor world")
            source_relative = matrix(source["actors_camera_relative"][name], "source camera-relative actor")
            require(np.max(np.abs(source_relative - inverse_source_camera @ source_world)) <= MATRIX_LIMIT,
                    "source camera-relative actor matrix inconsistent")
            expected = normalization @ source_world @ BASIS.T
            visible = visible_matrix(source_world)
            expected_visible.append(visible)
            actual_visible.append(sample["visible"])
            if visible:
                actor_errors.append(float(np.max(np.abs(actual - expected))))
                actor_world_errors.append(float(np.max(np.abs(reconstruction @ actual @ BASIS - source_world))))
                actor_camera_errors.append(float(np.max(np.abs(camera_relative @ actual @ BASIS - source_relative))))
                actor_origins.append(max_position_error(actual[:3, 3], expected[:3, 3]))
        errors.update(actor_normalized_matrix_error=max(actor_errors, default=0), actor_world_matrix_error=max(actor_world_errors, default=0),
                      actor_camera_relative_matrix_error=max(actor_camera_errors, default=0), actor_origin_error_m=max(actor_origins, default=0))
        meshes = result.get("rigid_meshes", [])
        require([s.get("mesh") for s in meshes] == list(range(len(self.rigid))), "Rust rigid mesh identity/order mismatch")
        positions = []
        for m, sample in enumerate(meshes):
            owner = self.mesh_actor[m]
            require(type(sample.get("actor")) is int and sample["actor"] == owner, "Rust rigid actor owner mismatch")
            require(type(sample.get("visible")) is bool and sample["visible"] == actual_visible[owner], "Rust rigid visibility mismatch")
            positions.append(finite(sample.get("positions"), self.rigid[m].shape, "Rust rigid positions"))
        if self.rigid_source is not None:
            normalized_errors, world_errors, camera_errors = [], [], []
            for i, actor in enumerate(self.pack["actors"]):
                if not expected_visible[i]:
                    continue
                name = actor["name"]
                actual = np.concatenate([positions[m] for m in actor["meshes"]])
                source_world = transformed(self.rigid_source[name], matrix(source["actors_world"][name], name))
                mapping = self.rigid_correspondence[name]
                normalized_errors.append(mapping.error(actual, transformed(source_world, normalization)))
                world_errors.append(mapping.error(transformed(actual, reconstruction), source_world))
                camera_errors.append(mapping.error(transformed(actual, camera_relative), transformed(source_world, inverse_source_camera)))
            errors.update(rigid_normalized_error_m=max(normalized_errors, default=0), rigid_world_error_m=max(world_errors, default=0),
                          rigid_camera_relative_error_m=max(camera_errors, default=0))
        record = {"source_frame": frame, "requested_time_seconds": time, **errors,
                  "expected_visible": expected_visible, "actual_visible": actual_visible,
                  "visibility_matches": actual_visible == expected_visible}
        record["passed"] = record["visibility_matches"] and all(value <= (MATRIX_LIMIT if "matrix" in key else POSITION_LIMIT)
                                                                for key, value in errors.items())
        self.records.append(record)

    def summary(self):
        require(len(self.records) == SAMPLE_COUNT, f"Rust probes returned {len(self.records)} samples, expected {SAMPLE_COUNT}")
        keys = [k for k in self.records[0] if k.endswith(("_error_m", "_matrix_error"))]
        def correspondence(value):
            return {"index_maps_sha256": value.digest, "first_pose_error_m": value.initial_error,
                    "runtime_vertices": value.actual_shape[0], "source_vertices": value.expected_shape[0]}
        measured_pass = all(row["passed"] for row in self.records)
        return {"passed": measured_pass and self.rigid_source is not None, "measured_checks_passed": measured_pass,
                "complete": self.rigid_source is not None, "samples": len(self.records),
                "maxima": {k: max(r[k] for r in self.records) for k in keys},
                "worst_source_frame": {k: max(self.records, key=lambda r: r[k])["source_frame"] for k in keys},
                "canonical_bones_measured": len(self.bones), "source_skin_vertices_per_frame": sum(VERTEX_COUNTS),
                "runtime_skin_vertices_per_frame": sum(self.skin_counts), "runtime_source_rest_head_error_m": self.rest_head_error,
                "rigid_geometry_measured": self.rigid_source is not None,
                "visibility_failures": sum(not r["visibility_matches"] for r in self.records),
                "correspondence": {"kind": "fixed-frame1-bidirectional-nearest-neighbor", "per_frame_remapping": False,
                                   "skin": correspondence(self.skin_correspondence),
                                   "rigid_local": {name: correspondence(c) for name, c in self.rigid_correspondence.items()}},
                "records": self.records}


def rust_samples(command):
    """Yield one bounded-memory JSON row; always reap on errors or early close."""
    with tempfile.TemporaryFile(mode="w+t") as errors:
        with subprocess.Popen([str(v) for v in command], stdout=subprocess.PIPE, stderr=errors, text=True) as process:
            try:
                for line in process.stdout:
                    require(line.strip(), "empty Rust probe output line")
                    value = json_loads(line)
                    require(isinstance(value, dict), "Rust probe row must be an object")
                    yield value
                code = process.wait()
                errors.seek(0)
                require(code == 0, f"Rust probe failed ({code}): {errors.read(4000)}")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def rust_sample_batches(prefix, times, suffix=(), max_samples=256, max_units=24000):
    """Keep exact clock/order while fitting Windows' UTF-16 command-line bound.

    Each actual Rust process loads the same immutable companions. A batch failure
    remains fatal and no sample is omitted, rounded, substituted or interpolated.
    """
    require(type(max_samples) is int and 1 <= max_samples <= 256, "invalid probe batch size")
    require(type(max_units) is int and 1024 <= max_units <= 24000, "invalid probe command bound")
    prefix, suffix = list(map(str, prefix)), list(map(str, suffix))
    batch = []
    def units(values):
        return len(subprocess.list2cmdline(values).encode("utf-16-le")) // 2 + 1
    for time in times:
        value = str(time)
        require(units(prefix + [value] + suffix) <= max_units, "single probe exceeds Windows command bound")
        if batch and (len(batch) >= max_samples or units(prefix + batch + [value] + suffix) > max_units):
            with closing(rust_samples(prefix + batch + suffix)) as samples:
                yield from samples
            batch = []
        batch.append(value)
    if batch:
        with closing(rust_samples(prefix + batch + suffix)) as samples:
            yield from samples


def verify(args, report):
    source = args.source_witnesses.resolve()
    index_path = source / "source-samples.json"
    provenance = None
    export_root = source
    index_sha, oracle_source_sha, runtime_source_sha = ORACLE_SHA, SOURCE_SHA, SOURCE_SHA
    fbx_sha, evidence_pins = FBX_SHA, EVIDENCE_PINS
    if getattr(args, "regenerated_provenance", None) is not None:
        from prone_r15_regenerated_contract import load_runtime_provenance
        provenance = load_runtime_provenance(args.regenerated_provenance, args.regenerated_provenance_sha256,
                                             args.generated_source, args.source_equivalence, args.source_equivalence_sha256)
        require(args.export_witnesses is not None, "regenerated provenance requires independent export witnesses")
        export_root = args.export_witnesses.resolve()
        index_sha = provenance["source_witness_sha256"]
        oracle_source_sha = provenance["source_witness_source_sha256"]
        runtime_source_sha = provenance["generated_source_sha256"]
        fbx_sha, evidence_pins = provenance["source_fbx_sha256"], provenance["export_evidence_sha256"]
        require(args.rigid_witness is not None and args.rigid_witness_sha256 == provenance["rigid_witness_sha256"],
                "regenerated verification requires the pinned independent rigid oracle")
        report["regenerated_source_provenance"] = provenance
    else:
        require(not any(getattr(args, name, None) is not None for name in
                        ("regenerated_provenance_sha256", "generated_source", "source_equivalence",
                         "source_equivalence_sha256", "export_witnesses")), "partial regenerated provenance is forbidden")
    witness = load_hashed_json(index_path, index_sha)
    canonical = vrview.decode_vra(hashed_bytes(args.skeleton_vra, CANONICAL_SHA))["bones"]
    grid = validate_source(witness, canonical, source_sha256=oracle_source_sha)
    export_verified = {**evidence_pins, ACTION + ".fbx": fbx_sha}
    verified = {"source-samples.json": index_sha, **export_verified}
    for name, digest in export_verified.items():
        pinned(export_root / name, digest)
    receipt = load_hashed_json(export_root / "export-receipt.json", evidence_pins["export-receipt.json"])
    require(receipt.get("source_sample_count") == SAMPLE_COUNT and receipt.get("sample_grid_sha256") == GRID_SHA,
            "export receipt sample grid mismatch")
    parity = load_hashed_json(export_root / "fresh-import-parity.json", evidence_pins["fresh-import-parity.json"])
    require(parity.get("passed") is True and parity.get("samples") == SAMPLE_COUNT, "independent fresh FBX gate did not pass")
    if provenance is not None:
        from prone_r15_regenerated_contract import validate_dense_evidence
        validate_dense_evidence(receipt, parity, provenance)
    require(args.asset.name == "asset.vra", "expected converter output asset.vra")
    names = ["asset.vra", "asset.vrs", "asset.vrm", "asset.prone-camera.json", "asset.prone-pair.json"]
    blobs = {name: (args.asset.parent / name).read_bytes() for name in names}
    hashes = {name: hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()}
    pack = vrview.decode_vra(blobs["asset.vra"], vrs=blobs["asset.vrs"], vrm=blobs["asset.vrm"])
    manifest_path = args.asset.parent / "manifest.json"
    manifest_hash = sha256(manifest_path)
    validate_manifest(load_hashed_json(manifest_path, manifest_hash), pack, blobs, canonical,
                      source_sha256=runtime_source_sha, fbx_sha256=fbx_sha)
    camera = validate_pair(blobs, provenance)
    bones, skin_counts, rigid = read_geometry(blobs["asset.vrs"], blobs["asset.vrm"])
    first, _ = load_source_row(source, next(iter(witness["frames"].values())), witness["source_rest_world"])
    require(np.max(np.abs(matrix(first["camera_world"], "initial source camera")
                          - matrix(camera["initial_camera_world"], "initial runtime camera"))) <= MATRIX_LIMIT,
            "source and runtime initial cameras differ")
    rigid_source = None
    if args.rigid_witness is not None:
        require(args.rigid_witness_sha256 is not None, "rigid witness needs independently recorded --rigid-witness-sha256")
        rigid_source = validate_rigid(load_hashed_json(args.rigid_witness, args.rigid_witness_sha256), grid, first, source_sha256=oracle_source_sha)
    else:
        report["not_measured"].append("Independent rigid geometry is absent; this run cannot be complete or pass")
    checker = ParityChecker(pack, bones, skin_counts, rigid, witness, camera, rigid_source)
    report.update(verified_inputs=verified, asset_sha256=hashes, manifest_sha256=manifest_hash,
                  sampler_sha256=sha256(args.sampler), camera_sampler_sha256=sha256(args.camera_sampler),
                  rigid_witness_sha256=args.rigid_witness_sha256, records=checker.records,
                  clock={"source_frames_inclusive": [1, 69], "fps": 60, "runtime_hz": 3840,
                         "runtime_keys": RUNTIME_KEYS, "source_oracle_samples": SAMPLE_COUNT,
                         "grid_sha256": GRID_SHA, "loop": False})
    times = [repr((frame - 1) / 60) for frame in grid]
    animation_command = [args.sampler.resolve(), args.asset.resolve(), ACTION]
    camera_command = [args.camera_sampler.resolve(), args.asset.resolve(), (args.asset.parent / "asset.prone-camera.json").resolve(),
                      (args.asset.parent / "asset.prone-pair.json").resolve(), ACTION]
    with closing(rust_sample_batches(animation_command, times, ["--clamp"])) as poses, closing(rust_sample_batches(camera_command, times)) as cameras:
        for descriptor in witness["frames"].values():
            pose, sampled_camera = next(poses, None), next(cameras, None)
            require(pose is not None and sampled_camera is not None, "Rust probe ended before all 1,944 samples")
            source_row, source_skin = load_source_row(source, descriptor, witness["source_rest_world"])
            checker.check(pose, sampled_camera, source_row, source_skin)
            if len(checker.records) % 128 == 0:
                print(f"PRONE_PARITY {len(checker.records)}/{SAMPLE_COUNT} "
                      f"failed_samples={sum(not r['passed'] for r in checker.records)} "
                      f"max_skin_m={max(r['skin_normalized_error_m'] for r in checker.records):.9g}",
                      file=sys.stderr, flush=True)
        require(next(poses, None) is None and next(cameras, None) is None, "Rust probe returned extra samples")
    report.update(checker.summary())
    # Recheck immutable inputs after subprocesses independently open companions.
    for name, digest in hashes.items():
        pinned(args.asset.parent / name, digest)
    pinned(manifest_path, manifest_hash)
    pinned(args.sampler, report["sampler_sha256"])
    pinned(args.camera_sampler, report["camera_sampler_sha256"])
    pinned(args.skeleton_vra, CANONICAL_SHA)
    pinned(Path(__file__), report["verifier_sha256"])
    pinned(index_path, index_sha)
    for name, digest in export_verified.items():
        pinned(export_root / name, digest)
    if provenance is not None:
        load_runtime_provenance(args.regenerated_provenance, args.regenerated_provenance_sha256,
                                args.generated_source, args.source_equivalence, args.source_equivalence_sha256)
    if args.rigid_witness is not None:
        pinned(args.rigid_witness, args.rigid_witness_sha256)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", type=Path)
    parser.add_argument("source_witnesses", type=Path)
    parser.add_argument("--sampler", type=Path, required=True)
    parser.add_argument("--camera-sampler", type=Path, required=True)
    parser.add_argument("--skeleton-vra", type=Path, required=True)
    parser.add_argument("--rigid-witness", type=Path)
    parser.add_argument("--rigid-witness-sha256", dest="rigid_witness_sha256")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--regenerated-provenance", type=Path)
    parser.add_argument("--regenerated-provenance-sha256")
    parser.add_argument("--generated-source", type=Path)
    parser.add_argument("--source-equivalence", type=Path)
    parser.add_argument("--source-equivalence-sha256")
    parser.add_argument("--export-witnesses", type=Path)
    args = parser.parse_args(argv)
    protected = [args.sampler.resolve(), args.camera_sampler.resolve(), args.skeleton_vra.resolve(), Path(__file__).resolve()]
    protected += [(args.asset.parent / name).resolve() for name in ("asset.vra", "asset.vrs", "asset.vrm", "manifest.json",
                                                                   "asset.prone-camera.json", "asset.prone-pair.json")]
    if args.rigid_witness is not None:
        protected.append(args.rigid_witness.resolve())
    protected += [value.resolve() for value in (args.regenerated_provenance, args.generated_source, args.source_equivalence)
                  if value is not None]
    require(args.export_witnesses is None or not args.report.resolve().is_relative_to(args.export_witnesses.resolve()),
            "report must not enter immutable export evidence")
    require(args.report.resolve() not in protected and not args.report.resolve().is_relative_to(args.source_witnesses.resolve()),
            "report must not overwrite or enter immutable input paths")
    report = {"schema": "rust-duty-prone-r15-cpu-parity/v1", "backend": "actual Rust CPU animation and camera probes",
              "verifier_sha256": sha256(__file__), "passed": False, "complete": False,
              "runtime_approved": False, "artistic_approval": False, "runtime_activated": False,
              "position_limit_m": POSITION_LIMIT, "matrix_element_limit": MATRIX_LIMIT,
              "common_motion_removal": pair.REMOVAL,
              "basis": {"mapping": "Blender (X,Z,-Y) to glTF", "matrix": BASIS.tolist()},
              "not_measured": ["Arbitrary continuous times outside the independently evaluated 1,944-sample oracle",
                               "GPU execution, rasterized appearance, triangle connectivity, textures, normals, UVs, and runtime projection",
                               "76 unweighted helper bones outside the 72-bone runtime canonical closure",
                               "Gameplay traversal, stance transition behavior, camera collision, visual acceptance, or activation"]}
    try:
        verify(args, report)
    except Exception as exc:
        report.update(passed=False, complete=False, error=f"{type(exc).__name__}: {exc}")
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "records"}, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
