import copy
import hashlib
import json
from pathlib import Path
import unittest
from report_contract import validate
from projection_contract import validate_projection
P = Path(__file__).resolve().parent
class VaultRevisionContracts(unittest.TestCase):
    def setUp(self):
        self.summary = json.loads((P / 'candidate/evaluation.json').read_text())['summary']
        self.projection = json.loads((P / 'candidate/hand_projection.json').read_text())
    def test_saved_source_technical_gates(self):
        self.assertEqual(validate(self.summary), [])
    def test_projection_cues_are_limited_but_met(self):
        self.assertEqual(validate_projection(self.projection), [])
    def test_exact_current_source_identity(self):
        sha = hashlib.sha256((P / 'candidate/aella_mantle_r3.blend').read_bytes()).hexdigest()
        self.assertEqual(self.summary['source_sha256'], sha)
        self.assertEqual(self.projection['source_sha256'], sha)
    def test_actual_initial_diagnostic_hid_hand_too_early(self):
        old = json.loads((P / 'initial_spatial_diagnostic/hand_projection.json').read_text())
        self.assertIn('visible_cue_7296', validate_projection(old))
    def test_actual_discrete_switch_failure_still_rejected(self):
        old = json.loads((P.parent / 'r2/discrete_switch_evaluation.json').read_text())['summary']
        self.assertIn('source_switch_position', validate(old))
    def test_middle_palm_visibility_violation_is_rejected(self):
        bad = copy.deepcopy(self.projection)
        row = next(r for r in bad['samples'] if r['native'] == 7315)
        row['projected_bbox_pixels'] = [100, 100, 400, 400]
        row['bbox_disjoint_from_viewport'] = False
        self.assertIn('middle_out_of_view_7315', validate_projection(bad))
    def test_weapon_drift_is_rejected(self):
        bad = copy.deepcopy(self.summary); bad['weapon_matrix_max_component_delta'] = 1e-6
        self.assertIn('unchanged_weapon', validate(bad))
if __name__ == '__main__': unittest.main()
