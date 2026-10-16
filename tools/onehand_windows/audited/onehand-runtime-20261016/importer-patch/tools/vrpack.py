#!/usr/bin/env python3
"""Strict local GLB 2.0 -> Vector Range mesh converter. See docs/ASSET_FORMAT.md.

No source GLB, JSON metadata, names, animation, or external resources are copied.
The format is not encrypted and provides no protection against extraction.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib

MAGIC = b"VRMESH01"
VERSION = 1
HEADER = struct.Struct("<8sIIII")
MAX_FILE = 128 * 1024 * 1024
MAX_MESHES = 256
MAX_VERTICES = 1_000_000
MAX_INDICES = 3_000_000
MAX_TEXTURE_DIM = 2048
MAX_TEXTURE_BYTES = 64 * 1024 * 1024
MAX_NODES = 100_000
MAX_DEPTH = 256
MAX_POSITION = 10_000.0
MAX_UV = 1_000_000.0
IDENTITY = (1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0)


class AssetError(ValueError):
    """Invalid or unsupported source/output; safe to display as a CLI error."""


def require(condition, message):
    if not condition:
        raise AssetError(message)


def uint(value, label, maximum=0xFFFFFFFF):
    require(type(value) is int and 0 <= value <= maximum,
            f"{label} must be a nonnegative integer <= {maximum}")
    return value


def number(value, label):
    require(type(value) in (int, float), f"{label} must be a number")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise AssetError(f"{label} must be finite") from exc
    require(math.isfinite(value) and abs(value) <= 3.4028234663852886e38,
            f"{label} must be finite and representable as float32")
    return value


def vector(value, size, label):
    require(isinstance(value, list) and len(value) == size,
            f"{label} must have {size} numbers")
    return tuple(number(x, label) for x in value)


def objects(value, label):
    require(isinstance(value, list) and all(isinstance(x, dict) for x in value),
            f"{label} must be an array of objects")
    return value


def at(items, index, label):
    index = uint(index, label)
    require(index < len(items), f"{label} is out of range")
    return items[index]


def read_limited(path):
    with open(path, "rb") as source:
        data = source.read(MAX_FILE + 1)
    require(len(data) <= MAX_FILE, "file exceeds 128 MiB limit")
    return data


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bad_constant(value):
    raise AssetError(f"non-finite JSON constant: {value}")


def parse_glb(data):
    require(12 <= len(data) <= MAX_FILE, "GLB is truncated or exceeds 128 MiB")
    magic, version, length = struct.unpack_from("<4sII", data)
    require(magic == b"glTF", "input is not a GLB")
    require(version == 2, "only GLB version 2 is supported")
    require(length == len(data), "GLB declared length does not match file")
    chunks = []
    cursor = 12
    while cursor < length:
        require(len(chunks) < 2, "GLB contains more than JSON and BIN chunks")
        require(cursor + 8 <= length, "truncated GLB chunk header")
        size, kind = struct.unpack_from("<II", data, cursor)
        cursor += 8
        require(size % 4 == 0, "GLB chunk length must be 4-byte aligned")
        require(size <= length - cursor, "GLB chunk exceeds file")
        chunks.append((kind, data[cursor:cursor + size]))
        cursor += size
    require(1 <= len(chunks) <= 2 and chunks[0][0] == 0x4E4F534A,
            "GLB must contain JSON first, followed only by optional BIN")
    require(len(chunks) == 1 or chunks[1][0] == 0x004E4942,
            "unsupported GLB chunk (only JSON and BIN are accepted)")
    try:
        doc = json.loads(chunks[0][1].decode("utf-8"),
                         parse_constant=_bad_constant,
                         object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise AssetError(f"invalid GLB JSON: {exc}") from exc
    require(isinstance(doc, dict), "GLB JSON root must be an object")
    asset = doc.get("asset", {})
    require(isinstance(asset, dict) and asset.get("version") == "2.0",
            "only glTF asset version 2.0 is supported")
    require(asset.get("minVersion", "2.0") == "2.0", "unsupported glTF minVersion")
    return doc, chunks[1][1] if len(chunks) == 2 else b""


def matmul(a, b):
    """Row-major internal matrices; glTF input matrices are column-major."""
    return tuple(sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
                 for r in range(4) for c in range(4))


def determinant(m):
    a, b, c, d, e, f, g, h, i = (m[x] for x in (0, 1, 2, 4, 5, 6, 8, 9, 10))
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def normal_matrix(m):
    a, b, c, d, e, f, g, h, i = (m[x] for x in (0, 1, 2, 4, 5, 6, 8, 9, 10))
    det = determinant(m)
    require(math.isfinite(det) and det != 0.0, "singular or non-finite node transform")
    # Cofactor matrix divided by determinant = inverse transpose.
    return tuple(x / det for x in (e*i-f*h, f*g-d*i, d*h-e*g,
                                   c*h-b*i, a*i-c*g, b*g-a*h,
                                   b*f-c*e, c*d-a*f, a*e-b*d))


def f32(value):
    """Round a bounded arithmetic result exactly as the runtime float type."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def normalized(v, label):
    length = math.hypot(*v)
    require(math.isfinite(length) and length > 0.0, f"{label} has zero/non-finite length")
    result = tuple(x / length for x in v)
    require(all(math.isfinite(x) for x in result), f"{label} is non-finite")
    return result


