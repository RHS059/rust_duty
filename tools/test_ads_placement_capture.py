import json
from pathlib import Path
import tempfile
import unittest
from verify_ads_placement_capture import verify


class PlacementComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)/'base';self.shifted=Path(self.temp.name)/'shifted'
        self.base.mkdir();self.shifted.mkdir()
        for i in range(530):
            row={'route':'ads.hold' if 100<=i<250 else 'ready','run_weight':0,
                 'speed':1 if 150<=i<200 else 0,'renderer_failed':False}
            for folder in [self.base,self.shifted]:
                (folder/f'{i:04}.png.gameplay.json').write_text(json.dumps(row))
                payload=b'\x89PNG\r\n\x1a\n'+(b'offset' if folder==self.shifted and row['route']=='ready' else b'base')
                (folder/f'{i:04}.png').write_bytes(payload)

    def test_held_images_and_telemetry_match_while_hip_placement_returns(self):
        self.assertEqual(verify(self.base,self.shifted)['identical_moving_ads_frames'],50)

    def test_full_aim_displacement_fails(self):
        (self.shifted/'0100.png').write_bytes(b'\x89PNG\r\n\x1a\nwrong')
        with self.assertRaisesRegex(ValueError,'fully aimed'): verify(self.base,self.shifted)

    def test_ineffective_hip_offset_fails(self):
        (self.shifted/'0529.png').write_bytes((self.base/'0529.png').read_bytes())
        with self.assertRaisesRegex(ValueError,'before and after'): verify(self.base,self.shifted)

    def test_gameplay_change_and_missing_capture_fail(self):
        p=self.shifted/'0200.png.gameplay.json';row=json.loads(p.read_text());row['speed']=2;p.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError,'telemetry'): verify(self.base,self.shifted)
        p.unlink()
        with self.assertRaisesRegex(ValueError,'truncated'): verify(self.base,self.shifted)


class WitnessedPlacementComparisonTests(unittest.TestCase):
    def setUp(self):
        from test_capture_frame_witness import marker, metadata
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = []
        for role, identity in [('baseline','a'*64),('offset','b'*64)]:
            folder=self.root/role;folder.mkdir();path=folder/'0000.png'
            marker(0,identity).save(path)
            Path(str(path)+'.json').write_text(json.dumps(metadata(0,identity)))
            self.paths.append(path)

    def test_only_valid_marker_identity_difference_is_excluded(self):
        from verify_ads_placement_capture import same_capture
        self.assertTrue(same_capture(*self.paths))

    def test_one_pixel_outside_marker_still_changes_visual_comparison(self):
        from PIL import Image
        from verify_ads_placement_capture import same_capture
        with Image.open(self.paths[1]) as original: image=original.copy()
        image.putpixel((64,0),(255,255,255,255));image.save(self.paths[1])
        self.assertFalse(same_capture(*self.paths))

    def test_invalid_marker_or_removed_metadata_cannot_be_masked(self):
        from PIL import Image
        from verify_ads_placement_capture import same_capture
        with Image.open(self.paths[1]) as original: image=original.copy()
        image.putpixel((0,0),(0,0,0,255));image.save(self.paths[1])
        with self.assertRaises(ValueError): same_capture(*self.paths)
        Path(str(self.paths[1])+'.json').write_text('{}')
        with self.assertRaises(ValueError): same_capture(*self.paths)
