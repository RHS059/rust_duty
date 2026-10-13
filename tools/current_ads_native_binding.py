#!/usr/bin/env python3
"""Bind complete independent ADS source meshes to actual native draw receipts.

This is input/execution evidence only. It never grants image acceptance or
turns unresolved arithmetic, clipping, or fragment obligations into a pass.
"""
from decimal import Decimal
import hashlib
import re
import struct

import ads_source_visibility_binding as source
from run_dx12_authored_shard import role_witness_identity

SCHEMA = 'rust-duty-native-visibility-receipt/v1'
require = source._require
equal = source.telemetry._compare


def _integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, label + ': invalid integer')
    return value


def _sha(value, label):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), label + ': invalid SHA256')
    return value


def _bits(values, count, label):
    require(type(values) is list and len(values) == count, label + ': incomplete float bits')
    for value in values:
        require(type(value) is int and 0 <= value < 2**32 and (value >> 23) & 255 != 255,
                label + ': nonfinite or invalid float bits')
    return values


def _float_bits(value):
    return struct.unpack('<I', struct.pack('<f', float(value)))[0]


def _texture(value):
    source.shared._exact_keys(value, ('kind', 'width', 'height', 'sampler', 'rgba8_sha256'), 'source texture')
    require(value['kind'] == 'rgba8', 'source capture must not sample a render target')
    _integer(value['width'], 'texture width', 1)
    _integer(value['height'], 'texture height', 1)
    _sha(value['rgba8_sha256'], 'texture content')
    sampler = value['sampler']
    source.shared._exact_keys(sampler, ('filter', 'wrap_x', 'wrap_y'), 'texture sampler')
    require(sampler['filter'] in ('linear', 'nearest') and
            sampler['wrap_x'] in ('clamp', 'repeat') and sampler['wrap_y'] in ('clamp', 'repeat'),
            'unsupported source sampler')


# These are the small shader expressions used by the operational arithmetic
# proof, not a historical application-source equivalence inventory. A changed
# shader needs new proof; unrelated renderer/HUD/application files do not.
VERTEX_SHADER = """#version 100
attribute vec3 position;
attribute vec2 texcoord;
attribute vec4 color0;
varying lowp vec2 uv;
varying lowp vec4 vertex_color;
uniform mat4 Model;
uniform mat4 Projection;
void main() {
    gl_Position = Projection * Model * vec4(position, 1.0);
    uv = texcoord;
    vertex_color = color0 / 255.0;
}
"""
FRAGMENT_SHADER = """#version 100
precision mediump float;
varying lowp vec2 uv;
varying lowp vec4 vertex_color;
uniform sampler2D Texture;
void main() {
    gl_FragColor = texture2D(Texture, uv) * vertex_color;
}
"""
WITNESS_FRAGMENT_SHADER = """#version 100
precision mediump float;
varying lowp vec2 uv;
varying lowp vec4 vertex_color;
uniform sampler2D Texture;
void main() {
    vec4 straight = texture2D(Texture, uv) * vertex_color;
    gl_FragColor = vec4(straight.rgb * straight.a, straight.a);
}
"""


def shader_identities(witness=False):
    return [{'stage': stage, 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
             'provenance': 'material-creation-input' if stage == 'vertex' else 'live-attached-shader'}
            for stage, text in (('vertex', VERTEX_SHADER),
                                ('fragment', WITNESS_FRAGMENT_SHADER if witness else FRAGMENT_SHADER))]


