"""Bound the separate Halcyon source-contract job; no native game is executed."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class CpuEncodeDetailWorkflowTests(unittest.TestCase):
    def test_owned_branch_read_only_permissions_and_bounded_job(self):
        body = (ROOT / '.github/workflows/cpu-encode-detail.yml').read_text()
        workflow = yaml.load(body, Loader=yaml.BaseLoader)
        self.assertEqual(workflow['on']['push']['branches'], ['halcyon/cpu-encode-detail'])
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'false')
        job = workflow['jobs']['source-contracts']
        self.assertEqual(job['runs-on'], 'windows-latest')
        self.assertEqual(job['timeout-minutes'], '30')
        self.assertIn("github.ref == 'refs/heads/halcyon/cpu-encode-detail'", job['if'])
        checkout = job['steps'][0]['with']
        self.assertEqual(checkout['persist-credentials'], 'false')
        self.assertNotIn('/assets', checkout['sparse-checkout'])
        self.assertNotIn('uploaded_references', checkout['sparse-checkout'])
        self.assertIn('tools/**', workflow['on']['push']['paths'])
        self.assertIn('cargo test --locked --no-default-features --features wgpu-runtime --lib encode_detail', body)
        self.assertIn('test_summarize_cpu_encode_detail', body)
        self.assertIn('test_cpu_encode_detail_source', body)
        self.assertIn('rustfmt --edition 2021 --config skip_children=true $copy', body)
        self.assertIn('Tested source was not modified', body)
        self.assertIn('Copy-Item $file $copy', body)
        for forbidden in ('workflow_dispatch', 'pull_request:', 'continue-on-error',
                          'run_gpu_session_contract.py', 'actions/download-artifact', 'secrets.'):
            self.assertNotIn(forbidden, body)


if __name__ == '__main__':
    unittest.main()
