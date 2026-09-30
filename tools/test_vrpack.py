#!/usr/bin/env python3
"""Original synthetic fixtures only; no purchased or third-party source models.

Run: python3 -m unittest discover -s tools -p 'test_*.py' -v
Regenerate shared Rust fixture: python3 tools/test_vrpack.py --write-fixture tests/fixtures/triangle.vrm
"""
import io
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

import vrpack


POSITIONS = [(-0.5, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 1.0, 0.0)]
UVS = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
FACTORS = (0.2, 0.4, 0.8, 1.0, 0.1, 0.7)


def fixture(indexed=True, normals=False, texture=None):
    """Create our own triangle and optionally an in-memory original 2x1 PNG."""
    blob = bytearray()
    views, accessors = [], []

    def add_view(data, stride=None):
        blob.extend(b"\0" * ((-len(blob)) % 4))
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if stride:
            view["byteStride"] = stride
        views.append(view)
        blob.extend(data)
        return len(views) - 1

    def add_accessor(values, fmt, kind, component_type):
        flat = [part for row in values for part in row] if kind != "SCALAR" else values
        view = add_view(struct.pack("<" + fmt * len(flat), *flat))
        accessors.append({"bufferView": view, "componentType": component_type,
                          "count": len(values), "type": kind})
        return len(accessors) - 1

    attrs = {"POSITION": add_accessor(POSITIONS, "f", "VEC3", 5126),
             "TEXCOORD_0": add_accessor(UVS, "f", "VEC2", 5126)}
    if normals:
        attrs["NORMAL"] = add_accessor([(0, 0, 1)] * 3, "f", "VEC3", 5126)
    primitive = {"attributes": attrs, "material": 0}
    if indexed:
        primitive["indices"] = add_accessor([0, 1, 2], "H", "SCALAR", 5123)
    doc = {"asset": {"version": "2.0", "generator": "original test fixture; metadata not shipped"},
           "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
           "meshes": [{"primitives": [primitive]}], "bufferViews": views, "accessors": accessors,
           "materials": [{"pbrMetallicRoughness": {"baseColorFactor": list(FACTORS[:4]),
                                                   "metallicFactor": FACTORS[4], "roughnessFactor": FACTORS[5]}}]}
    if texture is not None:
        doc["images"] = [{"bufferView": add_view(texture), "mimeType": "image/png"}]
        doc["textures"] = [{"source": 0}]
        doc["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    doc["buffers"] = [{"byteLength": len(blob)}]
    return doc, blob


def glb(doc, blob):
    raw_json = json.dumps(doc, separators=(",", ":"), allow_nan=True).encode("utf-8")
    raw_json += b" " * (-len(raw_json) % 4)
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)
    chunks = struct.pack("<II", len(raw_json), 0x4E4F534A) + raw_json
    chunks += struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


def packed_fixture():
    return vrpack.convert_glb(glb(*fixture()))


def mesh_bytes(data):
    """Independent tiny fixture decoder, not the production inspector."""
    cursor = 28
    factors = struct.unpack_from("<6f", data, cursor)
    cursor += 24
    w, h, n = struct.unpack_from("<III", data, cursor)
    cursor += 12
    pixels = data[cursor:cursor + n]
    cursor += n
    vc, ic = struct.unpack_from("<II", data, cursor)
    cursor += 8
    vertices = [struct.unpack_from("<8f", data, cursor + i * 32) for i in range(vc)]
    cursor += vc * 32
    indices = struct.unpack_from("<" + "I" * ic, data, cursor)
    return factors, (w, h, pixels), vertices, indices


def repack_payload(payload):
    return vrpack.HEADER.pack(vrpack.MAGIC, 1, len(payload), zlib.crc32(payload), 0) + payload


