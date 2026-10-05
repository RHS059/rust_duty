"""Self-contained source-faithful CPU observer fixtures; no GPU/performance claim."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import summarize_frame_performance as perf


def present(at, interval=None, eligible=True, reason=None):
    return {'at_ns': at, 'kind': 'successful_present_return', 'eligible': eligible,
            'ineligible_reason': reason, 'interval_ns': interval}


def control():
    # Matches the independently known 100/200/210 observer contract example.
    return {
        'schema': 'rust_duty_frame_performance_v1',
        'measurement': 'cpu_wall_clock_successful_present_return_interval_ns',
        'clock': 'caller_injected_monotonic_nanoseconds',
        'interpretation': 'CPU wall-clock intervals between successful present returns; not GPU time, display cadence or simulation time.',
        'identity': {'runtime_observed': {'actual_backend': 'Dx12',
                                        'actual_adapter': {'name': 'synthetic', 'device_type': 'unknown'},
                                        'build': {'commit': 'synthetic'},
                                        'initial_window': {'physical_width': 960, 'physical_height': 540,
                                                           'scale_factor': 1.25, 'mode': 'windowed'},
                                        'scene': {'name': 'synthetic'}},
                     'operator_supplied': {'machine_label': 'unverified claim'},
                     'hardware_classification': 'unknown',
                     'hardware_classification_basis': 'This observer does not authenticate hardware evidence.'},
        'status': {'state': 'complete', 'error': None},
        'start_ns': 100, 'stop_requested_ns': 210, 'stopped_at_ns': 210, 'last_observed_ns': 200,
        'incomplete_at_ns': None, 'limits': {'max_records': 120000, 'max_metadata_bytes': 65536},
        'successful_present_count': 2, 'ineligible_present_count': 0, 'skipped_frame_count': 0,
        'count_scope': 'retained events only; incomplete capture does not assert counts for unobserved activity',
        'summary': {'interval_count': 1, 'total_interval_ns': 100, 'min_ns': 100, 'max_ns': 100,
                    'p50_ns': 100, 'p95_ns': 100, 'p99_ns': 100,
                    'percentile_method': 'nearest_rank_ceil_p_times_n_no_interpolation'},
        'records': [present(100), present(200, 100)]}


class PerformanceSummaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'trace.json'
        self.report = control()

    def save(self, value=None):
        self.path.write_text(json.dumps(self.report if value is None else value))

    def summarize(self, output=None):
        self.save()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = perf.summarize_report(self.path, output)
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, stderr.getvalue()

    def test_complete_control_preserves_identity_and_scope(self):
        code, result, error = self.summarize()
        self.assertEqual(code, 0, error)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['identity'], self.report['identity'])
        self.assertEqual(result['count_scope'], self.report['count_scope'])
        self.assertEqual(result['p50_ns'], 100)
        self.assertEqual(result['retained_record_count'], 2)
        self.assertIn('no GPU', result['scope'])

    def test_skips_retain_gaps_and_exclusions_and_context_reset_anchors(self):
        self.report['records'] = [present(110),
            {'at_ns': 120, 'kind': 'skipped_frame', 'reason': 'surface_skipped', 'resets_interval_anchor': False},
            present(210, 100), {'at_ns': 220, 'kind': 'boundary', 'reason': 'focus_lost'},
            present(230, eligible=False, reason='focus_lost'),
            {'at_ns': 240, 'kind': 'window_context', 'context': self.report['identity']['runtime_observed']['initial_window']},
            present(250), present(450, 200)]
        self.report.update(stop_requested_ns=500, stopped_at_ns=500, last_observed_ns=450,
                           successful_present_count=5, ineligible_present_count=1, skipped_frame_count=1)
        self.report['summary'].update(interval_count=2, total_interval_ns=300, max_ns=200, p95_ns=200, p99_ns=200)
        perf.validate_report(self.report)
        self.report['records'][2]['interval_ns'] = 90
        with self.assertRaisesRegex(ValueError, 'anchor'):
            perf.validate_report(self.report)

    def test_zero_length_interval_is_an_actual_eligible_sample(self):
        self.report['records'][1] = present(100, 0)
        self.report['last_observed_ns'] = 100
        for key in ('total_interval_ns', 'min_ns', 'max_ns', 'p50_ns', 'p95_ns', 'p99_ns'):
            self.report['summary'][key] = 0
        perf.validate_report(self.report)

    def test_no_eligible_intervals_is_preserved_as_incomplete(self):
        self.report.update(records=[present(100)], successful_present_count=1, last_observed_ns=100,
                           incomplete_at_ns=210, status={'state': 'incomplete', 'error': 'capture has no eligible present-return intervals'})
        self.report['summary'].update(interval_count=0, total_interval_ns=0, min_ns=None, max_ns=None,
                                      p50_ns=None, p95_ns=None, p99_ns=None)
        code, result, error = self.summarize()
        self.assertEqual(code, 0, error)
        self.assertEqual(result['status'], 'incomplete')
        self.assertIsNone(result['p50_ns'])
        self.report.update(records=[], successful_present_count=0)
        perf.validate_report(self.report)

    def test_incomplete_capacity_retains_samples_but_not_complete_verdict(self):
        self.report['limits']['max_records'] = 2
        self.report.update(incomplete_at_ns=300, stop_requested_ns=310, stopped_at_ns=310,
                           status={'state': 'incomplete', 'error': 'capture reached its 2-record limit; later events were not retained'})
        code, result, error = self.summarize()
        self.assertEqual(code, 0, error)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['interval_count'], 1)
        self.report.update(stop_requested_ns=250, stopped_at_ns=None)
        perf.validate_report(self.report)  # Rejected event300 constrains stop250.

    def test_backward_event_or_stop_can_make_a_valid_incomplete_report(self):
        self.report.update(incomplete_at_ns=150,
                           status={'state': 'incomplete', 'error': 'non-monotonic timestamp: 150 ns follows 200 ns'})
        perf.validate_report(self.report)  # Backward rejected event, then valid stop210.
        self.report.update(stop_requested_ns=150, stopped_at_ns=None)
        perf.validate_report(self.report)  # stop itself was the backward observation.

    def test_missing_records_or_inconsistent_counts_and_summary_reject(self):
        cases = [('records', []), ('successful_present_count', 3), ('ineligible_present_count', 1),
                 ('skipped_frame_count', 1), ('last_observed_ns', 201)]
        for field, value in cases:
            report = control()
            report[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                perf.validate_report(report)
        report = control()
        del report['records']
        with self.assertRaises(ValueError):
            perf.validate_report(report)
        for field in ('interval_count', 'total_interval_ns', 'min_ns', 'max_ns', 'p50_ns', 'p95_ns', 'p99_ns'):
            report = control()
            report['summary'][field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                perf.validate_report(report)

    def test_numeric_fields_reject_boolean_fractional_negative_and_overflow(self):
        for value in (True, 2.0, -1, 2**64):
            for field in ('successful_present_count', 'start_ns', 'stop_requested_ns'):
                report = control()
                report[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    perf.validate_report(report)
        for value in (True, 100.0, -1):
            report = control()
            report['summary']['p50_ns'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                perf.validate_report(report)

    def test_records_types_ordering_and_window_constraints(self):
        mutations = [lambda r: r['records'][1].update(at_ns=99),
                     lambda r: r['records'][1].update(eligible=1),
                     lambda r: r['records'][1].update(interval_ns=True),
                     lambda r: r['records'][1].update(kind='invented'),
                     lambda r: r['identity']['runtime_observed']['initial_window'].update(scale_factor=0),
                     lambda r: r['limits'].update(max_records=1),
                     lambda r: r.update(status={'state': 'complete', 'error': 'failed'})]
        for index, mutate in enumerate(mutations):
            report = control()
            mutate(report)
            with self.subTest(index=index), self.assertRaises(ValueError):
                perf.validate_report(report)

    def test_invalid_claims_shapes_and_nonfinite_values_do_not_crash(self):
        for field, value in [('measurement', 'gpu-time'), ('clock', 'wall-clock'), ('identity', []),
                             ('summary', None), ('status', 'complete')]:
            report = control()
            report[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                perf.validate_report(report)
        for value in (float('nan'), float('inf'), float('-inf')):
            report = control()
            report['identity']['operator_supplied']['probe'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                perf.validate_report(report)
        report = control()
        report['identity']['hardware_classification'] = 'real_gpu_verified'
        with self.assertRaisesRegex(ValueError, 'unknown'):
            perf.validate_report(report)
        self.report['summary']['percentile_method'] = 'invented'
        with self.assertRaisesRegex(ValueError, 'percentile_method'):
            perf.validate_report(self.report)

    def test_strict_json_duplicate_nonfinite_encoding_and_partial_inputs(self):
        raw = json.dumps(control())
        for data in (raw[:-1] + ',"successful_present_count":2}', '{"a":NaN}', '{"a":1e9999}',
                     '[]', '{', 'null'):
            self.path.write_text(data)
            with self.subTest(data=data[:40]), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(perf.summarize_report(self.path), 1)
                self.assertIn('Validation error:', errors.getvalue())
        self.path.write_bytes(b'\xff')
        with self.assertRaises(ValueError):
            perf.read_report(self.path)

    def test_exclusive_report_preserves_existing_source_and_links(self):
        report_path = self.root / 'output.json'
        code, result, error = self.summarize(report_path)
        self.assertEqual(code, 0, error)
        before = report_path.read_bytes()
        code, _, _ = self.summarize(report_path)
        self.assertEqual(code, 1)
        self.assertEqual(report_path.read_bytes(), before)
        self.save()
        before = self.path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(perf.main([str(self.path), '--report', str(self.path)]), 1)
        self.assertEqual(self.path.read_bytes(), before)
        link = self.root / 'dangling'
        try:
            link.symlink_to(self.root / 'absent')
        except OSError as error:
            self.skipTest(str(error))
        code, _, _ = self.summarize(link)
        self.assertEqual(code, 1)
        self.assertFalse((self.root / 'absent').exists())


if __name__ == '__main__':
    unittest.main()
