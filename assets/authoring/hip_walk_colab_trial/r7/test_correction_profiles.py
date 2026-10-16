"""Small pure-Python contract tests. Run only after the coordinator releases tests."""
import math
import unittest
from correction_profiles import PROFILES, correction, native_map, solve_total_roll_delta


class CorrectionProfiles(unittest.TestCase):
    def test_native_mapping_and_closure(self):
        for direction, spec in PROFILES.items():
            rows = native_map(direction)
            self.assertEqual(len(rows), spec['period'] + 1)
            self.assertEqual(sum(r['include_in_unique_playback'] for r in rows), spec['period'])
            self.assertEqual(sum(r['closure_witness'] for r in rows), 1)
            self.assertEqual(rows[-1]['source_frame'], spec['reference_start'] + spec['period'])
            self.assertEqual(correction(direction, 1), correction(direction, spec['period'] + 1))

    def test_dense_bounded_and_finite(self):
        for direction, spec in PROFILES.items():
            limits = [spec['bounds'][k] for k in ('x_px','y_px','total_roll_degrees')]
            for i in range(spec['period'] * 32 + 1):
                delta = correction(direction, 1 + i / 32)
                for v, bound in zip(delta, limits):
                    self.assertTrue(math.isfinite(v))
                    self.assertLessEqual(abs(v), bound + 1e-10)

    def test_requested_beat_signs(self):
        for f in (6,10,13,29,31,33):
            self.assertGreater(correction('forward', f)[1], 0)
        for f in (17,21,25):
            self.assertLess(correction('forward', f)[1], 0)
        for f in (12,15,17,35,37,42):
            self.assertGreater(correction('backward', f)[1], 0)
        for f in (21,25,29):
            self.assertLess(correction('backward', f)[1], 0)
        for f in (1,4,7):
            self.assertEqual(correction('backward', f)[2], -6)
        for f in (30,32,34):
            self.assertEqual(correction('backward', f)[2], 6)

    def test_forward_seam_keys_untouched(self):
        for f in PROFILES['forward']['preserved_keys']:
            self.assertEqual(correction('forward', f), (0,0,0))
        self.assertEqual(PROFILES['forward']['allowed'], ['location'])

    def test_corrective_lateral_peak_at_eight(self):
        values = [correction('forward', f)[0] for f in range(1,39)]
        self.assertEqual(values.index(max(values)) + 1, 8)
        # This is the corrective envelope peak, not a claimed rendered peak.

    def test_total_roll_correction_with_existing_pitch_yaw(self):
        for pitch, yaw, roll in [(0,0,0),(12,-8,5),(-7,11,-6),(3,4,7)]:
            p,y,z = map(math.radians, (pitch,yaw,roll))
            cp,sp,cy,sy,cz,sz = math.cos(p),math.sin(p),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
            R = [[cy*cz,-cy*sz,sy],
                 [cp*sz+sp*sy*cz,cp*cz-sp*sy*sz,-sp*cy],
                 [sp*sz-cp*sy*cz,sp*cz+cp*sy*sz,cp*cy]]
            for target in (-6,0,6):
                theta = -math.radians(solve_total_roll_delta(R,target))
                x = math.cos(theta)*R[0][0]-math.sin(theta)*R[1][0]
                yv = math.cos(theta)*R[0][1]-math.sin(theta)*R[1][1]
                self.assertAlmostEqual(math.degrees(math.atan2(yv,x)),target,places=10)


if __name__ == '__main__':
    unittest.main()
