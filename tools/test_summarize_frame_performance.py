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


# Captured from the actual unchanged FramePerformanceObserver/PerformanceSession
# public API at 178cd9a, using a fake monotonic clock, not handwritten reports.
# Start 0 -> presents 10, 15 -> request 20 -> final 25 covers completion/skip/error/
# shutdown. Additional cases retain backwards request/final-present evidence.
# Common fields are factored only to avoid repeating identical serialized data.
SOURCE_SESSION_COMMON = {'clock': 'caller_injected_monotonic_nanoseconds',
 'count_scope': 'retained events only; incomplete capture does not assert counts for unobserved '
                'activity',
 'identity': {'hardware_classification': 'unknown',
              'hardware_classification_basis': 'This observer does not authenticate hardware '
                                               'evidence.',
              'operator_supplied': None,
              'runtime_observed': {'actual_adapter': None,
                                   'actual_backend': 'synthetic source fixture',
                                   'build': {'test_fixture': True},
                                   'initial_window': {'mode': 'windowed',
                                                      'physical_height': 540,
                                                      'physical_width': 960,
                                                      'scale_factor': 1.0},
                                   'scene': None}},
 'ineligible_present_count': 0,
 'interpretation': 'CPU wall-clock intervals between successful present returns; not GPU time, '
                   'display cadence or simulation time.',
 'limits': {'max_metadata_bytes': 65536, 'max_records': 120000},
 'measurement': 'cpu_wall_clock_successful_present_return_interval_ns',
 'schema': 'rust_duty_frame_performance_v1'}
