import copy
import unittest
from config import validate


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'schema': 'rust-duty-weapon-nla/v1', 'clips': [
            {'id': 'reload', 'scene': 'Reload', 'rig': 'Arms', 'track_name': 'EXPORT::reload',
             'frame_start': 40, 'frame_end': 80, 'fps': 60, 'fps_base': 1.001}]}

    def test_preserves_authored_timing(self):
        original = copy.deepcopy(self.manifest)
        self.assertEqual(validate(self.manifest), original)

    def test_rejects_history_tracks(self):
        self.manifest['clips'][0]['track_name'] = 'ARCHIVE::reload'
        with self.assertRaises(ValueError):
            validate(self.manifest)

    def test_rejects_duplicate_output(self):
        self.manifest['clips'] *= 2
        with self.assertRaises(ValueError):
            validate(self.manifest)

    def test_rejects_path_traversal(self):
        self.manifest['clips'][0]['id'] = '../outside'
        with self.assertRaises(ValueError):
            validate(self.manifest)

    def test_camera_mapping_needs_camera(self):
        self.manifest['clips'][0]['camera_track_name'] = 'EXPORT::camera'
        with self.assertRaises(ValueError):
            validate(self.manifest)

    def test_accepts_integral_float_frames_and_static_poses(self):
        self.manifest['clips'][0].update(frame_start=55.0, frame_end=55.0)
        self.assertEqual(validate(self.manifest)['clips'][0]['frame_end'], 55.0)

    def test_rejects_fractional_bounds(self):
        self.manifest['clips'][0]['frame_start'] = 40.5
        with self.assertRaises(ValueError):
            validate(self.manifest)

    def test_invalid_time(self):
        self.manifest['clips'][0]['fps_base'] = float('nan')
        with self.assertRaises(ValueError):
            validate(self.manifest)


if __name__ == '__main__':
    unittest.main()
