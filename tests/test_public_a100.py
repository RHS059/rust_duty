"""Offline A100 host/controller safety tests. Never allocate/run a GPU or game."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import a100_public_build as b
import prepare_public_a100 as entry
import run_public_a100_matrix as c
PORTABLE = Path(__file__).resolve().parent / 'fixtures/public-matrix'


class A100Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='a100-proposal-test-')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def gpu(self, text=None, code=0):
        text = '0, NVIDIA A100-SXM4-40GB, GPU-fixture, 0x20B010DE, 570.195.03, 40536\n' if text is None else text
        return b.a100_gate(run=lambda *a, **k: subprocess.CompletedProcess([], code, text, ''), which=lambda *a, **k: '/usr/bin/nvidia-smi')

    def test_a100_inventory_is_exact_and_single(self):
        self.assertEqual(self.gpu()['host_kind'], b.A100_NAME)
        for text in ('', '0, NVIDIA A100 80GB PCIe, GPU-fixture, 0x20B010DE, 570, 81920',
                     '0, NVIDIA A100-SXM4-40GB, GPU-fixture, 0x20B08086, 570, 40536',
                     '0, NVIDIA A100-SXM4-40GB, GPU-fixture, 0x20B010DE, 570, 81920',
                     '0, NVIDIA A100-SXM4-40GB, GPU-fixture, 0x20B010DE, 570, 40536\n1, NVIDIA A100-SXM4-40GB, GPU-other, 0x20B010DE, 570, 40536'):
            with self.subTest(text=text), self.assertRaises(ValueError): self.gpu(text)
        with self.assertRaises(ValueError): self.gpu(code=1)
        with self.assertRaises(ValueError): b.a100_gate(which=lambda *a, **k: None)

    def test_a100_env_never_hides_gpu_or_inherits_credentials(self):
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'secret', 'LD_PRELOAD': 'bad', 'CUDA_VISIBLE_DEVICES': '', 'NVIDIA_VISIBLE_DEVICES': 'void'}):
            env = b.public_env(self.root)
        for key in ('GITHUB_TOKEN', 'LD_PRELOAD', 'CUDA_VISIBLE_DEVICES', 'NVIDIA_VISIBLE_DEVICES'):
            self.assertNotIn(key, env)
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')

    def test_frozen_cpu_is_unchanged_and_still_rejects_gpu(self):
        self.assertEqual(b.sha(TOOLS / 'prepare_linux_actual_game.py'), b.CPU_HELPERS_SHA)
        with self.assertRaises(ValueError):
            b.neutral.gpu_gate(run=lambda *a, **k: subprocess.CompletedProcess([], 0, '0, NVIDIA A100, GPU-fixture', ''),
                               which=lambda *a, **k: '/usr/bin/nvidia-smi', dev_root=self.root)

    def test_dry_run_performs_no_gpu_or_build_work(self):
        with mock.patch.object(b, 'a100_gate') as gate, mock.patch.object(b, 'prepare_a100') as prepare, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(entry.main(['--dry-run']), 0)
        gate.assert_not_called(); prepare.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())['runtime_executed'])

    def test_execute_and_observed_deadline_are_required_before_setup(self):
        for args in ([], ['--execute', '--support-commit', 'a' * 40]):
            with self.subTest(args=args), mock.patch.object(b, 'a100_gate') as gate, self.assertRaises(ValueError):
                entry.main(args + ['--runs-root', str(self.root / 'uncreated')])
            gate.assert_not_called()
            self.assertFalse((self.root / 'uncreated').exists())

    def test_budget_uses_observed_allocation_and_reserves_export(self):
        now = time.time()
        budget = c.Budget(now - 870.439, now + 329.561, now=now)
        self.assertLessEqual(budget.remaining(), 239.561)
        budget.require_time(150)
        expanded = c.Budget(now - 870.439, now + 929.561, now=now)
        self.assertLessEqual(expanded.remaining(), 839.561)
        expanded.require_time(150 + 480)
        with self.assertRaisesRegex(ValueError, 'Insufficient'): budget.require_time(480)
        for start, end, reserve in ((now, now + 1801, 90), (now + 1, now + 100, 90), (now - 1801, now - 1, 90), (now, now + 500, 89), (now, float('nan'), 90)):
            with self.subTest(start=start, end=end, reserve=reserve), self.assertRaises(ValueError): c.Budget(start, end, reserve, now)

    def test_clock_rollback_cannot_increase_monotonic_budget(self):
        now = time.time()
        budget = c.Budget(now, now + 1800, now=now)
        with mock.patch.object(c.time, 'time', return_value=now - 10000):
            self.assertLessEqual(budget.remaining(), 1710)

    def test_a100_runner_kills_owned_nested_process_and_preserves_logs(self):
        runner = b.Runner(self.root, b.public_env(self.root), inactivity=180)
        code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)'],start_new_session=True); print(p.pid,flush=True); time.sleep(300)"
        with self.assertRaises(TimeoutError): runner.run('deadline', [sys.executable, '-I', '-c', code], timeout=.2)
        pid = int((self.root / 'logs/deadline.log').read_text().strip())
        status = Path('/proc') / str(pid) / 'stat'
        if status.exists(): self.assertEqual(status.read_text().rsplit(') ', 1)[1].split()[0], 'Z')
        self.assertEqual(json.loads((self.root / 'PHASES.json').read_text())[0]['status'], 'failed')

    def test_regeneration_rejected_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'public-release'):
            b.prepare_a100(mock.Mock(asset_mode='regenerate'), self.root, self.gpu())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_runtime_receipt_does_not_abort_export_finalization(self):
        path = self.root / 'RESULT.json'
        path.write_text('{"status":')
        result = {'status': 'failed', 'surface_and_record_proven': False, 'pilot_proven': False}
        entry.merge_runtime_result(result, path)
        self.assertIn('runtime_receipt_error', result)
        self.assertFalse(result['surface_and_record_proven'])
        b.save(path, {'status': 'partial', 'actual_surface_record_passed': True, 'pilot_passed': False, 'pilot_skip_reason': 'budget'})
        entry.merge_runtime_result(result, path)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['surface_and_record_proven'])

    def test_early_entry_failure_still_reminds_disconnect(self):
        with mock.patch.object(entry, 'main', side_effect=ValueError('wrong host')), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(entry.cli(['--execute']), 1)
        self.assertIn('DISCONNECT_AND_DELETE_COLAB_RUNTIME_NOW', out.getvalue())
        with mock.patch.object(c, 'run', side_effect=ValueError('wrong receipt')), mock.patch.object(c, 'parser') as parser, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(c.cli([]), 1)
        self.assertIn('DISCONNECT_COLAB_RUNTIME_NOW', out.getvalue())

    def mocked_smoke(self, fail_postflight=False):
        now = time.time()
        args = mock.Mock(allocation_start_unix=now - 880, deadline_unix=now + 320,
                         export_reserve_seconds=90, build_root=self.root / 'build', output=self.root / 'runtime',
                         expectations_sha256='a' * 64, smoke_only=False, install_system_deps=False)
        inventory = self.gpu()
        x = {'source_witness_sha256': 'b' * 64}
        host = {'a100_postflight': inventory}
        matrix = mock.Mock()
        verified = (x, host, matrix)
        values = [verified, ValueError('postflight changed')] if fail_postflight else [verified, verified]
        original_is_file, original_exists = Path.is_file, Path.exists
        def is_file(path):
            return True if str(path) == '/usr/lib64-nvidia/libEGL_nvidia.so.0' else original_is_file(path)
        def exists(path):
            return False if str(path) in ('/tmp/.X97-lock', '/tmp/.X11-unix/X97') else original_exists(path)
        child = mock.Mock(pid=123456)
        child.poll.return_value = None
        runner = mock.Mock(); runner.run.return_value = ''
        with mock.patch.object(c, 'verify_fresh', side_effect=values) as verify, mock.patch.object(b, 'a100_gate', return_value=inventory), \
             mock.patch.object(b, 'Runner', return_value=runner), mock.patch.object(c.shutil, 'which', return_value='/usr/bin/tool'), \
             mock.patch.object(Path, 'is_file', is_file), mock.patch.object(Path, 'exists', exists), \
             mock.patch.object(c.subprocess, 'Popen', return_value=child), mock.patch.object(c.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '4096 2304', '')), \
             mock.patch.object(b, 'terminate_group'), mock.patch.object(c, 'completed_summary', return_value={'fixture': 'validated'}):
            c.run(args)
        self.assertEqual(verify.call_count, 2)
        names = [call.args[0] for call in runner.run.call_args_list]
        self.assertIn('smoke', names); self.assertNotIn('pilot', names)
        return c.read(args.output / 'RESULT.json')

    def test_budget_skipped_pilot_still_requires_postflight(self):
        result = self.mocked_smoke()
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['actual_surface_record_passed'])
        self.assertTrue(result['postflight_passed'])
        self.assertFalse(result['pilot_passed'])

    def test_postflight_failure_clears_proven_stage_flags(self):
        result = self.mocked_smoke(fail_postflight=True)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['actual_surface_record_passed'])
        self.assertFalse(result['pilot_passed'])
        self.assertFalse(result['postflight_passed'])

    def fixture(self):
        root = self.root / 'build'
        root.mkdir()
        for name in ('matrix-tools', 'source-witness', 'evidence', 'package'):(root / name).mkdir()
        for name in b.MATRIX_FILES: shutil.copyfile(PORTABLE / 'tools' / name, root / 'matrix-tools' / name)
        shutil.copytree(PORTABLE / 'source-witness', root / 'source-witness', dirs_exist_ok=True)
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(root / 'matrix-tools'))
        spec = importlib.util.spec_from_file_location('test_fresh_matrix', root / 'matrix-tools/performance_matrix.py')
        matrix = importlib.util.module_from_spec(spec); spec.loader.exec_module(matrix)
        witness_sha = b.sha(root / 'source-witness/SOURCE_WITNESS.json')
        source = matrix.artifact_source(root / 'source-witness', witness_sha)
        package = root / 'package'
        (package / 'vector-range').write_bytes(b'OFFLINE FIXTURE ONLY')
        (package / 'ui').mkdir(); (package / 'ui/theme.css').write_text('source49 test fixture')
        (package / 'settings.cfg').write_text('test fixture settings')
        assets = {'schema': 'rust-duty-public-release-assets/v1', 'status': 'passed',
                  'origin': {'url': b.RELEASE_URL, 'sha256': b.RELEASE_SHA, 'bytes': b.RELEASE_BYTES},
                  'new_parity_measured': False, 'release_executable_used': False, 'freshly_generated': False,
                  'comparison_limits': '8 of 12 reload companions differ',
                  'source_contract_bindings': {name: {} for name in ('locomotion', 'walk', 'ads', 'directional', 'jump', 'reload')}}
        b.save(root / 'evidence/authored-assets.json', assets)
        files = {str(i): {'sha256': 'a' * 64, 'bytes': 1} for i in range(110)}
        for name in ('source-before.json', 'source-after.json'): b.save(root / 'evidence' / name, files)
        b.save(root / 'evidence/source-identity.json', {'production_files': files, 'source_commit': b.SOURCE_COMMIT, 'production_files_byte_identical_to_commit': True})
        overlay = {'patch_sha256': b.PATCH_SHA, 'official_crate_sha256': b.CRATE_SHA, 'egl_patched_sha256': b.neutral.EGL_AFTER,
                   'validation_flags_changed': False, 'game_sources_changed': False}
        b.save(root / 'evidence/dependency-overlay.json', overlay)
        receipt = {'schema': 'rust-duty-actual-game-harness/v1', 'kind': 'linux_native_gl_actual_game_harness', 'source_commit': b.SOURCE_COMMIT,
                   'source_sha256': b.HARNESS_SHA, 'executable_sha256': b.sha(package / 'vector-range'), 'production_modules_byte_identical': True,
                   'authored_assets': {'receipt_sha256': b.sha(root / 'evidence/authored-assets.json')}, 'dependency_overlay': overlay}
        b.save(package / 'ACTUAL_GAME_HARNESS_RECEIPT.json', receipt)
        build = b.neutral.build_identity(root / 'source-witness', package / 'vector-range', '0.1.11', 'local.fixture', '0.1.11+build.local.fixture', package / 'ACTUAL_GAME_HARNESS_RECEIPT.json')
        b.save(package / 'BUILD_IDENTITY.json', build)
        identity = matrix.package_identity(package / 'vector-range', source, 'gl-harness')
        b.save(root / 'evidence/matrix-package-identity.json', identity)
        host = {'host_kind': b.A100_NAME, 'source_commit': b.SOURCE_COMMIT, 'asset_mode': 'public-release', 'production_files_preserved': True,
                'runtime_executed': False, 'a100_preflight': self.gpu(), 'a100_postflight': self.gpu()}
        b.save(root / 'PREPARATION_INPUTS.json', host)
        b.save(root / 'expected-a100.json', {'schema': 'rust-duty-graphics-device/v1', 'adapter': b.ADAPTER})
        for kind, warm, sample in (('smoke', 10, 10), ('pilot', 15, 30)):
            plan = matrix.make_plan(source, 'gl-harness', 1, warm, sample, kind == 'smoke', kind == 'pilot', {'mode': 'artifact-witness', 'witness_sha256': witness_sha})
            b.save(root / (kind + '-plan.json'), plan)
        b.save(root / 'PACKAGE_FILES.json', b.tree_manifest(package))
        x = {'schema': 'rust-duty-fresh-linux-matrix-inputs/v1', 'source_commit': b.SOURCE_COMMIT, 'asset_mode': 'public-release', 'host_kind': b.A100_NAME,
             'runtime_executed': False, 'source_witness_sha256': witness_sha, 'matrix_tools': b.MATRIX_FILES, 'preparation_tools': b.preparation_tool_hashes(),
             'evidence_files': b.tree_manifest(root / 'evidence'), 'plans': {kind: b.sha(root / (kind + '-plan.json')) for kind in ('smoke', 'pilot')},
             'adjacent_files_digest': identity['adjacent_files_digest']}
        for key, path in (('package_manifest_sha256', 'PACKAGE_FILES.json'), ('build_identity_sha256', 'package/BUILD_IDENTITY.json'),
                          ('harness_receipt_sha256', 'package/ACTUAL_GAME_HARNESS_RECEIPT.json'), ('executable_sha256', 'package/vector-range'),
                          ('preparation_inputs_sha256', 'PREPARATION_INPUTS.json'), ('expected_adapter_sha256', 'expected-a100.json')): x[key] = b.sha(root / path)
        b.save(root / 'NEW_EXPECTATIONS.json', x)
        return root, x

    def test_fresh_offline_contract_validates_without_graphics(self):
        root, x = self.fixture()
        with mock.patch.object(b, 'a100_gate') as gate:
            verified, host, matrix = c.verify_fresh(root, b.sha(root / 'NEW_EXPECTATIONS.json'))
        gate.assert_not_called(); self.assertEqual(verified, x)

    def test_old_or_changed_expectations_rejected_before_graphics(self):
        root, x = self.fixture()
        with self.assertRaisesRegex(ValueError, 'expectations SHA'): c.verify_fresh(root, '0' * 64)
        x['executable_sha256'] = 'bff0863adde5752ea2eb870e5ec65105d5120772edd540efcede786c8a691e59'
        b.save(root / 'NEW_EXPECTATIONS.json', x)
        with self.assertRaisesRegex(ValueError, 'artifact pin'): c.verify_fresh(root, b.sha(root / 'NEW_EXPECTATIONS.json'))

    def test_matrix_tool_drift_rejected(self):
        root, x = self.fixture()
        with (root / 'matrix-tools/performance_matrix.py').open('a') as stream: stream.write('\n# changed\n')
        with self.assertRaisesRegex(ValueError, 'Matrix tools'): c.verify_fresh(root, b.sha(root / 'NEW_EXPECTATIONS.json'))

    def test_package_extra_file_rejected(self):
        root, x = self.fixture(); (root / 'package/extra').write_text('bad')
        with self.assertRaisesRegex(ValueError, 'Package inventory'): c.verify_fresh(root, b.sha(root / 'NEW_EXPECTATIONS.json'))

    def test_plan_change_requires_explicit_new_expectations(self):
        root, x = self.fixture()
        plan = c.read(root / 'smoke-plan.json'); plan['sample_seconds'] = 45; b.save(root / 'smoke-plan.json', plan)
        with self.assertRaisesRegex(ValueError, 'plan pin'): c.verify_fresh(root, b.sha(root / 'NEW_EXPECTATIONS.json'))
        x['plans']['smoke'] = b.sha(root / 'smoke-plan.json'); b.save(root / 'NEW_EXPECTATIONS.json', x)
        with self.assertRaisesRegex(ValueError, 'bounded smoke'): c.verify_fresh(root, b.sha(root / 'NEW_EXPECTATIONS.json'))

    def test_summary_requires_record_completion_and_actual_gpu(self):
        matrix = mock.Mock()
        matrix.BACKENDS = {'gl-harness': 'Gl'}
        matrix.analyze_matrix.return_value = {'state': 'incomplete', 'failures': [{'error': 'no CSV'}], 'runs': []}
        with self.assertRaisesRegex(ValueError, 'evidence incomplete'): c.completed_summary(matrix, self.root, 1)
        summary = {'state': 'complete', 'failures': [], 'runs': [{'runtime_observed': {'actual_backend': 'vulkan', 'actual_adapter': {'actual_fingerprint': b.ADAPTER}}, 'gpu_frame_duration_ns': None}]}
        matrix.analyze_matrix.return_value = summary
        with self.assertRaisesRegex(ValueError, 'Observed GL'): c.completed_summary(matrix, self.root, 1)
        summary['runs'][0]['runtime_observed']['actual_backend'] = 'Gl'
        b.save(self.root / 'SUMMARY.json', summary)
        self.assertEqual(c.completed_summary(matrix, self.root, 1), summary)


if __name__ == '__main__': unittest.main()