def node_matrix(node):
    if "matrix" in node:
        require(not any(k in node for k in ("translation", "rotation", "scale")),
                "node cannot combine matrix with TRS")
        col = vector(node["matrix"], 16, "node matrix")
        result = tuple(col[c * 4 + r] for r in range(4) for c in range(4))
        require(result[12:16] == (0.0, 0.0, 0.0, 1.0), "node matrix must be affine")
        return result
    t = vector(node.get("translation", [0, 0, 0]), 3, "node translation")
    s = vector(node.get("scale", [1, 1, 1]), 3, "node scale")
    q = vector(node.get("rotation", [0, 0, 0, 1]), 4, "node rotation")
    require(abs(math.hypot(*q) - 1.0) <= 0.001, "node quaternion must be normalized")
    x, y, z, w = normalized(q, "node quaternion")
    rot = (1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), 0,
           2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), 0,
           2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y), 0,
           0, 0, 0, 1)
    return (rot[0]*s[0], rot[1]*s[1], rot[2]*s[2], t[0],
            rot[4]*s[0], rot[5]*s[1], rot[6]*s[2], t[1],
            rot[8]*s[0], rot[9]*s[1], rot[10]*s[2], t[2],
            0.0, 0.0, 0.0, 1.0)


def reject_extensions(doc):
    # Extras are intentionally ignored. Extensions may change the interpretation
    # of otherwise ordinary values, so even optional extensions are rejected.
    stack = [doc]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key in ("extensions", "extensionsUsed", "extensionsRequired"):
                require(not value.get(key), f"glTF {key} are not supported")
            stack.extend(v for k, v in value.items() if k != "extras")
        elif isinstance(value, list):
            stack.extend(value)


