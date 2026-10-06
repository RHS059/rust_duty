"""The bounded comparison remains separate from full game verification."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class PassSubmissionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (ROOT / '.github/workflows/pass-submission-feedback.yml').read_text()
        cls.workflow = yaml.load(cls.body, Loader=yaml.BaseLoader)
        cls.steps = cls.workflow['jobs']['compare']['steps']

    def test_only_main_scoped_changes_trigger_read_only_non_canceling_job(self):
        self.assertEqual(set(self.workflow['on']), {'push'})
        push = self.workflow['on']['push']
        self.assertEqual(push['branches'], ['main'])
        self.assertEqual(set(push['paths']), {
            '.github/workflows/pass-submission-feedback.yml',
            'examples/pass_submission_benchmark.rs', 'tools/run_pass_submission_benchmark.py',
            'tools/test_pass_submission_benchmark.py', 'tools/test_pass_submission_workflow.py',
            'src/render/frame.rs', 'src/render/plan.rs'})
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(self.workflow['concurrency'], {
            'group': 'pass-submission-feedback-${{ github.ref }}', 'cancel-in-progress': 'false'})
        self.assertEqual(set(self.workflow['jobs']), {'compare'})
        self.assertEqual(self.workflow['jobs']['compare']['runs-on'], 'windows-latest')

    def test_pinned_sources_and_guards_precede_sole_native_caller(self):
        find = lambda text: next(s for s in self.steps if text in s.get('run', ''))
        fetch = find('git fetch')
        for sha in ('17023450076b668c279539e0e450b8cb58a7c1a2',
                    '5abf2bca825a252fb7ad6665c444c89861ee8ef9'):
            self.assertIn('--no-write-fetch-head --no-tags --depth=1 origin ' + sha, fetch['run'])
        guards = find('python -m unittest')
        compiler = find('rustup toolchain install')
        native = find('python tools/run_pass_submission_benchmark.py')
        indexes = [self.steps.index(s) for s in (fetch, guards, compiler, native)]
        self.assertEqual(indexes, sorted(indexes))
        self.assertIn('1.99.0-x86_64-pc-windows-msvc --profile minimal', compiler['run'])
        self.assertIn('--candidate-root . --output-dir evidence/pass-submission', native['run'])
        self.assertEqual(native['timeout-minutes'], '48')
        checkout = self.steps[0]['with']
        self.assertEqual(checkout['persist-credentials'], 'false')
        self.assertIn('/.github/workflows/pass-submission-feedback.yml', checkout['sparse-checkout'].splitlines())
        self.assertNotIn('/assets/', checkout['sparse-checkout'])
        for value in ('cargo build', '--bin vector-range', 'finite-warp-profile.yml',
                      'continue-on-error', 'secrets.', 'workflow_dispatch'):
            self.assertNotIn(value, self.body)

    def test_failure_evidence_includes_exact_pixels_and_sources_without_build_cache(self):
        uploads = [s for s in self.steps if s.get('uses') == 'actions/upload-artifact@v4']
        self.assertEqual(len(uploads), 2)
        self.assertTrue(all(s['if'] == 'always()' for s in uploads))
        self.assertTrue(all(s['with']['include-hidden-files'] == 'true' for s in uploads))
        full, review = (s['with']['path'] for s in uploads)
        self.assertIn('!evidence/pass-submission/target/**', full)
        self.assertIn('!evidence/pass-submission/temp/**', full)
        for suffix in ('*.json', '*.log', '*-source/**', 'verifier/**',
                       '*-renderer-contract/**', 'pair-*/**'):
            self.assertIn('evidence/pass-submission/' + suffix, review)
        for excluded in ('*.exe', 'target/', 'temp/', 'evidence/pass-submission/**\n'):
            self.assertNotIn(excluded, review)


if __name__ == '__main__':
    unittest.main()
