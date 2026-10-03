"""The live smoke must distinguish helper admission from proven replacement."""
import unittest
from smoke_game_update import validate_relaunch


class RelaunchProofTests(unittest.TestCase):
    outcome = "Update installed and replacement startup acknowledged"

    def test_acknowledged_replacement_and_current_relaunch_pass(self):
        validate_relaunch(self.outcome, dict(version="0.1.4", status="current", exit_code=0), "0.1.4")

    def test_admission_rollback_and_old_success_wording_are_not_proof(self):
        for outcome in ["helper_admitted", "Update rolled back", "Update installed and game restarted"]:
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                validate_relaunch(outcome, dict(version="0.1.4", status="current", exit_code=0), "0.1.4")

    def test_ack_alone_cannot_hide_failed_or_wrong_relaunch(self):
        for version, status, code in [("0.1.3", "current", 0), ("0.1.4", "error", 1),
                                       ("0.1.4", "helper_admitted", 0), ("0.1.4", "current", 1)]:
            with self.subTest(version=version, status=status, code=code), self.assertRaises(ValueError):
                validate_relaunch(self.outcome, dict(version=version, status=status, exit_code=code), "0.1.4")


if __name__ == "__main__":
    unittest.main()
