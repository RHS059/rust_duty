"""Source-free, opt-in prone r6 camera/foreground pairing contracts.

All matrices here are row-major Blender-world matrices. Common motion is
removed before the importer's existing Blender-to-glTF basis conversion.
This module does not import Blender, read private assets, or render anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json

import vrpack
from vrpack import require


SIDECAR_SCHEMA = 'prone-entry-r6-camera-motion/v1'
RECEIPT_SCHEMA = 'rust-duty-prone-camera-pair/v1'
RIG_ACTION = 'prone_crawl_enter_r6'
CAMERA_ACTION = 'prone_crawl_enter_camera_r6'
REMOVAL = 'inverse(C(t)*inverse(C0))*evaluated_global_before_blender_to_gltf'
MATRIX_TOLERANCE = 1e-5
MAX_SIDECAR_BYTES = 2 * 1024 * 1024


def sha256(value, label):
    require(isinstance(value, str) and len(value) == 64 and
            all(c in '0123456789abcdef' for c in value),
            f'{label} must be a lowercase SHA256')
    return value


def affine_matrix(value, label):
    """Accept flat row-major arrays or four rows; reject non-finite entries."""
    require(isinstance(value, (list, tuple)), f'{label} must be a matrix')
    if len(value) == 4:
        require(all(isinstance(r, (list, tuple)) and len(r) == 4 for r in value),
                f'{label} must have four rows of four numbers')
        value = tuple(x for row in value for x in row)
    require(len(value) == 16, f'{label} must contain 16 numbers')
    result = tuple(vrpack.number(x, label) for x in value)
    require(max(abs(a-b) for a, b in zip(result[12:], (0, 0, 0, 1))) <= 1e-8,
            f'{label} must be affine')
    return result


def rigid_matrix(value, label='camera matrix'):
    result = affine_matrix(value, label)
    for a in range(3):
        for b in range(3):
            dot = sum(result[r*4+a] * result[r*4+b] for r in range(3))
            require(abs(dot - int(a == b)) <= MATRIX_TOLERANCE,
                    f'{label} must be rigid (no scale or shear)')
    require(abs(vrpack.determinant(result) - 1) <= MATRIX_TOLERANCE,
            f'{label} must be a proper rotation (no reflection)')
    return result


def inverse_rigid(value):
    m = rigid_matrix(value)
    result = list(vrpack.IDENTITY)
    for r in range(3):
        for c in range(3):
            result[r*4+c] = m[c*4+r]
        result[r*4+3] = -sum(m[c*4+r] * m[c*4+3] for c in range(3))
    return tuple(result)


def common_world_delta(camera_world, initial_camera_world):
    """D(t) = C(t) * inverse(C0), with validated rigid camera matrices."""
    return vrpack.matmul(rigid_matrix(camera_world), inverse_rigid(initial_camera_world))


def remove_common_motion(evaluated_global, delta):
    """Undo one common world transform; preserves any bone-local motion/scale.

    Zero-scale rigid actors remain zero-scale, retaining the importer's existing
    visibility sentinel. They are not replaced with a visible identity here.
    """
    return vrpack.matmul(inverse_rigid(delta),
                        affine_matrix(evaluated_global, 'evaluated global'))


def verify_armature_motion(evaluated_world, delta, canonical_world):
    """Reject fixed/already-normalized FBX object tracks instead of stripping twice."""
    normalized = remove_common_motion(evaluated_world, delta)
    canonical = affine_matrix(canonical_world, 'canonical armature world')
    require(max(abs(a-b) for a, b in zip(normalized, canonical)) < 1e-4,
            'paired FBX armature does not carry the declared common world motion')


def restore_canonical_worlds(objects, canonical_worlds, matrix_factory, update):
    """Restore explicit rest worlds in parent-first order, including skin nodes.

    Called after clearing animation and selecting armature REST mode. The
    caller supplies Blender's Matrix and dependency-graph update; tests can
    exercise this orchestration without importing Blender.
    """
    objects = list(objects)
    require(len({o.name for o in objects}) == len(objects), 'duplicate rest object')
    require(set(canonical_worlds) == {o.name for o in objects},
            'canonical rest object set mismatch')
    remaining = list(objects)
    while remaining:
        remaining_names = {o.name for o in remaining}
        ready = [o for o in remaining if o.parent is None or o.parent.name not in remaining_names]
        require(ready, 'cyclic rest object parenting')
        for obj in ready:
            values = affine_matrix(canonical_worlds[obj.name], 'canonical rest world')
            obj.matrix_world = matrix_factory([values[i:i+4] for i in range(0, 16, 4)])
            remaining.remove(obj)
        update()
    for obj in objects:
        actual = tuple(float(v) for row in obj.matrix_world for v in row)
        require(max(abs(a-b) for a, b in zip(actual, canonical_worlds[obj.name])) <= MATRIX_TOLERANCE,
                f'canonical initial rest world was not restored: {obj.name}')


@dataclass(frozen=True)
class CameraPair:
    sidecar_bytes: bytes
    sidecar_sha256: str
    candidate_sha256: str
    action_fingerprints: dict
    deltas: dict
    native_start: int
    native_end: int
    candidate_frame_offset: int

    def delta_at(self, native_frame):
        candidate = Fraction(native_frame) + self.candidate_frame_offset
        require(candidate in self.deltas,
                f'candidate frame {candidate} has no exact camera sample; no interpolation is permitted')
        return self.deltas[candidate]

    def receipt(self, vra_bytes, source_fbx_sha256, clip_name):
        require(isinstance(vra_bytes, bytes) and vra_bytes, 'receipt requires encoded VRA bytes')
        require(isinstance(clip_name, str) and clip_name, 'receipt requires clip name')
        return {
            'schema': RECEIPT_SCHEMA,
            'asset_vra_sha256': hashlib.sha256(vra_bytes).hexdigest(),
            'camera_sidecar_sha256': self.sidecar_sha256,
            'candidate_sha256': self.candidate_sha256,
            'action_fingerprints': dict(self.action_fingerprints),
            'source_fbx_sha256': sha256(source_fbx_sha256, 'source FBX hash'),
            'clip_name': clip_name,
            'native_crop': [self.native_start, self.native_end],
            'native_fps': [60, 1],
            'candidate_frame_offset': self.candidate_frame_offset,
            'candidate_frame_range': [1, 69],
            'common_motion_removal': REMOVAL,
            'canonical_rest_frame': 1,
        }


def load_camera_pair(sidecar_bytes, *, expected_sidecar_sha256, candidate_sha256,
                     action_fingerprints, native_start, native_end, fps,
                     candidate_frame_offset, frames):
    """Verify immutable input identity, exact timing and every camera/delta pair."""
    require(isinstance(sidecar_bytes, bytes) and 0 < len(sidecar_bytes) <= MAX_SIDECAR_BYTES,
            'camera sidecar must be bytes within 2 MiB')
    require(hashlib.sha256(sidecar_bytes).hexdigest() ==
            sha256(expected_sidecar_sha256, 'camera sidecar hash'), 'camera sidecar hash mismatch')
    try:
        document = json.loads(sidecar_bytes.decode('utf-8'),
                              object_pairs_hook=vrpack._no_duplicate_keys,
                              parse_constant=vrpack._bad_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise vrpack.AssetError(f'invalid camera sidecar: {exc}') from exc
    require(isinstance(document, dict) and document.get('schema') == SIDECAR_SCHEMA,
            'invalid prone camera sidecar schema')
    candidate_sha256 = sha256(candidate_sha256, 'candidate hash')
    require(document.get('candidate_sha256') == candidate_sha256, 'camera candidate hash mismatch')
    require(isinstance(action_fingerprints, dict) and
            set(action_fingerprints) == {RIG_ACTION, CAMERA_ACTION},
            'both paired Action fingerprints are required')
    for name, fingerprint in action_fingerprints.items():
        sha256(fingerprint, name + ' fingerprint')
    require(document.get('action_fingerprints') == action_fingerprints,
            'camera Action fingerprint mismatch')
    require(type(native_start) is int and type(native_end) is int and
            type(candidate_frame_offset) is int and native_start >= 0 and
            native_start + candidate_frame_offset == 1 and
            native_end + candidate_frame_offset == 69,
            'paired clip requires explicit complete candidate frame range 1..69')
    require(fps == Fraction(60) and document.get('fps') == 60 and
            document.get('sample_hz') == 480, 'paired camera requires 60 fps and 480 Hz source samples')
    require(document.get('units') == 'metres and radians; Blender world +Z up' and
            document.get('camera_local_axes') == '+X right, +Y up, -Z forward',
            'paired camera coordinate convention mismatch')
    require(abs(vrpack.number(document.get('duration_key_span_seconds'), 'camera key span') - 68/60) <= 1e-8,
            'paired camera key span must be 68/60 seconds')
    initial = rigid_matrix(document.get('initial_camera_world'), 'initial camera world')
    rows = document.get('rows')
    require(isinstance(rows, list) and len(rows) == 545, 'camera requires all 545 samples')
    deltas = {}
    for i, row in enumerate(rows):
        require(isinstance(row, dict), 'camera sample must be an object')
        candidate = Fraction(1) + Fraction(i, 8)
        require(vrpack.number(row.get('candidate_frame'), 'candidate frame') == float(candidate),
                'camera samples must follow the exact 1..69 frame grid')
        require(abs(vrpack.number(row.get('time_seconds'), 'camera sample time') - i/480) <= 1e-8,
                'camera sample time/frame mapping mismatch')
        expected = common_world_delta(row.get('camera_world'), initial)
        declared = rigid_matrix(row.get('common_world_delta'), 'common world delta')
        require(max(abs(a-b) for a, b in zip(expected, declared)) <= MATRIX_TOLERANCE,
                'common world delta differs from C(t)*inverse(C0)')
        # Recompute from the validated camera values; do not trust an unrelated
        # declared delta merely because it is a plausible rigid transform.
        deltas[candidate] = expected
    pair = CameraPair(sidecar_bytes, expected_sidecar_sha256, candidate_sha256,
                      dict(action_fingerprints), deltas, native_start, native_end,
                      candidate_frame_offset)
    frames = list(frames)
    require(frames and frames[0] == native_start and frames[-1] == native_end and
            all(b > a for a, b in zip(frames, frames[1:])),
            'paired samples must span the complete increasing native crop')
    for frame in frames:
        pair.delta_at(frame)
    return pair
