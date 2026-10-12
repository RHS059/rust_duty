"""Actual CPU encode-detail reader contracts using synthetic, non-GPU evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import summarize_cpu_encode_detail as detail
import summarize_cpu_substages as substages
import summarize_frame_performance as frames
from test_summarize_cpu_substages import fixture as substage_fixture

# Independent exact field expectations: a new producer key must not silently
# expand either version's reader contract merely by changing production tuples.
V1_COUNTERS = ('prepared_draws', 'text_characters', 'upload_arenas', 'vertex_bytes',
               'index_bytes', 'uniform_bytes', 'draw_calls', 'render_passes',
               'texture_cache_misses', 'pipeline_cache_misses')
V2_COUNTERS = V1_COUNTERS + ('gpu_buffer_allocations', 'gpu_buffer_reuses',
                            'gpu_buffer_allocated_bytes', 'transform_binding_allocations',
                            'uncached_upload_arenas')


def span(stage, begin, end):
    return {'stage': stage, 'started_at_ns': begin, 'ended_at_ns': end, 'duration_ns': end - begin}


def fixture():
    primary, substage, data, digest = substage_fixture()
    encode = {'schema': 'rust_duty_cpu_encode_detail_v1', 'measurement': detail.MEASUREMENT,
              'interpretation': detail.INTERPRETATION, 'frame_report_sha256': digest,
              'frame_status': copy.deepcopy(primary['status']), 'samples': [
                  {'record_index': 1, 'details': {'state': 'complete', 'error': None,
                      'spans': [span(name, begin, end) for name, begin, end in zip(
                          detail.PHASES, (145, 148, 152, 156, 160), (147, 151, 156, 159, 165))],
                      'counters': {name: index + 1 for index, name in enumerate(V1_COUNTERS)}}}]}
    primary['identity']['runtime_observed']['actual_adapter']['instance_descriptor'] = {
        'schema': 'rust-duty-wgpu-instance-descriptor/v1', 'wgpu_version': '30.0.1',
        'flags_bits': 35, 'debug': True, 'validation': True, 'gpu_based_validation': False,
        'validation_indirect_call': True, 'application_debug_assertions': False,
        'environment_overrides_applied': False}
    data, digest = rebind(primary, substage, encode)
    return primary, substage, encode, data, digest


def v2_fixture(upload_policy='bounded_reuse_v1'):
    primary, substage, encode, data, digest = fixture()
    encode.update(schema='rust_duty_cpu_encode_detail_v2', upload_policy=upload_policy)
    encode['samples'][0]['details']['counters'] = {
        name: index + 1 for index, name in enumerate(V2_COUNTERS)}
    return primary, substage, encode, data, digest


def rebind(primary, substage, encode):
    data = json.dumps(primary).encode('utf-8')
    digest = hashlib.sha256(data).hexdigest()
    for sidecar in (substage, encode):
        sidecar['frame_report_sha256'] = digest
        sidecar['frame_status'] = copy.deepcopy(primary['status'])
    return data, digest


def append_attempt(primary, substage, encode, kind='successful_present_return', eligible=True):
    """Add a distinct valid parent/child attempt, independently maintaining totals."""
    if kind == 'successful_present_return':
        primary['records'].append({'kind': kind, 'at_ns': 300, 'eligible': eligible,
                                   'ineligible_reason': None if eligible else 'diagnostic_capture',
                                   'interval_ns': 100 if eligible else None})
        primary['successful_present_count'] += 1
        if eligible:
            primary['summary'].update(interval_count=2, total_interval_ns=200)
        else:
            primary['ineligible_present_count'] += 1
    elif kind == 'skipped_frame':
        primary['records'].append({'kind': kind, 'at_ns': 300, 'reason': 'surface_skipped',
                                   'resets_interval_anchor': False})
        primary['skipped_frame_count'] += 1
    else:
        primary['records'].append({'kind': 'boundary', 'at_ns': 300, 'reason': 'surface_error'})
    primary.update(last_observed_ns=300, stop_requested_ns=310, stopped_at_ns=310)
    parent = copy.deepcopy(primary['cpu_frame_stages']['samples'][-1])
    parent.update(record_index=2, started_at_ns=205, finished_at_ns=300)
    for observation in parent['spans'].values():
        observation['started_at_ns'] += 100
        observation['ended_at_ns'] += 100
    primary['cpu_frame_stages']['samples'].append(parent)
    for sidecar in (substage, encode):
        sample = copy.deepcopy(sidecar['samples'][-1])
        sample['record_index'] = 2
        for observation in sample['details']['spans']:
            observation['started_at_ns'] += 100
            observation['ended_at_ns'] += 100
        sidecar['samples'].append(sample)


class CpuEncodeDetailTests(unittest.TestCase):
    fixture = staticmethod(fixture)
    counter_names = V1_COUNTERS

    def test_complete_control_binds_both_parents_without_mutating_evidence(self):
        primary, substage, encode, _, digest = self.fixture()
        originals = copy.deepcopy((primary, substage, encode))
        result = detail.summarize(encode, substage, primary, digest)
        self.assertEqual(result['diagnostic_status'], 'complete')
        self.assertEqual(result['summarized_attempts'], 1)
        self.assertEqual(result['stages']['frame_plan']['per_frame_total_ns']['p50_ns'], 2)
        self.assertEqual(result['stages']['queue_submit']['per_frame_total_ns']['p99_ns'], 5)
        self.assertEqual(result['counters']['text_characters']['total'], 2)
        self.assertEqual(result['counters']['pipeline_cache_misses']['p95'], 10)
        self.assertEqual((primary, substage, encode), originals)
        frames.validate_report(primary)
        substages.validate(substage, primary, digest)
        self.assertNotIn('gpu_duration', result)

    def assert_unavailable(self, result):
        self.assertEqual(result['summarized_attempts'], 0)
        for stage in result['stages'].values():
            self.assertEqual(stage['per_frame_total_ns']['sample_count'], 0)
            self.assertIsNone(stage['per_frame_total_ns']['p50_ns'])
        for counter in result['counters'].values():
            self.assertEqual(counter['sample_count'], 0)
            self.assertIsNone(counter['p50'])

    def test_missing_phases_require_incomplete_and_never_zero_fill_partial_counters(self):
        for count in range(5):
            primary, substage, encode, _, digest = self.fixture()
            row = encode['samples'][0]['details']
            row['spans'] = row['spans'][:count]
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'all five'):
                detail.validate(encode, substage, primary, digest)
            row.update(state='incomplete', error='encode_not_observed' if count == 0 else 'encode_incomplete')
            original_counters = copy.deepcopy(row['counters'])
            result = detail.summarize(encode, substage, primary, digest)
            self.assertEqual(result['diagnostic_status'], 'incomplete')
            self.assertEqual(result['incomplete_detail_attempts'], 1)
            self.assertEqual(row['counters'], original_counters)
            self.assert_unavailable(result)

    def test_zero_length_observations_and_zero_counters_are_real_complete_samples(self):
        primary, substage, encode, _, digest = self.fixture()
        row = encode['samples'][0]['details']
        row['spans'] = [span(name, 145, 145) for name in detail.PHASES]
        row['counters'] = dict.fromkeys(self.counter_names, 0)
        result = detail.summarize(encode, substage, primary, digest)
        self.assertEqual(result['summarized_attempts'], 1)
        for phase in result['stages'].values():
            self.assertEqual(phase['per_frame_total_ns']['p50_ns'], 0)
        for counter in result['counters'].values():
            self.assertEqual(counter['sample_count'], 1)
            self.assertEqual(counter['p50'], 0)

    def test_complete_rows_are_suppressed_when_primary_is_incomplete(self):
        primary, substage, encode, _, _ = self.fixture()
        primary.update(incomplete_at_ns=205, status={'state': 'incomplete', 'error': 'synthetic failure'})
        _, digest = rebind(primary, substage, encode)
        result = detail.summarize(encode, substage, primary, digest)
        self.assertEqual(result['diagnostic_status'], 'incomplete')
        self.assert_unavailable(result)

    def test_incomplete_existing_substage_suppresses_even_full_encode_details(self):
        primary, substage, encode, _, digest = self.fixture()
        substage['samples'][0]['details'].update(state='incomplete', error='unterminated_substage')
        result = detail.summarize(encode, substage, primary, digest)
        self.assertEqual(result['diagnostic_status'], 'incomplete')
        self.assertEqual(result['incomplete_substage_attempts'], 1)
        self.assert_unavailable(result)

    def test_failed_skipped_and_ineligible_attempts_are_not_summarized(self):
        for kind, eligible in (('successful_present_return', False), ('skipped_frame', True),
                               ('boundary', True)):
            primary, substage, encode, _, _ = self.fixture()
            append_attempt(primary, substage, encode, kind, eligible)
            encode['samples'][1]['details']['counters']['prepared_draws'] = 999
            _, digest = rebind(primary, substage, encode)
            with self.subTest(kind=kind):
                result = detail.summarize(encode, substage, primary, digest)
                self.assertEqual(result['retained_attempts'], 2)
                self.assertEqual(result['summarized_attempts'], 1)
                self.assertEqual(result['counters']['prepared_draws']['total'], 1)

    def test_baseline_present_without_interval_is_not_summarized(self):
        primary, substage, encode, _, _ = self.fixture()
        parent = copy.deepcopy(primary['cpu_frame_stages']['samples'][0])
        parent.update(record_index=0, started_at_ns=100, finished_at_ns=100)
        for key in parent['spans']:
            parent['spans'][key] = {'started_at_ns': 100, 'ended_at_ns': 100, 'duration_ns': 0}
        primary['cpu_frame_stages']['samples'].insert(0, parent)
        child = {'record_index': 0, 'details': {'state': 'complete', 'error': None, 'spans': [
            {'stage': 'encode_submit', 'parent': 'renderer_submit', 'started_at_ns': 100,
             'ended_at_ns': 100, 'duration_ns': 0}]}}
        substage['samples'].insert(0, child)
        row = copy.deepcopy(encode['samples'][0])
        row['record_index'] = 0
        row['details']['spans'] = [span(name, 100, 100) for name in detail.PHASES]
        row['details']['counters']['prepared_draws'] = 999
        encode['samples'].insert(0, row)
        _, digest = rebind(primary, substage, encode)
        result = detail.summarize(encode, substage, primary, digest)
        self.assertEqual(result['retained_attempts'], 2)
        self.assertEqual(result['summarized_attempts'], 1)
        self.assertEqual(result['counters']['prepared_draws']['total'], 1)

    def test_parentless_partial_observations_remain_incomplete_and_bounded(self):
        for missing in ('renderer', 'encode', 'both'):
            primary, substage, encode, _, _ = self.fixture()
            if missing in ('renderer', 'both'):
                primary['cpu_frame_stages']['samples'][0]['spans']['renderer_submit'] = None
                substage['samples'][0]['details'].update(state='incomplete', error='parent_span_unavailable')
            if missing in ('encode', 'both'):
                substage['samples'][0]['details']['spans'] = substage['samples'][0]['details']['spans'][:4]
            _, digest = rebind(primary, substage, encode)
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'require.*parents'):
                detail.validate(encode, substage, primary, digest)
            row = encode['samples'][0]['details']
            row.update(state='incomplete', error='encode_incomplete')
            row['spans'] = row['spans'][:2]
            result = detail.summarize(encode, substage, primary, digest)
            self.assert_unavailable(result)
            row['spans'][0].update(started_at_ns=104, ended_at_ns=106, duration_ns=2)
            with self.assertRaisesRegex(ValueError, 'outside|disjoint and ordered'):
                detail.validate(encode, substage, primary, digest)

    def test_nonempty_complete_details_require_existing_substage_validation(self):
        mutations = [lambda s: s.update(schema='unknown'),
                     lambda s: s.update(frame_report_sha256='0' * 64),
                     lambda s: s['samples'][0]['details']['spans'][4].update(duration_ns=999),
                     lambda s: s['samples'][0].update(record_index=0),
                     lambda s: s['samples'][0]['details'].update(state='incomplete', error='invented')]
        for mutate in mutations:
            primary, substage, encode, _, digest = self.fixture()
            mutate(substage)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                detail.validate(encode, substage, primary, digest)

    def test_instance_descriptor_requires_exact_final_flags_and_types(self):
        mutations = [lambda d: d.update(schema='other'), lambda d: d.update(wgpu_version='29.0.0'),
                     lambda d: d.update(flags_bits=256), lambda d: d.update(flags_bits=-1),
                     lambda d: d.update(flags_bits=True), lambda d: d.update(flags_bits=35.0),
                     lambda d: d.update(debug=False), lambda d: d.update(validation=False),
                     lambda d: d.update(gpu_based_validation=True),
                     lambda d: d.update(validation_indirect_call=False),
                     lambda d: d.update(debug=1), lambda d: d.update(validation=1),
                     lambda d: d.update(application_debug_assertions=0),
                     lambda d: d.update(environment_overrides_applied=True),
                     lambda d: d.update(environment_overrides_applied=0),
                     lambda d: d.update(unexpected=True), lambda d: d.pop('validation')]
        for mutate in mutations:
            primary, substage, encode, _, _ = self.fixture()
            mutate(primary['identity']['runtime_observed']['actual_adapter']['instance_descriptor'])
            _, digest = rebind(primary, substage, encode)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                detail.validate(encode, substage, primary, digest)
        for adapter in (None, {}, {'instance_descriptor': None}):
            primary, substage, encode, _, _ = self.fixture()
            primary['identity']['runtime_observed']['actual_adapter'] = adapter
            _, digest = rebind(primary, substage, encode)
            with self.subTest(adapter=adapter), self.assertRaises(ValueError):
                detail.validate(encode, substage, primary, digest)

    def test_application_build_flag_does_not_infer_dependency_instance_flags(self):
        for application_debug_assertions in (False, True):
            for bits in (0, 3, 16, 32, 255):
                primary, substage, encode, _, _ = self.fixture()
                descriptor = primary['identity']['runtime_observed']['actual_adapter']['instance_descriptor']
                descriptor.update(flags_bits=bits, application_debug_assertions=application_debug_assertions)
                for name, mask in detail.INSTANCE_FLAGS.items():
                    descriptor[name] = bool(bits & mask)
                _, digest = rebind(primary, substage, encode)
                with self.subTest(application=application_debug_assertions, bits=bits):
                    self.assertEqual(detail.summarize(encode, substage, primary, digest)['diagnostic_status'],
                                     'complete')

    def test_matching_malformed_expected_digest_is_not_a_sha256_binding(self):
        for digest in ('not-a-hash', 'G' * 64, 'A' * 64, 42):
            primary, substage, encode, _, _ = self.fixture()
            substage['frame_report_sha256'] = digest
            encode['frame_report_sha256'] = digest
            with self.subTest(digest=digest), self.assertRaisesRegex(ValueError, 'SHA-256'):
                detail.validate(encode, substage, primary, digest)

    def test_exact_fields_identity_and_state_fail_closed(self):
        mutations = [lambda d: d.update(schema='unknown'), lambda d: d.update(measurement='GPU time'),
                     lambda d: d.update(interpretation='different'),
                     lambda d: d.update(frame_report_sha256='0' * 64),
                     lambda d: d.update(frame_status={'state': 'incomplete', 'error': 'failure'}),
                     lambda d: d.update(unexpected=True),
                     lambda d: d['samples'][0].update(unexpected=True),
                     lambda d: d['samples'][0]['details'].update(unexpected=True),
                     lambda d: d['samples'][0]['details']['spans'][0].update(parent='encode_submit'),
                     lambda d: d['samples'][0]['details']['counters'].update(glyph_quads=0),
                     lambda d: d['samples'][0]['details']['counters'].pop('vertex_bytes'),
                     lambda d: d['samples'][0]['details'].update(state='unavailable'),
                     lambda d: d['samples'][0]['details'].update(error='hidden failure'),
                     lambda d: d['samples'][0]['details'].update(state='incomplete', error=None),
                     lambda d: d['samples'][0]['details'].update(state='incomplete', error=' '),
                     lambda d: d['samples'][0]['details'].update(state='incomplete', error='x' * 257),
                     lambda d: d['samples'][0]['details'].update(state='incomplete', error=7)]
        for mutate in mutations:
            primary, substage, encode, _, digest = self.fixture()
            mutate(encode)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                detail.validate(encode, substage, primary, digest)

    def test_unknown_reordered_overlapping_reversed_and_overcapacity_spans_fail(self):
        mutations = [lambda s: s[0].update(stage='gpu_time'), lambda s: s.reverse(),
                     lambda s: s[1].update(stage='frame_plan'),
                     lambda s: s[0].update(started_at_ns=148, ended_at_ns=147, duration_ns=0),
                     lambda s: s[1].update(started_at_ns=146, duration_ns=5),
                     lambda s: s[0].update(duration_ns=999),
                     lambda s: s[0].update(started_at_ns=True),
                     lambda s: s[0].update(ended_at_ns=2**64),
                     lambda s: s.append(copy.deepcopy(s[-1]))]
        for mutate in mutations:
            primary, substage, encode, _, digest = self.fixture()
            mutate(encode['samples'][0]['details']['spans'])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                detail.validate(encode, substage, primary, digest)

    def test_incomplete_phase_sequence_must_be_a_prefix(self):
        primary, substage, encode, _, digest = self.fixture()
        row = encode['samples'][0]['details']
        row.update(state='incomplete', error='encode_incomplete')
        row['spans'] = [row['spans'][0], row['spans'][2]]
        with self.assertRaisesRegex(ValueError, 'out of order'):
            detail.validate(encode, substage, primary, digest)

    def test_encode_parent_is_tighter_than_renderer_parent_even_if_marked_incomplete(self):
        for state in ('complete', 'incomplete'):
            primary, substage, encode, _, digest = self.fixture()
            row = encode['samples'][0]['details']
            row.update(state=state, error=None if state == 'complete' else 'encode_outside_parent')
            row['spans'][0].update(started_at_ns=144, duration_ns=3)  # Inside renderer, outside encode.
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, 'outside'):
                detail.validate(encode, substage, primary, digest)

    def test_renderer_parent_bounds_apply_when_substage_is_explicitly_invalid(self):
        primary, substage, encode, _, digest = self.fixture()
        child = substage['samples'][0]['details']
        child.update(state='incomplete', error='substage_outside_parent')
        child['spans'] = [child['spans'][4]]
        child['spans'][0].update(started_at_ns=139, duration_ns=26)
        row = encode['samples'][0]['details']
        row.update(state='incomplete', error='encode_outside_parent')
        row['spans'][0].update(started_at_ns=139, duration_ns=8)
        substages.validate(substage, primary, digest)  # Control reaches the additional parent check.
        with self.assertRaisesRegex(ValueError, 'outside'):
            detail.validate(encode, substage, primary, digest)

    def test_counters_are_exact_nonnegative_u64_and_never_bool_float_or_null(self):
        for name in self.counter_names:
            for invalid in (-1, 2**64, True, 1.0, '1', None, float('inf')):
                primary, substage, encode, _, digest = self.fixture()
                encode['samples'][0]['details']['counters'][name] = invalid
                with self.subTest(name=name, value=invalid), self.assertRaises(ValueError):
                    detail.validate(encode, substage, primary, digest)
        primary, substage, encode, _, digest = self.fixture()
        encode['samples'][0]['details']['counters']['vertex_bytes'] = 2**64 - 1
        result = detail.summarize(encode, substage, primary, digest)
        self.assertEqual(result['counters']['vertex_bytes']['total'], 2**64 - 1)

    def test_sample_sets_require_exact_distinct_ordered_joins(self):
        mutations = [lambda s: s.clear(), lambda s: s.append(copy.deepcopy(s[-1])),
                     lambda s: s[0].update(record_index=True), lambda s: s[0].update(record_index=-1),
                     lambda s: s[0].update(record_index=0), lambda s: s[0].update(record_index=2**64)]
        for mutate in mutations:
            primary, substage, encode, _, digest = self.fixture()
            mutate(encode['samples'])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                detail.validate(encode, substage, primary, digest)
        for mutate in (lambda s: s.reverse(), lambda s: s[1].update(record_index=1)):
            primary, substage, encode, _, _ = self.fixture()
            append_attempt(primary, substage, encode)
            _, digest = rebind(primary, substage, encode)
            mutate(encode['samples'])
            with self.assertRaisesRegex(ValueError, 'distinct ordered'):
                detail.validate(encode, substage, primary, digest)

    def test_summary_nearest_rank_and_totals_use_only_complete_observations(self):
        primary, substage, encode, _, _ = self.fixture()
        append_attempt(primary, substage, encode)
        encode['samples'][1]['details']['spans'][0].update(ended_at_ns=246, duration_ns=1)
        encode['samples'][1]['details']['counters']['prepared_draws'] = 9
        _, digest = rebind(primary, substage, encode)
        result = detail.summarize(encode, substage, primary, digest)
        stats = result['stages']['frame_plan']['per_frame_total_ns']
        self.assertEqual((stats['sample_count'], stats['p50_ns'], stats['p95_ns'], stats['total_ns']),
                         (2, 1, 2, 3))
        counters = result['counters']['prepared_draws']
        self.assertEqual((counters['sample_count'], counters['p50'], counters['p95'], counters['total']),
                         (2, 1, 9, 10))
        self.assertEqual(counters['percentile_method'], frames.METHOD)


class CpuEncodeDetailCliTests(unittest.TestCase):
    fixture = staticmethod(fixture)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.primary, self.substage, self.encode = [self.root / name for name in (
            'frames.json', 'frames.cpu-substages.json', 'frames.cpu-encode-detail.json')]
        self.output = self.root / 'summary.json'
        primary, substage, encode, data, _ = self.fixture()
        self.primary.write_bytes(data)
        self.substage.write_text(json.dumps(substage), encoding='utf-8')
        self.encode.write_text(json.dumps(encode), encoding='utf-8')

    def cli(self, output=False):
        command = [sys.executable, str(Path(detail.__file__).resolve()),
                   str(self.primary), str(self.substage), str(self.encode)]
        if output:
            command += ['--output', str(self.output)]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def test_actual_cli_success_and_exclusive_output_preserve_existing_bytes(self):
        result = self.cli(output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['summarized_attempts'], 1)
        before = self.output.read_bytes()
        self.assertEqual(json.loads(before), json.loads(result.stdout))
        result = self.cli(output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.output.read_bytes(), before)

    def test_exact_original_primary_bytes_not_reserialized_semantics_are_hashed(self):
        self.assertEqual(self.cli().returncode, 0)
        self.primary.write_bytes(self.primary.read_bytes() + b' ')
        result = self.cli(output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('binding differs', result.stdout)
        self.assertFalse(self.output.exists())

    def test_duplicate_fields_in_any_input_reach_actual_cli_and_fail_without_output(self):
        for path, field in ((self.primary, 'schema'), (self.substage, 'schema'), (self.encode, 'schema')):
            before = path.read_bytes()
            path.write_bytes(b'{"' + field.encode() + b'": "duplicate",' + before[1:])
            with self.subTest(path=path):
                result = self.cli(output=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn('duplicate JSON field', result.stdout)
                self.assertFalse(self.output.exists())
            path.write_bytes(before)

    def test_nonfinite_numbers_duplicate_nested_counter_and_invalid_utf8_fail(self):
        before = self.encode.read_bytes()
        for data in (before.replace(b'"prepared_draws": 1', b'"prepared_draws": NaN'),
                     before.replace(b'"prepared_draws": 1', b'"prepared_draws": 1e999'),
                     before.replace(b'"prepared_draws": 1', b'"prepared_draws": 1, "prepared_draws": 2'),
                     b'\xff'):
            self.encode.write_bytes(data)
            with self.subTest(data=data[:30]):
                self.assertEqual(self.cli(output=True).returncode, 1)
                self.assertFalse(self.output.exists())

    def test_bad_join_and_unknown_phase_fail_actual_cli(self):
        original = json.loads(self.encode.read_text())
        for mutation in ('join', 'phase'):
            value = copy.deepcopy(original)
            if mutation == 'join':
                value['samples'][0]['record_index'] = 0
            else:
                value['samples'][0]['details']['spans'][0]['stage'] = 'gpu_time'
            self.encode.write_text(json.dumps(value))
            with self.subTest(mutation=mutation):
                self.assertEqual(self.cli(output=True).returncode, 1)
                self.assertFalse(self.output.exists())

    def test_incomplete_primary_exits_failure_and_emits_no_complete_distributions(self):
        primary = json.loads(self.primary.read_text())
        substage = json.loads(self.substage.read_text())
        encode = json.loads(self.encode.read_text())
        primary.update(incomplete_at_ns=205, status={'state': 'incomplete', 'error': 'synthetic failure'})
        data, _ = rebind(primary, substage, encode)
        self.primary.write_bytes(data)
        self.substage.write_text(json.dumps(substage))
        self.encode.write_text(json.dumps(encode))
        result = self.cli(output=True)
        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertEqual(summary['diagnostic_status'], 'incomplete')
        self.assertEqual(summary['summarized_attempts'], 0)
        self.assertIsNone(summary['stages']['queue_submit']['per_frame_total_ns']['p99_ns'])

    def test_incomplete_detail_exits_failure_and_retains_partial_values_only_in_source(self):
        value = json.loads(self.encode.read_text())
        value['samples'][0]['details'].update(state='incomplete', error='encode_incomplete')
        value['samples'][0]['details']['spans'] = value['samples'][0]['details']['spans'][:2]
        self.encode.write_text(json.dumps(value))
        before = self.encode.read_bytes()
        result = self.cli(output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['summarized_attempts'], 0)
        self.assertEqual(self.encode.read_bytes(), before)

    def test_symlink_inputs_missing_files_and_existing_output_symlinks_are_rejected(self):
        for path in (self.primary, self.substage, self.encode):
            original = path.read_bytes()
            target = self.root / (path.name + '.real')
            path.rename(target)
            try:
                path.symlink_to(target)
            except OSError as error:
                self.skipTest(str(error))
            with self.subTest(path=path):
                self.assertEqual(self.cli(output=True).returncode, 1)
                self.assertFalse(self.output.exists())
            path.unlink()
            path.write_bytes(original)
        sentinel = self.root / 'untouched.json'
        sentinel.write_text('untouched')
        self.output.symlink_to(sentinel)
        self.assertEqual(self.cli(output=True).returncode, 1)
        self.assertEqual(sentinel.read_text(), 'untouched')
        self.output.unlink()
        self.encode.unlink()
        self.assertEqual(self.cli(output=True).returncode, 1)
        self.assertFalse(self.output.exists())

    def test_bounded_reader_checks_bytes_before_parsing(self):
        # Reuse the production reader with a tiny bound rather than allocating
        # a half-gigabyte fixture; the ordinary CLI valid controls run separately.
        with mock.patch.object(frames, 'MAX_REPORT_BYTES', 32):
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                detail.read_json(self.primary)

    def test_contradictory_descriptor_reaches_actual_cli_after_hash_is_repaired(self):
        primary = json.loads(self.primary.read_text())
        substage = json.loads(self.substage.read_text())
        encode = json.loads(self.encode.read_text())
        primary['identity']['runtime_observed']['actual_adapter']['instance_descriptor']['debug'] = False
        data, _ = rebind(primary, substage, encode)
        self.primary.write_bytes(data)
        self.substage.write_text(json.dumps(substage))
        self.encode.write_text(json.dumps(encode))
        result = self.cli(output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('flag differs', result.stdout)
        self.assertFalse(self.output.exists())

    def test_missing_substage_file_is_not_silently_optional(self):
        self.substage.unlink()
        result = self.cli(output=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.output.exists())


class CpuEncodeDetailV2Tests(CpuEncodeDetailTests):
    fixture = staticmethod(v2_fixture)
    counter_names = V2_COUNTERS

    def test_both_upload_policies_preserve_identity_and_exact_fifteen_counters(self):
        for policy in ('bounded_reuse_v1', 'immutable_per_frame_v1'):
            primary, substage, encode, _, digest = v2_fixture(policy)
            with self.subTest(policy=policy):
                result = detail.summarize(encode, substage, primary, digest)
                self.assertEqual(result['schema'], 'rust_duty_cpu_encode_detail_v2')
                self.assertEqual(result['upload_policy'], policy)
                self.assertEqual(tuple(result['counters']), V2_COUNTERS)
                self.assertEqual(len(result['counters']), 15)
                for index, name in enumerate(V2_COUNTERS, 1):
                    self.assertEqual(result['counters'][name]['total'], index)
                    self.assertEqual(result['counters'][name]['sample_count'], 1)

    def test_policy_is_required_exact_and_not_inferred_from_counters(self):
        primary, substage, original, _, digest = v2_fixture()
        for policy in ('unknown', 'bounded_reuse_v2', '', None, 0, True, [], {}):
            encode = copy.deepcopy(original)
            encode['upload_policy'] = policy
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, 'upload_policy'):
                detail.validate(encode, substage, primary, digest)
        encode = copy.deepcopy(original)
        del encode['upload_policy']
        with self.assertRaisesRegex(ValueError, 'sidecar fields differ'):
            detail.validate(encode, substage, primary, digest)

    def test_new_counters_are_per_attempt_sums_not_last_value_gauges(self):
        primary, substage, encode, _, _ = v2_fixture()
        append_attempt(primary, substage, encode)
        for name in V2_COUNTERS[10:]:
            encode['samples'][0]['details']['counters'][name] = 2**64 - 1
            encode['samples'][1]['details']['counters'][name] = 7
        _, digest = rebind(primary, substage, encode)
        result = detail.summarize(encode, substage, primary, digest)
        for name in V2_COUNTERS[10:]:
            self.assertEqual(result['counters'][name]['total'], 2**64 + 6)
            self.assertEqual(result['counters'][name]['sample_count'], 2)
            self.assertEqual(result['counters'][name]['min'], 7)


class CpuEncodeDetailVersionTests(unittest.TestCase):
    def test_v1_complete_and_incomplete_summaries_replay_exact_historical_bytes(self):
        # SHA-256 of pretty-printed summaries from the unmodified v1 reader,
        # recorded before v2 was added. No v2 key, zero-fill or relabel is allowed.
        for incomplete, expected in (
                (False, 'b9b5f611b3606969351b303f642f4456da1d6f4177174c0325dad4cb149081b7'),
                (True, '28be570f95e4953c855249c6f9625dd62a28bf848332b85b0a58444ebd73506b')):
            primary, substage, encode, _, digest = fixture()
            if incomplete:
                encode['samples'][0]['details'].update(
                    state='incomplete', error='encode_incomplete', spans=[])
            result = detail.summarize(encode, substage, primary, digest)
            raw = (json.dumps(result, indent=2, allow_nan=False) + '\n').encode('utf-8')
            with self.subTest(incomplete=incomplete):
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)
                self.assertEqual(result['schema'], 'rust_duty_cpu_encode_detail_v1')
                self.assertEqual(tuple(result['counters']), V1_COUNTERS)
                self.assertNotIn('upload_policy', result)

    def test_each_counter_is_required_and_unknown_keys_fail_on_both_row_states(self):
        for make_fixture, names in ((fixture, V1_COUNTERS), (v2_fixture, V2_COUNTERS)):
            for incomplete in (False, True):
                primary, substage, original, _, digest = make_fixture()
                if incomplete:
                    original['samples'][0]['details'].update(
                        state='incomplete', error='encode_incomplete', spans=[])
                detail.validate(original, substage, primary, digest)  # Valid control first.
                for name in names:
                    encode = copy.deepcopy(original)
                    del encode['samples'][0]['details']['counters'][name]
                    with self.subTest(schema=encode['schema'], incomplete=incomplete, missing=name):
                        with self.assertRaisesRegex(ValueError, 'encode counters fields differ'):
                            detail.validate(encode, substage, primary, digest)
                encode = copy.deepcopy(original)
                encode['samples'][0]['details']['counters']['retained_gpu_bytes'] = 0
                with self.subTest(schema=encode['schema'], incomplete=incomplete, unknown=True):
                    with self.assertRaisesRegex(ValueError, 'encode counters fields differ'):
                        detail.validate(encode, substage, primary, digest)

    def test_versions_cannot_mix_counter_sets_or_borrow_policy_identity(self):
        for make_fixture, wrong_names in ((fixture, V2_COUNTERS), (v2_fixture, V1_COUNTERS)):
            primary, substage, encode, _, _ = make_fixture()
            append_attempt(primary, substage, encode)
            _, digest = rebind(primary, substage, encode)
            detail.validate(encode, substage, primary, digest)
            encode['samples'][1]['details']['counters'] = dict.fromkeys(wrong_names, 0)
            with self.subTest(schema=encode['schema']), self.assertRaisesRegex(
                    ValueError, 'encode counters fields differ'):
                detail.validate(encode, substage, primary, digest)
        primary, substage, encode, _, digest = fixture()
        encode['upload_policy'] = 'immutable_per_frame_v1'
        with self.assertRaisesRegex(ValueError, 'sidecar fields differ'):
            detail.validate(encode, substage, primary, digest)


class CpuEncodeDetailV2CliTests(CpuEncodeDetailCliTests):
    fixture = staticmethod(v2_fixture)

    def test_v2_policy_and_fifteen_counters_survive_actual_cli(self):
        result = self.cli(output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary['schema'], 'rust_duty_cpu_encode_detail_v2')
        self.assertEqual(summary['upload_policy'], 'bounded_reuse_v1')
        self.assertEqual(tuple(summary['counters']), V2_COUNTERS)

    def test_missing_unknown_wrong_type_and_negative_v2_fields_fail_actual_cli(self):
        original = json.loads(self.encode.read_text())
        mutations = [lambda e: e.pop('upload_policy'),
                     lambda e: e.update(upload_policy='unknown'),
                     lambda e: e['samples'][0]['details']['counters'].pop('gpu_buffer_allocations'),
                     lambda e: e['samples'][0]['details']['counters'].update(retained_gpu_bytes=0),
                     lambda e: e['samples'][0]['details']['counters'].update(gpu_buffer_reuses=True),
                     lambda e: e['samples'][0]['details']['counters'].update(gpu_buffer_allocated_bytes=-1)]
        for mutate in mutations:
            encode = copy.deepcopy(original)
            mutate(encode)
            self.encode.write_text(json.dumps(encode), encoding='utf-8')
            with self.subTest(mutate=mutate):
                self.assertEqual(self.cli(output=True).returncode, 1)
                self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