class Converter:
    def __init__(self, doc, blob):
        self.doc, self.blob = doc, blob
        reject_extensions(doc)
        require(not doc.get("animations") and not doc.get("skins"),
                "animations and skinning are not supported; export a static mesh")
        self.buffers = objects(doc.get("buffers", []), "buffers")
        require(len(self.buffers) == 1, "one embedded GLB buffer is required")
        require("uri" not in self.buffers[0], "external/data-URI buffers are not supported")
        self.buffer_length = uint(self.buffers[0].get("byteLength"), "buffer byteLength")
        require(self.buffer_length <= len(blob) <= self.buffer_length + 3,
                "BIN length does not match buffer byteLength (plus <=3 padding bytes)")
        require(not any(blob[self.buffer_length:]), "BIN padding must be zero")
        self.views = objects(doc.get("bufferViews", []), "bufferViews")
        self.accessors = objects(doc.get("accessors", []), "accessors")
        self.images = objects(doc.get("images", []), "images")
        self.textures = objects(doc.get("textures", []), "textures")
        self.samplers = objects(doc.get("samplers", []), "samplers")
        self.materials = objects(doc.get("materials", []), "materials")
        self.meshes = objects(doc.get("meshes", []), "meshes")
        self.nodes = objects(doc.get("nodes", []), "nodes")
        self.scenes = objects(doc.get("scenes", []), "scenes")
        require(len(self.nodes) <= MAX_NODES, "too many GLB nodes")
        for img in self.images:
            require("uri" not in img, "external/data-URI images are not supported")
        for mesh in self.meshes:
            require("weights" not in mesh, "morph weights are not supported")
            for primitive in objects(mesh.get("primitives", []), "primitives"):
                require("targets" not in primitive, "morph targets are not supported")
        for node in self.nodes:
            require("skin" not in node and "weights" not in node,
                    "node skinning/morph weights are not supported")
        for material in self.materials:
            self.validate_material(material)
        self.total_vertices = self.total_indices = self.total_texels = 0
        self.texture_cache = {}

    def view(self, index):
        view = at(self.views, index, "bufferView")
        require(view.get("buffer") == 0 and type(view.get("buffer")) is int,
                "bufferView must reference embedded buffer 0")
        offset = uint(view.get("byteOffset", 0), "bufferView byteOffset")
        length = uint(view.get("byteLength"), "bufferView byteLength")
        require(offset <= self.buffer_length and length <= self.buffer_length - offset,
                "bufferView exceeds embedded buffer")
        return view, offset, length

    def accessor(self, index, semantic):
        acc = at(self.accessors, index, f"{semantic} accessor")
        require("sparse" not in acc, "sparse accessors are not supported")
        require(acc.get("normalized", False) is False, "normalized accessors are not supported")
        if semantic == "indices":
            comp = acc.get("componentType")
            require(type(comp) is int and comp in (5121, 5123, 5125),
                    "indices require UNSIGNED_BYTE/SHORT/INT")
            components, fmt, size, maximum = 1, {5121: "B", 5123: "H", 5125: "I"}[comp], {5121: 1, 5123: 2, 5125: 4}[comp], MAX_INDICES
            require(acc.get("type") == "SCALAR", "indices require SCALAR accessor")
        else:
            components = 2 if semantic == "TEXCOORD_0" else 3
            require(acc.get("componentType") == 5126 and type(acc.get("componentType")) is int,
                    f"{semantic} requires FLOAT components")
            require(acc.get("type") == f"VEC{components}", f"{semantic} requires VEC{components}")
            fmt, size, maximum = "f", 4, MAX_VERTICES
        count = uint(acc.get("count"), f"{semantic} count", maximum)
        require(count > 0, f"{semantic} accessor is empty")
        view, base, length = self.view(acc.get("bufferView"))
        offset = uint(acc.get("byteOffset", 0), "accessor byteOffset")
        require(offset % size == 0 and (base + offset) % size == 0,
                "accessor offset is not component aligned")
        elem_size = size * components
        if "byteStride" in view:
            require(semantic != "indices", "indices cannot have byteStride")
            stride = uint(view["byteStride"], "byteStride", 252)
            require(stride >= elem_size and stride % 4 == 0, "invalid accessor byteStride")
        else:
            stride = elem_size
        require(offset <= length and (count - 1) * stride + elem_size <= length - offset,
                "accessor exceeds bufferView bounds")
        unpack = struct.Struct("<" + fmt * components).unpack_from
        result = [unpack(self.blob, base + offset + i * stride) for i in range(count)]
        if semantic != "indices":
            require(all(math.isfinite(x) for row in result for x in row),
                    f"{semantic} contains non-finite floats")
        return [x[0] for x in result] if semantic == "indices" else result

    @staticmethod
    def validate_material(material):
        require(material.get("alphaMode", "OPAQUE") == "OPAQUE", "only OPAQUE materials are supported")
        require(material.get("doubleSided", False) is False, "double-sided materials are not supported")
        for field in ("normalTexture", "occlusionTexture", "emissiveTexture"):
            require(field not in material, f"{field} is not supported")
        emissive = vector(material.get("emissiveFactor", [0, 0, 0]), 3, "emissiveFactor")
        require(emissive == (0, 0, 0), "emissive material factors are not supported")
        pbr = material.get("pbrMetallicRoughness", {})
        require(isinstance(pbr, dict), "pbrMetallicRoughness must be an object")
        require("metallicRoughnessTexture" not in pbr, "metallicRoughnessTexture is not supported")
        color = vector(pbr.get("baseColorFactor", [1, 1, 1, 1]), 4, "baseColorFactor")
        factors = color + (number(pbr.get("metallicFactor", 1), "metallicFactor"),
                           number(pbr.get("roughnessFactor", 1), "roughnessFactor"))
        require(all(0 <= f <= 1 for f in factors), "material factors must be in [0, 1]")
        return pbr, factors

    def texture(self, texture_info):
        require(isinstance(texture_info, dict), "baseColorTexture must be an object")
        require(texture_info.get("texCoord", 0) == 0 and type(texture_info.get("texCoord", 0)) is int,
                "only TEXCOORD_0 is supported")
        index = uint(texture_info.get("index"), "texture index")
        if index in self.texture_cache:
            return self.texture_cache[index]
        texture = at(self.textures, index, "texture")
        if "sampler" in texture:
            sampler = at(self.samplers, texture["sampler"], "sampler")
            require(sampler.get("wrapS", 10497) == 10497 and sampler.get("wrapT", 10497) == 10497,
                    "v1 supports only REPEAT texture wrapping")
            require(sampler.get("magFilter", 9729) == 9729 and sampler.get("minFilter", 9729) == 9729,
                    "v1 supports only LINEAR texture filtering without mipmaps")
        image = at(self.images, texture.get("source"), "texture source")
        mime = image.get("mimeType")
        require(mime in ("image/png", "image/jpeg"), "only embedded PNG/JPEG images are supported")
        view, offset, length = self.view(image.get("bufferView"))
        require("byteStride" not in view, "image bufferView cannot have a byteStride")
        try:
            from PIL import Image
        except ImportError as exc:
            raise AssetError("embedded textures need Pillow: python3 -m pip install -r tools/requirements-assets.txt") from exc
        try:
            with Image.open(io.BytesIO(self.blob[offset:offset + length])) as decoded:
                require(decoded.format == {"image/png": "PNG", "image/jpeg": "JPEG"}[mime],
                        "image bytes do not match mimeType")
                width, height = decoded.size
                require(0 < width <= MAX_TEXTURE_DIM and 0 < height <= MAX_TEXTURE_DIM,
                        "texture dimensions must be 1..2048 (resize before packing)")
                require(getattr(decoded, "n_frames", 1) == 1, "animated images are not supported")
                # Check dimensions before decoding or allocating the RGBA raster.
                raster = decoded.convert("RGBA").tobytes()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            if isinstance(exc, AssetError):
                raise
            raise AssetError(f"cannot decode embedded image: {exc}") from exc
        require(len(raster) == width * height * 4, "decoded texture length mismatch")
        result = width, height, raster
        self.texture_cache[index] = result
        return result

    def primitive(self, primitive, world):
        require(primitive.get("mode", 4) == 4 and type(primitive.get("mode", 4)) is int,
                "only TRIANGLES primitives are supported")
        attrs = primitive.get("attributes")
        require(isinstance(attrs, dict) and "POSITION" in attrs, "primitive requires POSITION")
        unsupported = set(attrs) - {"POSITION", "NORMAL", "TEXCOORD_0"}
        require(not unsupported, f"unsupported vertex attributes: {', '.join(sorted(unsupported))}")
        positions = self.accessor(attrs["POSITION"], "POSITION")
        n = len(positions)
        indices = self.accessor(primitive["indices"], "indices") if "indices" in primitive else list(range(n))
        require(len(indices) % 3 == 0, "triangle index count must be divisible by 3")
        require(all(i < n for i in indices), "index references a vertex outside POSITION")
        self.total_vertices += n
        self.total_indices += len(indices)
        require(self.total_vertices <= MAX_VERTICES and self.total_indices <= MAX_INDICES,
                "aggregate vertex/index limit exceeded")
        if "NORMAL" in attrs:
            normals = self.accessor(attrs["NORMAL"], "NORMAL")
            require(len(normals) == n, "NORMAL count must match POSITION")
            normals = [normalized(v, "source normal") for v in normals]
        else:
            normals = [[0.0, 0.0, 0.0] for _ in positions]
            for k in range(0, len(indices), 3):
                ia, ib, ic = indices[k:k + 3]
                a, b, c = positions[ia], positions[ib], positions[ic]
                u = tuple(b[j] - a[j] for j in range(3))
                v = tuple(c[j] - a[j] for j in range(3))
                cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
                for idx in (ia, ib, ic):
                    for j in range(3):
                        normals[idx][j] += cross[j]
            normals = [normalized(v, "computed normal (isolated/degenerate vertex)") for v in normals]
        uvs = self.accessor(attrs["TEXCOORD_0"], "TEXCOORD_0") if "TEXCOORD_0" in attrs else [(0.0, 0.0)] * n
        require(len(uvs) == n, "TEXCOORD_0 count must match POSITION")
        material = at(self.materials, primitive["material"], "material") if "material" in primitive else {}
        pbr, factors = self.validate_material(material)
        width, height, raster = 0, 0, b""
        if "baseColorTexture" in pbr:
            require("TEXCOORD_0" in attrs, "textured primitive requires TEXCOORD_0")
            width, height, raster = self.texture(pbr["baseColorTexture"])
        self.total_texels += len(raster)
        require(self.total_texels <= MAX_TEXTURE_BYTES, "aggregate texture bytes exceed 64 MiB")
        nm = normal_matrix(world)
        vertices = []
        for pos, normal, uv in zip(positions, normals, uvs):
            transformed = tuple(sum(world[r * 4 + j] * pos[j] for j in range(3)) + world[r * 4 + 3] for r in range(3))
            direction = normalized(tuple(sum(nm[r * 3 + j] * normal[j] for j in range(3)) for r in range(3)), "transformed normal")
            vertex = transformed + direction + tuple(uv)
            require(all(abs(v) <= MAX_POSITION for v in transformed), "output position exceeds +/-10000 units")
            require(all(abs(v) <= MAX_UV for v in uv), "output UV exceeds +/-1000000")
            for value in vertex:
                number(value, "output vertex")
            vertices.append(vertex)
        if determinant(world) < 0:
            for k in range(0, len(indices), 3):
                indices[k + 1], indices[k + 2] = indices[k + 2], indices[k + 1]
        return factors, width, height, raster, vertices, indices

    def convert(self, scale=1.0, axes="gltf", translate=(0.0, 0.0, 0.0)):
        scale = number(scale, "scale")
        require(scale > 0, "scale must be positive")
        require(axes in ("gltf", "z-up"), "axes must be gltf or z-up")
        shift = vector(list(translate), 3, "translate")
        root_transform = (scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1)
        if axes == "z-up":
            root_transform = (scale, 0, 0, 0, 0, 0, scale, 0, 0, -scale, 0, 0, 0, 0, 0, 1)
        root_transform = list(root_transform)
        root_transform[3], root_transform[7], root_transform[11] = shift
        root_transform = tuple(root_transform)
        require(self.scenes, "a scene with mesh nodes is required")
        scene = at(self.scenes, self.doc.get("scene", 0), "default scene")
        roots = scene.get("nodes", [])
        require(isinstance(roots, list), "scene nodes must be an array")
        require(len(roots) == len(set(uint(n, "scene node") for n in roots)), "duplicate root nodes")
        seen, active = set(), set()
        output = []

        def walk(index, parent, depth):
            require(depth <= MAX_DEPTH, "node hierarchy exceeds 256 levels")
            node = at(self.nodes, index, "node")
            require(index not in active, "cycle in node hierarchy")
            require(index not in seen, "node has multiple parents or occurs multiple times")
            seen.add(index)
            active.add(index)
            world = matmul(parent, node_matrix(node))
            require(all(math.isfinite(v) for v in world), "non-finite composed transform")
            if "mesh" in node:
                mesh = at(self.meshes, node["mesh"], "node mesh")
                primitives = objects(mesh.get("primitives", []), "primitives")
                require(primitives, "mesh has no primitives")
                require(len(output) + len(primitives) <= MAX_MESHES, "mesh primitive count exceeds 256")
                for primitive in primitives:
                    output.append(self.primitive(primitive, world))
            children = node.get("children", [])
            require(isinstance(children, list), "node children must be an array")
            for child in children:
                walk(uint(child, "child node"), world, depth + 1)
            active.remove(index)

        for root in roots:
            walk(uint(root, "root node"), root_transform, 0)
        require(output, "default scene contains no triangle meshes")
        return encode_vrm(output)