SOURCE_SESSION_CASES = {'backward_final_present': {'incomplete_at_ns': 15,
                            'last_observed_ns': 10,
                            'records': [{'at_ns': 10,
                                         'eligible': True,
                                         'ineligible_reason': None,
                                         'interval_ns': None,
                                         'kind': 'successful_present_return'}],
                            'skipped_frame_count': 0,
                            'start_ns': 0,
                            'status': {'error': 'non-monotonic timestamp: 15 ns follows 20 ns',
                                       'state': 'incomplete'},
                            'stop_requested_ns': 20,
                            'stopped_at_ns': None,
                            'successful_present_count': 1,
                            'summary': {'interval_count': 0,
                                        'max_ns': None,
                                        'min_ns': None,
                                        'p50_ns': None,
                                        'p95_ns': None,
                                        'p99_ns': None,
                                        'percentile_method': 'nearest_rank_ceil_p_times_n_no_interpolation',
                                        'total_interval_ns': 0}},
 'backward_request': {'incomplete_at_ns': 5,
                      'last_observed_ns': 10,
                      'records': [{'at_ns': 10,
                                   'eligible': True,
                                   'ineligible_reason': None,
                                   'interval_ns': None,
                                   'kind': 'successful_present_return'}],
                      'skipped_frame_count': 0,
                      'start_ns': 0,
                      'status': {'error': 'non-monotonic timestamp: 5 ns follows 10 ns',
                                 'state': 'incomplete'},
                      'stop_requested_ns': 5,
                      'stopped_at_ns': 20,
                      'successful_present_count': 1,
                      'summary': {'interval_count': 0,
                                  'max_ns': None,
                                  'min_ns': None,
                                  'p50_ns': None,
                                  'p95_ns': None,
                                  'p99_ns': None,
                                  'percentile_method': 'nearest_rank_ceil_p_times_n_no_interpolation',
                                  'total_interval_ns': 0}},
 'complete_final_present': {'incomplete_at_ns': None,
                            'last_observed_ns': 25,
                            'records': [{'at_ns': 10,
                                         'eligible': True,
                                         'ineligible_reason': None,
                                         'interval_ns': None,
                                         'kind': 'successful_present_return'},
                                        {'at_ns': 15,
                                         'eligible': True,
                                         'ineligible_reason': None,
                                         'interval_ns': 5,
                                         'kind': 'successful_present_return'},
                                        {'at_ns': 25,
                                         'eligible': True,
                                         'ineligible_reason': None,
                                         'interval_ns': 10,
                                         'kind': 'successful_present_return'}],
                            'skipped_frame_count': 0,
                            'start_ns': 0,
                            'status': {'error': None, 'state': 'complete'},
                            'stop_requested_ns': 20,
                            'stopped_at_ns': 25,
                            'successful_present_count': 3,
                            'summary': {'interval_count': 2,
                                        'max_ns': 10,
                                        'min_ns': 5,
                                        'p50_ns': 5,
                                        'p95_ns': 10,
                                        'p99_ns': 10,
                                        'percentile_method': 'nearest_rank_ceil_p_times_n_no_interpolation',
                                        'total_interval_ns': 15}},
 'incomplete_final_skip': {'incomplete_at_ns': 25,
                           'last_observed_ns': 25,
                           'records': [{'at_ns': 10,
                                        'eligible': True,
                                        'ineligible_reason': None,
                                        'interval_ns': None,
                                        'kind': 'successful_present_return'},
                                       {'at_ns': 15,
                                        'eligible': True,
                                        'ineligible_reason': None,
                                        'interval_ns': 5,
                                        'kind': 'successful_present_return'},
                                       {'at_ns': 25,
                                        'kind': 'skipped_frame',
                                        'reason': 'surface_skipped',
                                        'resets_interval_anchor': False}],
                           'skipped_frame_count': 1,
                           'start_ns': 0,
                           'status': {'error': 'capture ended before its final requested '
                                               'presentation returned',
                                      'state': 'incomplete'},
                           'stop_requested_ns': 20,
                           'stopped_at_ns': 25,
                           'successful_present_count': 2,
                           'summary': {'interval_count': 1,
                                       'max_ns': 5,
                                       'min_ns': 5,
                                       'p50_ns': 5,
                                       'p95_ns': 5,
                                       'p99_ns': 5,
                                       'percentile_method': 'nearest_rank_ceil_p_times_n_no_interpolation',
                                       'total_interval_ns': 5}},
 'incomplete_present_failure': {'incomplete_at_ns': 25,
                                'last_observed_ns': 25,
                                'records': [{'at_ns': 10,
                                             'eligible': True,
                                             'ineligible_reason': None,
                                             'interval_ns': None,
                                             'kind': 'successful_present_return'},
                                            {'at_ns': 15,
                                             'eligible': True,
                                             'ineligible_reason': None,
                                             'interval_ns': 5,
                                             'kind': 'successful_present_return'},
                                            {'at_ns': 25,
                                             'kind': 'boundary',
                                             'reason': 'surface_error'}],
                                'skipped_frame_count': 0,
                                'start_ns': 0,
                                'status': {'error': 'final requested presentation failed',
                                           'state': 'incomplete'},
                                'stop_requested_ns': 20,
                                'stopped_at_ns': 25,
                                'successful_present_count': 2,
                                'summary': {'interval_count': 1,
                                            'max_ns': 5,
                                            'min_ns': 5,
                                            'p50_ns': 5,
                                            'p95_ns': 5,
                                            'p99_ns': 5,
                                            'percentile_method': 'nearest_rank_ceil_p_times_n_no_interpolation',
                                            'total_interval_ns': 5}},
 'incomplete_shutdown': {'incomplete_at_ns': 25,
                         'last_observed_ns': 25,
                         'records': [{'at_ns': 10,
                                      'eligible': True,
                                      'ineligible_reason': None,
                                      'interval_ns': None,
                                      'kind': 'successful_present_return'},
                                     {'at_ns': 15,
                                      'eligible': True,
                                      'ineligible_reason': None,
                                      'interval_ns': 5,
                                      'kind': 'successful_present_return'},
                                     {'at_ns': 25, 'kind': 'boundary', 'reason': 'shutdown'}],
                         'skipped_frame_count': 0,
                         'start_ns': 0,
                         'status': {'error': 'capture ended before its final requested '
                                             'presentation returned',
                                    'state': 'incomplete'},
                         'stop_requested_ns': 20,
                         'stopped_at_ns': 25,
                         'successful_present_count': 2,
                         'summary': {'interval_count': 1,
                                     'max_ns': 5,
                                     'min_ns': 5,
                                     'p50_ns': 5,
                                     'p95_ns': 5,
                                     'p99_ns': 5,
                                     'percentile_method': 'nearest_rank_ceil_p_times_n_no_interpolation',
                                     'total_interval_ns': 5}},
 'request_before_start': {'incomplete_at_ns': 95,
                          'last_observed_ns': 110,
                          'records': [{'at_ns': 110,
                                       'eligible': True,
                                       'ineligible_reason': None,
                                       'interval_ns': None,
                                       'kind': 'successful_present_return'}],
                          'skipped_frame_count': 0,
                          'start_ns': 100,
                          'status': {'error': 'non-monotonic timestamp: 95 ns follows 110 ns',
                                     'state': 'incomplete'},
                          'stop_requested_ns': 95,
                          'stopped_at_ns': 120,
                          'successful_present_count': 1,
                          'summary': {'interval_count': 0,
                                      'max_ns': None,
                                      'min_ns': None,
                                      'p50_ns': None,
                                      'p95_ns': None,
                                      'p99_ns': None,
                                      'percentile_method': 'nearest_rank_ceil_p_times_n_no_interpolation',
                                      'total_interval_ns': 0}}}

