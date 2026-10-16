"""Audit measured report semantics without Blender or rendering."""
import hashlib,json,math,unittest
from pathlib import Path
P=Path(__file__).resolve().parent
class Diagnostics(unittest.TestCase):
 def test_source_unchanged(self):
  self.assertEqual(hashlib.sha256((P.parent/'aella_climb_r1.blend').read_bytes()).hexdigest(),'baca19e147f8384bdebcb78b54837ad559b4882a3992deab503190f21040d593')
 def test_shortest_angle_from_raw_evidence(self):
  raw=json.loads((P/'baseline_evaluation/aella_climb_roof_r1_native.json').read_text())['quarter_frames']
  summary=json.loads((P/'baseline_evaluation/shortest_angle_summary.json').read_text())['peaks']
  self.assertEqual(len(raw),301)
  for side in ['l','r']:
   vals=[min(r['hands'][side]['guard_error_degrees'],360-r['hands'][side]['guard_error_degrees']) for r in raw]
   self.assertTrue(all(0<=v<=180 for v in vals))
   self.assertAlmostEqual(max(vals),summary[side]['max_shortest_guard_error_deg'])
 def test_probe_not_a_pass(self):
  rows=json.loads((P/'combined_visible_probe.json').read_text())
  for n in [8522,8524]:
   self.assertGreater(min(r['guard_deg'] for r in rows if r['native']==n),5)
 def test_no_r2_source_claim(self):
  self.assertFalse(list(P.glob('*.blend')))
if __name__=='__main__':unittest.main()
