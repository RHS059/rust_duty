"""Synthetic evidence/schema checks only; never GPU or frame-rate measurements."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import summarize_gpu_timing as gpu
from test_summarize_frame_performance import with_cpu_stages


def fixture():
    report = with_cpu_stages()
    report['identity']['runtime_observed']['actual_adapter'].update(
        gpu_timestamps_requested=True, gpu_timestamp_features_enabled=True)
    data = json.dumps(report).encode()
    digest = hashlib.sha256(data).hexdigest()
    sidecar = {'schema': gpu.SCHEMA, 'measurement': gpu.MEASUREMENT, 'scope': gpu.SCOPE,
               'frame_report_sha256': digest, 'accounting_state': 'complete', 'error': None,
               'session': 3, 'limits': {'max_attempts': report['limits']['max_records'], 'ring_slots': 4},
               'availability': {'state': 'available', 'timestamp_period_ns': 2.0},
               'feature_negotiation': {'adapter_supports_required_features': True, 'device_features_enabled': True},
               'samples': [{'session': 3, 'attempt': 0, 'record_index': 1, 'status': 'measured',
                            'start_ticks': 10, 'end_ticks': 20, 'timestamp_period_ns': 2.0, 'elapsed_ns': 20.0}]}
    return report, sidecar, data, digest


def unavailable(sidecar, status):
    sidecar['samples'][0].update(status=status, **dict.fromkeys(gpu.NUMERIC))


class GpuTimingTests(unittest.TestCase):
    def test_exact_binding_and_measurement_leave_primary_unchanged(self):
        report, sidecar, _, digest = fixture()
        before = copy.deepcopy(report)
        result = gpu.summarize(sidecar, report, digest)
        self.assertEqual(result['measured_eligible_count'], 1)
        self.assertEqual(result['p95_ns'], 20.0)
        self.assertNotIn('fps', result)
        self.assertEqual(before, report)

    def test_zero_duration_is_real_only_when_both_ticks_are_present(self):
        report, sidecar, _, digest = fixture()
        sidecar['samples'][0].update(end_ticks=10, elapsed_ns=0.0)
        self.assertEqual(gpu.summarize(sidecar, report, digest)['p50_ns'], 0.0)
        unavailable(sidecar, 'pending_at_stop')
        sidecar['samples'][0]['elapsed_ns'] = 0
        with self.assertRaises(ValueError):
            gpu.validate(sidecar, report, digest)

    def test_missing_statuses_never_enter_measured_percentiles(self):
        for status in gpu.UNAVAILABLE - {'disabled', 'device_features_not_enabled', 'invalid_timestamp_period'}:
            report, sidecar, _, digest = fixture()
            unavailable(sidecar, status)
            with self.subTest(status=status):
                result = gpu.summarize(sidecar, report, digest)
                self.assertIsNone(result['p99_ns'])
                self.assertEqual(result['unavailable_eligible_count'], 1)

    def test_missing_device_features_distinguished_from_adapter_support(self):
        for adapter in (False, True):
            report, sidecar, _, digest = fixture()
            report['identity']['runtime_observed']['actual_adapter']['gpu_timestamp_features_enabled'] = False
            sidecar['feature_negotiation'].update(adapter_supports_required_features=adapter, device_features_enabled=False)
            sidecar['availability'] = {'state': 'device_features_not_enabled'}
            unavailable(sidecar, 'device_features_not_enabled')
            self.assertIsNone(gpu.summarize(sidecar, report, digest)['p50_ns'])

    def test_rejected_submission_never_retains_stale_ticks(self):
        report, sidecar, _, digest = fixture()
        sidecar['samples'][0]['status'] = 'submission_rejected'
        with self.assertRaises(ValueError):
            gpu.validate(sidecar, report, digest)
        unavailable(sidecar, 'submission_rejected')
        self.assertEqual(gpu.summarize(sidecar, report, digest)['status_counts'], {'submission_rejected': 1})

    def test_reversed_ticks_are_retained_without_elapsed_value(self):
        report, sidecar, _, digest = fixture()
        sidecar['samples'][0].update(status='invalid_timestamp_order', start_ticks=20, end_ticks=10, elapsed_ns=None)
        self.assertIsNone(gpu.summarize(sidecar, report, digest)['p50_ns'])
        sidecar['samples'][0]['elapsed_ns'] = -20
        with self.assertRaises(ValueError):
            gpu.validate(sidecar, report, digest)

    def test_integer_subtraction_precedes_float_conversion(self):
        report, sidecar, _, digest = fixture()
        sidecar['samples'][0].update(start_ticks=2**63, end_ticks=2**63 + 1, elapsed_ns=2.0)
        self.assertEqual(gpu.summarize(sidecar, report, digest)['p50_ns'], 2.0)
        sidecar['samples'][0]['elapsed_ns'] = 0.0
        with self.assertRaises(ValueError):
            gpu.validate(sidecar, report, digest)

    def test_wrong_identity_order_parent_and_unknown_fields_fail_closed(self):
        mutations = [lambda s: s.update(frame_report_sha256='0' * 64),
                     lambda s: s.update(extra=True), lambda s: s.update(session=0),
                     lambda s: s.update(session=True), lambda s: s.update(samples=[]),
                     lambda s: s['samples'][0].update(session=4),
                     lambda s: s['samples'][0].update(attempt=1),
                     lambda s: s['samples'][0].update(record_index=0),
                     lambda s: s['samples'][0].update(record_index=True),
                     lambda s: s['samples'].append(copy.deepcopy(s['samples'][0])),
                     lambda s: s['limits'].update(ring_slots=5),
                     lambda s: s['limits'].update(max_attempts=5),
                     lambda s: s.update(error='hidden'),
                     lambda s: s['samples'][0].update(timestamp_period_ns=3.0),
                     lambda s: s['samples'][0].update(start_ticks=True),
                     lambda s: s['samples'][0].update(start_ticks=2**64)]
        for mutate in mutations:
            report, sidecar, _, digest = fixture()
            mutate(sidecar)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                gpu.validate(sidecar, report, digest)

    def test_unjoined_attempt_is_explicit_incomplete_and_suppresses_summary(self):
        report, sidecar, _, digest = fixture()
        sidecar['samples'][0]['record_index'] = None
        with self.assertRaises(ValueError):
            gpu.validate(sidecar, report, digest)
        sidecar.update(accounting_state='incomplete', error='record limit prevented a CPU terminal')
        result = gpu.summarize(sidecar, report, digest)
        self.assertEqual(result['state'], 'incomplete')
        self.assertEqual(result['measured_eligible_count'], 0)
        self.assertIsNone(result['p50_ns'])

    def test_failed_primary_suppresses_otherwise_valid_gpu_measurements(self):
        report, sidecar, _, digest = fixture()
        report['status'] = {'state': 'incomplete', 'error': 'synthetic diagnostic failure'}
        report['incomplete_at_ns'] = report['stop_requested_ns']
        result = gpu.summarize(sidecar, report, digest)
        self.assertEqual(result['state'], 'incomplete')
        self.assertIsNone(result['p95_ns'])

    def test_feature_and_availability_contradictions_fail(self):
        mutations = [lambda s: s['feature_negotiation'].update(adapter_supports_required_features=False),
                     lambda s: s['feature_negotiation'].update(device_features_enabled=1),
                     lambda s: s['availability'].update(timestamp_period_ns=0),
                     lambda s: s['availability'].update(timestamp_period_ns=float('nan')),
                     lambda s: s.update(availability={'state': 'allocation_failed'}),
                     lambda s: s.update(availability={'state': 'unsupported'})]
        for mutate in mutations:
            report, sidecar, _, digest = fixture()
            mutate(sidecar)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                gpu.validate(sidecar, report, digest)

    def test_skipped_attempt_is_not_shifted_onto_a_later_measured_present(self):
        report, sidecar, _, _ = fixture()
        report['records'].insert(1, {'at_ns': 150, 'kind': 'skipped_frame', 'reason': 'surface_skipped', 'resets_interval_anchor': False})
        report['skipped_frame_count'] = 1
        samples = report['cpu_frame_stages']['samples']
        samples[0].update(record_index=2, started_at_ns=155,
                          spans=dict.fromkeys(samples[0]['spans']))
        samples.insert(0, dict(samples[0], record_index=1, started_at_ns=105, finished_at_ns=150))
        measured = sidecar['samples'][0]
        measured.update(attempt=1, record_index=2)
        skipped = dict(measured, attempt=0, record_index=1, status='not_submitted', **dict.fromkeys(gpu.NUMERIC))
        sidecar['samples'].insert(0, skipped)
        digest = hashlib.sha256(json.dumps(report).encode()).hexdigest()
        sidecar['frame_report_sha256'] = digest
        self.assertEqual(gpu.summarize(sidecar, report, digest)['measured_eligible_count'], 1)
        skipped.update(status='measured', start_ticks=10, end_ticks=20, timestamp_period_ns=2.0, elapsed_ns=20.0)
        with self.assertRaisesRegex(ValueError, 'Skipped'):
            gpu.validate(sidecar, report, digest)

    def test_honest_hash_does_not_hide_primary_feature_contradictions(self):
        for requested, enabled in [(False, True), (True, False), (None, True), (True, None)]:
            report, sidecar, _, _ = fixture()
            report['identity']['runtime_observed']['actual_adapter'].update(
                gpu_timestamps_requested=requested, gpu_timestamp_features_enabled=enabled)
            digest = hashlib.sha256(json.dumps(report).encode()).hexdigest()
            sidecar['frame_report_sha256'] = digest
            with self.subTest(requested=requested, enabled=enabled), self.assertRaises(ValueError):
                gpu.validate(sidecar, report, digest)

    def test_initialization_failure_is_incomplete_without_fabricated_samples(self):
        report, sidecar, _, digest = fixture()
        sidecar.update(availability={'state': 'initialization_failed'}, accounting_state='incomplete',
                       error='validation failed', samples=[])
        self.assertEqual(gpu.summarize(sidecar, report, digest)['state'], 'incomplete')

    def test_cli_hashes_actual_bytes_and_writes_exclusively(self):
        _, sidecar, data, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, diagnostic, output = [root / name for name in ('frames.json', 'gpu.json', 'summary.json')]
            primary.write_bytes(data)
            diagnostic.write_text(json.dumps(sidecar))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gpu.main([str(primary), str(diagnostic), '--output', str(output)]), 0)
                before = output.read_bytes()
                self.assertEqual(gpu.main([str(primary), str(diagnostic), '--output', str(output)]), 2)
                self.assertEqual(output.read_bytes(), before)
                primary.write_bytes(data + b' ')
                self.assertEqual(gpu.main([str(primary), str(diagnostic)]), 2)


if __name__ == '__main__':
    unittest.main()
