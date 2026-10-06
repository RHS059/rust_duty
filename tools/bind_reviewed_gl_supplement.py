#!/usr/bin/env python3
"""Ingest the reviewed, fixed-capture GL supplement without granting acceptance.

The hard-coded digests are review anchors, not values supplied by the packet.
This is deliberately not a reusable native-profile gate. See the accompanying
engineering note for the still-separate native input/execution obligations.
"""
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import ads_source_visibility_binding as source


FRAME_IDS = (17, 18, 19, 20, 58, 59, 60, 61, 77, 78, 79, 80, 81, 82, 83, 84, 85,
             163, 164, 165, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 216,
             217, 258, 259, 315, 316, 317, 318, 319, 320, 321, 322, 414, 415, 467,
             468, 469, 517, 518, 519)
_REVIEWED_SHA256 = {
    'source_receipt': '241bb21d23bb711daaff9dac33b75b504e1c69104fa0949099b38f0f86453370',
    'native_source': '93d730d84e5f0055cd51e4e613f7210974ae7a4682bdb7e7f8e246d3ad1227ca',
    'geometry': '458655709d010fd004eccc04234094ec09d66428e286e47c892ab5578d9a3204',
    'fragment': 'edaecbca5d3a485187a02d2662588170b32b6df59f9e1cc1e032ebfc99648696',
}
_REVIEWED_COUNTS = (49716, 47558, 4, 53473, 1487)
SOURCE_FALSE_FLAGS = ('backend_native_upload_identity_verified',
                      'native_invocation_binding_verified',
                      'profile_assumptions_independently_established', 'profile_native_verified')
GEOMETRY_HEADER = {
    'schema': 'rust-duty-bounded-geometry-supplement/v1',
    'backend_implementation': 'Mesa26.2.4 draw_pipe_clip float32 operational profile; not a native-execution observation',
    'native_profile_binding_verified': False, 'acceptance_verdict': None,
}
Run = tuple[int, int]


@dataclass(frozen=True)
class EvidenceContext:
    source_commit: str
    run_id: str
    run_attempt: str

    def __post_init__(self):
        source.shared._validate_context(asdict(self))


CAPTURE_CONTEXT = EvidenceContext('8f571464be706d0abde862e124582a188f633baf', '37415102452', '1')
SOURCE_CONTEXT = EvidenceContext('371bca3d848f5b749cf9ea989fa1fbfaca8c20cc', '37427554951', '1')


@dataclass(frozen=True)
class ConditionalGlFrame:
    frame: int
    required_runs: tuple[Run, ...]
    possible_runs: tuple[Run, ...]
    required_before_fragment: int
    required_after_fragment: int
    examined_overlapping_subtriangles: int
    unsafe_subtriangles: int


@dataclass(frozen=True)
class BoundReviewedGlSupplement:
    capture_context: EvidenceContext
    source_context: EvidenceContext
    frames: tuple[ConditionalGlFrame, ...]
    artifact_sha256: tuple[tuple[str, str], ...]
    # These remain false even when all receipt/inventory checks succeed.
    native_profile_binding_verified: bool = field(default=False, init=False)
    native_geometry_profile_verified: bool = field(default=False, init=False)
    native_fragment_profile_verified: bool = field(default=False, init=False)
    acceptance_complete: bool = field(default=False, init=False)
    acceptance_verdict: None = field(default=None, init=False)
    _snapshots: tuple[tuple[Path, int, str], ...] = field(default=(), repr=False)

    def __bool__(self):
        raise TypeError('conditional evidence is not an acceptance boolean')

    def verify_unchanged(self):
        """Recheck immediately before any downstream evidence report is written."""
        for path, size, sha256 in self._snapshots:
            source.telemetry._compare(source._digest(path), {'bytes': size, 'sha256': sha256},
                                      f'{path}: late mutation')


def _require(condition, message):
    source._require(condition, message)


def _equal(actual, expected, label):
    source.telemetry._compare(actual, expected, label)


def _integer(value, label, minimum=0):
    _require(type(value) is int and value >= minimum, f'{label}: invalid integer')
    return value


def _number(value, label):
    _require(type(value) is int or (type(value) is Decimal and value.is_finite()),
             f'{label}: expected finite number')
    return value


def _mask(value, label):
    _require(type(value) is list, f'{label}: runs must be an array')
    result = set()
    previous = -1
    for pair in value:
        _require(type(pair) is list and len(pair) == 2, f'{label}: malformed run')
        start, count = pair
        _integer(start, label)
        _integer(count, label, 1)
        _require(start > previous and start + count <= 960 * 540,
                 f'{label}: overlapping, unsorted or out-of-extent run')
        result.update(range(start, start + count))
        previous = start + count - 1
    return result


