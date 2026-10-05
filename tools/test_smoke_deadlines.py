import unittest
from smoke_game_update import headless_transfer_budget

class SmokeDeadlineTests(unittest.TestCase):
    def test_baseline_specific_finite_budgets_keep_the_existing_game_limit(self):
        self.assertEqual(headless_transfer_budget('full'), 150)
        self.assertEqual(headless_transfer_budget('one-file'), 600)
        with self.assertRaises(ValueError): headless_transfer_budget('unbounded')