def source_session_reports():
    return {name: json.loads(json.dumps({**SOURCE_SESSION_COMMON, **case}))
            for name, case in SOURCE_SESSION_CASES.items()}


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

    def test_actual_session_exports_preserve_completion_and_incomplete_evidence(self):
        for name, report in source_session_reports().items():
            with self.subTest(name=name):
                self.report = report
                before = json.dumps(report, sort_keys=True)
                code, result, error = self.summarize()
                self.assertEqual(code, 0, error)
                self.assertEqual(result['status'], report['status']['state'])
                self.assertEqual(result['error'], report['status']['error'])
                for field in ('start_ns', 'stop_requested_ns', 'stopped_at_ns',
                              'last_observed_ns', 'incomplete_at_ns'):
                    self.assertEqual(result[field], report[field])
                self.assertEqual(json.dumps(report, sort_keys=True), before)
        complete = source_session_reports()['complete_final_present']
        self.assertEqual(complete['stop_requested_ns'], 20)
        self.assertEqual(complete['stopped_at_ns'], 25)
        self.assertEqual(complete['summary']['interval_count'], 2)

    def test_deferred_stop_rejects_missing_final_present_or_impossible_order(self):
        original = source_session_reports()['complete_final_present']
        mutations = [
            lambda r: r.update(stopped_at_ns=None),
            lambda r: r.update(stopped_at_ns=24),
            lambda r: r.update(stopped_at_ns=30),
            lambda r: r.update(stop_requested_ns=25, stopped_at_ns=30),
            lambda r: r.update(stop_requested_ns=30),
            lambda r: r.update(stop_requested_ns=5),
        ]
        for mutate in mutations:
            report = json.loads(json.dumps(original))
            mutate(report)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                perf.validate_report(report)
        # An ineligible successful return may still finish the session, but a
        # boundary/skip at the same timestamp cannot stand in for that return.
        report = source_session_reports()['incomplete_final_skip']
        report.update(status={'state': 'complete', 'error': None}, incomplete_at_ns=None)
        with self.assertRaisesRegex(ValueError, 'final successful present'):
            perf.validate_report(report)

    def test_missing_completion_needs_actual_backward_clock_evidence(self):
        report = source_session_reports()['incomplete_present_failure']
        report.update(stop_requested_ns=25, stopped_at_ns=None)
        with self.assertRaisesRegex(ValueError, 'contradictory clock evidence'):
            perf.validate_report(report)
        report = source_session_reports()['backward_final_present']
        report['stopped_at_ns'] = 15
        with self.assertRaisesRegex(ValueError, 'stop request'):
            perf.validate_report(report)

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
        original_link = link.readlink()
        code, _, _ = self.summarize(link)
        self.assertEqual(code, 1)
        self.assertFalse((self.root / 'absent').exists())
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.readlink(), original_link)


def with_cpu_stages():
    report = control()
    spans = {name: {'started_at_ns': begin, 'ended_at_ns': end, 'duration_ns': end - begin}
             for name, begin, end in zip(perf.CPU_STAGE_DEFINITIONS,
                                         (110, 120, 140, 190), (120, 140, 180, 195))}
    report['cpu_frame_stages'] = {
        'measurement': perf.CPU_STAGE_MEASUREMENT,
        'interpretation': perf.CPU_STAGE_INTERPRETATION,
        'stage_definitions': dict(perf.CPU_STAGE_DEFINITIONS),
        'samples': [{'record_index': 1, 'started_at_ns': 105, 'finished_at_ns': 200,
                     'physical_width': 960, 'physical_height': 540, 'spans': spans}],
    }
    return report


