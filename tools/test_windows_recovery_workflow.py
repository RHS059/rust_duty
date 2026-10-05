"""Bounded recovery wiring contracts, without downloading or rendering."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecoveryWorkflowTests(unittest.TestCase):
    def test_recovery_is_independent_and_branch_bounded(self):
        caller = (ROOT / '.github/workflows/build.yml').read_text()
        block = caller.split('  windows-source-bound-recovery:\n', 1)[1].split('  windows-same-platform-return:', 1)[0]
        self.assertNotIn('needs:', block)
        self.assertIn("github.head_ref == 'aella/wgpu-renderer-port'", block)
        self.assertIn('actions: read', block)
        self.assertNotIn('write', block)
        self.assertIn('uses: ./.github/workflows/windows-source-bound-recovery.yml', block)

    def test_inputs_verified_before_any_game_execution(self):
        body = (ROOT / '.github/workflows/windows-source-bound-recovery.yml').read_text()
        ordered = ['python tools/fetch_source_bound_companions.py',
                   'python tools/revalidate_reused_companions.py',
                   'git worktree add --detach evidence/runtime-root HEAD',
                   'python tools/package_game.py materialize',
                   'python tools/ci_quality_checks.py',
                   'cargo build --locked --release --features wgpu-runtime --bin vector-range',
                   'python tools/run_dx12_smoke.py',
                   'python tools/collect_game_licenses.py --check',
                   'python tools/stage_dx12_preview.py',
                   'python tools/run_windows_same_platform_return.py']
        offsets = [body.index(item) for item in ordered]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn('--expected-source-commit ${{ github.sha }}', body)
        for kind, identifier in [('reload',11357733263),('walk',11358380091),('ads',11357971900),('directional',11357009655),('jump',11357977549)]:
            self.assertIn(f'--artifact {kind}=evidence/original-inputs/{identifier}.zip', body)

    def test_honest_reuse_and_no_distribution_promotion(self):
        body = (ROOT / '.github/workflows/windows-source-bound-recovery.yml').read_text()
        self.assertIn('COMPANION_REUSE.json', body)
        self.assertIn('source-oracle generation/parity did not rerun', body)
        self.assertIn('DX12-Revalidated-Preview-Windows-x64', body)
        self.assertIn('if: always()', body)
        for bad in ('continue-on-error:', 'contents: write', 'actions: write', 'gh release', 'release_update.py', 'secrets.'):
            self.assertNotIn(bad, body)
        self.assertEqual(body.count('GITHUB_TOKEN: ${{ github.token }}'), 1)
        self.assertIn("GIT_CONFIG_KEY_0: core.autocrlf", body)
        self.assertIn("GIT_CONFIG_VALUE_0: 'false'", body)


if __name__ == '__main__':
    unittest.main()
