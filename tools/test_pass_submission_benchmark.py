import copy
import json
from pathlib import Path
import tempfile
import unittest

import run_pass_submission_benchmark as benchmark


class Guards(unittest.TestCase):
    def test_candidate_rejects_unrelated_changes_missing_and_extra_inputs(self):
        baseline = {'src/render/frame.rs': b'frame', 'src/render/plan.rs': b'plan', 'Cargo.lock': b'lock'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in baseline.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data + b'-candidate' if name in benchmark.ALLOWED else data)
            result = benchmark.candidate_sources(baseline, root)
            self.assertEqual(set(result), set(baseline))
            (root / 'Cargo.lock').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'outside'):
                benchmark.candidate_sources(baseline, root)
            (root / 'Cargo.lock').write_bytes(b'lock')
            (root / 'src/extra.rs').write_text('unbound', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'extra'):
                benchmark.candidate_sources(baseline, root)
            (root / 'src/extra.rs').unlink()
            (root / 'src/render/frame.rs').write_bytes(b'frame')
            with self.assertRaisesRegex(ValueError, 'both'):
                benchmark.candidate_sources(baseline, root)

    def test_manifest_and_identical_harness_bind_every_materialized_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = {'src/render/frame.rs': b'baseline'}
            left = benchmark.materialize(root / 'left', sources, b'identical harness')
            right = benchmark.materialize(root / 'right', sources, b'identical harness')
            self.assertEqual(left, right)
            (root / 'right' / benchmark.HARNESS).write_bytes(b'tampered')
            self.assertNotEqual(left, benchmark.source_manifest(root / 'right'))

    def test_shader_compiler_must_come_from_native_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'native.log'
            log.write_text('renderer dx12_shader_compiler=Fxc\n', encoding='utf-8')
            benchmark.verify_shader_compiler(log)
            for invalid in ('', 'renderer dx12_shader_compiler=Dxc\n', 'requested Fxc'):
                log.write_text(invalid, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'initialization'):
                    benchmark.verify_shader_compiler(log)

    def test_actual_devices_require_cpu_identity_and_exact_pair_equality(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'native.log'
            evidence = dict(device_type='Cpu', vendor_id=5140, device_id=140,
                            driver='', driver_info='', present_mode=None, force_fallback_requested=True)
            log.write_text('renderer dx12_shader_compiler=Fxc\nrenderer device_evidence=' + json.dumps(evidence) + '\n')
            parsed = benchmark.device_evidence(log)
            self.assertEqual(benchmark.require_same_devices([parsed, parsed]), evidence)
            changed = {**parsed, 'driver_info': 'different'}
            with self.assertRaisesRegex(ValueError, 'differs'):
                benchmark.require_same_devices([parsed, changed])
            for key, value in [('device_type', 'DiscreteGpu'), ('force_fallback_requested', False),
                               ('vendor_id', True), ('present_mode', 'Fifo')]:
                broken = {**evidence, key: value}
                log.write_text('renderer dx12_shader_compiler=Fxc\nrenderer device_evidence=' + json.dumps(broken) + '\n')
                with self.assertRaises(ValueError):
                    benchmark.device_evidence(log)

    def test_fixed_validator_runs_in_retained_verifier_and_propagates_failure(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tools').mkdir()
            validator = root / 'tools/run_renderer_contract.py'
            validator.write_text('def validate_outputs(path):\n    raise ValueError("original fixed expectation failed")\n')
            log = root / 'fixed.log'
            with self.assertRaisesRegex(ValueError, 'process exited'):
                benchmark.fixed_validation(root / 'captures', root, log, os.environ.copy())
            self.assertIn('original fixed expectation failed', log.read_text())

    def report(self):
        return dict(schema_version=1, status='passed', fixture='pass-submission-synthetic-305-v1',
                    source_receipt_sha256='source', platform='windows', backend='Dx12', requested='dx12',
                    adapter='Microsoft Basic Render Driver', force_fallback_adapter=True,
                    width=320, height=180, prepared_draw_count=305, nontext_draw_count=135,
                    glyph_draw_count=170, warmup_frames=2, timed_frames=4, timed_capture_count=0,
                    presentation=False, gpu_timestamp_ms=None, whole_submit_ms=[1., 2., 3., 4.],
                    pre_control_submit_drain_png_ms=5., final_control_submit_drain_png_ms=6.,
                    bounded_batch_with_final_control_ms=17.)

    def test_native_identity_scope_finite_timings_and_total_are_required(self):
        baseline = self.report()
        benchmark.validate_report(baseline, 'source')
        for field, value in [('source_receipt_sha256', None), ('platform', 'linux'),
                             ('backend', 'Vulkan'), ('adapter', 'NVIDIA RTX'),
                             ('force_fallback_adapter', False), ('force_fallback_adapter', 1),
                             ('timed_capture_count', 1), ('prepared_draw_count', 324),
                             ('whole_submit_ms', [1., 2.]), ('whole_submit_ms', [1., 2., 3., float('nan')]),
                             ('final_control_submit_drain_png_ms', -1.),
                             ('bounded_batch_with_final_control_ms', 15.), ('presentation', True)]:
            broken = copy.deepcopy(baseline)
            broken[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                benchmark.validate_report(broken, 'source')

    def test_exact_rgba_rejects_one_bit_flip_even_with_valid_png(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = root / 'a.png', root / 'b.png'
            image = Image.new('RGBA', (320, 180), (1, 2, 3, 255))
            image.putpixel((20, 30), (4, 5, 6, 255))
            image.save(a)
            image.save(b)
            receipt = benchmark.exact_pixels([a, b])
            self.assertEqual(receipt[str(a)]['rgba_sha256'], receipt[str(b)]['rgba_sha256'])
            image.putpixel((20, 30), (4, 5, 7, 255))
            image.save(b)
            with self.assertRaisesRegex(ValueError, 'zero tolerance'):
                benchmark.exact_pixels([a, b])
            image = Image.new('RGBA', (320, 180), (1, 2, 3, 255))
            image.save(b)
            with self.assertRaisesRegex(ValueError, 'uniform'):
                benchmark.exact_pixels([a, b])

    def test_process_failure_and_timeout_retain_logs(self):
        import os
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'process.log'
            with self.assertRaisesRegex(ValueError, 'exited 7'):
                benchmark.run_logged([sys.executable, '-c', 'print("failure evidence"); exit(7)'],
                                     root, log, os.environ.copy(), 5)
            self.assertIn('failure evidence', log.read_text())
            self.assertEqual(json.loads(log.with_suffix('.command.json').read_text())['returncode'], 7)
            with self.assertRaises(subprocess.TimeoutExpired):
                benchmark.run_logged([sys.executable, '-c', 'import time; time.sleep(5)'],
                                     root, log, os.environ.copy(), 0.05)
            self.assertTrue(json.loads(log.with_suffix('.command.json').read_text())['timed_out'])

    def test_contract_closed_set_and_zero_tolerance_keep_all_failure_checks(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label in ('baseline', 'candidate'):
                output = root / label
                output.mkdir()
                report = dict(schema_version=1, status='passed', native_execution=True,
                              requested='dx12', backend='Dx12', adapter='Microsoft Basic Render Driver',
                              force_fallback_adapter=True, platform='windows',
                              captures=[{'filename': name} for name in sorted(benchmark.CONTRACT_NAMES)],
                              expected_failures=[{'expected_error': value, 'actual_error': value} for value in
                                                 ['create capture directory', 'write capture',
                                                  'capture path must not be empty', 'non-finite']])
                benchmark.write_json(output / 'renderer-contract-report.json', report)
                for name in benchmark.CONTRACT_NAMES:
                    size = {'readback-width-65.png': (65, 49), 'text-100-percent.png': (64, 48),
                            'text-200-percent.png': (128, 96), 'after-errors.png': (16, 16)}.get(name, (96, 64))
                    Image.new('RGBA', size, (15, 25, 30, 120)).save(output / name)
            baseline, candidate = root / 'baseline', root / 'candidate'
            self.assertEqual(len(benchmark.contract_pixels(baseline, candidate)), 21)
            extra = candidate / 'extra.png'
            Image.new('RGBA', (1, 1)).save(extra)
            with self.assertRaisesRegex(ValueError, 'closed'):
                benchmark.contract_pixels(baseline, candidate)
            extra.unlink()
            changed = candidate / 'alpha-target.png'
            with Image.open(changed) as image:
                modified = image.copy()
            modified.putpixel((0, 0), (15, 25, 31, 120))
            modified.save(changed)
            with self.assertRaisesRegex(ValueError, 'zero tolerance'):
                benchmark.contract_pixels(baseline, candidate)
            modified.putpixel((0, 0), (15, 25, 30, 120))
            modified.save(changed)
            report['expected_failures'].pop()
            benchmark.write_json(candidate / 'renderer-contract-report.json', report)
            with self.assertRaisesRegex(ValueError, 'failure/recovery'):
                benchmark.contract_pixels(baseline, candidate)


if __name__ == '__main__':
    unittest.main()