class CpuStageSummaryTests(unittest.TestCase):
    def test_sample_cannot_start_before_an_uninstrumented_terminal_frame(self):
        report = with_cpu_stages()
        report['start_ns'] = 0
        sample = report['cpu_frame_stages']['samples'][0]
        sample['started_at_ns'] = 99  # Earlier uninstrumented present is at 100.
        with self.assertRaisesRegex(ValueError, 'CPU frame times'):
            perf.validate_report(report)
        sample['started_at_ns'] = 100
        perf.validate_report(report)

    def test_optional_extension_keeps_old_reports_and_primary_statistics(self):
        original = control()
        perf.validate_report(original)
        report = with_cpu_stages()
        perf.validate_report(report)
        self.assertEqual(report['summary'], original['summary'])
        self.assertEqual(report['records'], original['records'])
        result = perf._cpu_stage_summary(report['cpu_frame_stages'], report['records'])
        self.assertNotIn('samples', result)
        self.assertEqual(result['summary']['renderer_submit']['p95_ns'], 40)
        self.assertNotIn('fps', result)

    def test_null_is_unavailable_and_zero_is_a_real_paired_duration(self):
        report = with_cpu_stages()
        spans = report['cpu_frame_stages']['samples'][0]['spans']
        spans['game_recording'] = None
        spans['present_call'] = {'started_at_ns': 190, 'ended_at_ns': 190, 'duration_ns': 0}
        perf.validate_report(report)
        result = perf._cpu_stage_summary(report['cpu_frame_stages'], report['records'])
        self.assertEqual(result['summary']['game_recording']['sample_count'], 0)
        self.assertIsNone(result['summary']['game_recording']['p50_ns'])
        self.assertEqual(result['summary']['present_call']['sample_count'], 1)
        self.assertEqual(result['summary']['present_call']['p50_ns'], 0)

    def test_rejects_fabricated_overlapping_negative_or_out_of_frame_cpu_spans(self):
        mutations = [
            lambda s: s['spans']['surface_acquire'].update(duration_ns=11),
            lambda s: s['spans']['surface_acquire'].update(started_at_ns=-1),
            lambda s: s['spans']['surface_acquire'].update(duration_ns=True),
            lambda s: s['spans']['game_recording'].update(started_at_ns=119, duration_ns=21),
            lambda s: s['spans']['present_call'].update(ended_at_ns=201, duration_ns=11),
            lambda s: s.update(started_at_ns=130),
            lambda s: s.update(finished_at_ns=201),
            lambda s: s.update(record_index=True),
            lambda s: s.update(record_index=2),
            lambda s: s.update(physical_width=-1920),
            lambda s: s.update(physical_height=2**32),
            lambda s: s['spans'].update(gpu_time=1),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                report = with_cpu_stages()
                mutate(report['cpu_frame_stages']['samples'][0])
                with self.assertRaises(ValueError):
                    perf.validate_report(report)

    def test_rejects_duplicate_samples_and_unknown_semantics(self):
        report = with_cpu_stages()
        report['cpu_frame_stages']['samples'] *= 2
        with self.assertRaises(ValueError):
            perf.validate_report(report)
        for field in ('measurement', 'interpretation', 'stage_definitions'):
            report = with_cpu_stages()
            report['cpu_frame_stages'][field] = 'GPU timing'
            with self.assertRaises(ValueError):
                perf.validate_report(report)

    def test_paused_retry_and_baseline_samples_do_not_enter_eligible_summary(self):
        report = with_cpu_stages()
        extension = report['cpu_frame_stages']
        for record in [present(200, eligible=False, reason='paused'), present(200),
                       {'kind': 'skipped_frame', 'at_ns': 200, 'reason': 'surface_skipped',
                        'resets_interval_anchor': False}]:
            result = perf._cpu_stage_summary(extension, [present(100), record])
            self.assertEqual(result['retained_attempt_count'], 1)
            self.assertEqual(result['summary']['renderer_submit']['sample_count'], 0)


if __name__ == '__main__':
    unittest.main()
