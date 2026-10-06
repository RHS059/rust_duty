"""Static CI contracts; these tests do not establish native rendering success."""
from pathlib import Path
import unittest

import yaml

import dx12_authored_shards as shared


class AuthoredWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / '.github/workflows/wgpu-dx12-authored.yml'
        cls.workflow = yaml.safe_load(cls.path.read_text(encoding='utf-8'))
        cls.jobs = cls.workflow['jobs']

    def steps(self, job):
        return self.jobs[job]['steps']

    def downloads(self, job):
        return [step['with'] for step in self.steps(job)
                if step.get('uses') == 'actions/download-artifact@v4']

    def uploads(self, job):
        return [step for step in self.steps(job)
                if step.get('uses') == 'actions/upload-artifact@v4']

    def test_closed_nine_scenario_matrix_and_measured_budgets(self):
        strategy = self.jobs['authored-capture']['strategy']
        self.assertIs(strategy['fail-fast'], False)
        self.assertEqual(strategy['max-parallel'], 4)
        expected = [{'scenario': name, **{key: value for key, value in profile.items() if key != 'expected_frames'}}
                    for name, profile in shared.PROFILES.items()]
        self.assertEqual(strategy['matrix'], {'include': expected})
        self.assertEqual(sum(profile['expected_frames'] or 0 for profile in shared.PROFILES.values()), 3347)
        self.assertEqual(self.jobs['authored-capture']['timeout-minutes'], '${{ matrix.job_timeout_minutes }}')

    def test_single_dual_runtime_build_and_unchanged_binaries(self):
        builds = [(job, step['run']) for job in self.jobs for step in self.steps(job)
                  if 'cargo build' in step.get('run', '')]
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0][0], 'authored-inputs')
        self.assertEqual(builds[0][1].split(), ['cargo', 'build', '--locked', '--release', '--no-default-features',
                        '--features', 'legacy-macroquad,wgpu-runtime', '--bin', 'vector-range', '--example', 'renderer_contract'])
        executable_upload = self.uploads('authored-inputs')[0]['with']
        self.assertEqual(executable_upload['name'], 'dx12-authored-inputs-attempt-${{ github.run_attempt }}')
        self.assertEqual(executable_upload['if-no-files-found'], 'error')
        self.assertEqual(executable_upload['path'].splitlines(), [
            'target/release/vector-range.exe', 'target/release/examples/renderer_contract.exe',
            'evidence/authored-inputs/input-manifest.json', 'evidence/authored-inputs/historical-manifest.json',
            'evidence/gl-runtime/'])
        for job in ('authored-capture', 'authored-aggregate'):
            self.assertIn({'name': executable_upload['name'], 'path': '.'}, self.downloads(job))

    def test_compiler_cache_never_substitutes_for_current_source_build(self):
        steps = self.steps('authored-inputs')
        caches = [step for step in steps if step.get('uses') == 'actions/cache@v4']
        self.assertEqual(len(caches), 1)
        cache = caches[0]
        self.assertEqual(cache['with']['path'].splitlines(),
                         ['~/.cargo/registry', '~/.cargo/git', 'target'])
        prefix = ('authored-dual-release-v1-${{ runner.os }}-${{ runner.arch }}-'
                  '${{ steps.authored-rust-version.outputs.hash }}-'
                  "${{ hashFiles('Cargo.lock') }}-")
        self.assertEqual(cache['with']['key'], prefix + '${{ github.sha }}')
        self.assertEqual(cache['with']['restore-keys'].splitlines(), [prefix])
        fingerprint = next(step for step in steps
                           if step.get('id') == 'authored-rust-version')
        self.assertIn("['rustc','-Vv']", fingerprint['run'])
        build = next(step for step in steps if 'cargo build' in step.get('run', ''))
        self.assertNotIn('if', build)
        self.assertLess(steps.index(fingerprint), steps.index(cache))
        self.assertLess(steps.index(cache), steps.index(build))
        prepare = next(step for step in steps
                       if 'run_dx12_authored_shard.py prepare' in step.get('run', ''))
        self.assertLess(steps.index(build), steps.index(prepare))
        self.assertNotIn('if', prepare)

    def test_mesa_staged_once_and_distributed_with_exact_build(self):
        staging = [(job, step) for job in self.jobs for step in self.steps(job)
                   if 'stage_windows_gl_reference.ps1' in step.get('run', '')]
        self.assertEqual(len(staging), 1)
        job, step = staging[0]
        self.assertEqual(job, 'authored-inputs')
        self.assertEqual(step['shell'], 'pwsh')
        self.assertEqual(step['timeout-minutes'], 10)
        self.assertIn('-Manifest tools/windows_gl_reference_lock.json -OutputDirectory evidence/gl-runtime', step['run'])
        self.assertIn('New-Item -ItemType Directory -Path evidence', step['run'])
        steps = self.steps(job)
        prepare = next(s for s in steps if 'run_dx12_authored_shard.py prepare' in s.get('run', ''))
        self.assertLess(steps.index(step), steps.index(prepare))
        self.assertIn('evidence/gl-runtime/', self.uploads(job)[0]['with']['path'].splitlines())
        text = self.path.read_text(encoding='utf-8')
        self.assertNotIn('No Mesa fallback is installed', text)
        self.assertIn('app-local Mesa/llvmpipe', text)

    def test_every_job_uses_same_run_validated_assets(self):
        for job in self.jobs:
            downloads = self.downloads(job)
            for name in ('reload', 'walk', 'ads', 'directional', 'jump'):
                self.assertIn({'name': f'generated-{name}-runtime', 'path': f'assets/{name}'}, downloads)
            materialize = [s['run'] for s in self.steps(job) if 'package_game.py materialize' in s.get('run', '')]
            self.assertEqual(len(materialize), 1)
            self.assertIn('--include-walk --include-ads --include-directional --include-jump --require-generated', materialize[0])
            for download in downloads:
                self.assertTrue(set(download) <= {'name', 'pattern', 'path', 'merge-multiple'})
                self.assertFalse(any(key in download for key in ('repository', 'run-id', 'github-token')))

    def test_historical_downloads_remain_exact_same_attempt(self):
        names = ['gameplay-jump', 'gameplay-reload', 'gameplay-walk', 'gameplay-ads', 'ads-placement', 'layered-locomotion', 'reload-return']
        folders = ['jump-gameplay', 'reload-gameplay', 'walk-gameplay', 'ads-gameplay', 'ads-placement', 'layered', 'reload-return']
        expected = [{'name': f'native-{name}-evidence-attempt-${{{{ github.run_attempt }}}}', 'path': f'evidence/legacy/{folder}'}
                    for name, folder in zip(names, folders)]
        for job in ('authored-inputs', 'authored-aggregate'):
            actual = [d for d in self.downloads(job) if d.get('name', '').startswith('native-')]
            self.assertEqual(actual, expected)
        self.assertFalse(any(d.get('name', '').startswith('native-') for d in self.downloads('authored-capture')))

    def test_failed_and_canceled_shards_cannot_skip_aggregate(self):
        self.assertEqual(self.jobs['authored-capture']['needs'], 'authored-inputs')
        aggregate = self.jobs['authored-aggregate']
        self.assertEqual(aggregate['needs'], ['authored-inputs', 'authored-capture'])
        self.assertEqual(aggregate['if'], 'always()')
        self.assertEqual(aggregate['timeout-minutes'], 150)
        steps = self.steps('authored-aggregate')
        downloads = [step for step in steps if step.get('with', {}).get('pattern')]
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0]['if'], 'always()')
        self.assertEqual(downloads[0]['with'], {
            'pattern': 'dx12-authored-shard-*-evidence-attempt-${{ github.run_attempt }}',
            'path': 'evidence/downloaded-authored-shards', 'merge-multiple': False})
        runner = next(step for step in steps if 'tools/aggregate_dx12_authored.py' in step.get('run', ''))
        self.assertEqual(runner['if'], 'always()')
        self.assertEqual(runner['timeout-minutes'], 45)
        self.assertIn('--timeout 900 --run-timeout 2400', runner['run'])
        self.assertIn('--historical-manifest evidence/authored-inputs/historical-manifest.json', runner['run'])

    def test_scoped_execution_and_always_artifacts(self):
        steps = self.steps('authored-capture')
        runner = next(step for step in steps if 'tools/run_dx12_authored_shard.py run' in step.get('run', ''))
        self.assertEqual(runner['timeout-minutes'], '${{ matrix.step_timeout_minutes }}')
        for flag in ('--scenario ${{ matrix.scenario }}', '--timeout ${{ matrix.capture_timeout_seconds }}',
                     '--run-timeout ${{ matrix.run_timeout_seconds }}'):
            self.assertIn(flag, runner['run'])
        for job in ('authored-capture', 'authored-aggregate'):
            for step in self.uploads(job):
                expected = ('always()' + (" && env.CURRENT_ADS_SOURCE_PROOF == 'true'" if
                    ('offset collection status' in step['name'] or 'source proof and correction' in step['name']) else '')
                    + (" && matrix.scenario == 'ads-offset'" if 'offset collection status' in step['name'] else ''))
                self.assertEqual(step['if'], expected)
                self.assertEqual(step['with']['retention-days'], 7)
        self.assertEqual(self.uploads('authored-aggregate')[0]['with']['name'],
                         'dx12-authored-evidence-attempt-${{ github.run_attempt }}')

    def test_all_existing_and_new_suites_remain_selected(self):
        steps = self.steps('authored-inputs')
        test = next(step for step in steps if 'python -m unittest' in step.get('run', ''))
        self.assertEqual(test['env'], {'PYTHONPATH': 'tools'})
        self.assertEqual(test['run'].split()[4:], [
            'test_dx12_authored', 'test_dx12_capture_progress', 'test_dx12_authored_adversarial',
            'test_dx12_authored_shards', 'test_run_dx12_authored_shard', 'test_aggregate_dx12_authored',
            'test_dx12_authored_workflow', 'test_finite_ads_profile_binding', 'test_finite_ads_profile_gate'])
        self.assertTrue(any(step.get('run') == 'python -m pip install PyYAML==6.0.3' for step in steps))

    def test_no_relaxed_failures_or_permissions_or_release_actions(self):
        self.assertEqual(set(self.jobs), {'authored-inputs', 'authored-capture', 'authored-aggregate'})
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        for job in self.jobs.values():
            self.assertEqual(job['runs-on'], 'windows-latest')
            self.assertNotIn('continue-on-error', job)
            self.assertNotIn('permissions', job)
            for step in job['steps']:
                self.assertNotIn('continue-on-error', step)
                if step.get('uses') == 'actions/checkout@v4':
                    self.assertEqual(step['with'], {'persist-credentials': False})
                if step.get('uses') == 'actions/upload-artifact@v4':
                    self.assertTrue(step['with']['name'].startswith('dx12-authored-'))
        text = self.path.read_text(encoding='utf-8')
        self.assertNotIn('run_dx12_authored.py\n', text)
        self.assertNotIn('workflow_dispatch', text)

    def test_oracle_receipt_anchors_are_job_outputs_and_companions_are_not_redistributed(self):
        outputs = self.jobs['authored-inputs']['outputs']
        self.assertEqual(outputs, {
            'oracle_receipt_sha256': '${{ steps.prepare-oracle.outputs.receipt_sha256 }}',
            'oracle_compiler_sha256': '${{ steps.authored-rust-version.outputs.hash }}'})
        steps = self.steps('authored-inputs')
        prepare = next(s for s in steps if s.get('id') == 'prepare-oracle')
        native = next(s for s in steps if 'run_dx12_authored_shard.py prepare' in s.get('run', ''))
        self.assertLess(steps.index(native), steps.index(prepare))
        self.assertIn('--capture-rustc-sha256 ${{ steps.authored-rust-version.outputs.hash }}', prepare['run'])
        package = next(s for s in self.uploads('authored-inputs') if 'precompiled-oracle' in s['with']['name'])
        self.assertEqual(package['with']['path'], 'evidence/ads-source-oracle-build/package/')
        expected = {'name': package['with']['name'], 'path': 'evidence/precompiled-ads-oracle'}
        self.assertIn(expected, self.downloads('authored-aggregate'))
        self.assertNotIn(expected, self.downloads('authored-capture'))

    def test_only_offset_collection_may_defer_and_original_capture_exit_is_preserved(self):
        step = next(s for s in self.steps('authored-capture') if 'run_dx12_authored_shard.py run' in s.get('run', ''))
        self.assertEqual(step['shell'], 'pwsh')
        text = step['run']
        self.assertIn('$captureExit = $LASTEXITCODE', text)
        self.assertIn("if ($env:CURRENT_ADS_SOURCE_PROOF -eq 'true' -and '${{ matrix.scenario }}' -eq 'ads-offset')", text)
        self.assertIn('collect_ads_offset_evidence.py', text)
        self.assertIn('--capture-exit-code $captureExit', text)
        self.assertIn('elseif ($captureExit -ne 0)', text)
        self.assertIn('exit $captureExit', text)
        self.assertIn("if ($LASTEXITCODE -ne 0) { throw", text)

    def test_current_source_correction_cannot_replace_the_final_required_aggregate(self):
        steps = self.steps('authored-aggregate')
        producer = next(s for s in steps if s.get('id') == 'current-source-oracle')
        final = next(s for s in steps if 'tools/aggregate_dx12_authored.py' in s.get('run', ''))
        self.assertEqual(producer['if'], "always() && env.CURRENT_ADS_SOURCE_PROOF == 'true'")
        self.assertEqual(producer['timeout-minutes'], 90)
        self.assertLess(steps.index(producer), steps.index(final))
        self.assertEqual(producer['env'], {
            'ORACLE_BUILD_RECEIPT_SHA256': '${{ needs.authored-inputs.outputs.oracle_receipt_sha256 }}',
            'CAPTURE_COMPILER_SHA256': '${{ needs.authored-inputs.outputs.oracle_compiler_sha256 }}'})
        self.assertEqual(final['env'], {'ADS_SOURCE_SUPPLEMENT_PATH': '${{ steps.current-source-oracle.outputs.supplement_path }}'})
        self.assertIn("@('--ads-source-supplement', $env:ADS_SOURCE_SUPPLEMENT_PATH)", final['run'])
        self.assertEqual(final['if'], 'always()')
        self.assertEqual(final['timeout-minutes'], 45)

    def test_current_correction_pins_independently_reviewed_finite_class(self):
        import hashlib
        expected = '96dfb631be9d59f6cf35d87e4f3c17a4a4303d74787bb773a8c47672efb53331'
        producer = next(s for s in self.steps('authored-aggregate') if s.get('id') == 'current-source-oracle')
        self.assertIn('--reviewed-class tools/finite_ads_reviewed_class.json', producer['run'])
        self.assertIn('--expected-class-sha256 ' + expected, producer['run'])
        self.assertNotIn('--conditional-diagnostic', producer['run'])
        descriptor = self.path.parents[2] / 'tools/finite_ads_reviewed_class.json'
        self.assertEqual(hashlib.sha256(descriptor.read_bytes()).hexdigest(), expected)

    def test_only_the_original_main_caller_activates_source_correction(self):
        self.assertEqual(self.workflow['env']['CURRENT_ADS_SOURCE_PROOF'],
            "${{ github.repository == 'RHS059/rust_duty' && github.ref == 'refs/heads/main' && github.workflow_ref == 'RHS059/rust_duty/.github/workflows/build.yml@refs/heads/main' }}")
        prepare = next(s for s in self.steps('authored-inputs') if s.get('id') == 'prepare-oracle')
        self.assertEqual(prepare['if'], "env.CURRENT_ADS_SOURCE_PROOF == 'true'")
        download = next(s for s in self.steps('authored-aggregate') if 'precompiled-oracle' in s.get('with', {}).get('name', ''))
        self.assertEqual(download['if'], "env.CURRENT_ADS_SOURCE_PROOF == 'true'")


if __name__ == '__main__':
    unittest.main()
