"""Generated-image CLI tests; these do not claim native renderer execution."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw


SCRIPT = Path(__file__).with_name('verify_render_capture.py')
BACKGROUND = (12, 18, 24, 255)


class RenderCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'capture.png'
        self.image = self.fixture()
        self.image.save(self.path)

    @staticmethod
    def fixture(size=(100, 100)):
        image = Image.new('RGBA', size, BACKGROUND)
        draw = ImageDraw.Draw(image)
        # Independent, explicit expected layout; do not import the validator's
        # probes or colors to manufacture the valid control.
        draw.rectangle((10, 10, 39, 39), fill=(255, 0, 0, 255))
        draw.rectangle((60, 10, 89, 39), fill=(0, 255, 0, 255))
        draw.rectangle((10, 60, 39, 89), fill=(0, 0, 255, 255))
        draw.rectangle((60, 60, 89, 89), fill=(255, 255, 0, 255))
        return image

    def run_cli(self, *extra, orientation=True):
        command = [sys.executable, str(SCRIPT), str(self.path), '--width', '100',
                   '--height', '100', '--background', '12,18,24,255',
                   '--min-coverage', '0.1']
        if orientation:
            command += ['--orientation', 'quadrants-v1']
        return subprocess.run(command + list(extra), capture_output=True,
                              text=True, timeout=10)

    def assert_failure(self, expected, *extra, orientation=True):
        result = self.run_cli(*extra, orientation=orientation)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_valid_orientation_cli(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['passed'])
        self.assertEqual(report['foreground_coverage'], 0.36)
        self.assertEqual(len(report['probes']), 4)

    def test_generic_capture_does_not_claim_orientation(self):
        result = self.run_cli(orientation=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout)['orientation'])

    def test_all_nonidentity_square_transforms_fail_orientation(self):
        for transform in Image.Transpose:
            with self.subTest(transform=transform):
                self.image.transpose(transform).save(self.path)
                self.assert_failure('orientation')

    def test_wrong_extent(self):
        self.assert_failure('wrong extent', '--width', '101')

    def test_rectangular_transpose_wrong_extent(self):
        self.image.resize((120, 100)).transpose(Image.Transpose.TRANSPOSE).save(self.path)
        self.assert_failure('wrong extent', '--width', '120')

    def test_uniform_background_and_wrong_clear_color(self):
        for color in (BACKGROUND, (0, 0, 0, 255), (255, 255, 255, 255), (0, 0, 0, 0)):
            with self.subTest(color=color):
                Image.new('RGBA', (100, 100), color).save(self.path)
                self.assert_failure('uniform image', orientation=False)

    def test_invisible_rgb_noise_is_not_foreground(self):
        self.image.putalpha(0)
        self.image.save(self.path)
        self.assert_failure('foreground coverage', orientation=False)

    def test_too_little_foreground(self):
        image = Image.new('RGBA', (100, 100), BACKGROUND)
        image.putpixel((25, 25), (255, 0, 0, 255))
        image.save(self.path)
        self.assert_failure('foreground coverage', orientation=False)

    def test_coverage_failure_identifies_the_exact_capture(self):
        image = Image.new('RGBA', (100, 100), BACKGROUND)
        image.putpixel((25, 25), (255, 0, 0, 255))
        image.save(self.path)
        result = self.run_cli(orientation=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{self.path}: foreground coverage 0.000100 below 0.100000',
                      result.stderr)
        self.assertEqual(result.stdout, '')

    def test_coverage_threshold_is_enforced(self):
        self.assert_failure('foreground coverage', '--min-coverage', '0.37')

    def test_wrong_color_and_missing_patch_fail_orientation(self):
        for color in ((255, 0, 255, 255), BACKGROUND):
            with self.subTest(color=color):
                image = self.image.copy()
                ImageDraw.Draw(image).rectangle((10, 10, 39, 39), fill=color)
                image.save(self.path)
                self.assert_failure('orientation top-left')

    def test_nonopaque_patch_fails_orientation(self):
        self.image.putalpha(200)
        self.image.save(self.path)
        self.assert_failure('orientation top-left')

    def test_tolerance_allows_small_color_changes(self):
        image = self.image.point(lambda channel: max(0, channel - 5))
        image.save(self.path)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_failure('orientation top-left', '--color-tolerance', '0')

    def test_region_coverage_is_enforced(self):
        ImageDraw.Draw(self.image).rectangle((10, 10, 13, 39), fill=BACKGROUND)
        self.image.save(self.path)
        self.assert_failure('orientation top-left')

    def test_missing_and_corrupt_png(self):
        self.path.unlink()
        self.assert_failure('validation failed')
        for payload in (b'', b'not an image', b'\x89PNG\r\n\x1a\n'):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                self.assert_failure('validation failed')

    def test_truncated_png(self):
        payload = self.path.read_bytes()
        self.path.write_bytes(payload[:len(payload) // 2])
        self.assert_failure('validation failed')

    def test_incomplete_iend_crc_cannot_pass_pillow_decode(self):
        payload = self.path.read_bytes()
        for removed in (1, 2, 3, 4, 8, 12):
            with self.subTest(removed=removed):
                self.path.write_bytes(payload[:-removed])
                self.assert_failure('truncated PNG')

    def test_bad_iend_crc_and_trailing_data_fail(self):
        payload = self.path.read_bytes()
        self.path.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
        self.assert_failure('PNG chunk CRC')
        self.path.write_bytes(payload + b'trailing data')
        self.assert_failure('trailing bytes')

    def test_near_uniform_unexpected_background_is_not_scene_coverage(self):
        image = Image.new('RGBA', (100, 100), (180, 160, 140, 255))
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.save(self.path)
        self.assert_failure('near-uniform', orientation=False)

    def test_crc_corruption(self):
        payload = bytearray(self.path.read_bytes())
        position = payload.index(b'IDAT') + 4
        payload[position] ^= 1
        self.path.write_bytes(payload)
        self.assert_failure('validation failed')

    def test_non_png_with_png_extension(self):
        self.image.convert('RGB').save(self.path, format='BMP')
        self.assert_failure('expected PNG format')

    def test_animated_png_rejected(self):
        second = self.image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        self.image.save(self.path, save_all=True, append_images=[second], duration=100)
        self.assert_failure('expected one static PNG frame')

    def test_extent_too_small_for_orientation(self):
        image = Image.new('RGBA', (2, 2), BACKGROUND)
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.save(self.path)
        self.assert_failure('extent too small', '--width', '2', '--height', '2')

    def test_rgb_png_supported(self):
        self.image.convert('RGB').save(self.path)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_malformed_options(self):
        for option, value in [('--width', '0'), ('--height', '-1'),
                              ('--width', '1.5'), ('--background', '1,2,3'),
                              ('--background', '1,2,3,256'), ('--background', 'no'),
                              ('--min-coverage', '0'), ('--min-coverage', '1.1'),
                              ('--min-coverage', 'NaN'), ('--min-coverage', 'inf'),
                              ('--color-tolerance', '-1'), ('--color-tolerance', '33'),
                              ('--orientation', 'undefined')]:
            with self.subTest(option=option, value=value):
                self.assert_failure('error:', option, value)

    def test_required_options_cannot_silently_default(self):
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.path)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('required', result.stderr)


if __name__ == '__main__':
    unittest.main()
