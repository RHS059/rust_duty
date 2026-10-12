"""Static guards for the bounded CPU image pair; no native execution."""
from pathlib import Path
import unittest

import yaml

from run_cpu_image_preservation import LOADER_BASELINE_COMMIT

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'aella/wgpu-1080p-diagnostics'


class CpuImageWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (ROOT / '.github/workflows/cpu-image-preservation.yml').read_text()
        cls.workflow = yaml.load(cls.body, Loader=yaml.BaseLoader)
        cls.job = cls.workflow['jobs']['exact-cpu-image-pair']
        cls.steps = cls.job['steps']

    def test_single_bounded_windows_push_without_gate_bypass(self):
        self.assertEqual(set(self.workflow['on']), {'push'})
        self.assertEqual(self.workflow['on']['push']['branches'], [BRANCH])
        paths=set(self.workflow['on']['push']['paths'])
        self.assertTrue({'.github/workflows/'+name+'-assets.yml' for name in
                         ('blender','walk','ads','directional','jump')} <= paths)
        self.assertEqual(self.workflow['env']['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(self.workflow['concurrency'], {
            'group': 'cpu-image-preservation-${{ github.ref }}', 'cancel-in-progress': 'false'})
        self.assertEqual(set(self.workflow['jobs']), {'pair-admission', 'exact-cpu-image-pair', 'animation-assets', 'walk-assets', 'ads-assets', 'directional-assets', 'jump-assets'})
        self.assertEqual(set(self.job['needs']), {'pair-admission','animation-assets','walk-assets','ads-assets','directional-assets','jump-assets'})
        self.assertEqual(self.job['runs-on'], 'windows-latest')
        self.assertEqual(self.job['timeout-minutes'], '60')
        self.assertIn("github.ref == 'refs/heads/" + BRANCH + "'", self.job['if'])
        for forbidden in ('workflow_dispatch', 'pull_request:', 'secrets.', 'continue-on-error',
                          'workflow_call', 'strategy:', 'merge-pull-request', 'gh pr merge',
                          'finite_ads_reviewed_class', 'CURRENT_ADS_SOURCE_PROOF'):
            self.assertNotIn(forbidden, self.body)

    def test_exact_public_sources_without_assets_or_downloaded_executables(self):
        checkout = next(s['with'] for s in self.steps if s.get('uses') == 'actions/checkout@v4')
        self.assertEqual(checkout['persist-credentials'], 'false')
        self.assertEqual(checkout['sparse-checkout-cone-mode'], 'false')
        paths = set(checkout['sparse-checkout'].splitlines())
        self.assertEqual(paths, {'/*', '!/assets/weapons/'})
        downloads = [step['with'] for step in self.steps if step.get('uses') == 'actions/download-artifact@v4']
        self.assertEqual(downloads, [{'name': 'generated-'+name+'-runtime', 'path': 'assets/'+name}
                                    for name in ('reload','walk','ads','directional','jump')])
        for name in ('animation','walk','ads','directional','jump'):
            job=self.workflow['jobs'][name+'-assets']
            self.assertEqual(job['uses'], './.github/workflows/'+('blender' if name=='animation' else name)+'-assets.yml')
        for name in ('ads','directional','jump'):
            self.assertEqual(self.workflow['jobs'][name+'-assets']['needs'], ['pair-admission', 'walk-assets'])
        fetch = next(s for s in self.steps if 'git fetch' in s.get('run', ''))
        self.assertIn('git fetch --no-write-fetch-head --no-tags --depth=1 origin ' + LOADER_BASELINE_COMMIT, fetch['run'])
        self.assertIn("throw 'Reviewed baseline source retrieval failed'", fetch['run'])
        self.assertEqual(self.workflow['env'], {'PYTHONDONTWRITEBYTECODE': '1', 'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': 'core.autocrlf', 'GIT_CONFIG_VALUE_0': 'false'})
        self.assertEqual(self.job['env'], {'CARGO_HOME': '${{ github.workspace }}/.cpu-image-cargo'})

    def test_runner_context_is_not_used_in_pre_runner_environment_scopes(self):
        # GitHub rejects this before assigning any job, unlike a step-level env.
        # https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
        for scope in (self.workflow.get('env', {}), self.job.get('env', {})):
            for value in scope.values():
                self.assertNotIn('${{ runner.', value)
        self.assertEqual(self.job['env']['CARGO_HOME'],
                         '${{ github.workspace }}/.cpu-image-cargo')

    def test_pinned_compiler_and_guards_precede_two_fresh_builds(self):
        compiler = next(s for s in self.steps if 'rustup toolchain install' in s.get('run', ''))
        self.assertIn('rustup toolchain install 1.99.0-x86_64-pc-windows-msvc --profile minimal', compiler['run'])
        self.assertIn('rustup which --toolchain 1.99.0-x86_64-pc-windows-msvc rustc', compiler['run'])
        self.assertIn('GITHUB_PATH', compiler['run'])
        guards = next(s for s in self.steps if 'python -m unittest' in s.get('run', ''))
        execution = next(s for s in self.steps if 'run_authored_loader_pair.py --root' in s.get('run', ''))
        self.assertLess(self.steps.index(compiler), self.steps.index(execution))
        self.assertLess(self.steps.index(guards), self.steps.index(execution))
        for name in ('test_cpu_image_preservation', 'test_arena_serialization_pair', 'test_pass_submission_benchmark',
                     'test_renderer_contract', 'test_cpu_image_workflow'):
            self.assertIn(name, guards['run'])
        self.assertEqual(execution['timeout-minutes'], '54')
        materialize=next(step for step in self.steps if 'package_game.py materialize' in step.get('run',''))
        for flag in ('--include-walk','--include-ads','--include-directional','--include-jump','--require-generated'):
            self.assertIn(flag, materialize['run'])
        self.assertLess(self.steps.index(materialize),self.steps.index(execution))
        self.assertIn('test_authored_loader_pair', guards['run'])
        self.assertIn('test_authored_loader_runner', guards['run'])
        for argument in ('--root .', '--output evidence/cpu-image-native',
                         '--build-timeout 1200', '--process-timeout 600'):
            self.assertIn(argument, execution['run'])
        for forbidden in ('--renderer=vulkan', '--renderer=gl', '--disable-validation', 'Start-Process'):
            self.assertNotIn(forbidden, self.body)

    def test_all_source_images_and_failed_logs_retained_without_build_trees(self):
        upload = next(s for s in self.steps if s.get('uses') == 'actions/upload-artifact@v4')
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['retention-days'], '7')
        self.assertEqual(upload['with']['include-hidden-files'], 'true')
        compact=next(step for step in self.steps if step.get('with',{}).get('name','').startswith('authored-loader-reports-'))
        self.assertEqual(compact['if'], 'always()')
        for path in ('sources/*.json','control-outputs.zip','*-authored/*.png','*-authored/*.json','*-process/**'):
            self.assertIn('evidence/cpu-image-native/'+path,compact['with']['path'])
        self.assertNotIn('corners.bin',compact['with']['path'])
        for name in ('camera-prepare','baseline-authored','candidate-authored'):
            packet=next(step for step in self.steps if step.get('with',{}).get('name','').startswith(name+'-outputs-'))
            self.assertEqual(packet['if'],'always()')
            self.assertEqual(packet['with']['path'],'evidence/cpu-image-native/'+name+'-outputs.zip')
        self.assertEqual(upload['with']['path'].splitlines(), [
            'evidence/cpu-image-native/**', '!evidence/cpu-image-native/*-target/**',
            '!evidence/cpu-image-native/**/*.exe', '!evidence/cpu-image-native/**/*.dll',
            '!evidence/cpu-image-native/**/assets/**'])


if __name__ == '__main__':
    unittest.main()