class ConversionTests(unittest.TestCase):
    def test_deterministic_original_fixture_and_no_source_metadata(self):
        data = packed_fixture()
        self.assertEqual(data, packed_fixture())
        self.assertEqual(len(data), 180)
        self.assertNotIn(b"glTF", data)
        self.assertNotIn(b"generator", data)
        summary = vrpack.inspect_vrm(data)
        self.assertEqual((summary["meshes"], summary["vertices"], summary["indices"]), (1, 3, 3))
        self.assertEqual(summary["bounds_min"], [-0.5, 0.0, 0.0])
        self.assertEqual(summary["bounds_max"], [0.5, 1.0, 0.0])
        factors, texture, vertices, indices = mesh_bytes(data)
        for actual, expected in zip(factors, FACTORS):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(texture, (0, 0, b""))
        for i, vertex in enumerate(vertices):
            self.assertEqual(vertex[:3], POSITIONS[i])
            self.assertEqual(vertex[3:6], (0, 0, 1))
            self.assertEqual(vertex[6:], UVS[i])
        self.assertEqual(indices, (0, 1, 2))

    def test_fixture_on_disk_matches_generator(self):
        fixture_path = Path(__file__).resolve().parents[1] / "tests/fixtures/triangle.vrm"
        self.assertEqual(fixture_path.read_bytes(), packed_fixture())

    def test_unindexed_triangles_and_supplied_normals(self):
        for indexed in (False, True):
            for normals in (False, True):
                self.assertEqual(vrpack.convert_glb(glb(*fixture(indexed, normals))), packed_fixture())

    def test_transform_and_mirrored_winding(self):
        doc, blob = fixture()
        doc["nodes"][0].update(translation=[1, 2, 3], scale=[-2, 3, 4])
        data = vrpack.convert_glb(glb(doc, blob))
        _, _, vertices, indices = mesh_bytes(data)
        self.assertEqual(vertices[0][:3], (2, 2, 3))
        self.assertEqual(vertices[2][:3], (1, 5, 3))
        self.assertEqual(vertices[0][3:6], (0, 0, 1))
        self.assertEqual(indices, (0, 2, 1))

    def test_inverse_transpose_normal_with_nonuniform_scale(self):
        doc, blob = fixture(normals=True)
        idx = doc["meshes"][0]["primitives"][0]["attributes"]["NORMAL"]
        view = doc["bufferViews"][doc["accessors"][idx]["bufferView"]]
        for i in range(3):
            struct.pack_into("<3f", blob, view["byteOffset"] + i * 12, 1, 1, 1)
        doc["nodes"][0]["scale"] = [2, 3, 4]
        vertices = mesh_bytes(vrpack.convert_glb(glb(doc, blob)))[2]
        expected = vrpack.normalized((1/2, 1/3, 1/4), "test")
        for actual, wanted in zip(vertices[0][3:6], expected):
            self.assertAlmostEqual(actual, wanted, places=6)

    def test_column_major_matrix(self):
        doc, blob = fixture()
        doc["nodes"][0]["matrix"] = [1, 0, 0, 0, 0, 2, 0, 0, 0, 0, 3, 0, 4, 5, 6, 1]
        vertices = mesh_bytes(vrpack.convert_glb(glb(doc, blob)))[2]
        self.assertEqual(vertices[0][:3], (3.5, 5, 6))
        self.assertEqual(vertices[2][:3], (4, 7, 6))

    def test_quaternion_rotation(self):
        doc, blob = fixture()
        doc["nodes"][0]["rotation"] = [0, 0, math.sqrt(0.5), math.sqrt(0.5)]
        vertices = mesh_bytes(vrpack.convert_glb(glb(doc, blob)))[2]
        self.assertAlmostEqual(vertices[2][0], -1)
        self.assertAlmostEqual(vertices[2][1], 0)

    def test_parent_child_and_mesh_instancing(self):
        doc, blob = fixture()
        doc["nodes"] = [{"translation": [1, 0, 0], "children": [1, 2]},
                        {"mesh": 0, "translation": [0, 2, 0]}, {"mesh": 0}]
        summary = vrpack.inspect_vrm(vrpack.convert_glb(glb(doc, blob)))
        self.assertEqual(summary["meshes"], 2)
        self.assertEqual(summary["bounds_min"], [0.5, 0, 0])
        self.assertEqual(summary["bounds_max"], [1.5, 3, 0])

    def test_default_scene_and_first_scene_fallback(self):
        doc, blob = fixture()
        doc["scenes"].append({"nodes": [1]})
        doc["nodes"].append({"mesh": 0, "translation": [10, 0, 0]})
        doc["scene"] = 1
        summary = vrpack.inspect_vrm(vrpack.convert_glb(glb(doc, blob)))
        self.assertEqual(summary["bounds_min"][0], 9.5)
        del doc["scene"]
        self.assertEqual(vrpack.convert_glb(glb(doc, blob)), packed_fixture())

    def test_scale_and_axes(self):
        data = vrpack.convert_glb(glb(*fixture()), scale=2, axes="z-up")
        vertices = mesh_bytes(data)[2]
        self.assertEqual(vertices[2][:3], (0, 0, -2))
        self.assertEqual(vertices[2][3:6], (0, 1, 0))
        for value in (0, -1, math.inf, math.nan):
            with self.subTest(scale=value), self.assertRaises(vrpack.AssetError):
                vrpack.convert_glb(glb(*fixture()), scale=value)

    def test_translate_applied_after_scale_and_axis_conversion(self):
        data = vrpack.convert_glb(glb(*fixture()), scale=2, axes="z-up", translate=(1, 2, 3))
        vertices = mesh_bytes(data)[2]
        self.assertEqual(vertices[0][:3], (0, 2, 3))
        self.assertEqual(vertices[2][:3], (1, 2, 1))
        with self.assertRaises(vrpack.AssetError):
            vrpack.convert_glb(glb(*fixture()), translate=(0, math.inf, 0))

    def test_position_and_uv_range_limits(self):
        with self.assertRaisesRegex(vrpack.AssetError, "position"):
            vrpack.convert_glb(glb(*fixture()), translate=(10001, 0, 0))
        doc, blob = fixture()
        uv_offset = doc["bufferViews"][doc["accessors"][1]["bufferView"]]["byteOffset"]
        struct.pack_into("<f", blob, uv_offset, 1000001)
        with self.assertRaisesRegex(vrpack.AssetError, "UV"):
            vrpack.convert_glb(glb(doc, blob))

    def test_interleaved_positions(self):
        doc, blob = fixture()
        new = b"".join(struct.pack("<4f", *p, 99) for p in POSITIONS)
        start = len(blob) + (-len(blob) % 4)
        blob += b"\0" * (-len(blob) % 4) + new
        doc["bufferViews"][0] = {"buffer": 0, "byteOffset": start, "byteLength": len(new), "byteStride": 16}
        doc["buffers"][0]["byteLength"] = len(blob)
        self.assertEqual(vrpack.convert_glb(glb(doc, blob)), packed_fixture())

    def test_missing_uv_defaults_to_zero_for_untextured_primitive(self):
        doc, blob = fixture()
        del doc["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"]
        self.assertTrue(all(v[6:] == (0, 0) for v in mesh_bytes(vrpack.convert_glb(glb(doc, blob)))[2]))

    def test_uint8_and_uint32_indices(self):
        for ctype, fmt in ((5121, "B"), (5125, "I")):
            doc, blob = fixture()
            acc = doc["accessors"][-1]
            offset = len(blob) + (-len(blob) % 4)
            raw = struct.pack("<" + fmt * 3, 0, 1, 2)
            blob += b"\0" * (-len(blob) % 4) + raw
            doc["bufferViews"][acc["bufferView"]] = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
            acc["componentType"] = ctype
            doc["buffers"][0]["byteLength"] = len(blob)
            self.assertEqual(vrpack.convert_glb(glb(doc, blob)), packed_fixture())

    def test_unsupported_source_semantics(self):
        mutations = [
            ("extensions", lambda d: d.update(extensionsUsed=["KHR_mesh_quantization"])),
            ("extension inside material", lambda d: d["materials"][0].update(extensions={"KHR_materials_unlit": {}})),
            ("animations", lambda d: d.update(animations=[{}])),
            ("skins", lambda d: d.update(skins=[{}])),
            ("node skin", lambda d: d["nodes"][0].update(skin=0)),
            ("morph weights", lambda d: d["meshes"][0].update(weights=[])),
            ("morph targets", lambda d: d["meshes"][0]["primitives"][0].update(targets=[])),
            ("external buffer", lambda d: d["buffers"][0].update(uri="external.bin")),
            ("external image", lambda d: d.update(images=[{"uri": "https://example.test/texture.png"}])),
            ("blend", lambda d: d["materials"][0].update(alphaMode="BLEND")),
            ("mask", lambda d: d["materials"][0].update(alphaMode="MASK")),
            ("two-sided", lambda d: d["materials"][0].update(doubleSided=True)),
            ("normal map", lambda d: d["materials"][0].update(normalTexture={"index": 0})),
            ("occlusion", lambda d: d["materials"][0].update(occlusionTexture={"index": 0})),
            ("emissive map", lambda d: d["materials"][0].update(emissiveTexture={"index": 0})),
            ("emissive factor", lambda d: d["materials"][0].update(emissiveFactor=[0, 0, 1])),
            ("metallic map", lambda d: d["materials"][0]["pbrMetallicRoughness"].update(metallicRoughnessTexture={"index": 0})),
            ("vertex color", lambda d: d["meshes"][0]["primitives"][0]["attributes"].update(COLOR_0=0)),
            ("lines", lambda d: d["meshes"][0]["primitives"][0].update(mode=1)),
            ("sparse", lambda d: d["accessors"][0].update(sparse={})),
            ("normalized", lambda d: d["accessors"][0].update(normalized=True)),
        ]
        for name, mutate in mutations:
            with self.subTest(case=name):
                doc, blob = fixture()
                mutate(doc)
                with self.assertRaises(vrpack.AssetError):
                    vrpack.convert_glb(glb(doc, blob))

    def test_malformed_accessor_and_buffer_bounds(self):
        mutations = [
            lambda d: d["accessors"][0].update(bufferView=999),
            lambda d: d["accessors"][0].update(count=0),
            lambda d: d["accessors"][0].update(count=4),
            lambda d: d["accessors"][0].update(count=vrpack.MAX_VERTICES+1),
            lambda d: d["accessors"][0].update(count=-1),
            lambda d: d["accessors"][0].update(count=True),
            lambda d: d["accessors"][0].update(count=3.0),
            lambda d: d["accessors"][0].update(byteOffset=2),
            lambda d: d["accessors"][0].update(byteOffset=99999),
            lambda d: d["accessors"][0].update(componentType=5123),
            lambda d: d["accessors"][0].update(type="VEC4"),
            lambda d: d["bufferViews"][0].update(byteLength=35),
            lambda d: d["bufferViews"][0].update(byteOffset=99999),
            lambda d: d["bufferViews"][0].update(byteStride=8),
            lambda d: d["bufferViews"][0].update(byteStride=13),
            lambda d: d["bufferViews"][0].update(byteStride=256),
            lambda d: d["bufferViews"][-1].update(byteStride=4),
            lambda d: d["bufferViews"][0].update(buffer=1),
            lambda d: d["accessors"][1].update(count=2),
            lambda d: d["buffers"][0].update(byteLength=1),
            lambda d: d["buffers"][0].update(byteLength=100000),
        ]
        for mutate in mutations:
            doc, blob = fixture()
            mutate(doc)
            with self.subTest(doc=doc), self.assertRaises(vrpack.AssetError):
                vrpack.convert_glb(glb(doc, blob))

    def test_nonfinite_positions_and_json(self):
        for value in (math.nan, math.inf, -math.inf):
            doc, blob = fixture()
            struct.pack_into("<f", blob, 0, value)
            with self.assertRaises(vrpack.AssetError):
                vrpack.convert_glb(glb(doc, blob))
            doc, blob = fixture()
            doc["nodes"][0]["translation"] = [0, value, 0]
            with self.assertRaises(vrpack.AssetError):
                vrpack.convert_glb(glb(doc, blob))

    def test_invalid_indices_and_degenerate_missing_normals(self):
        doc, blob = fixture()
        view = doc["bufferViews"][doc["accessors"][-1]["bufferView"]]
        struct.pack_into("<H", blob, view["byteOffset"], 999)
        with self.assertRaisesRegex(vrpack.AssetError, "outside POSITION"):
            vrpack.convert_glb(glb(doc, blob))
        doc, blob = fixture()
        doc["accessors"][-1]["count"] = 2
        with self.assertRaisesRegex(vrpack.AssetError, "divisible by 3"):
            vrpack.convert_glb(glb(doc, blob))
        doc, blob = fixture()
        struct.pack_into("<3f", blob, 24, 0, 0, 0)
        with self.assertRaisesRegex(vrpack.AssetError, "computed normal"):
            vrpack.convert_glb(glb(doc, blob))

    def test_invalid_material_factors(self):
        for field, value in (("baseColorFactor", [2, 1, 1, 1]), ("metallicFactor", -1), ("roughnessFactor", math.nan)):
            doc, blob = fixture()
            doc["materials"][0]["pbrMetallicRoughness"][field] = value
            with self.assertRaises(vrpack.AssetError):
                vrpack.convert_glb(glb(doc, blob))

    def test_cycles_multiple_parents_and_depth_limit(self):
        for nodes in ([{"children": [0]}],
                      [{"children": [1]}, {"children": [0]}],
                      [{"children": [1, 1]}, {"mesh": 0}],
                      [{"children": [i+1]} for i in range(258)] + [{"mesh": 0}]):
            doc, blob = fixture()
            doc["nodes"] = nodes
            with self.assertRaises(vrpack.AssetError):
                vrpack.convert_glb(glb(doc, blob))

    def test_bad_transforms(self):
        for update in ({"scale": [0, 1, 1]}, {"rotation": [0, 0, 0, 0]},
                       {"matrix": list(vrpack.IDENTITY), "scale": [1, 1, 1]},
                       {"matrix": [0]*16}, {"translation": [1, 2]}):
            doc, blob = fixture()
            doc["nodes"][0].update(update)
            with self.assertRaises(vrpack.AssetError):
                vrpack.convert_glb(glb(doc, blob))

    def test_aggregate_limits(self):
        for constant, limit, expected in (("MAX_MESHES", 0, "mesh primitive"),
                                           ("MAX_VERTICES", 2, "count"),
                                           ("MAX_INDICES", 2, "count")):
            with mock.patch.object(vrpack, constant, limit), self.assertRaisesRegex(vrpack.AssetError, expected):
                packed_fixture()
        doc, blob = fixture()
        doc["nodes"] = [{"mesh": 0}, {"mesh": 0}]
        doc["scenes"][0]["nodes"] = [0, 1]
        with mock.patch.object(vrpack, "MAX_VERTICES", 5), self.assertRaisesRegex(vrpack.AssetError, "aggregate"):
            vrpack.convert_glb(glb(doc, blob))

    def test_malformed_glb_container(self):
        raw = glb(*fixture())
        mutants = [b"", raw[:11], b"NOPE" + raw[4:], raw[:-1], raw + b"x"]
        for offset, value in ((4, 1), (8, 1), (12, 3), (16, 0), (12, 0xFFFFFFFC)):
            mutant = bytearray(raw)
            struct.pack_into("<I", mutant, offset, value)
            mutants.append(mutant)
        for mutant in mutants:
            with self.subTest(length=len(mutant)), self.assertRaises(vrpack.AssetError):
                vrpack.convert_glb(mutant)

    def test_extra_glb_chunks_are_rejected(self):
        raw = bytearray(glb(*fixture()))
        raw += struct.pack("<II", 0, 0x004E4942) * 10
        struct.pack_into("<I", raw, 8, len(raw))
        with self.assertRaisesRegex(vrpack.AssetError, "more than"):
            vrpack.convert_glb(raw)

    def test_duplicate_json_key_rejected(self):
        text = b'{"asset":{"version":"2.0","version":"2.0"}}'
        text += b" " * (-len(text) % 4)
        raw = struct.pack("<4sIIII", b"glTF", 2, 20+len(text), len(text), 0x4E4F534A) + text
        with self.assertRaisesRegex(vrpack.AssetError, "duplicate"):
            vrpack.convert_glb(raw)