def _gl_observation(value, *, witness):
    expected = {'verified': True, 'viewport': [0, 0, 960, 540], 'depth_test': not witness,
                'depth_write': not witness, 'cull': False, 'blend_enabled': not witness,
                'color_mask': [1, 1, 1, 1], 'front_face': 0x0901, 'depth_clamp': False,
                'alpha_to_coverage': False, 'sample_coverage': False, 'rasterizer_discard': False,
                'depth_range_bits': [0, _float_bits(1)]}
    source.shared._exact_keys(value, (*expected, 'program', 'scissor', 'scissor_enabled',
        'depth_compare', 'depth_write_mask', 'blend_rgb', 'blend_alpha', 'shaders',
        'material_id', 'material_binding', 'uniforms', 'attributes'), 'observed OpenGL state')
    equal({key: value[key] for key in expected}, expected, 'actual OpenGL state')
    _integer(value['program'], 'actual GL program', 1)
    _integer(value['material_id'], 'actual GL material identity', 1)
    equal(value['material_binding'], 'created-owned-material-selected-then-flushed', 'GL material/program binding')
    equal(value['uniforms'], [{'name': name, 'gl_type': kind, 'size': 1} for name, kind in
          [('Model', 35676), ('Projection', 35676), ('Texture', 35678)]], 'actual GL active uniforms')
    equal(value['attributes'], [{'name': name, 'gl_type': kind, 'size': 1} for name, kind in
          [('color0', 35666), ('position', 35665), ('texcoord', 35664)]], 'actual GL vertex input layout')
    for field in ('scissor_enabled', 'depth_write_mask'):
        require(type(value[field]) is bool, 'actual GL boolean state missing')
    require(type(value['scissor']) is list and len(value['scissor']) == 4
            and all(type(n) is int for n in value['scissor']), 'actual GL scissor missing')
    if value['scissor_enabled']:
        equal(value['scissor'], [0, 0, 960, 540], 'actual GL scissor')
    if not witness:
        equal(value['depth_write_mask'], True, 'actual GL depth write mask')
        equal(value['depth_compare'], 0x0203, 'actual GL depth compare')
        equal(value['blend_rgb'], [0x0302, 0x0303, 0x8006], 'actual GL color blend')
        equal(value['blend_alpha'], [1, 0x0303, 0x8006], 'actual GL alpha blend')
    else:
        _integer(value['depth_compare'], 'disabled GL depth comparator')
        for field in ('blend_rgb', 'blend_alpha'):
            require(type(value[field]) is list and len(value[field]) == 3
                    and all(type(n) is int for n in value[field]), 'disabled GL blend state missing')
    require(type(value['shaders']) is list, 'actual linked shaders missing')
    equal(sorted(value['shaders'], key=lambda item: item.get('stage', '')),
          sorted(shader_identities(witness), key=lambda item: item['stage']), 'actual linked GL shader semantics')


def _draw_state(state, role, *, witness=False):
    expected = {
        'topology': 'triangle-list', 'viewport': [0, 0, 960, 540],
        'scissor': [0, 0, 960, 540], 'depth_range_bits': [0, _float_bits(1)],
        'depth_test': not witness, 'depth_write': not witness,
        'depth_compare': 'always' if witness else 'less-equal',
        'blend': 'opaque' if witness else 'alpha',
        'color_blend': None if witness else ['src-alpha', 'one-minus-src-alpha', 'add'],
        'alpha_blend': None if witness else ['one', 'one-minus-src-alpha', 'add'],
        'cull': 'none', 'front_face': 'ccw', 'color_write': 'rgba', 'sample_count': 1,
        'clip_depth': 'minus-one-to-one' if role == 'windows-legacy' else 'zero-to-one',
        'depth_clamp': False, 'fragment': 'associate-straight' if witness else 'straight',
        'target_format': 'rgba8unorm',
    }
    source.shared._exact_keys(state, (*expected, 'observed_gl'), 'native pipeline state')
    equal({key: state[key] for key in expected}, expected, 'native supported pipeline state')
    if role == 'dx12':
        equal(state['observed_gl'], None, 'DX12 GL state')
    else:
        _gl_observation(state['observed_gl'], witness=witness)


