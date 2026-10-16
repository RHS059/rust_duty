"""Source-free, opt-in prone r6 camera/foreground pairing contracts.

All matrices here are row-major Blender-world matrices. Common motion is
removed before the importer's existing Blender-to-glTF basis conversion.
This module does not import Blender, read private assets, or render anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import copy
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
MAX_SIDECAR_BYTES = 16 * 1024 * 1024
R15_SIDECAR_SCHEMA = 'prone-entry-r15-camera-motion/v1'
R15_RECEIPT_SCHEMA = 'rust-duty-prone-camera-pair/v2'
R15_REGENERATED_SIDECAR_SCHEMA = 'prone-entry-r15-camera-motion/v2'
R15_REGENERATED_RECEIPT_SCHEMA = 'rust-duty-prone-camera-pair/v3'
R15_RIG_ACTION = 'aella_prone_crawl_enter_r15_roll_v1'
R15_CAMERA_ACTION = 'aella_prone_crawl_enter_camera_r9_viewray_v3'
R15_SOURCE_SHA = 'cbed3051bb8c4bbdb78f72a49a7a51bd585db33636ddc5312dde38b05a2a86c4'
R15_FINGERPRINTS = {
    R15_RIG_ACTION: '93ffbed2bd91d33bb2d6e1788ce3c3d95f915c228b8ce7f3c17af05b265c9640',
    R15_CAMERA_ACTION: '6872ef8f4301690dfd340ec9479f4a533fba743f1dc23b6a3691cd85c9e08844',
}
# Hash-only, reviewed evidence pins shared with the Rust receipt consumer. This
# contract covers one exact replay recipe and strict 1,944-sample motion witness.
# A new recipe or approved motion requires an explicit source revision.
R15_EQUIVALENCE_CONTRACT = json.loads(
    Path(__file__).with_name('prone_r15_equivalence_contract.json').read_text())
R15_EQUIVALENCE_DYNAMIC_FIELDS = frozenset((
    'generated_source_sha256', 'source_equivalence_sha256',
    'regenerated_witness_sha256', 'replay_receipt_sha256'))


def validate_r15_equivalence_descriptor(descriptor, candidate_sha256):
    """Validate a bounded, exact contract, not a self-asserted pass boolean.

    The runtime consumes this checked evidence binding; it cannot reopen BLEND.
    The source-proof pipeline separately measures and compares both witnesses.
    """
    candidate_sha256 = sha256(candidate_sha256, 'generated source hash')
    require(candidate_sha256 not in (R15_SOURCE_SHA, R15_EQUIVALENCE_CONTRACT['base_sha256']),
            'regenerated source identity must be distinct from original and base')
    require(isinstance(descriptor, dict) and
            set(descriptor) == set(R15_EQUIVALENCE_CONTRACT) | R15_EQUIVALENCE_DYNAMIC_FIELDS,
            'missing or unsupported r15 source equivalence descriptor')
    for key, expected in R15_EQUIVALENCE_CONTRACT.items():
        # Canonical JSON equality also rejects True standing in for an integer.
        require(json.dumps(descriptor[key], sort_keys=True, allow_nan=False) ==
                json.dumps(expected, sort_keys=True, allow_nan=False),
                'r15 source equivalence contract mismatch: ' + key)
    for key in R15_EQUIVALENCE_DYNAMIC_FIELDS:
        sha256(descriptor[key], key)
    require(descriptor['generated_source_sha256'] == candidate_sha256,
            'r15 source equivalence generated source mismatch')
    require(descriptor['regenerated_witness_sha256'] != descriptor['approved_witness_sha256'],
            'r15 source equivalence reuses the original witness')
    return copy.deepcopy(descriptor)


def r15_equivalence_descriptor(report, report_sha256, candidate_sha256):
    """Bind an explicitly pinned strict comparison report to actual source bytes."""
    sha256(report_sha256, 'source equivalence report hash')
    require(isinstance(report, dict) and
            report.get('schema') == 'rust-duty-prone-r15-source-equivalence/v1',
            'unsupported r15 source equivalence report')
    for key in ('passed', 'exact_complete_actions_proved', 'non_action_preservation_proved',
                'evaluated_pair_equivalence_proved'):
        require(report.get(key) is True, 'r15 source equivalence incomplete: ' + key)
    for key in ('source_byte_identity_with_approved', 'runtime_equivalence_proved', 'rendered'):
        require(report.get(key) is False, 'r15 source equivalence scope differs: ' + key)
    require(report.get('rig_action') == R15_RIG_ACTION and
            report.get('camera_action') == R15_CAMERA_ACTION and
            report.get('rig_action_fingerprint') == R15_FINGERPRINTS[R15_RIG_ACTION] and
            report.get('camera_action_fingerprint') == R15_FINGERPRINTS[R15_CAMERA_ACTION],
            'r15 source equivalence paired Actions differ')
    evidence = report.get('evidence_sha256')
    require(isinstance(evidence, dict) and set(evidence) == {
        'approved_witness', 'regenerated_witness', 'replay_receipt', 'delta'},
        'r15 source equivalence evidence is missing')
    for key, value in evidence.items():
        sha256(value, key + ' evidence hash')
    descriptor = {key: report.get(key) for key in R15_EQUIVALENCE_CONTRACT}
    descriptor.update(
        schema=R15_EQUIVALENCE_CONTRACT['schema'],
        recipe_sha256=report.get('delta_sha256'),
        approved_witness_sha256=evidence['approved_witness'],
        action_fingerprints={R15_RIG_ACTION: report.get('rig_action_fingerprint'),
                             R15_CAMERA_ACTION: report.get('camera_action_fingerprint')},
        generated_source_sha256=report.get('generated_source_sha256'),
        source_equivalence_sha256=report_sha256,
        regenerated_witness_sha256=evidence['regenerated_witness'],
        replay_receipt_sha256=evidence['replay_receipt'])
    require(evidence['delta'] == descriptor['recipe_sha256'],
            'r15 source equivalence recipe evidence differs')
    return validate_r15_equivalence_descriptor(descriptor, candidate_sha256)


def load_r15_equivalence_report(path, expected_sha256, candidate_sha256):
    """Read only an explicit small report whose actual byte hash is pinned."""
    sha256(expected_sha256, 'source equivalence report hash')
    with Path(path).open('rb') as stream:
        data = stream.read(65537)
    require(0 < len(data) <= 65536, 'r15 source equivalence report exceeds file bound')
    require(hashlib.sha256(data).hexdigest() == expected_sha256,
            'r15 source equivalence report hash mismatch')
    try:
        report = json.loads(data, object_pairs_hook=vrpack._no_duplicate_keys,
                            parse_constant=vrpack._bad_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise vrpack.AssetError(f'invalid r15 source equivalence report: {exc}') from exc
    return r15_equivalence_descriptor(report, expected_sha256, candidate_sha256)

def action_names_for_clip(clip):
    require(clip in (RIG_ACTION, R15_RIG_ACTION), 'unknown paired prone clip')
    return (RIG_ACTION, CAMERA_ACTION) if clip == RIG_ACTION else (R15_RIG_ACTION, R15_CAMERA_ACTION)


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
    sample_hz: int = 480
    sidecar_schema: str = SIDECAR_SCHEMA
    source_equivalence: dict | None = None

    def delta_at(self, native_frame):
        candidate = Fraction(native_frame) + self.candidate_frame_offset
        require(candidate in self.deltas,
                f'candidate frame {candidate} has no exact camera sample; no interpolation is permitted')
        return self.deltas[candidate]

    def receipt(self, vra_bytes, source_fbx_sha256, clip_name):
        require(isinstance(vra_bytes, bytes) and vra_bytes, 'receipt requires encoded VRA bytes')
        require(isinstance(clip_name, str) and clip_name, 'receipt requires clip name')
        receipt = {
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
        if self.sidecar_schema in (R15_SIDECAR_SCHEMA, R15_REGENERATED_SIDECAR_SCHEMA):
            receipt.update(schema=R15_RECEIPT_SCHEMA, camera_sample_hz=self.sample_hz,
                           source_rig_action=R15_RIG_ACTION, source_camera_action=R15_CAMERA_ACTION)
        if self.sidecar_schema == R15_REGENERATED_SIDECAR_SCHEMA:
            receipt.update(schema=R15_REGENERATED_RECEIPT_SCHEMA,
                           source_equivalence=validate_r15_equivalence_descriptor(
                               self.source_equivalence, self.candidate_sha256))
        return receipt


def load_camera_pair(sidecar_bytes, *, expected_sidecar_sha256, candidate_sha256,
                     action_fingerprints, native_start, native_end, fps,
                     candidate_frame_offset, frames):
    """Verify immutable input identity, exact timing and every camera/delta pair."""
    require(isinstance(sidecar_bytes, bytes) and 0 < len(sidecar_bytes) <= MAX_SIDECAR_BYTES,
            'camera sidecar must be bytes within 16 MiB')
    require(hashlib.sha256(sidecar_bytes).hexdigest() ==
            sha256(expected_sidecar_sha256, 'camera sidecar hash'), 'camera sidecar hash mismatch')
    try:
        document = json.loads(sidecar_bytes.decode('utf-8'),
                              object_pairs_hook=vrpack._no_duplicate_keys,
                              parse_constant=vrpack._bad_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise vrpack.AssetError(f'invalid camera sidecar: {exc}') from exc
    require(isinstance(document, dict) and document.get('schema') in (
            SIDECAR_SCHEMA, R15_SIDECAR_SCHEMA, R15_REGENERATED_SIDECAR_SCHEMA),
            'invalid prone camera sidecar schema')
    is_regenerated = document['schema'] == R15_REGENERATED_SIDECAR_SCHEMA
    is_r15 = document['schema'] in (R15_SIDECAR_SCHEMA, R15_REGENERATED_SIDECAR_SCHEMA)
    require(is_r15 or len(sidecar_bytes) <= 2 * 1024 * 1024, 'r6 sidecar exceeds 2 MiB')
    subdivision = 64 if is_r15 else 8
    sample_hz = 60 * subdivision
    rig_action, camera_action = (R15_RIG_ACTION, R15_CAMERA_ACTION) if is_r15 else (RIG_ACTION, CAMERA_ACTION)
    candidate_sha256 = sha256(candidate_sha256, 'candidate hash')
    require(document.get('candidate_sha256') == candidate_sha256, 'camera candidate hash mismatch')
    require(isinstance(action_fingerprints, dict) and
            set(action_fingerprints) == {rig_action, camera_action},
            'both paired Action fingerprints are required')
    for name, fingerprint in action_fingerprints.items():
        sha256(fingerprint, name + ' fingerprint')
    source_equivalence = None
    if is_r15:
        require(action_fingerprints == R15_FINGERPRINTS,
                'r15 requires the exact approved source and paired Actions')
        if is_regenerated:
            source_equivalence = validate_r15_equivalence_descriptor(
                document.get('source_equivalence'), candidate_sha256)
        else:
            require(candidate_sha256 == R15_SOURCE_SHA and 'source_equivalence' not in document,
                    'r15 requires the exact approved source and paired Actions')
    require(document.get('action_fingerprints') == action_fingerprints,
            'camera Action fingerprint mismatch')
    require(type(native_start) is int and type(native_end) is int and
            type(candidate_frame_offset) is int and native_start >= 0 and
            native_start + candidate_frame_offset == 1 and
            native_end + candidate_frame_offset == 69,
            'paired clip requires explicit complete candidate frame range 1..69')
    if is_regenerated:
        require((native_start, native_end, candidate_frame_offset) == (0, 68, 1),
                'regenerated r15 requires native crop 0..68 and source offset 1')
    require(fps == Fraction(60) and document.get('fps') == 60 and
            document.get('sample_hz') == sample_hz, 'paired camera sample clock mismatch')
    require(document.get('units') == 'metres and radians; Blender world +Z up' and
            document.get('camera_local_axes') == '+X right, +Y up, -Z forward',
            'paired camera coordinate convention mismatch')
    require(abs(vrpack.number(document.get('duration_key_span_seconds'), 'camera key span') - 68/60) <= 1e-8,
            'paired camera key span must be 68/60 seconds')
    initial = rigid_matrix(document.get('initial_camera_world'), 'initial camera world')
    rows = document.get('rows')
    require(isinstance(rows, list) and len(rows) == 68 * subdivision + 1, 'camera requires every sample of the declared grid')
    deltas = {}
    for i, row in enumerate(rows):
        require(isinstance(row, dict), 'camera sample must be an object')
        candidate = Fraction(1) + Fraction(i, subdivision)
        require(vrpack.number(row.get('candidate_frame'), 'candidate frame') == float(candidate),
                'camera samples must follow the exact 1..69 frame grid')
        require(abs(vrpack.number(row.get('time_seconds'), 'camera sample time') - i/sample_hz) <= 1e-8,
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
                      candidate_frame_offset, sample_hz, document['schema'], source_equivalence)
    frames = list(frames)
    require(frames and frames[0] == native_start and frames[-1] == native_end and
            all(b > a for a, b in zip(frames, frames[1:])),
            'paired samples must span the complete increasing native crop')
    for frame in frames:
        pair.delta_at(frame)
    return pair