try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


@unittest.skipUnless(HAS_PILLOW, "optional Pillow not installed")
class TextureTests(unittest.TestCase):
    def png(self, size=(2, 1)):
        image = Image.new("RGBA", size)
        if size == (2, 1):
            image.putdata([(255, 0, 0, 255), (0, 255, 0, 128)])
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def test_embedded_rgba_no_flip(self):
        data = vrpack.convert_glb(glb(*fixture(texture=self.png())))
        self.assertEqual(mesh_bytes(data)[1], (2, 1, bytes([255, 0, 0, 255, 0, 255, 0, 128])))
        summary = vrpack.inspect_vrm(data)
        self.assertEqual((summary["textures"], summary["texture_bytes"]), (1, 8))

    def test_jpeg_decode(self):
        output = io.BytesIO()
        Image.new("RGB", (1, 1), (17, 41, 69)).save(output, format="JPEG")
        doc, blob = fixture(texture=output.getvalue())
        doc["images"][0]["mimeType"] = "image/jpeg"
        w, h, pixels = mesh_bytes(vrpack.convert_glb(glb(doc, blob)))[1]
        self.assertEqual((w, h, len(pixels), pixels[3]), (1, 1, 4, 255))

    def test_texture_failures(self):
        mutators = [
            lambda d: d["images"][0].update(mimeType="image/webp"),
            lambda d: d["images"][0].update(mimeType="image/jpeg"),
            lambda d: d["textures"][0].update(source=2),
            lambda d: d["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"].update(texCoord=1),
            lambda d: d["meshes"][0]["primitives"][0]["attributes"].pop("TEXCOORD_0"),
            lambda d: d.update(samplers=[{"wrapS": 33071}]),
            lambda d: d.update(samplers=[{"magFilter": 9728}]),
            lambda d: d.update(samplers=[{"minFilter": 9987}]),
        ]
        for mutate in mutators:
            doc, blob = fixture(texture=self.png())
            mutate(doc)
            if "samplers" in doc:
                doc["textures"][0]["sampler"] = 0
            with self.assertRaises(vrpack.AssetError):
                vrpack.convert_glb(glb(doc, blob))
        with self.assertRaises(vrpack.AssetError):
            vrpack.convert_glb(glb(*fixture(texture=b"not an image")))
        with self.assertRaisesRegex(vrpack.AssetError, "1..2048"):
            vrpack.convert_glb(glb(*fixture(texture=self.png((2049, 1)))))
        with mock.patch.object(vrpack, "MAX_TEXTURE_BYTES", 7), self.assertRaisesRegex(vrpack.AssetError, "aggregate texture"):
            vrpack.convert_glb(glb(*fixture(texture=self.png())))

    def test_missing_pillow_explained(self):
        source = glb(*fixture(texture=self.png()))
        with mock.patch.dict(sys.modules, {"PIL": None}), self.assertRaisesRegex(vrpack.AssetError, "Pillow"):
            vrpack.convert_glb(source)


