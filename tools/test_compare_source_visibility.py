import unittest
from PIL import Image
from compare_source_visibility import BACKGROUND, EXTENT, compare, decode_runs


def frame(runs):
    count = sum(length for _, length in runs)
    return dict(required_contrast_runs=runs, required_contrast_samples=count,
                possible_support_runs=runs, possible_samples=count,
                unsupported_clip_triangles=0, possible_support_complete=True, unclassified_triangles=int(bool(runs)))


def image_for(row):
    image = Image.new('RGBA', EXTENT, BACKGROUND)
    image.paste((120, 100, 80, 255), mask=decode_runs(row['required_contrast_runs'], row['required_contrast_samples']))
    return image


class SourceVisibilityTests(unittest.TestCase):
    def setUp(self):
        # Two separated source-owned batches, each with a narrow visible patch.
        self.row = frame([[100 * 960 + 100, 4], [200 * 960 + 200, 8]])
        self.image = image_for(self.row)

    def test_valid_control_is_conditional_and_has_no_acceptance_verdict(self):
        result = compare(self.image, self.row)
        self.assertTrue(result['source_obligations_match'])
        self.assertIsNone(result['acceptance_verdict'])
        self.assertFalse(result['native_profile_binding_verified'])

    def test_missing_all_geometry(self):
        with self.assertRaisesRegex(ValueError, 'missing source-derived'):
            compare(Image.new('RGBA', EXTENT, BACKGROUND), self.row)

    def test_missing_entire_visible_batch(self):
        self.image.paste(BACKGROUND, (200, 200, 208, 201))
        with self.assertRaisesRegex(ValueError, 'missing source-derived'):
            compare(self.image, self.row)

    def test_single_source_pixel_patch_missing(self):
        self.image.putpixel((102, 100), BACKGROUND)
        with self.assertRaisesRegex(ValueError, 'missing source-derived'):
            compare(self.image, self.row)

    def test_unrelated_patch_cannot_replace_geometry(self):
        self.image.paste((255, 0, 0, 255), (400, 300, 420, 320))
        with self.assertRaisesRegex(ValueError, 'outside possible'):
            compare(self.image, self.row)

    def test_expected_empty_still_rejects_an_unrelated_patch(self):
        empty = frame([])
        image = image_for(empty)
        self.assertTrue(compare(image, empty)['source_obligations_match'])
        image.putpixel((300, 300), (255, 0, 0, 255))
        with self.assertRaisesRegex(ValueError, 'outside possible'):
            compare(image, empty)

    def test_witness_does_not_supply_source_visibility(self):
        image = Image.new('RGBA', EXTENT, BACKGROUND)
        image.paste((255, 0, 0, 255), (0, 0, 64, 22))
        with self.assertRaisesRegex(ValueError, 'missing source-derived'):
            compare(image, self.row)

    def test_ambiguous_clipping_or_positive_support_fails_closed(self):
        self.row['unsupported_clip_triangles'] = 1
        with self.assertRaisesRegex(ValueError, 'clipping remains'):
            compare(self.image, self.row)
        ambiguous = frame([])
        ambiguous['unclassified_triangles'] = 1
        with self.assertRaisesRegex(ValueError, 'visibility remains'):
            compare(image_for(ambiguous), ambiguous)

    def test_mutated_source_runs_and_missing_alpha_are_rejected(self):
        self.row['required_contrast_samples'] += 1
        with self.assertRaisesRegex(ValueError, 'count differs'):
            compare(self.image, self.row)
        self.row['required_contrast_samples'] -= 1
        self.image.putpixel((300, 300), (36, 48, 61, 0))
        with self.assertRaisesRegex(ValueError, 'opacity differs'):
            compare(self.image, self.row)


if __name__ == '__main__':
    unittest.main()
