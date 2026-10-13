"""Independent cross-attempt regressions for the separately versioned CPU detail.

All data are synthetic. No desktop, graphics adapter or timing claim is involved.
"""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import summarize_cpu_encode_detail as encode
import summarize_cpu_substages as substages
import summarize_frame_performance as frames
from test_summarize_cpu_encode_detail import fixture, rebind
from test_summarize_cpu_substages import fixture as historical_fixture

U64_MAX = 2**64 - 1


def attempts(count):
    """Extend the existing control without reusing its fixed second-row index."""
    primary, substage, detail, _, _ = fixture()
    parent_template = copy.deepcopy(primary['cpu_frame_stages']['samples'][0])
    child_templates = [copy.deepcopy(s['samples'][0]) for s in (substage, detail)]
    for index in range(2, count + 1):
        offset = 100 * (index - 1)
        primary['records'].append({'kind': 'successful_present_return', 'at_ns': 200 + offset,
                                  'eligible': True, 'ineligible_reason': None, 'interval_ns': 100})
        parent = copy.deepcopy(parent_template)
        parent.update(record_index=index, started_at_ns=105 + offset, finished_at_ns=200 + offset)
        for span in parent['spans'].values():
            span['started_at_ns'] += offset
            span['ended_at_ns'] += offset
        primary['cpu_frame_stages']['samples'].append(parent)
        for sidecar, template in zip((substage, detail), child_templates):
            child = copy.deepcopy(template)
            child['record_index'] = index
            for span in child['details']['spans']:
                span['started_at_ns'] += offset
                span['ended_at_ns'] += offset
            sidecar['samples'].append(child)
    end = 100 * (count + 1)
    primary.update(successful_present_count=count + 1, last_observed_ns=end,
                   stop_requested_ns=end + 10, stopped_at_ns=end + 10)
    primary['summary'].update(interval_count=count, total_interval_ns=count * 100)
    data, digest = rebind(primary, substage, detail)
    frames.validate_report(primary)
    return primary, substage, detail, data, digest