class VrmValidationTests(unittest.TestCase):
    def test_bad_headers(self):
        data = packed_fixture()
        mutants = [b"", data[:23], b"INVALID!" + data[8:], data[:-1], data + b"x"]
        for offset, value in ((8, 2), (12, 0), (16, 0), (20, 1)):
            value_bytes = bytearray(data)
            struct.pack_into("<I", value_bytes, offset, value)
            mutants.append(value_bytes)
        for raw in mutants:
            with self.assertRaises(vrpack.AssetError):
                vrpack.inspect_vrm(raw)

    def test_payload_mutations_with_valid_crc(self):
        # Payload layout: count@0; factors@4; texture@28; counts@40;
        # vertices@48 (32 bytes each); three indices@144.
        for offset, fmt, value in ((0, "I", 0), (0, "I", 257), (4, "f", math.nan),
                                   (4, "f", 1.01), (28, "I", 1), (32, "I", 2049),
                                   (36, "I", 4), (40, "I", 0), (40, "I", 1_000_001),
                                   (44, "I", 4), (44, "I", 3_000_003),
                                   (48, "f", math.inf), (48, "f", 10001), (72, "f", 1000001), (60, "f", 1), (144, "I", 3)):
            payload = bytearray(packed_fixture()[24:])
            struct.pack_into("<" + fmt, payload, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(vrpack.AssetError):
                vrpack.inspect_vrm(repack_payload(payload))
        for payload in (packed_fixture()[24:] + b"x", packed_fixture()[24:-1]):
            with self.assertRaises(vrpack.AssetError):
                vrpack.inspect_vrm(repack_payload(payload))

    def test_runtime_normal_tolerance(self):
        for z, accepted in ((0.99, True), (1.009, True), (0.98, False), (1.02, False)):
            payload = bytearray(packed_fixture()[24:])
            struct.pack_into("<f", payload, 68, z)
            if accepted:
                vrpack.inspect_vrm(repack_payload(payload))
            else:
                with self.assertRaises(vrpack.AssetError):
                    vrpack.inspect_vrm(repack_payload(payload))

    def test_all_truncated_prefixes_are_rejected(self):
        raw = packed_fixture()
        for length in range(len(raw)):
            with self.subTest(length=length), self.assertRaises(vrpack.AssetError):
                vrpack.inspect_vrm(raw[:length])

    def test_bad_texture_header(self):
        base = bytearray(packed_fixture()[24:])
        for values in ((2049, 1, 8196), (1, 1, 3), (0, 1, 0), (1, 0, 0), (2048, 2048, 16777216)):
            payload = base.copy()
            struct.pack_into("<III", payload, 28, *values)
            with self.assertRaises(vrpack.AssetError):
                vrpack.inspect_vrm(repack_payload(payload))


class FileAndCliTests(unittest.TestCase):
    def test_atomic_write_no_clobber_and_force(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.vrm"
            vrpack.atomic_write(path, b"first")
            with self.assertRaisesRegex(vrpack.AssetError, "already exists"):
                vrpack.atomic_write(path, b"second")
            self.assertEqual(path.read_bytes(), b"first")
            vrpack.atomic_write(path, b"second", force=True)
            self.assertEqual(path.read_bytes(), b"second")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_cli_pack_inspect_and_refuse_input_overwrite(self):
        command = [sys.executable, str(Path(vrpack.__file__).resolve())]
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.glb", Path(directory) / "weapon.vrm"
            source.write_bytes(glb(*fixture()))
            run = subprocess.run(command + ["pack", str(source), str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(output.read_bytes(), packed_fixture())
            run = subprocess.run(command + ["inspect", str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["triangles"], 1)
            run = subprocess.run(command + ["pack", str(source), str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertIn("already exists", run.stderr)
            run = subprocess.run(command + ["pack", str(source), str(source), "--force"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertIn("must differ", run.stderr)

    def test_cli_failure_does_not_create_or_replace_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "bad.glb", Path(directory) / "weapon.vrm"
            source.write_bytes(b"bad")
            output.write_bytes(b"keep")
            with mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(vrpack.main(["pack", str(source), str(output), "--force"]), 1)
            self.assertEqual(output.read_bytes(), b"keep")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--write-fixture":
        destination = Path(sys.argv[2])
        vrpack.atomic_write(destination, packed_fixture(), force=True)
        print(f"Wrote original generated fixture: {destination} ({len(packed_fixture())} bytes)")
    else:
        unittest.main()
