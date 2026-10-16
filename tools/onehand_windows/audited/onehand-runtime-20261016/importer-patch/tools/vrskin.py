#!/usr/bin/env python3
"""Strict local GLB -> VRSKIN02 converter. The container is not encryption.

Uses vrpack's unchanged generic GLB/geometry/image validation helpers. VRMESH01
continues to reject all skins; this is a separate, explicitly skinned pipeline.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import struct
import sys
import zlib
import vrpack as core
from vrpack import AssetError, require, uint, number, objects, at, matmul

MAGIC = b'VRSKIN02'
VERSION = 2
HEADER = struct.Struct('<8sIIII')
MAX_BONES = 128
MAX_MESHES = 128
VERTEX = struct.Struct('<8f8H8f')


def transpose(m):
    return tuple(m[c * 4 + r] for r in range(4) for c in range(4))


def matrix_valid(col, label):
    require(len(col) == 16 and all(math.isfinite(v) and abs(v) <= 3.4028234663852886e38 for v in col),
            f'{label} must contain 16 finite float32 values')
    require(tuple(col[i] for i in (3, 7, 11, 15)) == (0, 0, 0, 1), f'{label} must be affine')
    require(core.determinant(transpose(col)) != 0, f'{label} must be nonsingular')


def validate_parents(parents):
    for i, parent in enumerate(parents):
        require(-1 <= parent < len(parents) and parent != i, 'invalid bone parent')
        seen = set()
        at_index = i
        while at_index != -1:
            require(at_index not in seen, 'cycle in bone hierarchy')
            seen.add(at_index)
            at_index = parents[at_index]


class Converter(core.Converter):
    def __init__(self, doc, blob, *, base_color_only=False):
        require(not doc.get('animations'), 'embedded animations are not supported; author runtime animation separately')
        skins = objects(doc.get('skins', []), 'skins')
        require(len(skins) == 1, 'exactly one skin is required')
        self.skin = skins[0]
        self.warnings = []
        sanitized = copy.deepcopy(doc)
        sanitized.pop('skins', None)
        for node in objects(sanitized.get('nodes', []), 'nodes'):
            node.pop('skin', None)
        omitted = []
        for i, material in enumerate(objects(sanitized.get('materials', []), 'materials')):
            pbr = material.get('pbrMetallicRoughness', {})
            require(isinstance(pbr, dict), 'pbrMetallicRoughness must be an object')
            for field in ('normalTexture', 'occlusionTexture'):
                if field in material:
                    require(base_color_only, f'{field} omitted only with explicit --base-color-only')
                    material.pop(field)
                    omitted.append(f'material {i} {field}')
            if 'metallicRoughnessTexture' in pbr:
                require(base_color_only, 'metallicRoughnessTexture omitted only with explicit --base-color-only')
                pbr.pop('metallicRoughnessTexture')
                omitted.append(f'material {i} metallicRoughnessTexture')
        for i, sampler in enumerate(objects(sanitized.get('samplers', []), 'samplers')):
            if sampler.get('minFilter') in (9985, 9987):
                require(base_color_only, 'mipmap sampling simplified only with explicit --base-color-only')
                sampler['minFilter'] = 9729
                omitted.append(f'sampler {i} mipmap minification (output uses LINEAR)')
        if base_color_only:
            self.warnings.append('BASE-COLOR-ONLY: omitted ' + (', '.join(omitted) if omitted else 'no additional material maps'))
        # The original v1 constructor still rejects skins. A private sanitized
        # validation view merely lets us reuse its strict geometry/image helpers.
        super().__init__(sanitized, blob)
        core.reject_extensions(doc)  # Includes extensions on the skin itself.
        self.doc = doc
        self.nodes = objects(doc.get('nodes', []), 'nodes')

    def skin_accessor(self, index, semantic):
        acc = at(self.accessors, index, semantic)
        require('sparse' not in acc, 'sparse accessors are not supported')
        comp = acc.get('componentType')
        norm = acc.get('normalized', False)
        require(type(norm) is bool, 'accessor normalized must be boolean')
        require(type(comp) is int, 'accessor componentType must be an integer')
        if semantic == 'inverseBindMatrices':
            require(comp == 5126 and acc.get('type') == 'MAT4' and not norm,
                    'inverseBindMatrices requires unnormalized FLOAT MAT4')
            ncomp, maximum = 16, MAX_BONES
        elif semantic.startswith('JOINTS_'):
            require(comp in (5121, 5123) and acc.get('type') == 'VEC4' and not norm,
                    'JOINTS requires unnormalized UNSIGNED_BYTE/SHORT VEC4')
            ncomp, maximum = 4, core.MAX_VERTICES
        else:
            require(comp in (5121, 5123, 5126) and acc.get('type') == 'VEC4', 'WEIGHTS requires FLOAT or normalized unsigned VEC4')
            require(norm == (comp != 5126), 'integer weights must be normalized; float weights must not be')
            ncomp, maximum = 4, core.MAX_VERTICES
        fmt, width = {5121: ('B', 1), 5123: ('H', 2), 5126: ('f', 4)}[comp]
        count = uint(acc.get('count'), semantic + ' count', maximum)
        require(count > 0, semantic + ' is empty')
        view, base, length = self.view(acc.get('bufferView'))
        offset = uint(acc.get('byteOffset', 0), 'accessor byteOffset')
        require(offset % width == 0 and (base + offset) % width == 0, 'accessor must be component aligned')
        stride = uint(view.get('byteStride', width * ncomp), 'byteStride', 252)
        require(stride >= width * ncomp, 'accessor stride too short')
        if 'byteStride' in view:
            require(semantic != 'inverseBindMatrices' and stride % 4 == 0, 'invalid skin accessor byteStride')
        require(offset <= length and (count - 1) * stride + width * ncomp <= length - offset, 'skin accessor exceeds bufferView')
        unpack = struct.Struct('<' + fmt * ncomp).unpack_from
        rows = [unpack(self.blob, base + offset + i * stride) for i in range(count)]
        if norm:
            divisor = 255 if comp == 5121 else 65535
            rows = [tuple(v / divisor for v in row) for row in rows]
        require(all(math.isfinite(v) for row in rows for v in row), 'non-finite skin accessor')
        return rows

    def hierarchy(self):
        require(self.scenes, 'a default scene is required')
        scene = at(self.scenes, self.doc.get('scene', 0), 'scene')
        roots = scene.get('nodes', [])
        require(isinstance(roots, list), 'scene nodes must be an array')
        parents, globals_, locals_, active = {}, {}, {}, set()
        def walk(idx, parent, world, depth):
            idx = uint(idx, 'node index')
            node = at(self.nodes, idx, 'node')
            require(depth <= core.MAX_DEPTH, 'node hierarchy exceeds 256 levels')
            require(idx not in active, 'cycle in node hierarchy')
            require(idx not in parents, 'node has multiple parents or duplicate roots')
            active.add(idx)
            parents[idx] = parent
            local = core.node_matrix(node)
            global_ = matmul(world, local)
            matrix_valid(transpose(local), 'node local matrix')
            matrix_valid(transpose(global_), 'node global matrix')
            locals_[idx], globals_[idx] = local, global_
            children = node.get('children', [])
            require(isinstance(children, list), 'node children must be an array')
            for child in children:
                walk(child, idx, global_, depth + 1)
            active.remove(idx)
        for root in roots:
            walk(root, -1, core.IDENTITY, 0)
        return parents, globals_, locals_

    def convert(self):
        parents, globals_, locals_ = self.hierarchy()
        joints = self.skin.get('joints')
        require(isinstance(joints, list) and 1 <= len(joints) <= MAX_BONES, 'skin must have 1..128 joints')
        require(all(type(i) is int and i in parents for i in joints), 'every joint must be a node in the selected scene')
        require(len(set(joints)) == len(joints), 'duplicate skin joint')
        if 'skeleton' in self.skin:
            require(type(self.skin['skeleton']) is int and self.skin['skeleton'] in parents, 'skin skeleton is not in selected scene')
        joint_map = {node: index for index, node in enumerate(joints)}
        binds = self.skin_accessor(self.skin['inverseBindMatrices'], 'inverseBindMatrices') if 'inverseBindMatrices' in self.skin else [core.IDENTITY] * len(joints)
        require(len(binds) == len(joints), 'inverse bind count must equal joint count')
        bones = []
        for index, node in enumerate(joints):
            parent, local = parents[node], locals_[node]
            while parent != -1 and parent not in joint_map:
                local = matmul(locals_[parent], local)
                parent = parents[parent]
            name = self.nodes[node].get('name', f'joint_{index}')
            require(isinstance(name, str) and 1 <= len(name.encode('utf-8')) <= 64 and '\x00' not in name,
                    'joint names must be 1..64 UTF-8 bytes without NUL')
            local = transpose(local)
            matrix_valid(local, 'bone rest matrix')
            matrix_valid(binds[index], 'inverse bind matrix')
            bones.append((name, joint_map.get(parent, -1), local, binds[index]))
        validate_parents([b[1] for b in bones])
        output = []
        for node_idx in parents:
            node = self.nodes[node_idx]
            if 'mesh' not in node:
                require('skin' not in node, 'skin node requires a mesh')
                continue
            require(type(node.get('skin')) is int and node['skin'] == 0, 'all mesh nodes must reference the one skin')
            mesh = at(self.meshes, node['mesh'], 'node mesh')
            primitives = objects(mesh.get('primitives', []), 'primitives')
            require(primitives and len(output) + len(primitives) <= MAX_MESHES, 'mesh primitive count must be 1..128')
            # In glTF skinned WORLD output, meshGlobal cancels its inverse in
            # joint matrices. Do not bake it into positions or inverse binds.
            for primitive in primitives:
                output.append(self.skin_primitive(primitive, len(joints)))
        require(output, 'selected scene has no skinned meshes')
        self.bones, self.output_meshes, self.source_globals = bones, output, globals_
        return encode_vrs(bones, output)

    def skin_primitive(self, primitive, bone_count):
        attrs = primitive.get('attributes')
        require(isinstance(attrs, dict), 'primitive attributes must be an object')
        supported = {'POSITION', 'NORMAL', 'TEXCOORD_0', 'JOINTS_0', 'WEIGHTS_0', 'JOINTS_1', 'WEIGHTS_1'}
        require(not set(attrs) - supported, 'unsupported vertex attributes')
        require('JOINTS_0' in attrs and 'WEIGHTS_0' in attrs, 'JOINTS_0 and WEIGHTS_0 are required')
        require(('JOINTS_1' in attrs) == ('WEIGHTS_1' in attrs), 'JOINTS_1 and WEIGHTS_1 must occur together')
        static = dict(primitive)
        static['attributes'] = {k: v for k, v in attrs.items() if k in {'POSITION', 'NORMAL', 'TEXCOORD_0'}}
        factors, w, h, raster, vertices, indices = super().primitive(static, core.IDENTITY)
        joint_rows = self.skin_accessor(attrs['JOINTS_0'], 'JOINTS_0')
        weight_rows = self.skin_accessor(attrs['WEIGHTS_0'], 'WEIGHTS_0')
        require(len(joint_rows) == len(weight_rows) == len(vertices), 'skin attribute counts must match POSITION')
        if 'JOINTS_1' in attrs:
            j1 = self.skin_accessor(attrs['JOINTS_1'], 'JOINTS_1')
            w1 = self.skin_accessor(attrs['WEIGHTS_1'], 'WEIGHTS_1')
            require(len(j1) == len(w1) == len(vertices), 'skin attribute counts must match POSITION')
            joint_rows = [a + b for a, b in zip(joint_rows, j1)]
            weight_rows = [a + b for a, b in zip(weight_rows, w1)]
        result = []
        for vertex, joints, weights in zip(vertices, joint_rows, weight_rows):
            require(all(0 <= j < bone_count for j in joints), 'vertex joint index outside skin')
            require(all(0 <= w <= 1 for w in weights) and sum(weights) > 0, 'weights must be nonnegative, <=1 and have positive sum')
            total = sum(weights)
            js = tuple(joints) + (0,) * (8 - len(joints))
            ws = tuple(w / total for w in weights) + (0.0,) * (8 - len(weights))
            result.append(vertex + js + ws)
        return factors, w, h, raster, result, indices


def encode_vrs(bones, meshes):
    payload = bytearray(struct.pack('<I', len(bones)))
    for name, parent, rest, inverse in bones:
        name = name.encode('utf-8')
        payload.extend(struct.pack('<H', len(name)))
        payload.extend(name)
        payload.extend(struct.pack('<i32f', parent, *rest, *inverse))
    payload.extend(struct.pack('<I', len(meshes)))
    for factors, width, height, raster, vertices, indices in meshes:
        payload.extend(struct.pack('<6fIII', *factors, width, height, len(raster)))
        payload.extend(raster)
        payload.extend(struct.pack('<II', len(vertices), len(indices)))
        for vertex in vertices:
            payload.extend(VERTEX.pack(*vertex))
        for start in range(0, len(indices), 16384):
            part = indices[start:start + 16384]
            payload.extend(struct.pack('<' + 'I' * len(part), *part))
        require(len(payload) + HEADER.size <= core.MAX_FILE, 'output exceeds 128 MiB')
    data = HEADER.pack(MAGIC, VERSION, len(payload), zlib.crc32(payload), 0) + payload
    inspect_vrs(data)
    return data


def inspect_vrs(data):
    require(HEADER.size <= len(data) <= core.MAX_FILE, 'VRS is truncated or exceeds 128 MiB')
    magic, version, length, checksum, reserved = HEADER.unpack_from(data)
    require(magic == MAGIC and version == VERSION, 'invalid VRS magic/version')
    require(reserved == 0 and length == len(data) - HEADER.size, 'invalid VRS header')
    payload = memoryview(data)[HEADER.size:]
    require(zlib.crc32(payload) == checksum, 'VRS checksum mismatch')
    cursor = 0
    def take(n):
        nonlocal cursor
        require(n <= len(payload) - cursor, 'truncated VRS payload')
        result = payload[cursor:cursor + n]
        cursor += n
        return result
    def unpack(fmt):
        return struct.unpack(fmt, take(struct.calcsize(fmt)))
    count, = unpack('<I')
    require(1 <= count <= MAX_BONES, 'bone count outside 1..128')
    parents = []
    for _ in range(count):
        size, = unpack('<H')
        require(1 <= size <= 64, 'invalid bone name length')
        try:
            name = bytes(take(size)).decode('utf-8')
        except UnicodeDecodeError as exc:
            raise AssetError('invalid UTF-8 bone name') from exc
        require('\x00' not in name, 'NUL in bone name')
        parent, = unpack('<i')
        parents.append(parent)
        matrix_valid(unpack('<16f'), 'bone rest matrix')
        matrix_valid(unpack('<16f'), 'inverse bind matrix')
    validate_parents(parents)
    mesh_count, = unpack('<I')
    require(1 <= mesh_count <= MAX_MESHES, 'mesh count outside 1..128')
    total_v = total_i = total_t = textures = 0
    bounds_min, bounds_max = [math.inf] * 3, [-math.inf] * 3
    for _ in range(mesh_count):
        factors = unpack('<6f')
        require(all(math.isfinite(x) and 0 <= x <= 1 for x in factors), 'invalid material factor')
        width, height, size = unpack('<III')
        require(width <= core.MAX_TEXTURE_DIM and height <= core.MAX_TEXTURE_DIM, 'texture too large')
        require((width == height == size == 0) or (width > 0 and height > 0 and size == width * height * 4), 'invalid RGBA dimensions')
        total_t += size
        require(total_t <= core.MAX_TEXTURE_BYTES, 'aggregate texture budget exceeded')
        take(size)
        textures += int(size > 0)
        vc, ic = unpack('<II')
        require(vc > 0 and ic > 0 and ic % 3 == 0, 'invalid triangle geometry')
        total_v += vc
        total_i += ic
        require(total_v <= core.MAX_VERTICES and total_i <= core.MAX_INDICES, 'aggregate geometry budget exceeded')
        require(vc * VERTEX.size + ic * 4 <= len(payload) - cursor, 'truncated geometry')
        for _ in range(vc):
            v = unpack('<8f8H8f')
            require(all(math.isfinite(x) for x in v), 'non-finite vertex')
            require(all(abs(x) <= core.MAX_POSITION for x in v[:3]) and all(abs(x) <= core.MAX_UV for x in v[6:8]), 'vertex coordinates exceed bounds')
            require(all(abs(x) <= 1.01 for x in v[3:6]), 'normal must be normalized')
            n2 = 0.0
            for x in v[3:6]:
                n2 = core.f32(n2 + core.f32(x * x))
            require(core.f32(.98) <= n2 <= core.f32(1.02), 'normal must be normalized')
            require(all(0 <= j < count for j in v[8:16]), 'joint index outside skin')
            weights = v[16:24]
            require(all(0 <= x <= 1 for x in weights), 'weights must be nonnegative and <=1')
            s = 0.0
            for x in weights:
                s = core.f32(s + x)
            require(all(0 <= x <= 1 for x in weights) and core.f32(.9999) <= s <= core.f32(1.0001), 'weights must be normalized')
            for j in range(3):
                bounds_min[j], bounds_max[j] = min(bounds_min[j], v[j]), max(bounds_max[j], v[j])
        for _ in range(ic):
            idx, = unpack('<I')
            require(idx < vc, 'index outside vertex array')
    require(cursor == len(payload), 'trailing VRS payload bytes')
    return {'format': MAGIC.decode(), 'version': version, 'bones': count, 'meshes': mesh_count,
            'vertices': total_v, 'indices': total_i, 'triangles': total_i // 3,
            'textures': textures, 'texture_bytes': total_t, 'file_bytes': len(data),
            'crc32': f'{checksum:08x}', 'bounds_min': bounds_min, 'bounds_max': bounds_max}


def convert_glb(data, *, base_color_only=False):
    doc, blob = core.parse_glb(data)
    converter = Converter(doc, blob, base_color_only=base_color_only)
    result = converter.convert()
    return result, converter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pack = commands.add_parser('pack')
    pack.add_argument('input', type=Path)
    pack.add_argument('output', type=Path)
    pack.add_argument('--base-color-only', action='store_true', help='explicitly omit normal/ORM textures and simplify linear mipmap sampling')
    pack.add_argument('--force', action='store_true')
    inspect = commands.add_parser('inspect')
    inspect.add_argument('input', type=Path)
    args = parser.parse_args(argv)
    try:
        source = core.read_limited(args.input)
        if args.command == 'pack':
            require(args.input.resolve() != args.output.resolve(), 'input and output paths must differ')
            result, converter = convert_glb(source, base_color_only=args.base_color_only)
            for warning in converter.warnings:
                print(warning, file=sys.stderr)
            core.atomic_write(args.output, result, args.force)
            print(json.dumps(inspect_vrs(result), indent=2, sort_keys=True))
        else:
            print(json.dumps(inspect_vrs(source), indent=2, sort_keys=True))
        return 0
    except (AssetError, OSError, OverflowError, RecursionError, struct.error, UnicodeEncodeError) as exc:
        print(f'vrskin: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
