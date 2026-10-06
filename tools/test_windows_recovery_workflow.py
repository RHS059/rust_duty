"""Bounded recovery wiring contracts, without downloading or rendering."""
from pathlib import Path
import unittest
import yaml

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

    def test_quality_and_wip_build_are_independent_without_waiving_readiness(self):
        body = (ROOT / '.github/workflows/windows-source-bound-recovery.yml').read_text()
        self.assertIn('fail-fast: false', body)
        self.assertIn('max-parallel: 2', body)
        self.assertIn('lane: [quality, build-preview]', body)
        self.assertIn("if: matrix.lane == 'quality'", body)
        self.assertIn("if: matrix.lane == 'build-preview'", body)
        self.assertIn('final_readiness_requires_all_checks=$true', body)
        self.assertIn('QUALITY_SCOPE.json', body)
        caller = (ROOT / '.github/workflows/build.yml').read_text()
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.source_bound_recovery", caller)
        self.assertIn('default: false', caller)

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
        self.assertEqual(body.count('GITHUB_TOKEN: ${{ github.token }}'), 2)
        steps = yaml.safe_load(body)['jobs']['recover']['steps']
        token_steps = [step['name'] for step in steps if 'GITHUB_TOKEN' in step.get('env', {})]
        self.assertEqual(token_steps, ['Retrieve exact immutable original ZIPs and source witness',
                                      'Retrieve the fixed pre-facade Windows reference archive'])
        self.assertIn("GIT_CONFIG_KEY_0: core.autocrlf", body)
        self.assertIn("GIT_CONFIG_VALUE_0: 'false'", body)

    def test_cache_preserves_fresh_worktree_inputs_and_current_build(self):
        body = (ROOT / '.github/workflows/windows-source-bound-recovery.yml').read_text()
        steps = yaml.safe_load(body)['jobs']['recover']['steps']
        caches = [step for step in steps if step.get('uses') == 'actions/cache@v4']
        self.assertEqual(len(caches), 1)
        cache = caches[0]
        self.assertEqual(cache['with']['path'].splitlines(), [
            '~/.cargo/registry', '~/.cargo/git', 'evidence/runtime-root/target',
            'evidence/runtime-root/updater/target'])
        prefix = ('recovery-cargo-v1-${{ runner.os }}-${{ runner.arch }}-'
                  '${{ matrix.lane }}-${{ steps.recovery-rust-version.outputs.hash }}-'
                  "${{ hashFiles('Cargo.lock', 'updater/Cargo.lock') }}-")
        self.assertEqual(cache['with']['key'], prefix + '${{ github.sha }}')
        self.assertEqual(cache['with']['restore-keys'].splitlines(), [prefix])
        materialize = next(step for step in steps
                           if 'package_game.py materialize' in step.get('run', ''))
        self.assertLess(steps.index(materialize), steps.index(cache))
        build = next(step for step in steps if 'cargo build' in step.get('run', ''))
        self.assertEqual(build['if'], "matrix.lane == 'build-preview'")
        self.assertLess(steps.index(cache), steps.index(build))
        self.assertIn('python tools/ci_quality_checks.py', body)
        self.assertIn('python tools/run_dx12_smoke.py', body)
        self.assertIn('python tools/run_windows_same_platform_return.py', body)

    def test_facade_reference_runs_after_original_checks_without_another_build(self):
        body = (ROOT / '.github/workflows/windows-source-bound-recovery.yml').read_text()
        steps = yaml.safe_load(body)['jobs']['recover']['steps']
        def one(text):return next(step for step in steps if text in step.get('run', ''))
        pair = one('python tools/run_windows_same_platform_return.py')
        fetch = one('python tools/fetch_legacy_facade_reference.py')
        compare = one('python tools/run_legacy_facade_equivalence.py')
        package = next(step for step in steps if step.get('name')=='Retain isolated current Windows preview')
        self.assertLess(steps.index(package),steps.index(pair))
        self.assertLess(steps.index(pair),steps.index(fetch));self.assertLess(steps.index(fetch),steps.index(compare))
        self.assertEqual(sum('cargo build' in step.get('run','') for step in steps),1)
        self.assertEqual(fetch['if'],"matrix.lane == 'build-preview'")
        self.assertEqual(compare['if'],"matrix.lane == 'build-preview'")
        self.assertEqual(fetch['timeout-minutes'],5);self.assertEqual(compare['timeout-minutes'],16)
        self.assertEqual(fetch['env'],{'GITHUB_TOKEN':'${{ github.token }}'})
        self.assertNotIn('env',compare)
        self.assertEqual(compare['working-directory'],'evidence/runtime-root')
        for arg in ('--reference-zip ../legacy-facade-reference/11326905753.zip',
                    '--executable target/release/vector-range.exe','--root . --runtime ../gl-runtime',
                    '--evidence ../legacy-facade-equivalence --timeout 180'):
            self.assertIn(arg,compare['run'])
        self.assertNotIn('continue-on-error',compare)

    def test_facade_retention_is_explicit_and_excludes_archives_and_runtime(self):
        steps = yaml.safe_load((ROOT / '.github/workflows/windows-source-bound-recovery.yml').read_text())['jobs']['recover']['steps']
        step = next(step for step in steps if step.get('name')=='Retain bounded facade comparison evidence without binaries')
        self.assertEqual(step['if'],"always() && matrix.lane == 'build-preview'")
        self.assertEqual(step['uses'],'actions/upload-artifact@v4')
        self.assertEqual(step['with']['path'].splitlines(),[
            'evidence/legacy-facade-reference/reference-metadata.json',
            'evidence/legacy-facade-equivalence/captures/',
            'evidence/legacy-facade-equivalence/logs/',
            'evidence/legacy-facade-equivalence/summary.json',
            'evidence/legacy-facade-equivalence/input-manifest.json',
            'evidence/legacy-facade-equivalence/settings.cfg',
            'evidence/legacy-facade-equivalence/reference-input/BUILD_IDENTITY.json'])
        previous = next(s for s in steps if s.get('name')=='Retain actual smoke and authored pair evidence')
        self.assertEqual(previous['with']['path'],'evidence/runtime-root/evidence/')
        self.assertEqual(previous['if'],"always() && matrix.lane == 'build-preview'")


if __name__ == '__main__':
    unittest.main()
