"""Per-instance export regressions using original, synthetic source geometry."""
import contextlib
import gzip
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import numpy as np

import build_city
from city_buildings import Building, SPECS
import validate_city


def source_glb(path, primitive_specs=((3, '<u2'),)):
    """Write real glTF primitives; no downloaded or private source fixture."""
    payload = bytearray()
    views, accessors, primitives = [], [], []

    def accessor(values, component, kind):
        while len(payload) % 4:
            payload.append(0)
        encoded = values.tobytes()
        views.append({'buffer': 0, 'byteOffset': len(payload), 'byteLength': len(encoded)})
        payload.extend(encoded)
        accessors.append({'bufferView': len(views) - 1, 'componentType': component,
                          'count': len(values), 'type': kind})
        return len(accessors) - 1

    for count, index_type in primitive_specs:
        positions = np.zeros((count, 3), dtype='<f4')
        positions[:, 0] = np.arange(count)
        positions[:, 2] = np.arange(count) % 3
        normals = np.zeros_like(positions)
        normals[:, 1] = 1
        pos = accessor(positions, 5126, 'VEC3')
        normal = accessor(normals, 5126, 'VEC3')
        indices = accessor(np.arange(count, dtype=index_type),
                           5123 if index_type == '<u2' else 5125, 'SCALAR')
        primitives.append({'attributes': {'POSITION': pos, 'NORMAL': normal},
                           'indices': indices, 'material': 0})
    doc = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(payload)}],
           'bufferViews': views, 'accessors': accessors, 'meshes': [{'primitives': primitives}],
           'materials': [{'pbrMetallicRoughness': {'baseColorFactor': [.25, .5, .75, 1]}}]}
    encoded = json.dumps(doc).encode('utf-8')
    encoded += b' ' * (-len(encoded) % 4)
    payload.extend(b'\0' * (-len(payload) % 4))
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(encoded) + 8 + len(payload))
                     + struct.pack('<II', len(encoded), 0x4e4f534a) + encoded
                     + struct.pack('<II', len(payload), 0x004e4942) + payload)


def emitted_parts(path):
    """Inspect writer bytes independently from its in-memory arrays."""
    data = gzip.decompress(path.read_bytes())
    assert data[:8] == b'RDCITY04'
    flags, size = struct.unpack_from('<II', data, 8)
    assert flags == 0
    metadata = json.loads(data[16:16 + size])
    count, = struct.unpack_from('<I', data, 16 + size)
    offset = 20 + size
    parts = []
    for _ in range(count):
        *bounds, vc, ic = struct.unpack_from('<6fII', data, offset)
        offset += 32
        vertices = np.frombuffer(data, dtype='<f4', count=vc * 10, offset=offset).reshape(vc, 10)
        offset += vc * 40
        indices = np.frombuffer(data, dtype='<u4', count=ic, offset=offset)
        offset += ic * 4
        parts.append((bounds, vertices, indices))
    assert offset == len(data)
    assert len(metadata) == count
    return metadata, parts


class CityExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.out = self.root / 'output'

    def make_city(self, names=('fixture',), primitive_specs=((3, '<u2'),)):
        source_glb(self.source / 'fixture.glb', primitive_specs)
        (self.source / 'manifest.json').write_text(json.dumps({
            'assets': [{'name': name, 'glb': 'fixture.glb'} for name in names]}))
        return build_city.City(self.source)

    def write(self, city, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            city.write(self.out, **kwargs)
        return emitted_parts(self.out / 'meshes.bin')

    def test_source_instance_retains_more_than_65535_vertices_and_u32_indices(self):
        city = self.make_city(primitive_specs=((65538, '<u4'),))
        city.asset('fixture', 3, 2, 7, yaw=90, scale=(2, 1, .5))
        metadata, parts = self.write(city)
        self.assertEqual(len(parts), 1)
        self.assertEqual(metadata, [{'id': 0, 'asset': 'fixture', 'max_distance': 0.}])
        bounds, vertices, indices = parts[0]
        self.assertEqual(len(vertices), 65538)
        np.testing.assert_array_equal(indices, np.arange(65538, dtype='<u4'))
        np.testing.assert_array_equal(vertices, city.parts[0].vertices)
        np.testing.assert_allclose(vertices[-1, :3], [4, 2, -131067], atol=1e-5)
        self.assertEqual(bounds, list(vertices[:, :3].min(axis=0)) + list(vertices[:, :3].max(axis=0)))
        report = validate_city.verify_mesh(self.out / 'meshes.bin')
        self.assertEqual((report['chunks'], report['vertices'], report['triangles']), (1, 65538, 21846))

    def test_u16_source_primitive_indices_are_widened_before_offsets(self):
        city = self.make_city(primitive_specs=((40002, '<u2'), (40002, '<u2')))
        city.asset('fixture', 0, 0, 0)
        _, parts = self.write(city)
        self.assertEqual(len(parts[0][1]), 80004)
        np.testing.assert_array_equal(parts[0][2], np.arange(80004, dtype='<u4'))
        self.assertEqual(validate_city.verify_mesh(self.out / 'meshes.bin')['triangles'], 26668)

    def test_nearby_geometry_stays_in_separate_records_with_exact_vertices(self):
        city = self.make_city()
        city.asset('fixture', 0, 0, 0)
        city.asset('fixture', 1, 0, 0)
        metadata, parts = self.write(city)
        self.assertEqual(len(parts), 2)
        self.assertEqual([row['id'] for row in metadata], [0, 1])
        for expected, (_, vertices, indices) in zip(city.parts, parts):
            np.testing.assert_array_equal(vertices, expected.vertices)
            np.testing.assert_array_equal(indices, expected.indices)
        level = json.loads((self.out / 'level.json').read_text())
        self.assertEqual(level['geometry_format'], 'RDCITY04')
        self.assertEqual(level['statistics']['render_chunks'], 2)
        self.assertEqual(level['statistics']['vertices'], 6)
        self.assertEqual(level['statistics']['triangles'], 2)
        first_bytes = (self.out / 'meshes.bin').read_bytes()
        self.write(city)
        self.assertEqual((self.out / 'meshes.bin').read_bytes(), first_bytes)

    def test_building_ownership_and_only_reviewed_props_have_distance_limits(self):
        names = ('b16_takeaway_coffee_cup', 'b17_seamed_basketball',
                 'b21_wall_solid_4m', 'b16_unknown_future_architecture')
        city = self.make_city(names=names)
        building = Building(city.asset, city.box, city.buildings, 0, 0, 0, False, SPECS[0])
        for name in names:
            building.a(name, 0, 0, 0)
        building.b('floor', 0, 0, 0, 4, .1, 4)
        building.c('collision only', 0, 0, 0, 1, 1, 1)
        city.box('street', (0, 0, 0), (220, .1, 220), (.2, .2, .2), solid=False)
        metadata, parts = self.write(city)
        self.assertEqual(len(parts), 6)
        self.assertEqual([row['id'] for row in metadata], list(range(6)))
        self.assertEqual([row['max_distance'] for row in metadata], [120., 120., 0., 0., 0., 0.])
        self.assertTrue(all(row['building'] == 'B01' for row in metadata[:5]))
        self.assertNotIn('building', metadata[-1])
        self.assertEqual(metadata[4]['asset'], 'B01/floor')
        self.assertFalse(any(row['asset'].startswith('COLLIDER::') for row in metadata))
        layout = json.loads((self.out / 'layout.json').read_text())
        self.assertEqual([row['building'] for row in layout['instances']], ['B01'] * 4)
        validate_city.verify_mesh(self.out / 'meshes.bin')

    def test_sign_lettering_preserves_building_owner(self):
        city = self.make_city()
        city.buildings = [{'id': 'B03', 'signs': [{'text': 'A', 'height': 1, 'width': 2,
                                                 'position': [0, 2, 0], 'yaw': 0}]}]
        build_city.signage(city)
        metadata, parts = self.write(city)
        self.assertTrue(parts)
        self.assertTrue(all(row['building'] == 'B03' and row['asset'] == 'store lettering'
                            and row['max_distance'] == 0 for row in metadata))

    def test_alternate_output_does_not_modify_source_lock_without_opt_in(self):
        city = self.make_city()
        city.asset('fixture', 0, 0, 0)
        project = self.root / 'project'
        (project / 'tools').mkdir(parents=True)
        lock = project / 'tools/city_source_lock.json'
        sentinel = b'original tracked lock\n'
        lock.write_bytes(sentinel)
        with mock.patch.object(build_city, 'ROOT', project):
            self.write(city)
            self.assertEqual(lock.read_bytes(), sentinel)
            self.write(city, write_source_lock=True)
            written = json.loads(lock.read_text())
            self.assertEqual(written['assets'][0]['id'], 'fixture')
            with mock.patch.object(build_city, 'DEFAULT_OUT', self.out):
                lock.write_bytes(sentinel)
                self.write(city, write_source_lock=False)
                self.assertEqual(lock.read_bytes(), sentinel)
                self.write(city)
                self.assertEqual(json.loads(lock.read_text()), written)

    def test_invalid_source_indices_fail_before_emitting_output(self):
        city = self.make_city()
        city.asset('fixture', 0, 0, 0)
        city.parts[0].indices = np.array([0, 1, 65536], dtype='<u4')
        with self.assertRaisesRegex(ValueError, 'invalid city instance geometry'):
            self.write(city)
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