def _frames(rows, expected, label):
    _require(type(rows) is list and all(type(row) is dict for row in rows), f'{label}: expected frame array')
    ids = [_integer(row.get('frame'), label) for row in rows]
    _require(len(ids) == len(set(ids)) and set(ids) == set(expected),
             f'{label}: incomplete, duplicate or unexpected frame inventory')
    return {row['frame']: row for row in rows}


def _pinned(ledger, path, label):
    path = Path(path).absolute()
    _require(ledger._remember(path)['sha256'] == _REVIEWED_SHA256[label],
             f'{label}: bytes differ from reviewed SHA-256')
    return path


def _geometry_rows(ledger, path) -> Iterator[dict]:
    with path.open('rb') as stream:
        header = source._parse(next(stream, b''), 'geometry header')
        _equal(header, GEOMETRY_HEADER, 'geometry header')
        for number, line in enumerate(stream, 2):
            yield source._parse(line, f'geometry line {number}')
    ledger._remember(path)


def _bind_frame(native, geometry, fragment):
    frame = native['frame']
    label = f'frame {frame}'
    source.shared._exact_keys(geometry, ('frame', 'checks', 'triangles'), label)
    _equal(geometry['frame'], frame, label)
    _equal(fragment['frame'], frame, label)
    checks = geometry['checks']
    _require(type(checks) is dict, f'{label}: missing geometry checks')
    for key, expected in {'native_geometry_profile_verified': False,
                          'original_profile_flags_unchanged': True,
                          'all_source_domain_nodes_supported': True,
                          'local_native_masks_state_equal': True,
                          'unresolved_clipping_triangles': 0, 'unresolved': []}.items():
        _equal(checks.get(key), expected, f'{label}/{key}')
    _equal(fragment.get('native_fragment_profile_verified'), False, label)
    _equal(fragment.get('acceptance_verdict'), None, label)
    _require('acceptance_verdict' in fragment and 'acceptance_verdict' in native,
             f'{label}: missing null verdict')
    _equal(native['acceptance_verdict'], None, label)
    _equal(native['possible_support_complete'], True, label)
    _equal(native['unsupported_clip_triangles'], 0, label)
    old_required = _mask(native['required_contrast_runs'], label)
    old_possible = _mask(native['possible_support_runs'], label)
    required = _mask(checks['required_runs'], label)
    possible = _mask(checks['possible_runs'], label)
    retained = _mask(fragment['required_runs'], label)
    removed = _mask(fragment['removed_required_runs'], label)
    _require(retained <= required <= old_required <= old_possible <= possible,
             f'{label}: required must narrow and possible must expand')
    for actual, expected in ((native['required_contrast_samples'], len(old_required)),
                             (native['possible_samples'], len(old_possible)),
                             (checks['required_original'], len(old_required)),
                             (checks['required_retained'], len(required)),
                             (checks['required_original_not_reproved'], len(old_required - required)),
                             (checks['possible_original'], len(old_possible)),
                             (checks['possible_additional'], len(possible - old_possible)),
                             (fragment['required_before_fragment'], len(required)),
                             (fragment['required_after_fragment'], len(retained))):
        _equal(actual, expected, label + '/mask count')
    _equal(removed, required - retained, label + '/removed mask')
    considered = _integer(checks['source_triangles_considered'], label)
    _equal(considered, native['unclassified_triangles'], label + '/source triangle inventory')
    _equal(native['source_triangles'], native['outside_bottom'] + native['hidden_source_triangles'] + considered,
           label + '/complete source triangle partition')
    mesh_sizes = {}
    for mesh in native['meshes']:
        identity = (mesh['kind'], _integer(mesh['mesh'], label))
        _require(identity not in mesh_sizes, f'{label}: duplicate source mesh')
        mesh_sizes[identity] = _integer(mesh['triangles'], label)
    _equal(sum(mesh_sizes.values()), native['source_triangles'], label + '/source mesh inventory')
    _require(type(geometry['triangles']) is list and len(geometry['triangles']) <= considered,
             f'{label}: malformed geometry triangle inventory')
    expected_rows, triangle_ids, generated_possible = {}, set(), set()
    for triangle in geometry['triangles']:
        kind, mesh, index = triangle['kind'], triangle['mesh'], triangle['triangle']
        _require(type(kind) is str and kind in ('skin', 'rigid'), f'{label}: invalid triangle kind')
        _integer(mesh, label)
        _integer(index, label)
        identity = (kind, mesh, index)
        _require(identity not in triangle_ids and (kind, mesh) in mesh_sizes
                 and index < mesh_sizes[kind, mesh], f'{label}: duplicate or unknown source triangle')
        triangle_ids.add(identity)
        variants = _integer(triangle['variant_count'], label, 1)
        _require(type(triangle['subtriangles']) is list and triangle['subtriangles'],
                 f'{label}: missing subtriangle inventory')
        fans = set()
        for sid, sub in enumerate(triangle['subtriangles']):
            variant = _integer(sub['variant'], label)
            fan = sub['fan']
            _require(type(fan) is list and len(fan) == 3 and all(type(v) is int for v in fan)
                     and fan[0] == 0 and fan[1] >= 1 and fan[2] == fan[1] + 1,
                     f'{label}: invalid fan identity')
            fan_id = (variant, *fan)
            _require(variant < variants and fan_id not in fans, f'{label}: duplicate or unknown variant/fan')
            fans.add(fan_id)
            support = _mask(sub['possible_runs'], label)
            _require(bool(support), f'{label}: emitted subtriangle has no support')
            _require(_mask(sub['robust_runs'], label) <= support, f'{label}: robust support escapes possible')
            _equal(_mask(sub['required_overlap_runs'], label), support & old_required,
                   label + '/original subtriangle overlap')
            generated_possible |= support
            overlap = support & required
            if overlap:
                key = (mesh, index, sid)
                _require(key not in expected_rows, f'{label}: ambiguous fragment triangle identity')
                expected_rows[key] = (triangle, support, len(overlap))
    _equal(generated_possible | old_possible, possible, label + '/complete possible inventory')
    _equal(checks['possible_generated'], len(generated_possible), label)
    _equal(checks['possible_original_not_reproved'], len(old_possible - generated_possible), label)
    _require(type(fragment['triangles']) is list, f'{label}: missing fragment inventory')
    unsafe, seen, safe_bounds, unsafe_count = set(), set(), [], 0
    for row in fragment['triangles']:
        key = tuple(_integer(row.get(k), label) for k in ('mesh', 'triangle', 'subtriangle'))
        _require(key not in seen and key in expected_rows, f'{label}: duplicate or unexpected fragment triangle')
        seen.add(key)
        triangle, support, overlap_count = expected_rows[key]
        _equal(row['overlap_count'], overlap_count, label + '/fragment overlap')
        bound = row.get('cumulative_byte_bound')
        if bound is not None:
            _require(_number(bound, label) >= 0, f'{label}: negative fragment bound')
        if 'unsafe_reason' in row:
            _require(type(row['unsafe_reason']) is str and bool(row['unsafe_reason']), f'{label}: invalid unsafe reason')
            unsafe |= support
            unsafe_count += 1
        else:
            _require(bound is not None and bound <= 3, f'{label}: unsafe bound labeled safe')
            _require(triangle['kind'] == 'rigid' and triangle['texture_bounds'] == [[255, 255]] * 3
                     and all(type(v) is list and len(v) == 4 and type(v[3]) is int and v[3] == 255
                             for v in triangle['colors']), f'{label}: safe triangle outside rigid opaque scope')
            safe_bounds.append(bound)
    _require(seen == set(expected_rows), f'{label}: incomplete overlapping fragment triangle inventory')
    _equal(retained, required - unsafe, label + '/complete unsafe-winner subtraction')
    _equal(fragment['examined_overlapping_subtriangles'], len(expected_rows), label)
    _equal(fragment['unsafe_subtriangles'], unsafe_count, label)
    _equal(fragment['max_retained_triangle_byte_bound'], max(safe_bounds, default=None), label)
    return ConditionalGlFrame(frame, tuple(map(tuple, fragment['required_runs'])),
                              tuple(map(tuple, checks['possible_runs'])), len(required), len(retained),
                              len(expected_rows), unsafe_count)