def witness_triangles(frame, identity):
    _sha(identity, 'frame witness identity')
    rects = [(0, 0, 32, 2, (255, 0, 0, 255)), (32, 0, 32, 2, (0, 0, 255, 255))]
    payload = struct.pack('<II', frame, frame ^ 0xffffffff) + bytes.fromhex(identity)
    for bit, value in enumerate((byte >> bit) & 1 for byte in payload for bit in range(8)):
        rects.append((bit % 32 * 2, 2 + bit // 32 * 2, 2, 2, (value * 255,) * 3 + (255,)))
    result = []
    for x, y, width, height, color in rects:
        vertices = [struct.pack('<5f4B', a, b, 0, 0, 0, *color)
                    for a, b in ((x, y), (x + width, y), (x + width, y + height), (x, y + height))]
        result.extend(hashlib.sha256(b''.join(vertices[i] for i in indices)).hexdigest()
                      for indices in ((0, 1, 2), (0, 2, 3)))
    return result


def _numeric_matrix(values, expected, label):
    _bits(values, 16, label)
    # Signed zero has identical geometry. Every nonzero entry remains exact f32.
    actual = [struct.unpack('<f', struct.pack('<I', value))[0] for value in values]
    wanted = [struct.unpack('<f', struct.pack('<f', value))[0] for value in expected]
    require(actual == wanted, label + ': matrix differs')


def verify_witness_draw(draw, role, frame, identity):
    source.shared._exact_keys(draw, ('triangle_count', 'triangle_sha256', 'view_projection_bits',
        'model_bits', 'upload_transform_bits', 'texture', 'state'), 'native witness draw')
    hashes = witness_triangles(frame, identity)
    equal(draw['triangle_count'], len(hashes), 'native witness triangle count')
    equal(draw['triangle_sha256'], hashes, 'actual native witness geometry')
    screen = [2 / 960, 0, 0, 0, 0, -2 / 540, 0, 0, 0, 0, -1, 0, -1, 1, 0, 1]
    _numeric_matrix(draw['view_projection_bits'], screen, 'native witness screen projection')
    _numeric_matrix(draw['model_bits'], [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], 'native witness model')
    if role == 'dx12':
        upload = screen[:]
        upload[10], upload[14] = -.5, .5
        _numeric_matrix(draw['upload_transform_bits'], upload, 'native witness upload')
    else:
        equal(draw['upload_transform_bits'], None, 'native witness GL upload')
    equal(draw['texture'], {'kind': 'rgba8', 'width': 1, 'height': 1,
            'rgba8_sha256': hashlib.sha256(bytes([255] * 4)).hexdigest(),
            'sampler': {'filter': 'linear', 'wrap_x': 'clamp', 'wrap_y': 'clamp'}}, 'native witness texture')
    _draw_state(draw['state'], role, witness=True)


def draw_input_state_sha256(state):
    """Independent implementation of the native fixed-width input-state codec."""
    data = bytearray(b'rust-duty-draw-input-state/v1\0')
    for field in ('view_projection_bits', 'model_bits'):
        data.extend(struct.pack('<16I', *_bits(state[field], 16, field)))
    upload = state['upload_transform_bits']
    data.append(int(upload is not None))
    if upload is not None:
        data.extend(struct.pack('<16I', *_bits(upload, 16, 'upload transform')))
    texture = state['texture']
    _texture(texture)
    require(texture['width'] < 2**32 and texture['height'] < 2**32, 'texture extent exceeds native u32')
    data.extend(struct.pack('<II', texture['width'], texture['height']))
    sampler = texture['sampler']
    data.extend((int(sampler['filter'] == 'linear'), int(sampler['wrap_x'] == 'repeat'),
                 int(sampler['wrap_y'] == 'repeat')))
    data.extend(texture['rgba8_sha256'].encode('ascii'))
    return hashlib.sha256(data).hexdigest()


def ordered_draw_input_sha256(draws):
    """Hash test/reference input streams without retaining flattened triangles."""
    digest = hashlib.sha256()
    for state, triangles in draws:
        state_hash = draw_input_state_sha256(state).encode('ascii')
        for triangle in triangles:
            digest.update(state_hash)
            digest.update(_sha(triangle, 'canonical triangle').encode('ascii'))
    return digest.hexdigest()


def expected_triangles(row):
    """Validate complete asset inventory before considering any native draws."""
    inventory = row.get('expected_draw_inventory')
    require(type(inventory) is list and inventory, 'complete source mesh inventory missing')
    total = hidden = 0
    keys = []
    obligations = []
    source_meshes = {(item['kind'], item['mesh']): item for item in row['meshes']}
    require(len(source_meshes) == len(row['meshes']), 'duplicate source classification mesh')
    for mesh in inventory:
        source.shared._exact_keys(mesh, ('kind', 'mesh', 'triangles', 'visible', 'opacity_bits',
            'triangle_stream_sha256', 'triangle_chunk_sha256', 'texture', 'view_projection_bits',
            'model_bits', 'upload_transform_bits'), 'source expected mesh')
        require(mesh['kind'] in ('skin', 'rigid'), 'unexpected source mesh kind')
        key = (mesh['kind'], _integer(mesh['mesh'], 'source mesh ordinal'))
        keys.append(key)
        count = _integer(mesh['triangles'], 'source triangle count', 1)
        _sha(mesh['triangle_stream_sha256'], 'complete source triangle stream')
        chunks = mesh['triangle_chunk_sha256']
        require(type(chunks) is list and len(chunks) == (count + 255) // 256,
                'source triangle chunk inventory incomplete')
        for digest in chunks:
            _sha(digest, 'source triangle chunk')
        require(type(mesh['visible']) is bool, 'source visibility is not boolean')
        _bits([mesh['opacity_bits']], 1, 'source opacity')
        opacity = struct.unpack('<f', struct.pack('<I', mesh['opacity_bits']))[0]
        require(0 <= opacity <= 1, 'source opacity is out of range')
        _bits(mesh['view_projection_bits'], 16, 'source view projection')
        _bits(mesh['model_bits'], 16, 'source model')
        if mesh['upload_transform_bits'] is not None:
            _bits(mesh['upload_transform_bits'], 16, 'source upload transform')
        _texture(mesh['texture'])
        classified = source_meshes.get(key)
        require(classified is not None and classified['triangles'] == count,
                'expected mesh differs from complete source classifier inventory')
        equal(mesh['opacity_bits'], _float_bits(classified['opacity']), 'source mesh opacity')
        equal(mesh['visible'], classified['state'] == 'enumerated', 'source actor visibility')
        total += count
        if mesh['visible']:
            state = {name: mesh[name] for name in ('view_projection_bits', 'model_bits', 'upload_transform_bits', 'texture')}
            obligations.append((count, state))
        else:
            hidden += count
    require(len(set(keys)) == len(keys) and set(keys) == set(source_meshes), 'source mesh partition incomplete')
    require(keys == sorted(keys, key=lambda key: (key[0] == 'rigid', key[1])), 'source mesh submission order differs')
    for kind in ('skin', 'rigid'):
        ordinals = [index for mesh_kind, index in keys if mesh_kind == kind]
        require(ordinals == list(range(len(ordinals))), 'source mesh ordinal inventory incomplete')
    equal(total, row['source_triangles'], 'complete original source triangle count')
    equal(hidden, row['hidden_source_triangles'], 'independent source-hidden triangle count')
    require(obligations, 'expected nonempty pre-submission geometry inventory')
    return obligations


def verify_receipt(row, receipt, *, role, frame, capture_identity, capture_sha256):
    """Return only a validated native-input identity; no visibility verdict."""
    require(role in source.ROLES and type(frame) is int and row['frame'] == frame, 'source frame identity differs')
    expected = expected_triangles(row)
    source.shared._exact_keys(receipt, ('schema', 'capture_identity', 'frame_index', 'backend', 'capture_path',
        'capture_sha256', 'target', 'witness_exclusion', 'witness_count', 'triangle_count', 'draws', 'events',
        'submission_complete', 'capture_complete', 'ordered_draw_input_sha256'), 'native visibility receipt')
    for key, value in {'schema': SCHEMA, 'capture_identity': capture_identity, 'frame_index': frame,
        'backend': source.BACKENDS[role][1], 'capture_path': f'{frame:04}.png', 'capture_sha256': capture_sha256,
        'witness_exclusion': [0, 0, 64, 22], 'witness_count': 1,
        'submission_complete': True, 'capture_complete': True}.items():
        equal(receipt[key], value, 'native visibility ' + key)
    target = receipt['target']
    source.shared._exact_keys(target, ('resource_id', 'width', 'height', 'depth'), 'native target')
    _integer(target['resource_id'], 'native target ID', 1)
    equal({key: target[key] for key in ('width', 'height', 'depth')},
          {'width': 960, 'height': 540, 'depth': True}, 'actual native target extent/depth')
    draws = receipt['draws']
    require(type(draws) is list and draws, 'missing native draws')
    actual = []
    for draw in draws:
        source.shared._exact_keys(draw, ('triangle_count', 'view_projection_bits',
            'model_bits', 'upload_transform_bits', 'texture', 'state'), 'native draw')
        count = _integer(draw['triangle_count'], 'native draw triangle count', 1)
        _draw_state(draw['state'], role)
        state = {key: draw[key] for key in ('view_projection_bits', 'model_bits', 'upload_transform_bits', 'texture')}
        actual.append((count, state))
    total = sum(count for count, _ in actual)
    equal(total, receipt['triangle_count'], 'native receipt triangle count')
    equal(total, sum(count for count, _ in expected), 'missing or extra source-owned native triangles')
    # Compare ordered state ranges without allocating a tuple for every triangle.
    # A backend may split meshes, but cannot change state or omit any geometry.
    index, remaining = 0, expected[0][0]
    ordinal = 0
    for count, state in actual:
        while count:
            equal(state, expected[index][1], f'native triangle/input mismatch at ordinal {ordinal}')
            consumed = min(count, remaining)
            ordinal, count, remaining = ordinal + consumed, count - consumed, remaining - consumed
            if remaining == 0:
                index += 1
                if index < len(expected):
                    remaining = expected[index][0]
    equal(index, len(expected), 'complete source input range inventory')
    equal(_sha(receipt['ordered_draw_input_sha256'], 'native ordered draw inputs'),
          _sha(row.get('expected_ordered_draw_input_sha256'), 'independent expected ordered draw inputs'),
          'complete ordered native geometry/input stream')
    events = receipt['events']
    require(type(events) is list and len(events) == len(draws) + 3, 'native clear/draw/witness/capture sequence differs')
    equal(events[0], {'kind': 'clear', 'rgba_bits': [_float_bits(v) for v in (0.14, 0.19, 0.24, 1)],
                     'depth_bits': _float_bits(1)}, 'native source clear/depth')
    equal(events[1:-2], [{'kind': 'draw', 'draw_index': index} for index in range(len(draws))],
          'native draw order')
    require(type(events[-2]) is dict and set(events[-2]) == {'kind', 'draw'} and events[-2]['kind'] == 'witness',
            'native witness checkpoint missing')
    verify_witness_draw(events[-2]['draw'], role, frame, capture_identity)
    equal(events[-1], {'kind': 'capture'}, 'native ordered capture checkpoint')
    return {'frame': frame, 'triangles': total, 'hidden_source_triangles': row['hidden_source_triangles'],
            'native_input_binding_verified': True, 'visibility_verified': False}


def bind_all_native_frames(bound, ledger=None):
    require(type(bound) is source.BoundSourcePacket, 'source packet is not independently bound')
    ledger = ledger or source.BoundSourcePacket()
    result = {}
    for role in source.ROLES:
        equal(bound.headers_by_role[role].get('native_draw_inventory_schema'), SCHEMA,
              'current source requires native draw inventory')
        identity = role_witness_identity(bound.capture_binding, 'ads-offset', role)
        rows = []
        for index, path in enumerate(bound._frames[role]):
            row = bound.verify_frame_binding(path, role, index)
            catalog = [entry for entry in bound.headers_by_role[role]['sources']
                       if entry['vra'] == row['companion_catalog_vra']]
            require(len(catalog) == 1, 'current source catalog missing or ambiguous')
            for kind in ('skin', 'rigid'):
                equal(sum(mesh['kind'] == kind for mesh in row['expected_draw_inventory']),
                      catalog[0][kind + '_meshes'], 'complete source catalog ' + kind)
            receipt = ledger._json(path.with_name(path.name + '.visibility.json'))
            rows.append(verify_receipt(row, receipt, role=role, frame=index,
                        capture_identity=identity, capture_sha256=ledger._remember(path)['sha256']))
        result[role] = rows
    bound.verify_unchanged()
    ledger.verify_unchanged()
    return result
