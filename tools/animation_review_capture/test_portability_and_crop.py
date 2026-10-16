"""Asset-free regressions; every source and image fixture is synthetic."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

if __package__:
    from . import capture_common as common
    from . import extract_camera_crop as crop
    from .viewport_pixel_plan import rectangle_matches
else:
    import capture_common as common
    import extract_camera_crop as crop
    from viewport_pixel_plan import rectangle_matches


class Portability(unittest.TestCase):
    def test_missing_private_sources_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(common, 'INPUT_ROOT', Path(folder)):
            with self.assertRaisesRegex(AssertionError, 'Missing pinned source'):
                common.validate_contract(common.TAKES['entry-r4'])

    def test_configured_root_has_precedence(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(common, 'INPUT_ROOT'):
            common.configure_input_root(folder)
            # Windows TemporaryDirectory may use an 8.3 alias (RUNNER~1).
            # The configured root deliberately resolves it to its canonical path.
            self.assertEqual(common.source_path(common.TAKES['entry-r4']), Path(folder).resolve() / 'sources/prone-entry-r4.blend')

    def test_configured_root_normalizes_equivalent_spelling(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(common, 'INPUT_ROOT'):
            root = Path(folder)
            (root / 'child').mkdir()
            common.configure_input_root(root / 'child' / '..')
            self.assertEqual(common.INPUT_ROOT, root.resolve())
            self.assertEqual(common.source_path(common.TAKES['entry-r4']), root.resolve() / 'sources/prone-entry-r4.blend')

    def test_environment_root_and_optimized_python_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, RUST_DUTY_CAPTURE_INPUT_ROOT=folder)
            code = 'import capture_common; print(capture_common.INPUT_ROOT)'
            result = subprocess.run([sys.executable, '-c', code], cwd=common.HERE, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(Path(folder).resolve()))
            result = subprocess.run([sys.executable, '-O', '-c', code], cwd=common.HERE, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('requires Python assertions', result.stderr)

    def test_nonportable_source_paths_rejected(self):
        for path in ['C:/private/source.blend', '', '/private/source.blend', '../source.blend', 'sources/../source.blend', 'C:\\private\\source.blend']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                common.source_path(dict(source=path))

    def test_maps_have_exact_published_counts(self):
        maps = [row for take in common.TAKES.values() for row in common.frame_map(take)]
        self.assertEqual(len(maps), 599)
        self.assertEqual(sum(row['include_in_unique_playback'] for row in maps), 591)
        self.assertEqual(sum(row['closure_witness'] for row in maps), 8)

    def test_helpers_are_unchanged_and_paths_are_portable(self):
        provenance = json.loads((common.HERE / 'provenance.json').read_text())
        for helper in provenance['helpers']:
            self.assertEqual(common.sha(common.HERE / helper['path']), helper['sha256'])
        for path in common.HERE.rglob('*.py'):
            source = path.read_text()
            ast.parse(source)
            self.assertNotIn('/work' + 'space/', source)
            self.assertNotIn('/Us' + 'ers/', source)

    def test_rectangle_missing_coordinates_rejected(self):
        self.assertFalse(rectangle_matches([1, 2, 3, 4], [1]))
        self.assertFalse(rectangle_matches([1], [1, 2, 3, 4]))


class CropReview(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source = self.root / 'synthetic-source.bin'
        source.write_bytes(b'Original unit-test bytes. Not a Blender asset.')
        self.proof_path = self.root / 'proof.json'
        self.out = self.root / 'output'
        self.proof = dict(
            schema='rust-duty-live-eevee-native-pixel-witness/v1',
            source_path=str(source), source_sha256=common.sha(source),
            action='aella_vault_low_r3', action_frame=1,
            integer_camera_border_confirmed_by_projection=True,
            render_operator_used=False, source_saved=False,
            engine='BLENDER_EEVEE_NEXT', viewport_shading='RENDERED',
            same_pose_camera_crop_pixels_equal=True, screenshots=[])
        # A two-color original fixture: no private geometry or screenshot pixels.
        self.pixels = bytes([1, 2, 3, 12, 23, 34]) * (1280 * 720 // 2)
        for index in range(2):
            image = self.root / f'synthetic-{index}.png'
            image.write_bytes(crop.encode_png(1280, 720, 3, self.pixels))
            self.proof['screenshots'].append(dict(path=str(image), sha256=common.sha(image),
                dimensions=[1280, 720, 3], camera_crop_top_left=[0, 0, 1280, 720],
                native_camera_pixels_sha256=hashlib.sha256(self.pixels).hexdigest()))
        self.take = copy.deepcopy(common.TAKES['vault-low-r3'])
        self.take['source_sha256'] = self.proof['source_sha256']
        patch = mock.patch.dict(crop.TAKES, {'vault-low-r3': self.take})
        patch.start()
        self.addCleanup(patch.stop)
        self.write_review()

    def write_review(self):
        self.proof_path.write_text(json.dumps(self.proof))
        self.review = dict(accepted=True, review_note='Synthetic fixture only; this is not artistic approval.',
            proof_sha256=common.sha(self.proof_path), source_sha256=self.proof['source_sha256'],
            action=self.proof['action'], action_frame=1,
            screenshot_sha256=[row['sha256'] for row in self.proof['screenshots']])
        (self.root / 'visual-review.json').write_text(json.dumps(self.review))

    def assert_rejected(self):
        with self.assertRaises(AssertionError):
            crop.extract(self.proof_path, self.out)
        self.assertFalse(self.out.exists())

    def test_exact_crop_round_trip_does_not_claim_corpus(self):
        result = crop.extract(self.proof_path, self.out)
        self.assertFalse(result['native_frame_corpus'])
        self.assertFalse(result['render_opengl_output'])
        self.assertEqual(len(result['records']), 2)
        for record in result['records']:
            self.assertEqual(common.png_pixels(record['output']), ((1280, 720, 3), self.pixels))

    def test_missing_review_rejected(self):
        (self.root / 'visual-review.json').unlink()
        self.assert_rejected()

    def test_existing_rejection_blocks_review(self):
        (self.root / 'visual-rejection.json').write_text('{}')
        self.assert_rejected()

    def test_review_identity_and_meaningful_note_required(self):
        for key, value in [('accepted', False), ('proof_sha256', 'wrong'), ('source_sha256', 'wrong'),
                           ('action', 'wrong'), ('action_frame', 2), ('screenshot_sha256', []),
                           ('review_note', '   '), ('review_note', True)]:
            with self.subTest(key=key, value=value):
                wrong = dict(self.review, **{key: value})
                (self.root / 'visual-review.json').write_text(json.dumps(wrong))
                self.assert_rejected()

    def test_tampered_source_rejected(self):
        Path(self.proof['source_path']).write_bytes(b'Tampered fixture')
        self.assert_rejected()

    def test_wrong_pinned_action_or_frame_rejected(self):
        for key, value in [('action', 'another-action'), ('action_frame', 2)]:
            old = self.proof[key]
            self.proof[key] = value
            self.write_review()
            self.assert_rejected()
            self.proof[key] = old

    def test_stable_black_screenshot_rejected(self):
        for row in self.proof['screenshots']:
            Path(row['path']).write_bytes(crop.encode_png(1280, 720, 3, bytes(1280 * 720 * 3)))
            row['sha256'] = common.sha(row['path'])
            row['native_camera_pixels_sha256'] = hashlib.sha256(bytes(1280 * 720 * 3)).hexdigest()
        self.write_review()
        self.assert_rejected()

    def test_unequal_settled_crops_rejected_despite_claim(self):
        row = self.proof['screenshots'][-1]
        pixels = self.pixels[::-1]
        Path(row['path']).write_bytes(crop.encode_png(1280, 720, 3, pixels))
        row['sha256'] = common.sha(row['path'])
        row['native_camera_pixels_sha256'] = hashlib.sha256(pixels).hexdigest()
        self.write_review()
        self.assert_rejected()


if __name__ == '__main__':
    unittest.main()
