#!/usr/bin/env python3
"""Recompute a current, conditional Mesa GL ADS proof without candidate pixels.

The source receipt independently anchors the complete expected JSONL. A current
compiled geometry probe supplies a complete compressed triangle partition. The
caller MUST separately bind that trace to the probe execution, current production
inputs and actual native submissions. This module never promotes native/profile
flags and never treats a historical source hash as an equivalence class.

The arithmetic is reused from the existing Mesa 26.2.4 clipping, sample coverage
and fragment calculators. Required support may only narrow; possible support may
only grow from the current source obligations. Every selected visible frame must
retain required support. Empty frames require a complete strict-plane/hidden
partition. No PNG, native image or historical proof is an input.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import tempfile

import ads_source_visibility_binding as source
import audit_source_visibility_geometry as geometry
import dx12_authored_shards as shared
import narrow_ads_fragment_support as fragment
from source_visibility_clipping import Unresolved, clip_xy_variants, project

SCHEMA = 'rust-duty-current-ads-conditional-gl-proof/v1'
GEOMETRY_SCHEMA = 'rust-duty-current-ads-bounded-geometry/v1'
FRAGMENT_SCHEMA = 'rust-duty-current-ads-bounded-fragment/v1'
TRACE_SCHEMA = 'rust-duty-source-geometry-probe/v1'
MODEL = 'Mesa26.2.4 draw_pipe_clip float32 operational profile'
FALSE_FLAGS = ('profile_native_verified', 'native_geometry_profile_verified',
               'native_fragment_profile_verified', 'native_profile_binding_verified',
               'trace_execution_binding_verified', 'source_packet_inventory_binding_verified',
               'acceptance_complete')
TRACE_EXTRAS = {'geometry_domain', 'triangle_trace', 'triangle_partition',
                'original_native_observations'}
HEADER_EXTRAS = {'source_certificate_schema', 'requested_frames', 'original_native_observations'}
SOURCE_FIELDS = {'frame', 'committed_tick', 'time', 'route', 'visual_ads', 'ammo', 'shots',
                 'companion_catalog_vra', 'companion_crc32', 'source_triangles', 'outside_bottom',
                 'hidden_source_triangles', 'unclassified_triangles', 'classification',
                 'maximum_bottom_upper', 'meshes', 'unsupported_clip_triangles',
                 'possible_support_complete', 'required_contrast_samples', 'possible_samples',
                 'required_contrast_runs', 'possible_support_runs', 'acceptance_verdict',
                 'native_gameplay', 'native_time'}
IMPLEMENTATIONS = ('current_ads_profile_proof.py', 'audit_source_visibility_geometry.py',
                   'source_visibility_clipping.py', 'narrow_ads_fragment_support.py',
                   'ads_fragment_error_bound.py', 'ads_source_visibility_binding.py',
                   'dx12_authored_shards.py', 'verify_capture_telemetry.py')
MAX_LINE = 128 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, f'{label}: invalid integer')
    return value


def number(value, label):
    require(type(value) in (int, float, Decimal) and math.isfinite(value),
            f'{label}: expected finite number')
    result = float(value)
    require(math.isfinite(result), f'{label}: float conversion overflow')
    return result


def equal(actual, expected, label):
    """Compare all state without bool/integer coercion or decimal rounding."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        require(set(actual) == set(expected), f'{label}: field inventory differs')
        for key in expected:
            equal(actual[key], expected[key], f'{label}/{key}')
    elif isinstance(actual, list) and isinstance(expected, list):
        require(len(actual) == len(expected), f'{label}: length differs')
        for index, (a, b) in enumerate(zip(actual, expected)):
            equal(a, b, f'{label}/{index}')
    else:
        require(type(actual) is type(expected) and actual == expected, f'{label}: value differs')


def conditional_flags(record, label):
    for key, value in record.items():
        if key.endswith('_verified') or key in ('profile_assumptions_independently_established',
                                                'original_native_observations', 'acceptance_complete'):
            require(value is False, f'{label}: native/profile flag cannot be promoted: {key}')
        if key == 'acceptance_verdict':
            require(value is None, f'{label}: acceptance verdict cannot be promoted')


