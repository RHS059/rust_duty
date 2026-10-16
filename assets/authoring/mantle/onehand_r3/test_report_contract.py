import copy
import json
import unittest
from pathlib import Path
from report_contract import validate, validate_authoring
P = Path(__file__).resolve().parent
class SavedSourceContract(unittest.TestCase):
    def setUp(self):
        self.summary = json.loads((P / 'candidate/evaluation.json').read_text())['summary']
        self.authoring = json.loads((P / 'candidate/authoring_report.json').read_text())
    def test_actual_r3_saved_source(self):
        self.assertEqual(validate(self.summary), [])
        self.assertEqual(validate_authoring(self.authoring, self.summary['source_sha256']), [])
    def test_actual_r2_guard_failure(self):
        old = json.loads((P.parent / 'onehand_r2/candidate/evaluation.json').read_text())['summary']
        self.assertIn('attached_wrist_guard', validate(old))
    def test_actual_r2_inverse_solver_failure(self):
        old = json.loads((P.parent / 'onehand_r2/candidate/authoring_report.json').read_text())
        self.assertIn('authoring_target', validate_authoring(old, old['source_sha256']))
    def test_reject_mismatched_source_report(self):
        self.assertIn('bound_to_saved_source', validate_authoring(self.authoring, '0' * 64))
    def test_reject_weapon_drift(self):
        bad = copy.deepcopy(self.summary); bad['weapon_matrix_max_component_delta'] = 1e-6
        self.assertIn('unchanged_weapon', validate(bad))
    def test_reject_missing_subframes(self):
        bad = copy.deepcopy(self.summary); bad['samples'] = 96
        self.assertIn('dense_time_coverage', validate(bad))
    def test_reject_switch_discontinuity(self):
        bad = copy.deepcopy(self.summary); bad['switches']['7830']['position_mm'] = 0.1
        self.assertIn('source_switch_position', validate(bad))
if __name__ == '__main__': unittest.main()
