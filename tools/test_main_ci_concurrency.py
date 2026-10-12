"""Main verification survives newer commits while the pending queue stays bounded."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "${{ (github.head_ref || github.ref_name) != 'main' && (github.event_name != 'push' || github.ref != 'refs/heads/aella/automatic-game-updates-r1') }}"

class MainConcurrencyTests(unittest.TestCase):
    def test_main_uses_non_cancelling_existing_group_and_default_single_pending(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/build.yml').read_text())
        policy = workflow['concurrency']
        self.assertEqual(policy['cancel-in-progress'], EXPECTED)
        self.assertEqual(policy['group'], "game-${{ github.head_ref || github.ref_name }}-${{ github.ref == 'refs/heads/aella/automatic-game-updates-r1' && github.event_name || 'ci' }}")
        self.assertNotIn('queue', policy)
        self.assertEqual(workflow['permissions'], {'contents': 'read'})

    def test_policy_truth_table_preserves_existing_release_exception(self):
        # Evaluate only this deliberately fixed GitHub boolean expression.
        expression = EXPECTED[3:-2].strip().replace('&&', ' and ').replace('||', ' or ')
        cases = [
            ('', 'main', 'push', 'refs/heads/main', False),
            ('', 'main', 'workflow_dispatch', 'refs/heads/main', False),
            ('main', '99/merge', 'pull_request', 'refs/pull/99/merge', False),
            ('', 'aella/feature', 'push', 'refs/heads/aella/feature', True),
            ('aella/feature', '99/merge', 'pull_request', 'refs/pull/99/merge', True),
            ('', 'aella/automatic-game-updates-r1', 'push', 'refs/heads/aella/automatic-game-updates-r1', False),
            ('aella/automatic-game-updates-r1', '99/merge', 'pull_request', 'refs/pull/99/merge', True),
        ]
        for head_ref, ref_name, event_name, ref, expected in cases:
            with self.subTest(head_ref=head_ref, ref_name=ref_name, event_name=event_name):
                values = {'head_ref': head_ref, 'ref_name': ref_name, 'event_name': event_name, 'ref': ref}
                source = expression
                for name in ('head_ref', 'ref_name', 'event_name', 'ref'):
                    source = source.replace('github.' + name, repr(values[name]))
                self.assertEqual(eval(source, {'__builtins__': {}}, {}), expected)

if __name__ == '__main__':
    unittest.main()