def frame_ids(frames):
    require(type(frames) in (list, tuple) and bool(frames), 'selected frame inventory is empty')
    result = [integer(frame, 'selected frame') for frame in frames]
    require(all(frame < source.FRAME_COUNT for frame in result)
            and result == sorted(set(result)), 'selected frames must be unique and ordered')
    return result


def rows_by_frame(rows, label):
    if type(rows) is dict:
        for frame, row in rows.items():
            require(type(frame) is int and type(row) is dict and row.get('frame') == frame,
                    f'{label}: frame map key differs')
        rows = list(rows.values())
    require(type(rows) is list and bool(rows), f'{label}: empty frame inventory')
    result = {}
    for row in rows:
        require(type(row) is dict, f'{label}: row must be an object')
        frame = integer(row.get('frame'), f'{label}: frame')
        require(frame < source.FRAME_COUNT and frame not in result, f'{label}: duplicate or invalid frame')
        result[frame] = row
    return result


def mesh_key(row, label):
    require(type(row) is dict and row.get('kind') in ('skin', 'rigid'), f'{label}: invalid mesh kind')
    return row['kind'], integer(row.get('mesh'), f'{label}: mesh')


def keyed_meshes(rows, label):
    require(type(rows) is list, f'{label}: expected mesh list')
    result = {}
    for row in rows:
        key = mesh_key(row, label)
        require(key not in result, f'{label}: duplicate mesh')
        result[key] = row
    return result


def triangle_runs(value, count, label):
    require(type(value) is list, f'{label}: expected runs')
    result, last = set(), -1
    for run in value:
        require(type(run) is list and len(run) == 2, f'{label}: malformed run')
        start, length = integer(run[0], label), integer(run[1], label, 1)
        require(start > last and start + length <= count, f'{label}: overlapping or out-of-range run')
        result.update(range(start, start + length))
        last = start + length - 1
    return result


