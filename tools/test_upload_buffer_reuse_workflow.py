"""Keep destination-reuse evidence separate from existing diagnostic fixtures."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class UploadBufferReuseWorkflowTests(unittest.TestCase):
    def test_branch_permissions_and_synthetic_fixture_scope(self):
        body = (ROOT / '.github/workflows/upload-buffer-reuse.yml').read_text()
        workflow = yaml.load(body, Loader=yaml.BaseLoader)
        self.assertEqual(workflow['on']['push']['branches'], ['halcyon/upload-buffer-reuse'])
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'false')
        job = workflow['jobs']['native-upload-reuse']
        self.assertEqual(job['runs-on'], 'windows-latest')
        self.assertEqual(job['timeout-minutes'], '30')
        self.assertEqual(job['if'], "github.repository == 'RHS059/rust_duty' && "
                         "github.ref == 'refs/heads/halcyon/upload-buffer-reuse'")
        checkout = job['steps'][0]['with']
        self.assertEqual(checkout['persist-credentials'], 'false')
        self.assertEqual(checkout['sparse-checkout-cone-mode'], 'false')
        paths = checkout['sparse-checkout'].splitlines()
        fixtures = {path for path in paths if path.startswith('/tests/')}
        self.assertEqual(fixtures, {'/tests/fixtures/triangle.vrm',
                                    '/tests/fixtures/two_bone_triangle.vrs'})
        self.assertNotIn('/assets/', paths)
        self.assertNotIn('/uploaded_references/', paths)
        self.assertEqual({path for path in paths if path.startswith('/.github/')},
                         {'/.github/workflows/upload-buffer-reuse.yml'})
        for forbidden in ('workflow_dispatch', 'pull_request:', 'continue-on-error',
                          'run_gpu_session_contract.py', 'finite_warp_probe',
                          'actions/download-artifact', 'secrets.', '--ignored'):
            self.assertNotIn(forbidden, body)

    def test_actual_native_suite_and_strict_readers_are_required(self):
        body = (ROOT / '.github/workflows/upload-buffer-reuse.yml').read_text()
        self.assertIn('cargo test --locked --no-default-features --features wgpu-runtime '
                      '--lib --no-run --message-format=json', body)
        self.assertIn('& $exe render::upload_reuse_tests --nocapture --test-threads=1', body)
        self.assertIn('Get-FileReceipt $exe', body)
        self.assertIn('cargo clippy --locked --no-default-features --features wgpu-runtime --lib --tests -- -D warnings', body)
        self.assertIn('Get-FileReceipt $pdb', body)
        self.assertIn('git ls-files -- src updater tools Cargo.toml Cargo.lock', body)
        self.assertIn('Test executable changed during native proof', body)
        self.assertIn('test result: ok. 3 passed; 0 failed; 0 ignored;', body)
        self.assertIn("if ($LASTEXITCODE -ne 0) { throw 'DX12/WARP", body)
        for suite in ('render::upload_cache::tests', 'render::arena::tests',
                      'render::plan::tests', 'render::frame::tests', 'encode_detail',
                      'test_summarize_cpu_encode_detail', 'test_summarize_cpu_substages',
                      'test_summarize_frame_performance', 'test_cpu_encode_detail_source',
                      'test_upload_buffer_reuse_workflow'):
            self.assertIn(suite, body)
        self.assertIn('git rev-parse HEAD', body)
        self.assertIn('Copy-Item $file $copy', body)
        self.assertIn('rustfmt --edition 2021 --config skip_children=true $copy', body)
        self.assertIn('Tested source was not modified', body)

    def test_test_only_cache_constructor_matches_its_windows_callers(self):
        cache = (ROOT / 'src/render/upload_cache.rs').read_text()
        self.assertRegex(cache, r'#\[cfg\(all\(test, target_os = "windows"\)\)\]\s+'
                         r'pub fn for_test\(')
        native = (ROOT / 'src/render/upload_reuse_tests.rs').read_text()
        self.assertIn('#![cfg(target_os = "windows")]', native)
        self.assertIn('UploadCache::for_test(', native)

    def test_native_queue_proof_defers_all_readback_until_after_submissions(self):
        source = (ROOT / 'src/render/upload_reuse_tests.rs').read_text()
        self.assertIn('#![cfg(target_os = "windows")]', source)
        self.assertEqual(source.count('#[test]'), 3)
        self.assertNotIn('#[ignore', source)
        proof = source.split('fn changed_frames_without_cpu_waits_match_fresh_immutable_uploads()', 1)[1]
        proof = proof.split('\n#[test]', 1)[0]
        loop = proof.split('for (frame, counts)', 1)[1].split('let pixels = read_after_submissions', 1)[0]
        for forbidden in ('.poll(', '.map_async(', '.finish(&', 'block_on('):
            self.assertNotIn(forbidden, loop)
        self.assertIn('fixture.gpu.queue.submit([encoder.finish()]);', loop)
        self.assertIn('cache.submitted();', loop)
        compact_loop = ''.join(loop.split())
        self.assertIn('.upload_geometry(&fixture.gpu.device,&batch.arena)', compact_loop)
        compact_proof = ''.join(proof.split())
        self.assertIn('assert_eq!(current,previous', compact_loop)
        self.assertIn('assert_ne!(current[0].0,previous[0].0', compact_loop)
        self.assertIn('assert_eq!(pair[0],pair[1]', compact_proof)
        self.assertIn('assert_eq!(pair[2],pair[3]', compact_proof)


if __name__ == '__main__':
    unittest.main()
