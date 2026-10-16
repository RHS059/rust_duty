"""Exercise the actual saved-report gate with current evidence and rejected controls."""
import copy
import json
import unittest
from pathlib import Path
from report_contract import validate
P = Path(__file__).resolve().parent
class ReportContract(unittest.TestCase):
    def setUp(self):
        self.good = json.loads((P / 'candidate/evaluation.json').read_text())['summary']
    def test_current_saved_source(self):
        self.assertEqual(validate(self.good), [])
    def test_actual_failed_discrete_switch(self):
        old = json.loads((P / 'discrete_switch_evaluation.json').read_text())['summary']
        self.assertIn('source_switch_position', validate(old))
    def test_changed_weapon(self):
        bad = copy.deepcopy(self.good); bad['weapon_matrix_max_component_delta'] = 1e-6
        self.assertIn('unchanged_weapon', validate(bad))
    def test_invalid_skin(self):
        bad = copy.deepcopy(self.good); bad['all_finite'] = False
        self.assertIn('finite_skin_and_bones', validate(bad))
    def test_guard_clipping(self):
        bad = copy.deepcopy(self.good); bad['max_attached_guard_delta_deg'] = 1.2
        self.assertIn('attached_wrist_guard', validate(bad))
    def test_missing_subframes(self):
        bad = copy.deepcopy(self.good); bad['samples'] = 64
        self.assertIn('dense_time_coverage', validate(bad))
if __name__ == '__main__': unittest.main()
