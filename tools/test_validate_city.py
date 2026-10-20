"""Collision and binary rejection regressions for the city clearance audit."""
import math
import gzip
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import validate_city as city


def box(low, high):
    return {'min': low, 'max': high}


def mesh_fixture(version=4, flags=0, metadata=None, metadata_bytes=None, count=1):
    """An original triangle through the real binary parser, with chosen framing."""
    if metadata is None:
        metadata = [{'id': 7, 'asset': 'fixture triangle', 'building': 'B01', 'max_distance': 0.}]
    compact = version == 3 or (version == 4 and flags & 2)
    data = bytearray(f'RDCITY0{version}'.encode('ascii'))
    if version == 4:
        encoded = metadata_bytes if metadata_bytes is not None else json.dumps(metadata).encode('utf-8')
        data.extend(struct.pack('<II', flags, len(encoded)))
        data.extend(encoded)
    data.extend(struct.pack('<I', count))
    for _ in range(count):
        data.extend(struct.pack('<6fII', -1, 0, 0, 1, 1, 0, 3, 3))
        for position in [(-1, 0, 0), (1, 0, 0), (0, 1, 0)]:
            if compact:
                data.extend(struct.pack('<3f4B', *position, 127, 127, 127, 255))
            else:
                data.extend(struct.pack('<10f', *position, 0, 0, 1, .5, .5, .5, 1))
        data.extend(struct.pack('<3I' if version == 4 else '<3H', 0, 1, 2))
    return data


