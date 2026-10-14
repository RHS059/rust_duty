import unittest,json,copy,math
from pathlib import Path
from motion_design import parameters,validate_config,envelope
from report_contract import validate
P=Path(__file__).parent
class DesignTests(unittest.TestCase):
 def setUp(self):self.c=json.loads((P/'correction_design.json').read_text())
 def test_valid_design(self):self.assertTrue(validate_config(self.c))
 def test_no_retiming(self):self.assertEqual(self.c['frames'],[1,69]);self.assertEqual(self.c['reference_source_range_half_open'],[2241,2310])
 def test_early_protection(self):
  for i in range(81):self.assertTrue(all(x==0 for x in parameters(self.c,1+i/8).values()))
 def test_depth_is_held(self):
  for i in range(81):self.assertEqual(parameters(self.c,35+i/8)['camera_depth_m'],1.3)
 def test_roll_clears_by_45(self):
  for i in range(193):
   p=parameters(self.c,45+i/8);self.assertEqual(p['camera_roll_deg'],0);self.assertEqual(p['weapon_additional_roll_deg'],0)
 def test_late_motion_does_not_float_high(self):
  for i in range(193):
   p=parameters(self.c,45+i/8);self.assertGreaterEqual(p['camera_depth_m'],1.26);self.assertGreaterEqual(p['weapon_down_pixels'],60)
 def test_forward_push_only_after_45(self):
  for i in range(353):self.assertEqual(parameters(self.c,1+i/8)['weapon_depth_delta_m'],0)
 def test_no_envelope_overshoot(self):
  for name in parameters(self.c,1):
   lo=min(x[1] for x in self.c[name]);hi=max(x[1] for x in self.c[name])
   for i in range(5441):self.assertTrue(lo-1e-9<=envelope(self.c[name],1+i/80)<=hi+1e-9)
 def test_nonfinite_rejected(self):
  self.c['camera_depth_m'][2][1]=float('nan')
  with self.assertRaises(AssertionError):validate_config(self.c)
 def test_retime_rejected(self):
  self.c['fps']=30
  with self.assertRaises(AssertionError):validate_config(self.c)
class ReceiptTests(unittest.TestCase):
 def setUp(self):self.s=json.loads((P/'fresh_reopen_checks.json').read_text())['summary']
 def test_actual_receipt(self):self.assertEqual(validate(self.s),[])
 def test_pair_required(self):self.s['actions'].pop('prone_crawl_enter_camera_r6');self.assertTrue(validate(self.s))
 def test_high_camera_rejected(self):self.s['min_camera_height_above_ground_m']=1.6;self.assertTrue(validate(self.s))
 def test_contact_nan_rejected(self):self.s['contact_480hz_max_m']['l']=float('nan');self.assertTrue(validate(self.s))
 def test_guard_failure_rejected(self):self.s['new_wrist_guard_max_deg']['l']=20;self.assertTrue(validate(self.s))
 def test_missing_preservation_rejected(self):self.s['fresh_reopen_preservation']={};self.assertTrue(validate(self.s))
 def test_artistic_claim_rejected(self):self.s['visual_pass']=True;self.assertTrue(validate(self.s))
if __name__=='__main__':unittest.main()
