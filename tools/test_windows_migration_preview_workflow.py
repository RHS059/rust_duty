"""The independent preview reuses guarded recovery without duplicating the full build."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

class WindowsMigrationPreviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = yaml.load((ROOT / '.github/workflows/windows-migration-preview.yml').read_text(), Loader=yaml.BaseLoader)

    def test_only_explicit_preview_workflow_changes_or_manual_request_trigger(self):
        events = self.data['on']
        self.assertEqual(set(events), {'push', 'workflow_dispatch'})
        self.assertEqual(events['push']['branches'], ['main'])
        self.assertEqual(events['push']['paths'], [
            '.github/workflows/windows-migration-preview.yml',
            '.github/workflows/windows-source-bound-recovery.yml',
            'tools/test_windows_migration_preview_workflow.py',
            'tools/source_bound_companion_reuse_lock.json',
            'tools/revalidate_reused_companions.py',
            'tools/test_revalidate_reused_companions.py',
            'tools/run_legacy_facade_equivalence.py',
            'tools/test_legacy_facade_equivalence.py',
            'tools/fetch_legacy_facade_reference.py',
            'tools/test_fetch_legacy_facade_reference.py',
            'tools/test_windows_recovery_workflow.py',
            '.github/workflows/wgpu-dx12-authored.yml',
            'tools/prepare_ads_source_oracle.py',
            'tools/test_prepare_ads_source_oracle.py',
            'tools/build_ads_source_packet.py',
            'tools/test_build_ads_source_packet.py',
            'tools/current_ads_source_oracle.py',
            'tools/test_current_ads_source_oracle.py',
            'tools/collect_ads_offset_evidence.py',
            'tools/test_collect_ads_offset_evidence.py',
            'tools/package_source_companion_evidence.py',
            'tools/test_source_companion_evidence.py'])

    def test_reuses_complete_guarded_recovery_with_minimum_existing_permissions(self):
        self.assertEqual(self.data['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(self.data['jobs'], {
            'renderer-contract': {'uses': './.github/workflows/wgpu-renderer-contract.yml'},
            'source-bound-preview': {'uses': './.github/workflows/windows-source-bound-recovery.yml'}})

    def test_preview_group_is_distinct_from_protected_full_main_verification(self):
        self.assertEqual(self.data['concurrency'], {
            'group': 'migration-windows-preview-${{ github.ref }}',
            'cancel-in-progress': 'false'})
        self.assertNotIn('game-', self.data['concurrency']['group'])

if __name__ == '__main__':
    unittest.main()
