"""The independent preview reuses guarded recovery without duplicating the full build."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

class WindowsMigrationPreviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = yaml.load((ROOT / '.github/workflows/windows-migration-preview.yml').read_text(), Loader=yaml.BaseLoader)

    def test_source_and_preview_workflow_changes_or_manual_request_trigger(self):
        events = self.data['on']
        self.assertEqual(set(events), {'push', 'workflow_dispatch'})
        self.assertEqual(events['push']['branches'], ['main'])
        self.assertEqual(events['push']['paths'], [
            'src/**', 'tests/**', 'Cargo.toml', 'Cargo.lock', 'build.rs', 'build_number.rs',
            'rust-toolchain.toml', '.cargo/**', 'updater/src/**', 'updater/Cargo.toml',
            'updater/Cargo.lock', 'tools/summarize_frame_performance.py',
            'tools/test_summarize_frame_performance.py',
            '.github/workflows/windows-migration-preview.yml',
            '.gitattributes',
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
            'tools/finite_ads_profile_binding.py',
            'tools/test_finite_ads_profile_binding.py',
            'tools/test_finite_ads_profile_gate.py',
            'tools/test_finite_ads_pass_batching.py',
            'tools/finite_ads_reviewed_class.json',
            'tools/finite_ads_reviewed_evidence/**',
            'tools/finite_ads_pass_batching_class.json',
            'tools/finite_ads_pass_batching_evidence/**',
            'tools/test_finite_ads_gpu_cpu.py',
            'tools/test_finite_ads_gpu_cpu_native.py',
            'tools/finite_ads_gpu_cpu_class.json',
            'tools/finite_ads_gpu_cpu_evidence/**',
            'tools/collect_ads_offset_evidence.py',
            'tools/test_collect_ads_offset_evidence.py',
            'tools/package_source_companion_evidence.py',
            'tools/test_source_companion_evidence.py'])

    def test_reuses_complete_guarded_recovery_with_minimum_existing_permissions(self):
        self.assertEqual(self.data['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(self.data['jobs'], {
            'renderer-contract': {
                'concurrency': {'group': 'migration-renderer-contract-${{ github.ref }}',
                                'cancel-in-progress': 'false'},
                'uses': './.github/workflows/wgpu-renderer-contract.yml'},
            'source-bound-preview': {
                'uses': './.github/workflows/windows-source-bound-recovery.yml',
                'with': {'independent_preview': 'true'}}})

    def test_preview_group_is_distinct_from_protected_full_main_verification(self):
        self.assertNotIn('concurrency', self.data)
        recovery = yaml.load((ROOT / '.github/workflows/windows-source-bound-recovery.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(recovery['jobs']['recover']['concurrency'], {
            'group': 'source-bound-recovery-${{ github.repository }}-${{ inputs.independent_preview && github.ref || github.run_id }}-${{ matrix.lane }}',
            'cancel-in-progress': 'false'})
        self.assertNotIn('game-', recovery['jobs']['recover']['concurrency']['group'])

if __name__ == '__main__':
    unittest.main()