def support_runs(value, label):
    require(type(value) is list, f'{label}: expected support runs')
    try:
        result = fragment.indices(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{label}: invalid support runs') from error
    require(not any(i % 960 < 64 and i // 960 < 22 for i in result),
            f'{label}: support includes excluded HUD')
    return result


def header_pair(expected, trace, frames):
    require(type(expected) is dict and type(trace) is dict, 'both source headers are required')
    require(trace.get('schema') == TRACE_SCHEMA and expected.get('schema') == source.HEADER_FIELDS['schema']
            and trace.get('source_certificate_schema') == expected['schema'], 'trace/source schema differs')
    require(trace.get('requested_frames') == frames and trace.get('original_native_observations') is False,
            'trace selected frame scope differs')
    require(expected.get('backend_profile') == source.BACKEND_PROFILES['windows-legacy']
            and expected.get('extent') == [960, 540] and expected.get('expected_frames') == source.FRAME_COUNT,
            'current proof requires the declared GL 960x540 ADS scope')
    equal({k: v for k, v in trace.items() if k not in HEADER_EXTRAS | {'schema'}},
          {k: v for k, v in expected.items() if k != 'schema'}, 'source header')
    conditional_flags(expected, 'source header')
    conditional_flags(trace, 'trace header')
    require(type(expected.get('sources')) is list and bool(expected['sources']), 'missing source catalog')
    seen = set()
    for entry in expected['sources']:
        require(type(entry) is dict and type(entry.get('vra')) is str
                and entry['vra'] not in seen, 'missing or duplicate source catalog entry')
        seen.add(entry['vra'])
        integer(entry.get('skin_meshes'), 'skin mesh count')
        integer(entry.get('rigid_meshes'), 'rigid mesh count')
    return expected['sources']


def source_meshes(row, catalog):
    meshes = keyed_meshes(row['meshes'], 'source meshes')
    require(bool(meshes), 'source mesh inventory is empty')
    if catalog is not None:
        matching = [entry for entry in catalog if entry['vra'] == row['companion_catalog_vra']]
        require(len(matching) == 1, 'frame companion missing from source catalog')
        entry = matching[0]
        equal(entry.get('companion_crc32'), row['companion_crc32'], 'source companion CRC')
        required_keys = {(kind, index) for kind in ('skin', 'rigid')
                         for index in range(entry[f'{kind}_meshes'])}
        require(set(meshes) == required_keys, 'complete source mesh inventory differs from catalog')
    counts = {'triangles': 0, 'outside_bottom': 0, 'hidden': 0, 'unclassified': 0}
    for key, mesh in meshes.items():
        count = integer(mesh.get('triangles'), f'{key}: triangles')
        counts['triangles'] += count
        opacity = number(mesh.get('opacity'), f'{key}: opacity')
        require(0 <= opacity <= 1, 'source opacity outside unit interval')
        if mesh.get('state') == 'source_actor_hidden':
            require(key[0] == 'rigid', 'skin mesh cannot be actor-hidden')
            counts['hidden'] += count
        else:
            require(mesh.get('state') == 'enumerated', 'unresolved source mesh state')
            outside = integer(mesh.get('outside_bottom'), 'outside bottom')
            unclassified = integer(mesh.get('unclassified'), 'unclassified triangles')
            require(outside + unclassified == count, 'source mesh triangle accounting differs')
            if count:
                maximum = number(mesh.get('maximum_bottom_upper'), 'mesh bottom upper')
                require((maximum < 0) == (unclassified == 0), 'source bottom separator disagrees with count')
            counts['outside_bottom'] += outside
            counts['unclassified'] += unclassified
    for name, total in (('source_triangles', counts['triangles']), ('outside_bottom', counts['outside_bottom']),
                        ('hidden_source_triangles', counts['hidden']), ('unclassified_triangles', counts['unclassified'])):
        require(integer(row.get(name), name) == total, f'{name}: full source inventory differs')
    return meshes


def arithmetic_domains(row, meshes):
    domains = keyed_meshes(row['geometry_domain'], 'geometry domain')
    visible = {key for key, mesh in meshes.items() if mesh['state'] == 'enumerated'}
    require(set(domains) == visible, 'complete geometry domain mesh inventory differs')
    for key, entry in domains.items():
        d = entry.get('domain')
        require(type(d) is dict and d.get('normal_or_exact_zero_no_overflow') is True
                and type(d.get('unsupported_domain_nodes')) is int and d['unsupported_domain_nodes'] == 0,
                f'{key}: arithmetic domain is unresolved')
        integer(d.get('checked_abstract_nodes'), 'checked domain nodes', 1)
        integer(d.get('positions'), 'domain positions', 1)
        exponent = d.get('minimum_nonzero_dyadic_exponent')
        require(type(exponent) is int and exponent >= -126, 'arithmetic domain includes subnormals')
        maximum = number(d.get('maximum_rounded_magnitude_upper'), 'arithmetic domain maximum')
        require(0 <= maximum < float.fromhex('0x1.fffffep+127') / (1 + 2**-23),
                'arithmetic domain may overflow')
    return domains


def interval_tensor(value, rows, columns, label):
    require(type(value) is list and len(value) == rows, f'{label}: invalid vertex inventory')
    result = []
    for row in value:
        require(type(row) is list and len(row) == columns, f'{label}: invalid coordinate inventory')
        values = []
        for pair in row:
            require(type(pair) is list and len(pair) == 2, f'{label}: invalid interval')
            lo, hi = (number(n, label) for n in pair)
            require(lo <= hi, f'{label}: reversed interval')
            values.append([lo, hi])
        result.append(values)
    return result


def f32_bits(values, length, label):
    require(type(values) is list and len(values) == length, f'{label}: invalid bit inventory')
    for value in values:
        integer(value, label)
        require(value < 2**32 and math.isfinite(struct.unpack('<f', struct.pack('<I', value))[0]),
                f'{label}: nonfinite or invalid float32 bits')


def safe_contrast(colors, texture):
    if any(color[3] != 255 for color in colors):
        return False
    clear = (36, 48, 61)
    for c in range(3):
        lo = min(v[c] for v in colors) * texture[c][0] // 255
        hi = (max(v[c] for v in colors) * texture[c][1] + 254) // 255
        if clear[c] - hi > 11 or lo - clear[c] > 11:
            return True
    return False


def triangles_and_partition(row, meshes, domains):
    require(type(row['triangle_trace']) is list, 'missing triangle trace')
    triangles, per_mesh, states, vertices = {}, {}, {}, {}
    for original in row['triangle_trace']:
        key = mesh_key(original, 'triangle trace')
        require(key in domains, 'triangle trace refers to hidden or missing mesh')
        tid = integer(original.get('triangle'), 'triangle identity')
        require(tid < meshes[key]['triangles'] and (*key, tid) not in triangles,
                'duplicate or out-of-range triangle identity')
        triangle = deepcopy(original)
        triangle['clip'] = interval_tensor(triangle.get('clip'), 3, 4, 'clip')
        interval_tensor(triangle.get('screen'), 3, 2, 'screen')
        for name in ('projection_bits', 'model_bits'):
            f32_bits(triangle.get(name), 16, name)
        require(type(triangle.get('position_bits')) is list and len(triangle['position_bits']) == 3,
                'missing source triangle position bits')
        for position in triangle['position_bits']:
            f32_bits(position, 3, 'position bits')
        indices = triangle.get('indices')
        require(type(indices) is list and len(indices) == 3
                and all(type(i) is int and 0 <= i < domains[key]['domain']['positions'] for i in indices),
                'source triangle indices outside complete domain')
        for name, columns in (('colors', 4), ('texture_bounds', 2)):
            value = triangle.get(name)
            require(type(value) is list and len(value) == 3
                    and all(type(v) is list and len(v) == columns
                            and all(type(c) is int and 0 <= c <= 255 for c in v) for v in value),
                    f'{name}: invalid source color/texture inventory')
        require(all(lo <= hi for lo, hi in triangle['texture_bounds']), 'reversed source texture bound')
        require(type(triangle.get('safe_contrast')) is bool
                and triangle['safe_contrast'] == safe_contrast(triangle['colors'], triangle['texture_bounds']),
                'source contrast flag differs from recomputed color/texture separation')
        state = {name: triangle[name] for name in ('projection_bits', 'model_bits', 'texture_bounds')}
        if key in states:
            equal(state, states[key], 'per-mesh draw state')
        states[key] = state
        for index, vertex in enumerate(indices):
            value = {name: triangle[name][index] for name in ('position_bits', 'clip', 'colors')}
            if (*key, vertex) in vertices:
                equal(value, vertices[(*key, vertex)], 'shared source vertex')
            vertices[(*key, vertex)] = value
        triangles[(*key, tid)] = triangle
        per_mesh.setdefault(key, set()).add(tid)
    partition = keyed_meshes(row['triangle_partition'], 'triangle partition')
    require(set(partition) == set(meshes), 'complete triangle partition mesh inventory differs')
    separated_count = hidden_count = 0
    for key, mesh in meshes.items():
        ledger, count = partition[key], mesh['triangles']
        require(type(ledger.get('triangles')) is int and ledger['triangles'] == count,
                'triangle partition count differs')
        hidden = mesh['state'] == 'source_actor_hidden'
        require(type(ledger.get('source_hidden')) is bool and ledger['source_hidden'] == hidden,
                'triangle partition falsely hidden source mesh')
        traced = triangle_runs(ledger.get('traced_runs'), count, 'traced partition')
        require(traced == per_mesh.get(key, set()), 'triangle partition traced identities differ')
        groups = ledger.get('separated')
        require(type(groups) is list, 'missing strict-plane groups')
        if hidden:
            require(not traced and not groups, 'hidden mesh contains traced/separated triangles')
            hidden_count += count
            continue
        covered, planes = set(traced), set()
        for group in groups:
            require(type(group) is dict and type(group.get('axis')) is int and group['axis'] in (0, 1, 2)
                    and type(group.get('sign')) is int and group['sign'] in (-1, 1), 'invalid strict clip plane')
            plane = group['axis'], group['sign']
            require(plane not in planes, 'duplicate strict clip-plane group')
            planes.add(plane)
            require(number(group.get('maximum_plane_upper'), 'strict plane upper') < 0,
                    'omitted triangle lacks strict clip-plane separation')
            ids = triangle_runs(group.get('runs'), count, 'separated partition')
            require(bool(ids) and not (ids & covered), 'overlapping or empty triangle partition')
            covered |= ids
            separated_count += len(ids)
        require(covered == set(range(count)), 'incomplete source triangle partition')
    require(len(triangles) + separated_count + hidden_count == row['source_triangles'],
            'complete source triangle inventory differs')
    return list(triangles.values()), {'source_triangles': row['source_triangles'],
        'traced_triangles': len(triangles), 'strictly_separated_triangles': separated_count,
        'source_hidden_triangles': hidden_count, 'complete_mesh_count': len(meshes),
        'geometry_domain_mesh_count': len(domains), 'complete_triangle_partition': True}


def bounded_geometry(row, triangles, inventory):
    old_required = support_runs(row['required_contrast_runs'], 'current required support')
    old_possible = support_runs(row['possible_support_runs'], 'current possible support')
    require(old_required <= old_possible, 'required support escapes current possible mask')
    require(integer(row['required_contrast_samples'], 'required samples') == len(old_required)
            and integer(row['possible_samples'], 'possible samples') == len(old_possible),
            'source sample counts differ from masks')
    robust, possible, unsafe, emitted = set(), set(), set(), []
    generated = clipped = 0
    for triangle in triangles:
        try:
            variants = clip_xy_variants(triangle['clip'], triangle['colors'])
            required_triangle, possible_triangle, subtriangles, max_generated = None, set(), [], 0
            for variant_index, (poly, count) in enumerate(variants):
                max_generated = max(max_generated, count)
                projected = [project(vertex) for vertex in poly]
                screen = [p[0] for p in projected]
                vr, vp = set(), set()
                for index in range(1, len(poly) - 1):
                    fan = [0, index, index + 1]
                    rr, pp = geometry.vector_samples([screen[j] for j in fan])
                    vr |= rr
                    vp |= pp
                    if pp:
                        subtriangles.append({'variant': variant_index, 'fan': fan,
                            'clip': [[x.wire() for x in poly[j][:4]] for j in fan],
                            'colors': [[x.wire() for x in poly[j][4:7]] for j in fan],
                            'unsnapped_screen': [[x.wire() for x in project(poly[j], snap=False)[0]] for j in fan],
                            'screen': [[x.wire() for x in screen[j]] for j in fan],
                            'reciprocal_w': [projected[j][1].wire() for j in fan],
                            'possible_runs': fragment.runs(pp), 'robust_runs': fragment.runs(rr),
                            'required_overlap_runs': fragment.runs(pp & old_required)})
                required_triangle = vr if required_triangle is None else required_triangle & vr
                possible_triangle |= vp
            generated += max_generated
            clipped += bool(max_generated)
            possible |= possible_triangle
            if triangle['safe_contrast']:
                robust |= required_triangle or set()
            else:
                unsafe |= possible_triangle
            if possible_triangle:
                emitted.append({key: triangle[key] for key in
                                ('kind', 'mesh', 'triangle', 'colors', 'texture_bounds', 'safe_contrast')}
                               | {'generated_vertices': max_generated, 'variant_count': len(variants),
                                  'subtriangles': subtriangles})
        except (Unresolved, OverflowError, ArithmeticError) as error:
            raise ValueError(f"frame {row['frame']}: unresolved clipping for "
                             f"{triangle['kind']}/{triangle['mesh']}/{triangle['triangle']}: {error}") from error
    required = (robust - unsafe) & old_required
    checks = {**inventory, 'all_source_domain_nodes_supported': True, 'full_current_source_state_equal': True,
              'unresolved_clipping_triangles': 0, 'source_triangles_considered': len(triangles),
              'clipped_source_triangles': clipped, 'generated_vertices': generated,
              'required_original': len(old_required), 'required_retained': len(required),
              'required_original_not_reproved': len(old_required - required),
              'possible_original': len(old_possible), 'possible_generated': len(possible),
              'possible_additional': len(possible - old_possible),
              'required_runs': fragment.runs(required), 'possible_runs': fragment.runs(possible | old_possible),
              'native_geometry_profile_verified': False}
    return {'frame': row['frame'], 'checks': checks, 'triangles': emitted}


def validate_gl_proof(expected_rows, trace_rows, *, frames=None, expected_header=None, trace_header=None):
    """Recompute selected current rows; supplied flags/masks never prove themselves.

    Header arguments are paired. File entry points always supply them. Without
    headers the caller is responsible for the expected source catalog binding.
    This pure API still validates every selected row and complete mesh partition.
    """
    expected, trace = rows_by_frame(expected_rows, 'expected source'), rows_by_frame(trace_rows, 'trace')
    frames = frame_ids(list(trace) if frames is None else frames)
    require(list(trace) == frames and set(frames) <= set(expected), 'selected source/trace frame inventory differs')
    catalog = None
    if expected_header is not None or trace_header is not None:
        catalog = header_pair(expected_header, trace_header, frames)
    rows, geometry_frames, fragment_frames = [], [], []
    for frame in frames:
        row, original = trace[frame], expected[frame]
        require(SOURCE_FIELDS <= set(original) and TRACE_EXTRAS <= set(row),
                f'frame {frame}: missing full current source state or geometry trace')
        source_keys = set(original)
        if 'expected_draw_inventory' not in row:
            # Synthetic/legacy diagnostic fixtures have no native-input claim.
            require('expected_draw_inventory' not in original, 'trace lacks current expected input inventory')
        require(set(row) - TRACE_EXTRAS == source_keys, f'frame {frame}: source row field inventory differs')
        equal({k: row[k] for k in source_keys}, {k: original[k] for k in source_keys},
              f'frame {frame}: full current source state')
        conditional_flags(original, f'frame {frame}: source')
        conditional_flags(row, f'frame {frame}: trace')
        require(row['original_native_observations'] is False
                and type(row['unsupported_clip_triangles']) is int and row['unsupported_clip_triangles'] == 0
                and row['possible_support_complete'] is True, f'frame {frame}: unresolved source support')
        require(type(row['native_gameplay']) is dict and bool(row['native_gameplay'])
                and type(row['native_time']) is dict and bool(row['native_time']), 'missing gameplay/time state')
        meshes = source_meshes(row, catalog)
        domains = arithmetic_domains(row, meshes)
        triangles, inventory = triangles_and_partition(row, meshes, domains)
        bounded = bounded_geometry(row, triangles, inventory)
        narrowed = fragment.narrow_frame(bounded)
        classification = row['classification']
        if classification == 'expected_empty_under_profile':
            require(row['unclassified_triangles'] == 0 and row['required_contrast_samples'] == row['possible_samples'] == 0
                    and not triangles and not bounded['checks']['possible_runs'],
                    f'frame {frame}: empty support is not fully separated')
        else:
            require(classification == 'potentially_visible_unresolved' and row['unclassified_triangles'] > 0
                    and narrowed['required_after_fragment'] > 0,
                    f'frame {frame}: visible frame has no retained required support')
        rows.append({'frame': frame, 'classification': classification,
                     'required_runs': narrowed['required_runs'], 'possible_runs': bounded['checks']['possible_runs'],
                     'required_samples': narrowed['required_after_fragment'],
                     'possible_samples': sum(run[1] for run in bounded['checks']['possible_runs']),
                     'full_current_source_state_equal': True, **inventory})
        geometry_frames.append(bounded)
        fragment_frames.append(narrowed)
    return {'schema': SCHEMA, 'conditional_source_proof_complete': True,
            'backend_implementation': MODEL, 'frames': rows, 'frame_count': len(rows),
            'geometry_frames': geometry_frames, 'fragment_frames': fragment_frames,
            'source_catalog_checked': catalog is not None,
            **{flag: False for flag in FALSE_FLAGS}, 'acceptance_verdict': None,
            'limitations': ['Conditional arithmetic/model proof; not a native execution observation.',
                           'Compressed strict-plane ledger requires separately bound compiled-probe execution.',
                           'Production asset, draw submission and driver identity binding are the caller’s responsibility.']}


def digest(path):
    path = Path(path)
    sha = shared._read_regular(path)
    return {'bytes': shared._checked_stat(path, 'file').st_size, 'sha256': sha}


def records(path):
    shared._checked_stat(path, 'file')
    with Path(path).open('rb') as stream:
        for index, line in enumerate(stream):
            require(len(line) <= MAX_LINE and line.strip(), f'{path}:{index}: invalid JSONL record length')
            yield source._parse(line, f'{path}:{index}')


def read_json(path):
    require(shared._checked_stat(path, 'file').st_size <= MAX_LINE, 'oversized source receipt')
    return source._parse(Path(path).read_bytes(), str(path))


def receipt_binding(receipt, expected_digest):
    before, after = receipt.get('inputs_and_implementation_before'), receipt.get('inputs_and_implementation_after')
    require(type(before) is dict and bool(before) and type(after) is dict,
            'source receipt lacks current implementation/input inventory')
    equal(before, after, 'source receipt before/after inventory')
    for name, value in before.items():
        require(type(name) is str and bool(name), 'invalid source inventory path')
        source._digest_shape(value, f'source receipt inventory/{name}')
    required = (source.INPUTS - {'ads-offset.cfg'}) | {'Cargo.toml', 'Cargo.lock', 'src/lib.rs',
                                                        'examples/source_visibility_certificate.rs'}
    require(required <= set(before) and any(name.endswith('/ads-offset.cfg') or name == 'ads-offset.cfg'
                                            for name in before), 'source receipt implementation/assets inventory incomplete')
    backend = receipt.get('backend_reports', {}).get('opengl', {})
    require(type(backend) is dict and type(backend.get('exit_code')) is int and backend['exit_code'] == 0,
            'source receipt GL replay did not succeed')
    source._digest_shape(backend.get('output'), 'source receipt GL output')
    equal(backend['output'], expected_digest, 'expected JSONL differs from independently anchored source receipt')
    require(receipt.get('acceptance_verdict') is None, 'source receipt cannot approve native acceptance')


def json_bytes(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode('utf-8')


class CurrentGLProof(dict):
    """Conditional report with an immutable snapshot for downstream consumers."""
    def __init__(self, report, files):
        super().__init__(report)
        self._snapshot = deepcopy(report)
        self._files = dict(files)

    def verify_unchanged(self):
        equal(dict(self), self._snapshot, 'in-memory current GL proof changed')
        for path, expected in self._files.items():
            equal(digest(path), expected, f'current GL proof input/output changed: {path}')


def build_gl_proof(trace_path, expected_path, receipt_path, expected_receipt_sha256, frames, output_dir):
    """Build fresh proof files, retaining the independent source receipt anchor."""
    frames = frame_ids(frames)
    trace_path, expected_path, receipt_path = [Path(p).absolute() for p in (trace_path, expected_path, receipt_path)]
    output_dir = Path(output_dir).absolute()
    require(type(expected_receipt_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_receipt_sha256),
            'missing independent source receipt SHA256')
    require(len({trace_path, expected_path, receipt_path}) == 3, 'source proof inputs alias')
    require(not output_dir.exists() and not output_dir.is_symlink(), 'proof output directory must be fresh')
    require(not any(path.is_relative_to(output_dir) for path in (trace_path, expected_path, receipt_path)),
            'proof output directory contains immutable input')
    files = {path: digest(path) for path in (trace_path, expected_path, receipt_path)}
    require(files[receipt_path]['sha256'] == expected_receipt_sha256,
            'source receipt differs from independent SHA256 anchor')
    receipt = read_json(receipt_path)
    receipt_binding(receipt, files[expected_path])
    tool_root = Path(__file__).resolve().parent
    files.update({tool_root / name: digest(tool_root / name) for name in IMPLEMENTATIONS})
    originals = iter(records(expected_path))
    expected_header = next(originals, None)
    expected_rows = rows_by_frame(list(originals), 'expected source')
    require(list(expected_rows) == list(range(source.FRAME_COUNT)), 'expected source must enumerate all 553 rows')
    current = iter(records(trace_path))
    trace_header = next(current, None)
    catalog = header_pair(expected_header, trace_header, frames)
    # Source traces and generated fan intervals can be large. Keep only one
    # selected frame's detailed geometry in memory; publish nothing on failure.
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    shared._checked_root(output_dir.parent)
    with tempfile.TemporaryDirectory(prefix='.current-gl-proof-', dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        staged_geometry, staged_fragment = staging / 'geometry.jsonl', staging / 'fragment.json'
        report, seen = None, []
        with staged_geometry.open('xb') as geometry_stream, staged_fragment.open('xb') as fragment_stream:
            geometry_stream.write(json.dumps({'schema': GEOMETRY_SCHEMA,
                'trace_sha256': files[trace_path]['sha256'],
                **{flag: False for flag in FALSE_FLAGS}, 'acceptance_verdict': None}).encode() + b'\n')
            fragment_header = {'schema': FRAGMENT_SCHEMA, 'trace_sha256': files[trace_path]['sha256'],
                               **{flag: False for flag in FALSE_FLAGS}, 'acceptance_verdict': None}
            fragment_stream.write(json.dumps(fragment_header, allow_nan=False).encode()[:-1] + b',"frames":[')
            for index, row in enumerate(current):
                require(index < len(frames) and type(row.get('frame')) is int and row['frame'] == frames[index],
                        'selected source/trace frame inventory differs')
                frame = row['frame']
                # The per-frame pure call validates full state and partition;
                # catalog cardinality was fixed by the paired complete headers.
                source_meshes(expected_rows[frame], catalog)
                result = validate_gl_proof([expected_rows[frame]], [row], frames=[frame])
                bounded = result.pop('geometry_frames')[0]
                narrowed = result.pop('fragment_frames')[0]
                geometry_stream.write(json.dumps(bounded, allow_nan=False, separators=(',', ':')).encode() + b'\n')
                if seen:
                    fragment_stream.write(b',')
                fragment_stream.write(json.dumps(narrowed, allow_nan=False, separators=(',', ':')).encode())
                if report is None:
                    report = result
                else:
                    report['frames'].extend(result['frames'])
                seen.append(frame)
            require(seen == frames, 'selected source/trace frame inventory is incomplete')
            fragment_stream.write(b']}\n')
        report.update(frame_count=len(seen), source_catalog_checked=True,
                      source_receipt_sha256=expected_receipt_sha256,
                      trace_sha256=files[trace_path]['sha256'], expected_source_sha256=files[expected_path]['sha256'],
                      input_files={role: files[path] for role, path in
                                   (('trace', trace_path), ('expected', expected_path), ('source_receipt', receipt_path))},
                      implementation={name: files[tool_root / name] for name in IMPLEMENTATIONS})
        geometry_path, fragment_path, proof_path = [output_dir / name for name in
                                                   ('geometry.jsonl', 'fragment.json', 'proof.json')]
        report['outputs'] = {'geometry': {'path': str(geometry_path), **digest(staged_geometry)},
                             'fragment': {'path': str(fragment_path), **digest(staged_fragment)}}
        with (staging / 'proof.json').open('xb') as stream:
            stream.write(json_bytes(report))
        # Recheck every anchored input after all calculation/output writes and
        # immediately before the fresh result directory becomes visible.
        for path, value in files.items():
            equal(digest(path), value, f'current GL proof inputs changed during calculation: {path}')
        require(not output_dir.exists() and not output_dir.is_symlink(), 'proof output directory appeared during calculation')
        staging.rename(output_dir)
    files.update({path: digest(path) for path in (geometry_path, fragment_path, proof_path)})
    result = CurrentGLProof(report, files)
    result.verify_unchanged()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', required=True, type=Path)
    parser.add_argument('--expected', required=True, type=Path)
    parser.add_argument('--source-receipt', required=True, type=Path)
    parser.add_argument('--expected-receipt-sha256', required=True)
    parser.add_argument('--frames', required=True, type=Path, help='JSON list of selected current frame IDs')
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    frames = json.loads(args.frames.read_text())
    result = build_gl_proof(args.trace, args.expected, args.source_receipt,
                            args.expected_receipt_sha256, frames, args.output_dir)
    print(json.dumps({'schema': result['schema'], 'frame_count': result['frame_count'],
                      'conditional_source_proof_complete': True, 'profile_native_verified': False,
                      'acceptance_complete': False, 'proof': str(args.output_dir / 'proof.json')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
