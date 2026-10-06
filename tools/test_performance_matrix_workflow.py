"""Caller trust-boundary tests; synthetic providers, no download or game launch."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '49c3bf9b3d0482ce81a7d50683904bda28468d7d'
RUN = 37505927104
ARTIFACT = 11432281909
REPOSITORY_ID = 1398577887


def provider():
    repository = {'id': REPOSITORY_ID, 'full_name': 'RHS059/rust_duty'}
    return {
        'context': {'repo': {'owner': 'RHS059', 'repo': 'rust_duty'}},
        'artifact': {
            'id': ARTIFACT,
            'name': 'Rust-Duty-0.1.11+build.37505927104.1-DX12-Revalidated-Preview-Windows-x64',
            'size_in_bytes': 113472627,
            'digest': 'sha256:c6454a307a95a9d36583b2e6e6e8921510e01e6dce1cf5bde34d386ef0100747',
            'expired': False,
            'url': f'https://api.github.com/repos/RHS059/rust_duty/actions/artifacts/{ARTIFACT}',
            'archive_download_url': f'https://api.github.com/repos/RHS059/rust_duty/actions/artifacts/{ARTIFACT}/zip',
            'created_at': '2026-10-06T17:54:41Z',
            'expires_at': '2099-10-13T17:54:30Z',
            'workflow_run': {'id': RUN, 'repository_id': REPOSITORY_ID,
                             'head_repository_id': REPOSITORY_ID,
                             'head_branch': 'main', 'head_sha': SOURCE}},
        'attempt': {'id': RUN, 'run_attempt': 1, 'head_sha': SOURCE, 'head_branch': 'main',
                    'repository': repository, 'head_repository': copy.deepcopy(repository),
                    'path': '.github/workflows/windows-migration-preview.yml',
                    'name': 'Independent migration Windows preview',
                    'run_started_at': '2026-10-06T17:40:00Z',
                    'status': 'in_progress', 'conclusion': None}}


class PerformanceMatrixWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (ROOT / '.github/workflows/performance-matrix-feedback.yml').read_text(encoding='utf-8')
        cls.data = yaml.load(cls.body, Loader=yaml.BaseLoader)
        cls.job = cls.data['jobs']['software-diagnostic']
        cls.steps = cls.job['steps']

    def step(self, identifier):
        return next(step for step in self.steps if step.get('id') == identifier)

    def test_one_separate_source_triggered_runner_without_cancel_or_dispatch(self):
        self.assertEqual(set(self.data['on']), {'push'})
        self.assertEqual(self.data['on']['push']['branches'], ['main'])
        self.assertEqual(set(self.data['on']['push']['paths']), {
            '.github/workflows/performance-matrix-feedback.yml', 'tools/performance_matrix.py',
            'tools/performance_matrix_driver.py', 'tools/test_performance_matrix.py',
            'tools/test_performance_matrix_workflow.py', 'tools/summarize_frame_performance.py',
            'tools/test_summarize_frame_performance.py', 'tools/exclusive_output.py'})
        self.assertEqual(self.data['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(self.data['concurrency'], {
            'group': 'performance-matrix-feedback-${{ github.ref }}', 'cancel-in-progress': 'false'})
        self.assertEqual(set(self.data['jobs']), {'software-diagnostic'})
        self.assertEqual(self.job['runs-on'], 'windows-latest')
        self.assertEqual(self.job['timeout-minutes'], '20')
        self.assertIn("github.run_attempt == 1", self.job['if'])
        self.assertNotIn('strategy', self.job)
        for forbidden in ('continue-on-error', 'workflow_dispatch', 'secrets.', 'cargo build',
                          'rustup', '--disable-validation', 'Start-Process', 'Set-ExecutionPolicy'):
            self.assertNotIn(forbidden, self.body)

    def test_distinct_source_checkouts_have_clean_bytes_and_no_credentials(self):
        checkouts = [step['with'] for step in self.steps if step.get('uses') == 'actions/checkout@v4']
        self.assertEqual(len(checkouts), 2)
        self.assertEqual([(item['path'], item['ref']) for item in checkouts],
                         [('verifier', '${{ github.sha }}'), ('package-source', SOURCE)])
        self.assertTrue(all(item['persist-credentials'] == 'false' for item in checkouts))
        self.assertTrue(all('/assets/' not in item['sparse-checkout'] for item in checkouts))
        self.assertEqual(self.data['env']['GIT_CONFIG_KEY_0'], 'core.autocrlf')
        self.assertEqual(self.data['env']['GIT_CONFIG_VALUE_0'], 'false')
        identity = self.step('identity')['run']
        self.assertIn("m.source_identity(Path('package-source'))", identity)
        self.assertIn("m.package_identity(Path('package/vector-range.exe'), source, 'dx12')", identity)
        self.assertIn("commit == os.environ['GITHUB_SHA']", identity)
        self.assertIn("'rustc_fingerprint': None", identity)
        self.assertIn("'acceptance_proven': False", identity)
        self.assertIn("path.read_bytes() == committed", identity)

    def test_provider_guard_and_digest_enforcement_precede_any_game_process(self):
        downloads = [step for step in self.steps if step.get('uses', '').startswith('actions/download-artifact@')]
        self.assertEqual(len(downloads), 1)
        download = downloads[0]
        self.assertEqual(download['uses'], 'actions/download-artifact@v8')
        self.assertEqual(download['with'], {
            'repository': 'RHS059/rust_duty', 'run-id': str(RUN), 'artifact-ids': str(ARTIFACT),
            'github-token': '${{ github.token }}', 'merge-multiple': 'true',
            'digest-mismatch': 'error', 'path': 'package'})
        guard = next(step for step in self.steps if 'python -m unittest' in step.get('run', ''))
        stages = [guard, self.step('provider'), download, self.step('identity'), self.step('smoke')]
        positions = [self.steps.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(self.step('provider')['with']['retries'], '0')

    def test_pilot_requires_successful_smoke_and_independent_analysis(self):
        plans = [step for step in self.steps if 'performance_matrix.py prepare' in step.get('run', '')]
        self.assertEqual(len(plans), 2)
        for plan, preset in zip(plans, ('--smoke', '--pilot')):
            self.assertIn(preset, plan['run'])
            for token in ('--repository package-source', '--renderer dx12',
                          '--warmup-seconds 10', '--sample-seconds 30'):
                self.assertIn(token, plan['run'])
        gate = "steps.smoke.outcome == 'success' && steps.smoke_analysis.outcome == 'success'"
        self.assertEqual(plans[1]['if'], gate)
        self.assertEqual(self.step('pilot')['if'], gate)
        self.assertIn('performance_matrix.py analyze evidence/smoke', self.step('smoke_analysis')['run'])
        executions = [step for step in self.steps if 'performance_matrix.py run ' in step.get('run', '')]
        self.assertEqual(executions, [self.step('smoke'), self.step('pilot')])
        for execution in executions:
            for token in ('--executable package/vector-range.exe', '--settings package/settings.cfg',
                          '--force-fallback --driver win32', '--execute', '$LASTEXITCODE -ne 0'):
                self.assertIn(token, execution['run'])
            self.assertNotIn('--graphics-settings', execution['run'])
        self.assertLess(self.steps.index(self.step('smoke_analysis')), self.steps.index(plans[1]))

    def test_failure_evidence_retains_raw_exports_but_not_package_bytes(self):
        finalizer = next(step for step in self.steps if 'CI-SUMMARY.json' in step.get('run', ''))
        uploads = [step for step in self.steps if step.get('uses', '').startswith('actions/upload-artifact@')]
        self.assertEqual(len(uploads), 1)
        upload = uploads[0]
        self.assertEqual(finalizer['if'], 'always()')
        self.assertEqual(upload['if'], 'always()')
        self.assertIn('m.analyze_matrix(folder)', finalizer['run'])
        self.assertIn("'state': 'not_run'", finalizer['run'])
        self.assertIn("'state': 'incomplete'", finalizer['run'])
        self.assertIn("'maximum_game_launches': 6", finalizer['run'])
        self.assertEqual(upload['with']['retention-days'], '7')
        self.assertEqual(upload['with']['include-hidden-files'], 'true')
        self.assertEqual(upload['with']['path'].splitlines(), [
            'evidence/**', '!evidence/**/*.exe', '!evidence/**/*.dll',
            '!evidence/**/*.zip', '!evidence/**/assets/**'])
        self.assertNotIn('package/', upload['with']['path'])

    def test_embedded_python_parses_as_written_for_powershell(self):
        for step in self.steps:
            script = step.get('run', '')
            if "@'\n" in script:
                python = script.split("@'\n", 1)[1].split("\n'@ | python -", 1)[0]
                compile(python, step['name'], 'exec')
                self.assertIn("if ($LASTEXITCODE -ne 0)", script)

    def run_provider_cases(self, cases):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required to exercise the actual provider guard')
        harness = r'''
        const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
        const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
        const fn = new AsyncFunction('github', 'context', 'core', 'require', input.script);
        (async () => {
          const outputs = [];
          for (const item of input.cases) {
            const calls = [], written = [];
            const github = {rest: {actions: {
              getArtifact: async args => {calls.push(['artifact', args]); return {data: item.artifact};},
              getWorkflowRunAttempt: async args => {calls.push(['attempt', args]); return {data: item.attempt};}
            }}};
            const fakeRequire = name => {
              if (name !== 'fs') throw Error('Unexpected dependency');
              return {mkdirSync: () => {}, writeFileSync: (path, value, options) => {
                if (options.flag !== 'wx') throw Error('Nonexclusive provider write');
                written.push({path, value: JSON.parse(value)});
              }};
            };
            try {
              await fn(github, item.context, {notice: () => {}}, fakeRequire);
              outputs.push({ok: true, calls, written});
            } catch (error) { outputs.push({ok: false, error: String(error), calls, written}); }
          }
          process.stdout.write(JSON.stringify(outputs));
        })().catch(error => { process.stderr.write(String(error)); process.exit(1); });
        '''
        result = subprocess.run([node, '-e', harness], input=json.dumps({
            'script': self.step('provider')['with']['script'], 'cases': cases}),
            capture_output=True, text=True, check=True, timeout=20)
        return json.loads(result.stdout)

    def test_valid_provider_retains_original_status_and_reads_only_exact_targets(self):
        original = provider()
        result, = self.run_provider_cases([original])
        self.assertTrue(result['ok'], result.get('error'))
        self.assertEqual(result['calls'], [
            ['artifact', {'owner': 'RHS059', 'repo': 'rust_duty', 'artifact_id': ARTIFACT}],
            ['attempt', {'owner': 'RHS059', 'repo': 'rust_duty', 'run_id': RUN, 'attempt_number': 1}]])
        self.assertEqual(result['written'], [{'path': 'evidence/PROVIDER.json',
                                            'value': {key: original[key] for key in ('artifact', 'attempt')}}])

    def test_metadata_substitutions_fail_closed_before_download(self):
        mutations = [
            ('context.repo.owner', 'other'), ('context.repo.repo', 'other'),
            ('attempt.id', RUN + 1), ('attempt.run_attempt', 2), ('attempt.head_sha', 'a' * 40),
            ('attempt.head_branch', 'other'), ('attempt.repository.id', 1),
            ('attempt.repository.full_name', 'other/rust_duty'), ('attempt.head_repository.id', 1),
            ('attempt.head_repository.full_name', 'other/rust_duty'),
            ('attempt.path', '.github/workflows/build.yml'), ('attempt.name', 'other'),
            ('artifact.id', ARTIFACT + 1), ('artifact.name', 'same-looking-package'),
            ('artifact.size_in_bytes', 113472626), ('artifact.size_in_bytes', True),
            ('artifact.digest', 'sha256:' + '0' * 64), ('artifact.expired', True),
            ('artifact.expired', 'false'), ('artifact.url', 'https://example.invalid/artifact'),
            ('artifact.archive_download_url', 'https://example.invalid/archive'),
            ('artifact.workflow_run.id', RUN + 1), ('artifact.workflow_run.repository_id', 1),
            ('artifact.workflow_run.head_repository_id', 1),
            ('artifact.workflow_run.head_sha', 'b' * 40), ('artifact.workflow_run.head_branch', 'other'),
            ('artifact.created_at', 'broken'), ('artifact.created_at', '2099-10-06T17:54:41Z'),
            ('artifact.created_at', '2026-10-06T17:39:00Z'),
            ('artifact.expires_at', '2000-01-01T00:00:00Z'), ('artifact.expires_at', 'broken'),
            ('attempt.run_started_at', 'broken'), ('attempt.run_started_at', '2099-01-01T00:00:00Z')]
        cases = []
        for dotted, value in mutations:
            item = provider()
            parent = item
            parts = dotted.split('.')
            for part in parts[:-1]:
                parent = parent[part]
            parent[parts[-1]] = value
            cases.append(item)
        for mutation, result in zip(mutations, self.run_provider_cases(cases)):
            with self.subTest(mutation=mutation):
                self.assertFalse(result['ok'], 'Untrusted provider was accepted')
                self.assertIn('Error:', result['error'])


if __name__ == '__main__':
    unittest.main()
