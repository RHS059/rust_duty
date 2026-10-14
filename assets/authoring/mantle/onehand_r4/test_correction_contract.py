import copy
import unittest

from correction_contract import (evaluation_times, interpolate, protected,
                                 smooth5, source_frame, validate_report, weapon_protected)


class CorrectionContract(unittest.TestCase):
    def report(self):
        return {'input_sha256': 'f289c6d404a6c9c276baac3089887f77a15ac2d18029e1aa39f66d6e335081df',
                'source_window':[7787,7883], 'fps':[60,1], 'frames':96,
                'prior_actions_preserved':True,'structure_preserved':True,
                'protected_pose_max_delta':0.,'all_skin_finite':True,
                'all_bones_finite':True,'max_right_guard_delta_deg':0.,
                'protected_weapon_max_delta':0.,
                'all_drivers_valid':True,'samples':1533,
                'support_follow_at_65':1.,'max_wrist_target_mm':.001,
                'max_attached_guard_delta_deg':0.,'min_free_guard_margin_deg':6.,
                'max_switch_position_mm':.001,'max_switch_rotation_deg':.001}

    def test_native_map(self):
        self.assertEqual([source_frame(1),source_frame(96)],[7787,7882])
        self.assertEqual(source_frame(44.25),7830.25)
        for value in [0,97]:
            with self.assertRaises(ValueError):source_frame(value)

    def test_original_holds_are_protected(self):
        for value in [1,4.25,8,89,90.5,96]:self.assertTrue(protected(value))
        for value in [8.01,44,65,84.99,85,88.99]:self.assertFalse(protected(value))
        self.assertTrue(weapon_protected(85))

    def test_bounded_transition(self):
        values = [smooth5(i/100) for i in range(-10,111)]
        self.assertEqual(values,sorted(values))
        self.assertEqual((values[0],values[-1]),(0,1))
        keys = [[8,0,3],[20,-.3,4],[85,0,3]]
        for f in range(1,97):
            x,y=interpolate(keys,f)
            self.assertTrue(-.3<=x<=0)
            self.assertTrue(3<=y<=4)

    def test_dense_switch_neighborhoods(self):
        times=evaluation_times()
        self.assertEqual(times,sorted(set(times)))
        self.assertGreaterEqual(len(times),1533)
        for t in [44-.0001,44+.0001,65-.0001,65+.0001]:self.assertIn(t,times)

    def test_numerical_fixture(self):
        self.assertEqual(validate_report(self.report()),[])

    def test_known_r3_late_reattach_is_rejected(self):
        report=self.report();report['support_follow_at_65']=0
        self.assertIn('support_reattached',validate_report(report))

    def test_protected_pose_drift_is_rejected(self):
        report=self.report();report['protected_pose_max_delta']=2e-6
        self.assertIn('protected_pose',validate_report(report))

    def test_incomplete_reports_fail_closed(self):
        self.assertGreater(len(validate_report({})),10)
        report=self.report();report['frames']=95
        self.assertIn('native_mapping',validate_report(report))

    def test_reject_guard_clipping_and_source_mismatch(self):
        report=self.report();report['max_attached_guard_delta_deg']=.596
        report['input_sha256']='0'*64
        self.assertIn('guard_not_clipped',validate_report(report))
        self.assertIn('source_identity',validate_report(report))

if __name__=='__main__':unittest.main()