def encode_vrm(meshes):
    payload = bytearray(struct.pack("<I", len(meshes)))
    for factors, width, height, raster, vertices, indices in meshes:
        payload.extend(struct.pack("<6fIII", *factors, width, height, len(raster)))
        payload.extend(raster)
        payload.extend(struct.pack("<II", len(vertices), len(indices)))
        for vertex in vertices:
            payload.extend(struct.pack("<8f", *vertex))
        # Chunk to avoid a million-argument struct.pack call.
        for start in range(0, len(indices), 16384):
            part = indices[start:start + 16384]
            payload.extend(struct.pack("<" + "I" * len(part), *part))
        require(len(payload) + HEADER.size <= MAX_FILE, "output exceeds 128 MiB")
    data = HEADER.pack(MAGIC, VERSION, len(payload), zlib.crc32(payload), 0) + payload
    inspect_vrm(data)  # Self-check exact binary contract before committing a file.
    return data


def inspect_vrm(data):
    require(HEADER.size <= len(data) <= MAX_FILE, "VRM is truncated or exceeds 128 MiB")
    magic, version, length, checksum, reserved = HEADER.unpack_from(data)
    require(magic == MAGIC, "invalid VRM magic")
    require(version == VERSION, "unsupported VRM version")
    require(reserved == 0, "VRM reserved header word must be zero")
    require(length == len(data) - HEADER.size, "VRM payload length mismatch")
    payload = memoryview(data)[HEADER.size:]
    require(zlib.crc32(payload) == checksum, "VRM checksum mismatch")
    cursor = 0

    def unpack(fmt):
        nonlocal cursor
        layout = struct.Struct(fmt)
        require(cursor + layout.size <= len(payload), "truncated VRM payload")
        result = layout.unpack_from(payload, cursor)
        cursor += layout.size
        return result

    count, = unpack("<I")
    require(0 < count <= MAX_MESHES, "VRM mesh count must be 1..256")
    total_v = total_i = total_t = 0
    bounds_min, bounds_max = [math.inf] * 3, [-math.inf] * 3
    texture_count = 0
    for _ in range(count):
        factors = unpack("<6f")
        require(all(math.isfinite(f) and 0 <= f <= 1 for f in factors), "invalid VRM material factor")
        width, height, size = unpack("<III")
        if width == 0 or height == 0 or size == 0:
            require((width, height, size) == (0, 0, 0), "invalid empty VRM texture")
        else:
            require(width <= MAX_TEXTURE_DIM and height <= MAX_TEXTURE_DIM and size == width * height * 4,
                    "invalid VRM texture dimensions or length")
            texture_count += 1
        total_t += size
        require(total_t <= MAX_TEXTURE_BYTES, "VRM aggregate texture limit exceeded")
        require(size <= len(payload) - cursor, "truncated VRM texture")
        cursor += size
        vertex_count, index_count = unpack("<II")
        require(vertex_count > 0 and index_count > 0 and index_count % 3 == 0,
                "VRM needs nonempty triangle geometry")
        total_v += vertex_count
        total_i += index_count
        require(total_v <= MAX_VERTICES and total_i <= MAX_INDICES, "VRM aggregate geometry limit exceeded")
        require(vertex_count * 32 + index_count * 4 <= len(payload) - cursor,
                "VRM geometry exceeds payload")
        for _ in range(vertex_count):
            vertex = unpack("<8f")
            require(all(math.isfinite(v) for v in vertex), "VRM vertex contains non-finite float")
            require(all(abs(v) <= 1.01 for v in vertex[3:6]), "VRM normal is not normalized")
            # Mirror Rust f32 products/additions and bounds, including rounding
            # at the tolerance boundary instead of checking Python doubles.
            n2 = 0.0
            for value in vertex[3:6]:
                n2 = f32(n2 + f32(value * value))
            require(f32(0.98) <= n2 <= f32(1.02), "VRM normal is not normalized")
            require(all(abs(v) <= MAX_POSITION for v in vertex[:3]), "VRM position exceeds +/-10000 units")
            require(all(abs(v) <= MAX_UV for v in vertex[6:]), "VRM UV exceeds +/-1000000")
            for j in range(3):
                bounds_min[j] = min(bounds_min[j], vertex[j])
                bounds_max[j] = max(bounds_max[j], vertex[j])
        for _ in range(index_count):
            idx, = unpack("<I")
            require(idx < vertex_count, "VRM index is out of bounds")
    require(cursor == len(payload), "trailing VRM payload bytes")
    return {"format": MAGIC.decode("ascii"), "version": version, "file_bytes": len(data),
            "payload_bytes": length, "crc32": f"{checksum:08x}", "meshes": count,
            "vertices": total_v, "indices": total_i, "triangles": total_i // 3,
            "textures": texture_count, "texture_bytes": total_t,
            "bounds_min": bounds_min, "bounds_max": bounds_max}