class CityValidationTests(unittest.TestCase):
    def test_stair_route_is_walkable_both_directions_and_headroom_is_required(self):
        colliders = [box([-2, -.2, -2], [2, 0, 4])]
        for i in range(5):
            colliders.append(box([-.8, 0, i * .4], [.8, (i + 1) * .2, 3]))
        route = [[0, 0, -1], [0, 1, 2.5]]
        self.assertAlmostEqual(city.walk_route(route, colliders, 'up')['largest_step'], .2)
        city.walk_route(list(reversed(route)), colliders, 'down')
        colliders.append(box([-.8, 2.1, .8], [.8, 2.3, 2]))
        with self.assertRaisesRegex(ValueError, 'blocked'):
            city.walk_route(route, colliders, 'low ceiling')

    def test_standing_body_rejects_closed_and_too_narrow_door(self):
        route = [[0, 0, -1.2], [0, 0, 1.2]]
        wall = [box([-3, 0, -.1], [-.5, 3, .1]), box([.5, 0, -.1], [3, 3, .1])]
        city.walk_route(route, wall, 'open door')
        with self.assertRaisesRegex(ValueError, 'blocked'):
            city.walk_route(route, wall + [box([-.5, 0, -.1], [.5, 2.2, .1])], 'closed door')
        wall[0]['max'][0] = -.3
        wall[1]['min'][0] = .3
        with self.assertRaisesRegex(ValueError, 'blocked'):
            city.walk_route(route, wall, 'narrow door')

    def test_route_rejects_unwalkable_rise_and_unsupported_upper_floor(self):
        with self.assertRaisesRegex(ValueError, 'blocked'):
            city.walk_route([[0, 0, -1], [0, .6, 2]], [box([-.8, 0, 0], [.8, .6, 3])], 'too tall')
        with self.assertRaisesRegex(ValueError, 'lacks floor support'):
            city.walk_route([[0, 3, -1], [0, 3, 2]], [], 'floating route')

    def test_mesh_rejects_truncation_out_of_bounds_indices_and_nonfinite_data(self):
        vertices = [(-1, 0, 0), (1, 0, 0), (0, 1, 0)]
        data = bytearray(b'RDCITY01' + struct.pack('<I6fII', 1, -1, 0, 0, 1, 1, 0, 3, 3))
        for vertex in vertices:
            data.extend(struct.pack('<10f', *vertex, 0, 0, 1, .5, .5, .5, 1))
        data.extend(struct.pack('<3H', 0, 1, 2))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mesh.bin'
            path.write_bytes(data)
            self.assertEqual(city.verify_mesh(path)['triangles'], 1)
            compressed = gzip.compress(data, mtime=0)
            path.write_bytes(compressed)
            report = city.verify_mesh(path)
            self.assertEqual(report['sha256'], hashlib.sha256(compressed).hexdigest())
            self.assertEqual(report['decoded_bytes'], len(data))
            path.write_bytes(compressed[:-4])
            with self.assertRaisesRegex(ValueError, 'invalid compressed'):
                city.verify_mesh(path)
            altered = data.copy()
            struct.pack_into('<H', altered, len(altered) - 2, 3)
            path.write_bytes(altered)
            with self.assertRaisesRegex(ValueError, 'out of range index'):
                city.verify_mesh(path)
            altered = data.copy()
            struct.pack_into('<f', altered, 44, math.nan)
            path.write_bytes(altered)
            with self.assertRaisesRegex(ValueError, 'nonfinite vertex'):
                city.verify_mesh(path)
            path.write_bytes(data[:-2])
            with self.assertRaisesRegex(ValueError, 'truncated'):
                city.verify_mesh(path)

    def verify_bytes(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mesh.bin'
            path.write_bytes(data)
            return city.verify_mesh(path)

    def test_all_supported_mesh_encodings_and_gzip_are_accepted(self):
        for version, flags in ((1, 0), (2, 0), (3, 0), (4, 0), (4, 1), (4, 3)):
            with self.subTest(version=version, flags=flags):
                data = mesh_fixture(version=version, flags=flags)
                for encoded in (data, gzip.compress(data, mtime=0)):
                    report = self.verify_bytes(encoded)
                    self.assertEqual((report['chunks'], report['vertices'], report['triangles']), (1, 3, 1))
                    self.assertEqual(report['format'], f'RDCITY0{version}')
                    self.assertEqual(report['compact'], version == 3 or bool(flags & 2))
                    self.assertEqual(report['prelit'], version in (2, 3) or bool(flags & 1))

    def test_metadata_allows_bake_split_identity_and_optional_distance(self):
        metadata = [{'id': 12, 'asset': 'original wall'}] * 2
        self.assertEqual(self.verify_bytes(mesh_fixture(metadata=metadata, count=2))['chunks'], 2)

    def test_metadata_accepts_lighting_writer_null_records_and_optional_fields(self):
        metadata = [
            {'id': 12, 'asset': 'street', 'building': None, 'max_distance': 0.},
            {'id': 13, 'asset': 'wall', 'building': 'B01', 'max_distance': None},
            None,
        ]
        for flags in (0, 1, 3):
            with self.subTest(flags=flags):
                encoded = mesh_fixture(metadata=metadata, count=3, flags=flags)
                for data in (encoded, gzip.compress(encoded, mtime=0)):
                    self.assertEqual(self.verify_bytes(data)['chunks'], 3)

    def test_metadata_string_limits_count_utf8_bytes_and_distance_includes_far_plane(self):
        metadata = [{'id': 7, 'asset': '\u00e9' * 256, 'building': '\u00e9' * 64,
                     'max_distance': 400.}]
        self.assertEqual(self.verify_bytes(mesh_fixture(metadata=metadata))['chunks'], 1)
        # Runtime identity validation requires nonempty strings, without trimming.
        self.assertEqual(self.verify_bytes(mesh_fixture(metadata=[
            {'id': 7, 'asset': ' ', 'building': ' '},
        ]))['chunks'], 1)

    def test_metadata_rejects_malformed_identity_ownership_distance_and_framing(self):
        valid = {'id': 7, 'asset': 'fixture', 'building': 'B01', 'max_distance': 0.}
        self.verify_bytes(mesh_fixture(metadata=[valid]))
        invalid_rows = [
            ('invalid source instance id', {**valid, 'id': -1}),
            ('invalid source instance id', {**valid, 'id': 2**32}),
            ('invalid source instance id', {**valid, 'id': True}),
            ('missing asset identity', {**valid, 'asset': ''}),
            ('missing asset identity', {**valid, 'asset': 1}),
            ('missing asset identity', {**valid, 'asset': 'x' * 513}),
            ('missing asset identity', {**valid, 'asset': '\u00e9' * 257}),
            ('invalid building identity', {**valid, 'building': ''}),
            ('invalid building identity', {**valid, 'building': 1}),
            ('invalid building identity', {**valid, 'building': 'x' * 129}),
            ('invalid building identity', {**valid, 'building': '\u00e9' * 65}),
            ('invalid maximum draw distance', {**valid, 'max_distance': -1}),
            ('invalid maximum draw distance', {**valid, 'max_distance': 401}),
            ('invalid maximum draw distance', {**valid, 'max_distance': True}),
            ('invalid maximum draw distance', {**valid, 'max_distance': '120'}),
            ('invalid maximum draw distance', {**valid, 'max_distance': 1e40}),
            ('invalid maximum draw distance', {**valid, 'max_distance': 10**400}),
            ('invalid city instance metadata', {**valid, 'max_distance': math.nan}),
            ('invalid city instance metadata', {**valid, 'max_distance': math.inf}),
            ('metadata must be an object', 'fixture'),
        ]
        for expected, row in invalid_rows:
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, expected):
                self.verify_bytes(mesh_fixture(metadata=[row]))
        for metadata in ([], {}, None, 'identity'):
            encoded = json.dumps(metadata).encode('utf-8')
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, 'metadata array'):
                self.verify_bytes(mesh_fixture(metadata_bytes=encoded))
        for encoded in (b'[{"id":1,"id":2,"asset":"x"}]', b'[{', b'\xff'):
            with self.subTest(encoded=encoded), self.assertRaisesRegex(ValueError, 'invalid city instance metadata'):
                self.verify_bytes(mesh_fixture(metadata_bytes=encoded))
        with self.assertRaisesRegex(ValueError, 'metadata/geometry count mismatch'):
            self.verify_bytes(mesh_fixture(metadata=[valid, valid]))
        for flags in (2, 4, 0xffffffff):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, 'invalid city instance flags'):
                self.verify_bytes(mesh_fixture(flags=flags))
        for size in (0, city.MAX_METADATA_BYTES + 1):
            data = mesh_fixture()
            struct.pack_into('<I', data, 12, size)
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, 'metadata size'):
                self.verify_bytes(data)

    def test_instanced_mesh_rejects_geometry_corruption_without_losing_valid_control(self):
        data = mesh_fixture()
        self.verify_bytes(data)
        metadata_size, = struct.unpack_from('<I', data, 12)
        header = 20 + metadata_size
        cases = [
            (header, '<f', math.inf, 'nonfinite mesh bounds'),
            (header, '<f', 2., 'inverted mesh bounds'),
            (header + 24, '<I', city.MAX_INSTANCE_VERTICES + 1, 'invalid vertex/index count'),
            (header + 28, '<I', city.MAX_INSTANCE_INDICES + 3, 'invalid vertex/index count'),
            (header + 32, '<f', math.nan, 'nonfinite vertex'),
            (header + 32, '<f', -2., 'vertex outside bounds'),
            (header + 32 + 20, '<f', 0., 'non-unit normal'),
            (header + 32 + 24, '<f', 1.5, 'color outside range'),
            (len(data) - 4, '<I', 65536, 'out of range index'),
        ]
        for offset, fmt, value, expected in cases:
            altered = data.copy()
            struct.pack_into(fmt, altered, offset, value)
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                self.verify_bytes(altered)
        for truncated in (data[:14], data[:header - 2], data[:header + 10], data[:-1]):
            with self.subTest(size=len(truncated)), self.assertRaisesRegex(ValueError, 'truncated'):
                self.verify_bytes(truncated)
        with self.assertRaisesRegex(ValueError, 'trailing mesh data'):
            self.verify_bytes(data + b'\0')


if __name__ == '__main__':
    unittest.main()
