"""Synthetic CPU evidence contracts; never GPU performance measurements."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import summarize_cpu_substages as detail
import summarize_frame_performance as frames
from test_summarize_frame_performance import with_cpu_stages


def span(stage, begin, end):
    return {'stage': stage, 'parent': detail.PARENTS[stage],
            'started_at_ns': begin, 'ended_at_ns': end, 'duration_ns': end - begin}


def fixture():
    report = with_cpu_stages()
    data = json.dumps(report).encode()
    digest = hashlib.sha256(data).hexdigest()
    sidecar = {'schema': detail.SCHEMA, 'measurement': detail.MEASUREMENT,
               'interpretation': detail.INTERPRETATION, 'frame_report_sha256': digest,
               'frame_status': copy.deepcopy(report['status']), 'samples': [
                   {'record_index': 1, 'details': {'state': 'complete', 'error': None, 'spans': [
                       span('acquire_texture', 110, 114), span('acquire_validation_cpu', 114, 115),
                       span('acquire_texture', 115, 118), span('acquire_validation_cpu', 118, 120),
                       span('encode_submit', 145, 165), span('submit_validation_cpu', 166, 179)]}}]}
    return report, sidecar, data, digest


class CpuSubstageTests(unittest.TestCase):
    def test_exact_parent_binding_and_per_frame_totals_keep_original_schema(self):
        report, sidecar, _, digest = fixture()
        original = copy.deepcopy(report)
        result = detail.summarize(sidecar, report, digest)
        self.assertEqual(result['stages']['acquire_texture']['observed_calls'], 2)
        self.assertEqual(result['stages']['acquire_texture']['per_frame_total_ns']['p95_ns'], 7)
        self.assertEqual(result['stages']['submit_validation_cpu']['per_frame_total_ns']['p50_ns'], 13)
        self.assertEqual(report, original)
        frames.validate_report(report)  # Historical strict parser remains unchanged.
        self.assertNotIn('gpu_duration', result)

    def test_missing_calls_remain_unavailable_not_zero(self):
        report, sidecar, _, digest = fixture()
        sidecar['samples'][0]['details']['spans'] = []
        result = detail.summarize(sidecar, report, digest)
        for stage in result['stages'].values():
            self.assertEqual(stage['observed_calls'], 0)
            self.assertIsNone(stage['per_frame_total_ns']['p50_ns'])

    def test_zero_length_call_is_a_real_sample(self):
        report, sidecar, _, digest = fixture()
        sidecar['samples'][0]['details']['spans'] = [span('encode_submit', 145, 145)]
        result = detail.summarize(sidecar, report, digest)
        self.assertEqual(result['stages']['encode_submit']['per_frame_total_ns']['p50_ns'], 0)

    def test_incomplete_details_do_not_enter_summary(self):
        report, sidecar, _, digest = fixture()
        sidecar['samples'][0]['details'].update(state='incomplete', error='unterminated_substage')
        result = detail.summarize(sidecar, report, digest)
        self.assertEqual(result['diagnostic_status'], 'incomplete')
        self.assertEqual(result['incomplete_detail_attempts'], 1)
        self.assertEqual(result['stages']['encode_submit']['observed_calls'], 0)

    def test_missing_parent_requires_explicit_incomplete_detail(self):
        report, sidecar, _, digest = fixture()
        report['cpu_frame_stages']['samples'][0]['spans']['surface_acquire'] = None
        with self.assertRaisesRegex(ValueError, 'no complete parent'):
            detail.validate(sidecar, report, digest)
        sidecar['samples'][0]['details'].update(state='incomplete', error='parent_span_unavailable')
        result = detail.summarize(sidecar, report, digest)
        self.assertEqual(result['diagnostic_status'], 'incomplete')

    def test_wrong_digest_status_identity_and_unknown_fields_fail_closed(self):
        mutations = [lambda s: s.update(frame_report_sha256='0' * 64),
                     lambda s: s.update(frame_status={'state': 'incomplete', 'error': 'fake'}),
                     lambda s: s.update(schema='GPU timing'),
                     lambda s: s.update(unexpected=True),
                     lambda s: s['samples'][0].update(record_index=True),
                     lambda s: s['samples'][0].update(record_index=0),
                     lambda s: s.update(samples=[]),
                     lambda s: s['samples'].append(copy.deepcopy(s['samples'][0])),
                     lambda s: s['samples'][0]['details'].update(error='hidden-error')]
        for mutate in mutations:
            report, sidecar, _, digest = fixture()
            mutate(sidecar)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                detail.validate(sidecar, report, digest)

    def test_bad_duration_parent_overlap_extent_and_stage_count_fail(self):
        mutations = [lambda s: s[0].update(duration_ns=99),
                     lambda s: s[0].update(started_at_ns=True),
                     lambda s: s[0].update(parent='renderer_submit'),
                     lambda s: s[0].update(started_at_ns=109, duration_ns=5),
                     lambda s: s[1].update(started_at_ns=113, duration_ns=2),
                     lambda s: s[1].update(ended_at_ns=121, duration_ns=7),
                     lambda s: s[0].update(stage='gpu_time'),
                     lambda s: s.reverse(),
                     lambda s: s.append(copy.deepcopy(s[-1]))]
        for mutate in mutations:
            report, sidecar, _, digest = fixture()
            mutate(sidecar['samples'][0]['details']['spans'])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                detail.validate(sidecar, report, digest)

    def test_third_acquisition_pair_is_rejected_at_six_not_just_seven_spans(self):
        report, sidecar, _, digest = fixture()
        sidecar['samples'][0]['details']['spans'] = [
            span(name, 110 + i, 111 + i) for i, name in enumerate([
                'acquire_texture', 'acquire_validation_cpu'] * 3)]
        with self.assertRaisesRegex(ValueError, 'too many'):
            detail.validate(sidecar, report, digest)

    def test_explicit_outside_parent_error_retains_failed_evidence_without_summary(self):
        report, sidecar, _, digest = fixture()
        sample = sidecar['samples'][0]['details']
        sample['spans'] = [span('acquire_texture', 110, 250)]
        with self.assertRaisesRegex(ValueError, 'inside their parent'):
            detail.validate(sidecar, report, digest)
        sample.update(state='incomplete', error='substage_outside_parent')
        result = detail.summarize(sidecar, report, digest)
        self.assertEqual(result['diagnostic_status'], 'incomplete')
        self.assertEqual(result['stages']['acquire_texture']['observed_calls'], 0)

    def test_cli_reads_hashed_bytes_once_and_refuses_overwriting_output(self):
        report, sidecar, data, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, diagnostic, output = root / 'frames.json', root / 'detail.json', root / 'summary.json'
            primary.write_bytes(data)
            diagnostic.write_text(json.dumps(sidecar))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(detail.main([str(primary), str(diagnostic), '--output', str(output)]), 0)
                before = output.read_bytes()
                self.assertEqual(detail.main([str(primary), str(diagnostic), '--output', str(output)]), 1)
                self.assertEqual(output.read_bytes(), before)
                primary.write_bytes(data + b' ')
                self.assertEqual(detail.main([str(primary), str(diagnostic)]), 1)

    def test_reader_rejects_duplicate_keys_nonfinite_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'bad.json'
            for data in ('{"x":1,"x":2}', '{"x":NaN}'):
                path.write_text(data)
                with self.assertRaises(ValueError):
                    detail.read_json(path)
            link = root / 'link.json'
            try:
                link.symlink_to(path)
            except OSError as error:
                self.skipTest(str(error))
            with self.assertRaises(ValueError):
                detail.read_json(link)


if __name__ == '__main__':
    unittest.main()
