#!/usr/bin/env python3
"""Validate optional CPU substage sidecars without changing frames.json acceptance."""
import argparse
import hashlib
import json
from pathlib import Path

from exclusive_output import write_text_exclusive
import summarize_frame_performance as frames

SCHEMA = 'rust_duty_cpu_substages_v1'
MEASUREMENT = 'cpu_wall_clock_nested_frame_substage_ns'
INTERPRETATION = ('CPU call durations inside existing parent spans, not GPU time. '
                 'Validation CPU is the existing error-scope pop and pollster wrapper, not a GPU completion wait. '
                 'Missing calls are unavailable, not zero; parent and child times must not be added.')
PARENTS = {'acquire_texture': 'surface_acquire',
           'acquire_validation_cpu': 'surface_acquire',
           'encode_submit': 'renderer_submit',
           'submit_validation_cpu': 'renderer_submit'}
NEXT = {None: {'acquire_texture', 'encode_submit'},
        'acquire_texture': {'acquire_validation_cpu'},
        'acquire_validation_cpu': {'acquire_texture', 'encode_submit'},
        'encode_submit': {'submit_validation_cpu'},
        'submit_validation_cpu': set()}
ERRORS = {'overlapping_or_excess_substage', 'non_monotonic_substage',
          'unexpected_substage_order_or_count', 'unopened_substage',
          'mismatched_or_non_monotonic_substage', 'unterminated_substage',
          'substage_parent_mismatch', 'parent_span_unavailable', 'substage_outside_parent'}


def read_json(path):
    path = Path(path)
    frames._require(path.is_file() and not path.is_symlink(), 'expected regular nonsymlink evidence')
    with path.open('rb') as source:
        data = source.read(frames.MAX_REPORT_BYTES + 1)
    frames._require(len(data) <= frames.MAX_REPORT_BYTES, 'evidence exceeds 512 MiB')
    value = json.loads(data.decode('utf-8'), object_pairs_hook=frames._unique,
                       parse_constant=frames._constant)
    frames._finite_tree(value)
    return value, hashlib.sha256(data).hexdigest()


def validate(sidecar, report, report_sha256):
    frames.validate_report(report)
    frames._finite_tree(sidecar)
    frames._object(sidecar, ('schema', 'measurement', 'interpretation',
                            'frame_report_sha256', 'frame_status', 'samples'), 'CPU substage sidecar')
    for field, expected in (('schema', SCHEMA), ('measurement', MEASUREMENT),
                            ('interpretation', INTERPRETATION),
                            ('frame_report_sha256', report_sha256),
                            ('frame_status', report['status'])):
        frames._require(sidecar[field] == expected, 'CPU substage binding differs: ' + field)
    parents = report.get('cpu_frame_stages', {}).get('samples')
    samples = sidecar['samples']
    frames._require(isinstance(parents, list) and parents, 'parent CPU stages unavailable')
    frames._require(isinstance(samples, list) and len(samples) == len(parents),
                    'substage samples must exactly match retained parent attempts')
    for sample, parent in zip(samples, parents):
        frames._object(sample, ('record_index', 'details'), 'substage sample')
        frames._uint(sample['record_index'], 'substage record index')
        frames._require(sample['record_index'] == parent['record_index'], 'substage record index differs')
        details = sample['details']
        frames._object(details, ('state', 'error', 'spans'), 'substage details')
        frames._require((details['state'] == 'complete' and details['error'] is None)
                        or (details['state'] == 'incomplete' and isinstance(details['error'], str)
                            and details['error'] in ERRORS),
                        'invalid substage diagnostic state')
        spans = details['spans']
        frames._require(isinstance(spans, list) and len(spans) <= 6, 'substage capacity exceeded')
        previous, end, counts = None, parent['started_at_ns'], dict.fromkeys(PARENTS, 0)
        for span in spans:
            frames._object(span, ('stage', 'parent', 'started_at_ns', 'ended_at_ns', 'duration_ns'),
                           'substage span')
            stage = span['stage']
            frames._require(isinstance(stage, str) and stage in PARENTS, 'unknown CPU substage')
            frames._require(stage in NEXT[previous], 'CPU substages out of order')
            counts[stage] += 1
            frames._require(counts[stage] <= (2 if stage.startswith('acquire_') else 1),
                            'CPU substage repeated too many times')
            frames._require(span['parent'] == PARENTS[stage], 'CPU substage parent differs')
            outer = parent['spans'][PARENTS[stage]]
            if outer is None:
                frames._require(details['state'] == 'incomplete'
                                and details['error'] == 'parent_span_unavailable',
                                'CPU substage has no complete parent span')
                outer = {'started_at_ns': parent['started_at_ns'],
                         'ended_at_ns': parent['finished_at_ns']}
            begin = frames._uint(span['started_at_ns'], 'substage start')
            finish = frames._uint(span['ended_at_ns'], 'substage end')
            duration = frames._uint(span['duration_ns'], 'substage duration')
            contained = outer['started_at_ns'] <= begin and finish <= outer['ended_at_ns']
            explicitly_invalid = (details['state'] == 'incomplete'
                                  and details['error'] == 'substage_outside_parent')
            frames._require(end <= begin <= finish and (contained or explicitly_invalid),
                            'CPU substages must be disjoint and inside their parent spans')
            frames._require(duration == finish - begin, 'substage duration differs')
            previous, end = stage, finish
    return sidecar


def statistics(values):
    values = sorted(values)
    return {'sample_count': len(values), 'total_ns': sum(values),
            'min_ns': values[0] if values else None, 'max_ns': values[-1] if values else None,
            **{f'p{p}_ns': values[(len(values) * p + 99) // 100 - 1] if values else None
               for p in (50, 95, 99)}, 'percentile_method': frames.METHOD}


def summarize(sidecar, report, report_sha256):
    validate(sidecar, report, report_sha256)
    values = {stage: [] for stage in PARENTS}
    calls = dict.fromkeys(PARENTS, 0)
    incomplete = 0
    for sample in sidecar['samples']:
        details = sample['details']
        if details['state'] != 'complete':
            incomplete += 1
            continue
        record = report['records'][sample['record_index']]
        if (record['kind'] != 'successful_present_return' or not record['eligible']
                or record['interval_ns'] is None):
            continue
        for stage in PARENTS:
            durations = [span['duration_ns'] for span in details['spans'] if span['stage'] == stage]
            if durations:
                values[stage].append(sum(durations))
                calls[stage] += len(durations)
    return {'schema': SCHEMA, 'frame_report_sha256': report_sha256,
            'frame_status': report['status'],
            'diagnostic_status': 'incomplete' if incomplete else 'complete',
            'incomplete_detail_attempts': incomplete,
            'retained_attempts': len(sidecar['samples']),
            'scope': ('Per-frame totals of observed CPU calls on complete details paired with eligible '
                      'present intervals. Missing calls are omitted, not zero-filled. Parent spans '
                      'include these times; do not add them. No GPU-time or performance-pass verdict.'),
            'stages': {stage: {'parent': PARENTS[stage], 'observed_calls': calls[stage],
                               'per_frame_total_ns': statistics(values[stage])} for stage in PARENTS}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frames', type=Path)
    parser.add_argument('sidecar', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        report, digest = read_json(args.frames)
        sidecar, _ = read_json(args.sidecar)
        summary = summarize(sidecar, report, digest)
        text = json.dumps(summary, indent=2, allow_nan=False) + '\n'
        if args.output:
            write_text_exclusive(args.output, text)
        print(text, end='')
        return int(summary['diagnostic_status'] != 'complete' or report['status']['state'] != 'complete')
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
        print('CPU substage validation failed: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