def convert_glb(data, scale=1.0, axes="gltf", translate=(0.0, 0.0, 0.0)):
    doc, blob = parse_glb(data)
    return Converter(doc, blob).convert(scale=scale, axes=axes, translate=translate)


def atomic_write(path, data, force=False):
    path = Path(path)
    require(not path.exists() or force, f"output already exists: {path}; use --force to replace")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if force:
            os.replace(temp, path)
        else:
            # Same-directory hard link is an atomic no-clobber publication; the
            # pre-check alone would race another writer creating the destination.
            try:
                os.link(temp, path)
            except FileExistsError as exc:
                raise AssetError(f"output already exists: {path}; use --force to replace") from exc
            temp.unlink()
        temp = None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack", help="convert a locally licensed static GLB to .vrm")
    pack.add_argument("input", type=Path)
    pack.add_argument("output", type=Path)
    pack.add_argument("--scale", type=float, default=1.0, help="positive uniform scale applied after node transforms")
    pack.add_argument("--axes", choices=("gltf", "z-up"), default="gltf", help="gltf preserves x/y/z; z-up maps (x,y,z) to (x,z,-y)")
    pack.add_argument("--translate", type=float, nargs=3, metavar=("X", "Y", "Z"), default=(0, 0, 0),
                      help="translation in output units, applied after scale and axes conversion")
    pack.add_argument("--force", action="store_true", help="atomically replace an existing output")
    inspect = commands.add_parser("inspect", help="validate .vrm and print its geometry summary")
    inspect.add_argument("input", type=Path)
    args = parser.parse_args(argv)
    try:
        source = read_limited(args.input)
        if args.command == "pack":
            require(args.input.resolve() != args.output.resolve(), "input and output paths must differ")
            result = convert_glb(source, scale=args.scale, axes=args.axes, translate=args.translate)
            atomic_write(args.output, result, args.force)
            print(f"Packed {args.output}: {json.dumps(inspect_vrm(result), sort_keys=True)}")
        else:
            print(json.dumps(inspect_vrm(source), indent=2, sort_keys=True))
        return 0
    except (AssetError, OSError, OverflowError, RecursionError, struct.error) as exc:
        print(f"vrpack: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