class IndependentCpuEncodeTests(unittest.TestCase):
    def test_original_substage_v1_needs_no_new_metadata_or_detail_sidecar(self):
        primary, child, _, digest = historical_fixture()
        self.assertEqual(child['schema'], 'rust_duty_cpu_substages_v1')
        self.assertNotIn('instance_descriptor', primary['identity']['runtime_observed']['actual_adapter'])
        before = copy.deepcopy((primary, child))
        result = substages.summarize(child, primary, digest)
        self.assertEqual(result['diagnostic_status'], 'complete')
        self.assertEqual(result['stages']['encode_submit']['per_frame_total_ns']['p50_ns'], 20)
        self.assertEqual((primary, child), before)
        self.assertEqual(set(result['stages']), set(substages.PARENTS))

    def test_mixed_incomplete_cohorts_cannot_leak_partial_counter_totals(self):
        primary, child, detail, _, digest = attempts(3)
        detail['samples'][1]['details'].update(state='incomplete', error='encode_incomplete')
        child['samples'][2]['details'].update(state='incomplete', error='unterminated_substage')
        for row in detail['samples'][1:]:
            row['details']['counters'] = dict.fromkeys(encode.COUNTERS, U64_MAX)
        original = copy.deepcopy((primary, child, detail))
        result = encode.summarize(detail, child, primary, digest)
        self.assertEqual((result['retained_attempts'], result['summarized_attempts']), (3, 1))
        self.assertEqual((result['incomplete_detail_attempts'], result['incomplete_substage_attempts']), (1, 1))
        self.assertEqual(result['diagnostic_status'], 'incomplete')
        for index, name in enumerate(encode.COUNTERS, 1):
            self.assertEqual(result['counters'][name]['sample_count'], 1)
            self.assertEqual(result['counters'][name]['total'], index)
        for stage in result['stages'].values():
            self.assertEqual(stage['per_frame_total_ns']['sample_count'], 1)
        self.assertEqual((primary, child, detail), original)

    def test_all_counter_aggregates_are_exact_above_u64_without_wrapping(self):
        primary, child, detail, _, digest = attempts(2)
        for row in detail['samples']:
            row['details']['counters'] = dict.fromkeys(encode.COUNTERS, U64_MAX)
        result = encode.summarize(detail, child, primary, digest)
        for name in encode.COUNTERS:
            stats = result['counters'][name]
            self.assertEqual(stats['sample_count'], 2)
            self.assertEqual(stats['total'], 2 * U64_MAX)
            for key in ('min', 'max', 'p50', 'p95', 'p99'):
                self.assertEqual(stats[key], U64_MAX)
        self.assertEqual(json.loads(json.dumps(result))['counters']['prepared_draws']['total'], 2 * U64_MAX)

    def test_three_attempt_nearest_rank_uses_frame_observations_not_phase_pooling(self):
        primary, child, detail, _, digest = attempts(3)
        for row, duration, count in zip(detail['samples'], (2, 0, 1), (9, 0, 4)):
            phase = row['details']['spans'][0]
            phase.update(ended_at_ns=phase['started_at_ns'] + duration, duration_ns=duration)
            row['details']['counters']['prepared_draws'] = count
        result = encode.summarize(detail, child, primary, digest)
        times = result['stages']['frame_plan']['per_frame_total_ns']
        counts = result['counters']['prepared_draws']
        self.assertEqual((times['sample_count'], times['total_ns'], times['p50_ns'], times['p95_ns'], times['p99_ns']),
                         (3, 3, 1, 2, 2))
        self.assertEqual((counts['sample_count'], counts['total'], counts['p50'], counts['p95'], counts['p99']),
                         (3, 13, 4, 9, 9))
        self.assertEqual(times['percentile_method'], frames.METHOD)
        self.assertEqual(counts['percentile_method'], frames.METHOD)

    def test_every_valid_descriptor_bit_pattern_is_independent_of_application_profile(self):
        primary, child, detail, _, _ = fixture()
        descriptor = primary['identity']['runtime_observed']['actual_adapter']['instance_descriptor']
        for bits in range(256):
            for debug_assertions in (False, True):
                descriptor.update(flags_bits=bits, application_debug_assertions=debug_assertions)
                for name, mask in encode.INSTANCE_FLAGS.items():
                    descriptor[name] = bool(bits & mask)
                _, digest = rebind(primary, child, detail)
                with self.subTest(bits=bits, application=debug_assertions):
                    encode.validate(detail, child, primary, digest)

    def test_each_independent_flag_contradiction_fails_after_honest_rebinding(self):
        for bits in (0, 16, 32, 35, 255):
            for name in encode.INSTANCE_FLAGS:
                primary, child, detail, _, _ = fixture()
                descriptor = primary['identity']['runtime_observed']['actual_adapter']['instance_descriptor']
                descriptor['flags_bits'] = bits
                for key, mask in encode.INSTANCE_FLAGS.items():
                    descriptor[key] = bool(bits & mask)
                descriptor[name] = not descriptor[name]
                _, digest = rebind(primary, child, detail)
                with self.subTest(bits=bits, flag=name), self.assertRaisesRegex(ValueError, 'flag differs'):
                    encode.validate(detail, child, primary, digest)

    def test_error_limit_counts_utf8_bytes_and_accepts_its_exact_boundary(self):
        for error, allowed in (('é' * 128, True), ('é' * 129, False),
                               ('🧭' * 64, True), ('🧭' * 65, False)):
            primary, child, detail, _, digest = fixture()
            detail['samples'][0]['details'].update(state='incomplete', error=error)
            with self.subTest(length=len(error.encode('utf-8'))):
                if allowed:
                    result = encode.summarize(detail, child, primary, digest)
                    self.assertEqual(result['summarized_attempts'], 0)
                    self.assertEqual(result['diagnostic_status'], 'incomplete')
                else:
                    with self.assertRaisesRegex(ValueError, 'diagnostic state'):
                        encode.validate(detail, child, primary, digest)

    def test_empty_incomplete_detail_preserves_unavailable_instead_of_observed_zero(self):
        primary, child, detail, _, digest = fixture()
        row = detail['samples'][0]['details']
        row.update(state='incomplete', error='encode_not_observed', spans=[])
        row['counters'] = dict.fromkeys(encode.COUNTERS, 0)
        result = encode.summarize(detail, child, primary, digest)
        self.assertEqual(result['summarized_attempts'], 0)
        for counter in result['counters'].values():
            self.assertEqual(counter['sample_count'], 0)
            self.assertEqual(counter['total'], 0)
            self.assertIsNone(counter['min'])
            self.assertIsNone(counter['p99'])
        for phase in result['stages'].values():
            self.assertIsNone(phase['per_frame_total_ns']['p50_ns'])

    def test_partial_error_never_weakens_the_available_encode_parent_end(self):
        primary, child, detail, _, digest = fixture()
        row = detail['samples'][0]['details']
        row.update(state='incomplete', error='encode_phase_outside_parent')
        final = row['spans'][-1]
        final.update(ended_at_ns=166, duration_ns=6)  # Inside renderer [140,180], outside encode [145,165].
        with self.assertRaisesRegex(ValueError, 'outside'):
            encode.validate(detail, child, primary, digest)

    def test_substage_binding_is_required_even_when_detail_digest_matches(self):
        primary, child, detail, _, digest = fixture()
        child['frame_report_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'substage binding'):
            encode.validate(detail, child, primary, digest)

    def test_formatted_primary_requires_both_sidecars_to_follow_exact_new_bytes(self):
        primary, child, detail, _, old_digest = fixture()
        raw = (json.dumps(primary, indent=2) + '\r\n').encode('utf-8')
        fresh_digest = hashlib.sha256(raw).hexdigest()
        self.assertNotEqual(fresh_digest, old_digest)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frames.json'
            path.write_bytes(raw)
            parsed, actual_digest = encode.read_json(path)
            self.assertEqual(parsed, primary)
            self.assertEqual(actual_digest, fresh_digest)
            for repaired in ((), ('detail',), ('substage',)):
                current_child, current_detail = copy.deepcopy((child, detail))
                if 'detail' in repaired:
                    current_detail['frame_report_sha256'] = fresh_digest
                if 'substage' in repaired:
                    current_child['frame_report_sha256'] = fresh_digest
                with self.subTest(repaired=repaired), self.assertRaisesRegex(ValueError, 'binding differs'):
                    encode.validate(current_detail, current_child, parsed, actual_digest)
            child['frame_report_sha256'] = detail['frame_report_sha256'] = fresh_digest
            self.assertEqual(encode.summarize(detail, child, parsed, actual_digest)['summarized_attempts'], 1)
            self.assertEqual(path.read_bytes(), raw)

    def test_cli_rejects_lone_surrogate_in_error_without_writing_summary(self):
        primary, child, detail, data, _ = fixture()
        detail['samples'][0]['details'].update(state='incomplete', error='\ud800')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ('frames.json', 'substage.json', 'detail.json')]
            paths[0].write_bytes(data)
            paths[1].write_text(json.dumps(child), encoding='utf-8')
            paths[2].write_text(json.dumps(detail), encoding='utf-8')
            output = root / 'summary.json'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(encode.main([*map(str, paths), '--output', str(output)]), 1)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
