"""Collision and binary rejection regressions for the city clearance audit."""
import math
import gzip
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

import validate_city as city


def box(low, high):
    return {'min': low, 'max': high}


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


if __name__ == '__main__':
    unittest.main()