def bind_reviewed_gl_supplement(*, source_receipt, native_source, geometry, fragment,
                                capture_context: EvidenceContext,
                                source_context: EvidenceContext) -> BoundReviewedGlSupplement:
    """Bind four read-only artifacts to independently established caller contexts.

    Context arguments must come from original native/source receipt validation,
    not be inferred from this supplement. Digests cannot be supplied by a packet.
    Success establishes reviewed evidence identity/structure only. The caller must
    still run bind_source_packet and unchanged native image/telemetry validators.
    """
    _require(type(capture_context) is EvidenceContext and capture_context == CAPTURE_CONTEXT,
             'capture context differs from reviewed original capture')
    _require(type(source_context) is EvidenceContext and source_context == SOURCE_CONTEXT,
             'source context differs from reviewed original source run')
    ledger = source.BoundSourcePacket()
    paths = {key: _pinned(ledger, value, key) for key, value in
             {'source_receipt': source_receipt, 'native_source': native_source,
              'geometry': geometry, 'fragment': fragment}.items()}
    receipt = ledger._json(paths['source_receipt'])
    _equal(receipt.get('schema'), 'rust-duty-source-visibility-certificates-binding/v1', 'receipt schema')
    _equal(receipt.get('capture_context'), asdict(capture_context), 'capture context')
    _equal(receipt.get('source_execution_context'), asdict(source_context), 'source execution context')
    _equal(receipt.get('source_base_commit'), capture_context.source_commit, 'original source commit')
    _require('acceptance_verdict' in receipt, 'receipt missing verdict')
    _equal(receipt['acceptance_verdict'], None, 'source receipt verdict')
    native_records = [source._parse(line, 'native source')
                      for line in ledger._read(paths['native_source']).splitlines()]
    _require(bool(native_records), 'native source is empty')
    native_header = native_records[0]
    for key, expected in {**source.HEADER_FIELDS, **source.PROFILE_FIELDS,
                          'backend_profile': source.BACKEND_PROFILES['windows-legacy'],
                          **{key: False for key in SOURCE_FALSE_FLAGS}}.items():
        _require(key in native_header, f'native header missing {key}')
        _equal(native_header[key], expected, 'native header/' + key)
    report = receipt['backend_reports']['opengl']
    _equal(report['header'], native_header, 'receipt native header')
    _equal(report['output'], ledger._remember(paths['native_source']), 'receipt native bytes')
    native_rows = _frames(native_records[1:], range(source.FRAME_COUNT), 'original source')
    fragments = ledger._json(paths['fragment'])
    for key, expected in {'schema': 'rust-duty-bounded-fragment-supplement/v1',
                          'input_sha256': _REVIEWED_SHA256['geometry'], 'input_header': GEOMETRY_HEADER,
                          'frame_count': len(FRAME_IDS), 'native_fragment_profile_verified': False,
                          'acceptance_complete': False}.items():
        _equal(fragments.get(key), expected, 'fragment header/' + key)
    fragment_rows = _frames(fragments['frames'], FRAME_IDS, 'fragment')
    frames, seen = [], set()
    for row in _geometry_rows(ledger, paths['geometry']):
        frame = _integer(row.get('frame'), 'geometry')
        _require(frame in FRAME_IDS and frame not in seen, 'geometry: duplicate or unexpected frame')
        seen.add(frame)
        frames.append(_bind_frame(native_rows[frame], row, fragment_rows[frame]))
    _require(seen == set(FRAME_IDS), 'geometry: incomplete reviewed frame inventory')
    frames.sort(key=lambda row: row.frame)
    _equal(fragments['frames_with_retained_required_support'], sum(row.required_after_fragment > 0 for row in frames),
           'fragment positive-support summary')
    _equal(fragments['frames_without_retained_required_support'],
           [row.frame for row in frames if row.required_after_fragment == 0], 'fragment empty-support summary')
    counts = (sum(row.required_before_fragment for row in frames),
              sum(row.required_after_fragment for row in frames), min(row.required_after_fragment for row in frames),
              sum(row.examined_overlapping_subtriangles for row in frames), sum(row.unsafe_subtriangles for row in frames))
    _equal(counts, _REVIEWED_COUNTS, 'reviewed inventory totals')
    ledger.verify_unchanged()
    return BoundReviewedGlSupplement(capture_context, source_context, tuple(frames),
                                     tuple(sorted(_REVIEWED_SHA256.items())),
                                     _snapshots=tuple((path, d['bytes'], d['sha256'])
                                                      for path, d in ledger._snapshots.items()))


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-receipt', 'native-source', 'geometry', 'fragment'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('capture-context', 'source-context'):
        parser.add_argument('--' + name, required=True, nargs=3,
                            metavar=('SOURCE_COMMIT', 'RUN_ID', 'RUN_ATTEMPT'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = bind_reviewed_gl_supplement(
        source_receipt=args.source_receipt, native_source=args.native_source,
        geometry=args.geometry, fragment=args.fragment,
        capture_context=EvidenceContext(*args.capture_context),
        source_context=EvidenceContext(*args.source_context))
    report = {key: value for key, value in asdict(result).items() if key not in ('_snapshots', 'frames')}
    report.update(schema='rust-duty-reviewed-gl-supplement-binding/v1',
                  status='reviewed_conditional_evidence_bound',
                  frame_ids=[row.frame for row in result.frames],
                  required_samples=sum(row.required_after_fragment for row in result.frames),
                  minimum_required_samples=min(row.required_after_fragment for row in result.frames),
                  examined_overlapping_subtriangles=sum(row.examined_overlapping_subtriangles for row in result.frames),
                  unsafe_subtriangles=sum(row.unsafe_subtriangles for row in result.frames))
    result.verify_unchanged()
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
