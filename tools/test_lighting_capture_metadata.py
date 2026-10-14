"""Source-free direction checks keep the native lighting oracle independently pinned."""
import math
from pathlib import Path
import re
import unittest

import verify_lighting_capture as lighting


def normalized(vector):
    length = math.sqrt(sum(value * value for value in vector))
    return [value / length for value in vector]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def metadata(yaw, pitch, direction=(-0.45, 0.78, 0.43)):
    """Use cross products as an independent reference for the closed-form oracle."""
    y, p = math.radians(yaw), math.radians(pitch)
    forward = normalized([math.cos(y) * math.cos(p), math.sin(p),
                          math.sin(y) * math.cos(p)])
    right = normalized(cross(forward, [0, 1, 0]))
    up = cross(right, forward)
    world = normalized(direction)
    return {
        'yaw_degrees': yaw,
        'pitch_degrees': pitch,
        'simulation_time': 0,
        'world_light': world,
        'view_light': [sum(a * b for a, b in zip(axis, world))
                       for axis in [right, up, [-value for value in forward]]],
    }


class LightingMetadataTests(unittest.TestCase):
    def test_explicit_pin_matches_runtime_range_light(self):
        source = (Path(__file__).resolve().parents[1] / 'src' / 'scene_lighting.rs').read_text()
        range_body = source.split('pub fn range() -> Self {', 1)[1].split('pub fn at(', 1)[0]
        match = re.search(r'direction_to_light:\s*vec3\(([^)]+)\)\.normalize\(\)', range_body)
        self.assertIsNotNone(match)
        self.assertEqual(tuple(float(value.strip()) for value in match.group(1).split(',')),
                         lighting.WORLD_LIGHT_DIRECTION)
        self.assertEqual(lighting.WORLD_LIGHT_DIRECTION, (-0.45, 0.78, 0.43))

    def test_all_six_requested_directions_match_independent_camera_basis(self):
        for name, yaw, pitch in lighting.VIEWS:
            with self.subTest(view=name):
                lighting.verify_direction(metadata(yaw, pitch), yaw, pitch)

    def test_historical_world_light_is_rejected_even_with_consistent_sidecars(self):
        for name, yaw, pitch in lighting.VIEWS:
            with self.subTest(view=name):
                with self.assertRaisesRegex(ValueError, 'view light does not match'):
                    lighting.verify_direction(metadata(yaw, pitch, (-0.3, 0.8, 0.5)), yaw, pitch)

    def test_view_direction_error_is_rejected(self):
        data = metadata(-90, 35)
        data['view_light'][0] += 0.01
        with self.assertRaisesRegex(ValueError, 'view light does not match'):
            lighting.verify_direction(data, -90, 35)

    def test_rotating_world_light_is_rejected(self):
        data = metadata(0, 0)
        data['world_light'] = data['view_light'][:]
        with self.assertRaisesRegex(ValueError, 'level light rotated'):
            lighting.verify_direction(data, 0, 0)

    def test_wrong_requested_yaw_or_pitch_is_rejected(self):
        for field in ['yaw_degrees', 'pitch_degrees']:
            with self.subTest(field=field):
                data = metadata(-90, 35)
                data[field] += 0.01
                with self.assertRaisesRegex(ValueError, 'requested camera direction'):
                    lighting.verify_direction(data, -90, 35)

    def test_animation_time_must_stay_frozen(self):
        data = metadata(-90, 0)
        data['simulation_time'] = 0.001
        with self.assertRaisesRegex(ValueError, 'changed animation time'):
            lighting.verify_direction(data, -90, 0)

    def test_existing_one_e_minus_five_tolerance_is_preserved(self):
        for field, message in [('view_light', 'view light does not match'),
                               ('world_light', 'level light rotated')]:
            for axis in range(3):
                with self.subTest(field=field, axis=axis):
                    data = metadata(-90, 0)
                    data[field][axis] += 0.5e-5
                    lighting.verify_direction(data, -90, 0)
                    data[field][axis] += 1e-5
                    with self.assertRaisesRegex(ValueError, message):
                        lighting.verify_direction(data, -90, 0)


if __name__ == '__main__':
    unittest.main()
