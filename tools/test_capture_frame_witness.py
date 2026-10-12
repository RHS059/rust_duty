"""Independent synthetic marker fixtures; these tests are not native GPU proof."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from PIL import Image, ImageDraw

import verify_capture_frame_witness as witness


CONTEXT = {'source_commit': '0123456789abcdef0123456789abcdef01234567',
           'exe_sha256': '0123456789abcdef' * 4, 'run_id': '37382827411', 'run_attempt': '1',
           'scenario': 'reload-return', 'backend': 'Dx12'}
IDENTITY = '1b5b72fa7ebdffa879bfe48f1e7637341e0da03b0fc15f4023392ea9922e7cf7'
SCHEMA = 'rust-duty-capture-frame-witness/v1'


def marker(index=0, identity=IDENTITY):
    # Encode from the wire specification, without calling decoder helpers or
    # using its layout constants. Non-marker scene pixels stay unrelated.
    image = Image.new('RGBA', (96, 48), (13, 17, 19, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 31, 1), fill=(255, 0, 0, 255))
    draw.rectangle((32, 0, 63, 1), fill=(0, 0, 255, 255))
    data = struct.pack('<II', index, index ^ 0xffffffff) + bytes.fromhex(identity)
    for byte_number, byte in enumerate(data):
        for offset in range(8):
            bit_number = byte_number * 8 + offset
            x = bit_number % 32 * 2
            y = 2 + bit_number // 32 * 2
            value = 255 if byte & (1 << offset) else 0
            draw.rectangle((x, y, x + 1, y + 1), fill=(value, value, value, 255))
    return image


def metadata(index=0, identity=IDENTITY):
    return {'backend': 'Dx12', 'width': 96, 'height': 48,
            'frame_witness': {'schema': SCHEMA, 'frame_index': index, 'capture_identity': identity}}


def flip_cell(image, bit):
    x, y = bit % 32 * 2, 2 + bit // 32 * 2
    value = 255 - image.getpixel((x, y))[0]
    ImageDraw.Draw(image).rectangle((x, y, x + 1, y + 1), fill=(value, value, value, 255))


class ContextIdentityTests(unittest.TestCase):
    def test_canonical_cross_language_vector_and_key_order(self):
        canonical = ('{"backend":"Dx12","exe_sha256":"' + '0123456789abcdef' * 4 + '",'
                     '"run_attempt":"1","run_id":"37382827411","scenario":"reload-return",'
                     '"source_commit":"0123456789abcdef0123456789abcdef01234567"}').encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), IDENTITY)
        self.assertEqual(witness.capture_identity(CONTEXT), IDENTITY)
        self.assertEqual(witness.capture_identity(dict(reversed(list(CONTEXT.items())))), IDENTITY)

    def test_every_verified_context_field_changes_identity(self):
        for key, value in {'source_commit': 'a' * 40, 'exe_sha256': 'b' * 64,
                           'run_id': '37382827412', 'run_attempt': '2', 'scenario': 'ads-gameplay',
                           'backend': 'OpenGl'}.items():
            with self.subTest(key=key):
                self.assertNotEqual(witness.capture_identity({**CONTEXT, key: value}), IDENTITY)

    def test_context_types_hashes_bounds_and_exact_fields(self):
        invalid = [None, [], {**CONTEXT, 'extra': 'value'}, {k: v for k, v in CONTEXT.items() if k != 'backend'}]
        for key in CONTEXT:
            invalid += [{**CONTEXT, key: value} for value in (None, True, 1, 1.0, [], {})]
        for key, values in {
            'source_commit': ('A' * 40, 'a' * 39, 'g' * 40),
            'exe_sha256': ('A' * 64, 'a' * 63, 'g' * 64),
            'run_id': ('0', '01', '-1', '1.0', str(2**64), '9' * 1000),
            'run_attempt': ('0', '01', '-1', '1.0', str(2**64)),
            'scenario': ('', ' padded', 'trailing ', 'line\nbreak', 'a' * 129, '\ud800'),
            'backend': ('', 'dx12', 'gl', 'Vulkan', 'Dx12\n'),
        }.items():
            invalid += [{**CONTEXT, key: value} for value in values]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(witness.WitnessError):
                witness.capture_identity(value)

    def test_context_is_not_mutated_and_unicode_is_utf8(self):
        context = {**CONTEXT, 'scenario': 'capture-é'}
        before = copy.deepcopy(context)
        expected = hashlib.sha256(json.dumps(context, sort_keys=True, separators=(',', ':'),
                                             ensure_ascii=False).encode('utf-8')).hexdigest()
        self.assertEqual(witness.capture_identity(context), expected)
        self.assertEqual(context, before)


class PixelWitnessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'frame.png'

    def save(self, image):
        image.save(self.path)

    def test_decode_little_endian_index_complement_and_identity(self):
        for index in (0, 1, 0x12345678, 0x80000000, 0xffffffff):
            for identity in (IDENTITY, '00' * 32, 'ff' * 32, bytes(range(32)).hex()):
                with self.subTest(index=index, identity=identity):
                    self.save(marker(index, identity))
                    expected = {'schema': SCHEMA, 'frame_index': index, 'capture_identity': identity}
                    self.assertEqual(witness.decode(self.path), expected)
                    self.assertEqual(witness.verify(self.path, metadata(index, identity), index, identity),
                                     {'passed': True, **expected})

    def test_exact_minimum_marker_extent_and_unrelated_scene_pixels(self):
        image = marker(9)
        self.save(image.crop((0, 0, 64, 22)))
        self.assertTrue(witness.verify(self.path, metadata(9), 9, IDENTITY)['passed'])
        image.putpixel((95, 47), (255, 37, 151, 255))
        self.save(image)
        self.assertTrue(witness.verify(self.path, metadata(9), 9, IDENTITY)['passed'])

    def test_stale_and_swapped_pixels_fail_even_after_metadata_rewrite(self):
        for stored, expected in ((0, 1), (11, 12), (12, 11)):
            with self.subTest(stored=stored, expected=expected):
                self.save(marker(stored))
                with self.assertRaisesRegex(witness.WitnessError, 'PNG frame index'):
                    witness.verify(self.path, metadata(expected), expected, IDENTITY)

    def test_same_index_other_capture_and_run_cannot_pass(self):
        for key, value in (('scenario', 'ads-gameplay'), ('run_id', '37382827412'), ('run_attempt', '2')):
            other = witness.capture_identity({**CONTEXT, key: value})
            self.save(marker(8, other))
            with self.subTest(key=key), self.assertRaisesRegex(witness.WitnessError, 'PNG capture identity'):
                witness.verify(self.path, metadata(8), 8, IDENTITY)
            with self.assertRaisesRegex(witness.WitnessError, 'metadata capture identity'):
                witness.verify(self.path, metadata(8, other), 8, IDENTITY)

    def test_wrong_independent_context_and_metadata_cannot_override_expectation(self):
        self.save(marker(3))
        for key, value in (('source_commit', 'a' * 40), ('exe_sha256', 'b' * 64), ('backend', 'OpenGl')):
            wrong = witness.capture_identity({**CONTEXT, key: value})
            with self.subTest(key=key), self.assertRaises(witness.WitnessError):
                witness.verify(self.path, metadata(3), 3, wrong)
        with self.assertRaisesRegex(witness.WitnessError, 'metadata frame index'):
            witness.verify(self.path, metadata(4), 3, IDENTITY)

    def test_expected_and_recorded_index_types_are_exact_u32(self):
        self.save(marker())
        for index in (True, False, 0.0, 1.0, '0', None, -1, 2**32):
            with self.subTest(index=index):
                with self.assertRaisesRegex(witness.WitnessError, 'u32'):
                    witness.verify(self.path, metadata(), index, IDENTITY)
                with self.assertRaisesRegex(witness.WitnessError, 'u32'):
                    witness.verify(self.path, metadata(index), 0, IDENTITY)

    def test_identity_types_lowercase_and_length_are_strict(self):
        self.save(marker())
        for identity in (None, True, 0, 1.0, IDENTITY.upper(), 'a' * 63, 'g' * 64, ''):
            with self.subTest(identity=identity):
                with self.assertRaises(witness.WitnessError):
                    witness.verify(self.path, metadata(), 0, identity)
                with self.assertRaises(witness.WitnessError):
                    witness.verify(self.path, metadata(identity=identity), 0, IDENTITY)

    def test_metadata_requires_exact_witness_schema(self):
        self.save(marker())
        records = [None, [], {}, {'frame_witness': None}, {'frame_witness': []},
                   {'frame_witness': {**metadata()['frame_witness'], 'extra': 1}},
                   {'frame_witness': {**metadata()['frame_witness'], 'schema': 'v0'}}]
        records += [{'frame_witness': {k: v for k, v in metadata()['frame_witness'].items() if k != field}}
                    for field in ('schema', 'frame_index', 'capture_identity')]
        for record in records:
            with self.subTest(record=record), self.assertRaises(witness.WitnessError):
                witness.verify(self.path, record, 0, IDENTITY)

    def test_missing_blank_half_marker_and_too_small_images_fail(self):
        with self.assertRaises(witness.WitnessError):
            witness.verify(self.path, metadata(), 0, IDENTITY)
        partial = marker()
        ImageDraw.Draw(partial).rectangle((0, 12, 63, 21), fill=(0, 0, 0, 255))
        for image in (Image.new('RGBA', (96, 48), (0, 0, 0, 255)), partial,
                      marker().crop((0, 0, 63, 22)), marker().crop((0, 0, 64, 21))):
            self.save(image)
            with self.subTest(size=image.size), self.assertRaises(witness.WitnessError):
                witness.verify(self.path, metadata(), 0, IDENTITY)

    def test_every_header_pixel_is_required_with_rgb_tolerance_eight(self):
        good = marker()
        for y in range(2):
            for x in range(64):
                good.putpixel((x, y), (247, 8, 8, 255) if x < 32 else (8, 8, 247, 255))
        self.save(good)
        self.assertTrue(witness.verify(self.path, metadata(), 0, IDENTITY)['passed'])
        for location in ((0, 0), (31, 1), (32, 0), (63, 1)):
            bad = good.copy()
            bad.putpixel(location, (128, 128, 128, 255))
            self.save(bad)
            with self.subTest(location=location), self.assertRaisesRegex(witness.WitnessError, 'header pixel'):
                witness.decode(self.path)

    def test_all_four_cell_pixels_must_agree_not_majority_or_average(self):
        for location, pixel in (((0, 2), (9, 0, 0, 255)), ((1, 2), (128, 128, 128, 255)),
                                ((0, 3), (255, 255, 255, 255)), ((1, 3), (255, 255, 255, 255))):
            image = marker()  # index bit zero is black
            image.putpixel(location, pixel)
            self.save(image)
            with self.subTest(location=location), self.assertRaisesRegex(witness.WitnessError, 'cell 0'):
                witness.decode(self.path)
        image = marker()
        for y in range(2, 22):
            for x in range(64):
                value = 247 if image.getpixel((x, y))[0] else 8
                image.putpixel((x, y), (value, value, value, 255))
        self.save(image)
        self.assertTrue(witness.verify(self.path, metadata(), 0, IDENTITY)['passed'])

    def test_index_complement_and_identity_bit_flips_reject(self):
        for bit in (0, 31, 32, 63):
            image = marker(7)
            flip_cell(image, bit)
            self.save(image)
            with self.subTest(bit=bit), self.assertRaisesRegex(witness.WitnessError, 'complement'):
                witness.decode(self.path)
        for bit in (64, 127, 319):
            image = marker(7)
            flip_cell(image, bit)
            self.save(image)
            with self.subTest(bit=bit), self.assertRaisesRegex(witness.WitnessError, 'PNG capture identity'):
                witness.verify(self.path, metadata(7), 7, IDENTITY)
        image = marker(7)
        flip_cell(image, 0)
        flip_cell(image, 32)
        self.save(image)  # internally valid changed index still cannot override the caller
        with self.assertRaisesRegex(witness.WitnessError, 'PNG frame index'):
            witness.verify(self.path, metadata(7), 7, IDENTITY)

    def test_rgba8_and_exact_opaque_alpha_are_required(self):
        self.save(marker().convert('RGB'))
        with self.assertRaisesRegex(witness.WitnessError, 'RGBA8'):
            witness.decode(self.path)
        for location in ((0, 0), (1, 3), (95, 47)):
            image = marker()
            image.putpixel(location, (*image.getpixel(location)[:3], 254))
            self.save(image)
            with self.subTest(location=location), self.assertRaisesRegex(witness.WitnessError, 'alpha'):
                witness.decode(self.path)
        image = marker()
        w, h = image.size
        pixels = list(image.getdata())
        raw = b''.join(b'\x00' + b''.join(struct.pack('>4H', *(n * 257 for n in p))
                                        for p in pixels[y*w:(y+1)*w]) for y in range(h))
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        self.path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 16, 6, 0, 0, 0))
                              + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
        with self.assertRaisesRegex(witness.WitnessError, 'RGBA8'):
            witness.decode(self.path)

    def test_png_integrity_static_frame_and_orientation_fail_closed(self):
        self.save(marker())
        original = self.path.read_bytes()
        for data in (original[:-1], original + b'extra'):
            self.path.write_bytes(data)
            with self.assertRaises(witness.WitnessError):
                witness.decode(self.path)
        for operation in (Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.FLIP_TOP_BOTTOM,
                          Image.Transpose.ROTATE_180):
            self.save(marker().transpose(operation))
            with self.assertRaises(witness.WitnessError):
                witness.decode(self.path)
        self.save(marker().resize((192, 96), Image.Resampling.NEAREST))
        with self.assertRaises(witness.WitnessError):
            witness.decode(self.path)
        first, second = marker(), marker(1)
        first.save(self.path, save_all=True, append_images=[second], duration=100, loop=0)
        with self.assertRaises(witness.WitnessError):
            witness.decode(self.path)

    def test_reads_do_not_change_pixels_metadata_or_link_targets(self):
        self.save(marker())
        original, record = self.path.read_bytes(), metadata()
        before = copy.deepcopy(record)
        witness.verify(self.path, record, 0, IDENTITY)
        self.assertEqual(record, before)
        self.assertEqual(self.path.read_bytes(), original)
        target = self.root / 'elsewhere.png'
        self.path.rename(target)
        try:
            self.path.symlink_to(target)
        except OSError as error:
            self.skipTest(f'host cannot create symlinks: {error}')
        with self.assertRaises(witness.WitnessError):
            witness.verify(self.path, record, 0, IDENTITY)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
