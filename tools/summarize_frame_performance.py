#!/usr/bin/env python3
"""Validate and summarize retained CPU present-return intervals, read-only."""

import argparse
import json
import math
from pathlib import Path
import sys

from exclusive_output import write_text_exclusive


SCHEMA = 'rust_duty_frame_performance_v1'
MEASUREMENT = 'cpu_wall_clock_successful_present_return_interval_ns'
METHOD = 'nearest_rank_ceil_p_times_n_no_interpolation'
INTERPRETATION = 'CPU wall-clock intervals between successful present returns; not GPU time, display cadence or simulation time.'
COUNT_SCOPE = 'retained events only; incomplete capture does not assert counts for unobserved activity'
BASIS = 'This observer does not authenticate hardware evidence.'
# The optional four-span extension grows pretty-printed captures. This remains
# bounded and accommodates the producer's maximum 250,000 retained records.
MAX_REPORT_BYTES = 512 * 1024 * 1024
CPU_STAGE_MEASUREMENT = 'cpu_wall_clock_paired_frame_stage_ns'
CPU_STAGE_INTERPRETATION = 'Disjoint paired CPU wall-clock spans within one frame attempt, not GPU execution times. Missing spans are unavailable, not zero. Stages do not cover the whole present-return interval; no residual GPU time is inferred. Successful present-return intervals remain the primary end-to-end measurement.'
CPU_STAGE_DEFINITIONS = {
    'surface_acquire': 'CPU time in the surface acquisition call, including its internal recovery/retry; excludes surface resize/configuration before the call.',
    'game_recording': 'CPU time from acquired-frame recorder setup through application/input work and draw-list preparation, ending before renderer submission.',
    'renderer_submit': 'CPU time preparing resources, encoding and submitting commands, validating, and completing any requested diagnostic readbacks; excludes the present call and post-present error check.',
    'present_call': 'CPU time in queue.present only; return does not establish GPU completion or display scan-out.',
}
REASONS = {'focus_lost', 'focus_regained', 'paused', 'resumed', 'resize', 'minimized',
           'surface_skipped', 'surface_error', 'capture_readback', 'diagnostic_capture',
           'renderer_changed', 'scene_changed', 'caller_excluded', 'shutdown'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _object(value, fields, label):
    _require(isinstance(value, dict), f'{label} must be an object')
    _require(set(value) == set(fields), f'{label} fields differ from the producer schema')


def _uint(value, label, maximum=2**64 - 1):
    _require(type(value) is int and 0 <= value <= maximum,
             f'{label} must be an unsigned integer, not a boolean')
    return value


def _finite_tree(value):
    if isinstance(value, dict):
        for key, item in value.items():
            _require(isinstance(key, str), 'JSON object keys must be strings')
            _finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item)
    elif isinstance(value, float):
        _require(math.isfinite(value), 'non-finite JSON number')
    else:
        _require(value is None or type(value) in (int, bool, str), 'unsupported JSON value')


def _window(window):
    _object(window, ('physical_width', 'physical_height', 'scale_factor', 'mode'), 'window context')
    for field in ('physical_width', 'physical_height'):
        _uint(window[field], field, 2**32 - 1)
    scale = window['scale_factor']
    _require(type(scale) in (int, float) and scale > 0, 'window scale factor must be positive')
    _require(window['mode'] in ('unknown', 'windowed', 'borderless', 'exclusive_fullscreen'), 'unknown window mode')


def _cpu_frame_stages(extension, report):
    _object(extension, ('measurement', 'interpretation', 'stage_definitions', 'samples'), 'CPU frame stages')
    _require(extension['measurement'] == CPU_STAGE_MEASUREMENT
             and extension['interpretation'] == CPU_STAGE_INTERPRETATION,
             'unsupported CPU stage measurement or interpretation')
    _require(extension['stage_definitions'] == CPU_STAGE_DEFINITIONS, 'unsupported CPU stage definitions')
    samples, records = extension['samples'], report['records']
    _require(isinstance(samples, list) and len(samples) <= len(records), 'CPU samples must be bounded by retained records')
    previous_index, previous_end = -1, report['start_ns']
    for sample in samples:
        _object(sample, ('record_index', 'started_at_ns', 'finished_at_ns', 'physical_width',
                         'physical_height', 'spans'), 'CPU frame sample')
        index = _uint(sample['record_index'], 'CPU record_index')
        _require(previous_index < index < len(records), 'CPU record indexes must reference distinct ordered retained records')
        # Uninstrumented frames (for example capture enabled mid-frame) still
        # constrain this attempt's start. Ordinary in-frame boundaries do not.
        for earlier in range(previous_index + 1, index):
            row = records[earlier]
            if (row['kind'] in ('successful_present_return', 'skipped_frame')
                    or (row['kind'] == 'boundary' and row['reason'] in ('surface_error', 'shutdown'))):
                previous_end = max(previous_end, row['at_ns'])
        previous_index = index
        row = records[index]
        _require(row['kind'] in ('successful_present_return', 'skipped_frame')
                 or (row['kind'] == 'boundary' and row['reason'] in ('surface_error', 'shutdown')),
                 'CPU sample must reference a terminal frame event')
        start = _uint(sample['started_at_ns'], 'CPU frame start')
        end = _uint(sample['finished_at_ns'], 'CPU frame end')
        _require(previous_end <= start <= end == row['at_ns'], 'CPU frame times do not match the retained timeline')
        previous_end = end
        for field in ('physical_width', 'physical_height'):
            _uint(sample[field], field, 2**32 - 1)
        _object(sample['spans'], CPU_STAGE_DEFINITIONS, 'CPU stage spans')
        span_end = start
        for name in CPU_STAGE_DEFINITIONS:
            span = sample['spans'][name]
            if span is None:
                continue
            _object(span, ('started_at_ns', 'ended_at_ns', 'duration_ns'), f'CPU {name}')
            begin = _uint(span['started_at_ns'], 'CPU span start')
            finish = _uint(span['ended_at_ns'], 'CPU span end')
            duration = _uint(span['duration_ns'], 'CPU span duration')
            _require(span_end <= begin <= finish <= end, 'CPU spans must be disjoint, ordered and within their frame')
            _require(duration == finish - begin, 'CPU duration differs from its paired timestamps')
            span_end = finish


def _cpu_stage_summary(extension, records):
    result = {key: value for key, value in extension.items() if key != 'samples'}
    result['scope'] = 'Paired stages on eligible successful-present records with a retained end-to-end interval; missing stages omitted, not zero-filled. No GPU or FPS estimate.'
    result['retained_attempt_count'] = len(extension['samples'])
    result['summary'] = {}
    for name in CPU_STAGE_DEFINITIONS:
        values = sorted(sample['spans'][name]['duration_ns'] for sample in extension['samples']
                        if sample['spans'][name] is not None
                        and records[sample['record_index']]['kind'] == 'successful_present_return'
                        and records[sample['record_index']]['eligible']
                        and records[sample['record_index']]['interval_ns'] is not None)
        result['summary'][name] = {
            'sample_count': len(values), 'total_ns': sum(values),
            'min_ns': values[0] if values else None, 'max_ns': values[-1] if values else None,
            **{f'p{p}_ns': values[(len(values) * p + 99) // 100 - 1] if values else None
               for p in (50, 95, 99)}, 'percentile_method': METHOD,
        }
    return result


def validate_report(report):
    """Check the actual v1 producer schema and recompute every retained statistic."""
    try:
        _finite_tree(report)
        fields = ('schema', 'measurement', 'clock', 'interpretation', 'identity', 'status',
                         'start_ns', 'stop_requested_ns', 'stopped_at_ns', 'last_observed_ns',
                         'incomplete_at_ns', 'limits', 'successful_present_count',
                         'ineligible_present_count', 'skipped_frame_count', 'count_scope', 'summary', 'records')
        _object(report, fields + (('cpu_frame_stages',) if 'cpu_frame_stages' in report else ()), 'report')
        for key, expected in [('schema', SCHEMA), ('measurement', MEASUREMENT),
                              ('clock', 'caller_injected_monotonic_nanoseconds'),
                              ('interpretation', INTERPRETATION), ('count_scope', COUNT_SCOPE)]:
            _require(report[key] == expected, f'unsupported {key}')
        identity = report['identity']
        _object(identity, ('runtime_observed', 'operator_supplied', 'hardware_classification',
                           'hardware_classification_basis'), 'identity')
        _require(identity['hardware_classification'] == 'unknown'
                 and identity['hardware_classification_basis'] == BASIS, 'hardware classification must remain unknown')
        runtime = identity['runtime_observed']
        _object(runtime, ('actual_backend', 'actual_adapter', 'build', 'initial_window', 'scene'), 'runtime identity')
        _require(runtime['actual_backend'] is None or isinstance(runtime['actual_backend'], str), 'actual_backend must be text or null')
        _window(runtime['initial_window'])
        limits = report['limits']
        _object(limits, ('max_records', 'max_metadata_bytes'), 'limits')
        _require(_uint(limits['max_records'], 'max_records', 250_000) > 0, 'max_records must be positive')
        _require(_uint(limits['max_metadata_bytes'], 'max_metadata_bytes', 256 * 1024) > 0,
                 'max_metadata_bytes must be positive')
        for field in ('start_ns', 'stop_requested_ns', 'last_observed_ns',
                      'successful_present_count', 'ineligible_present_count', 'skipped_frame_count'):
            _uint(report[field], field)
        for field in ('stopped_at_ns', 'incomplete_at_ns'):
            if report[field] is not None:
                _uint(report[field], field)
        records = report['records']
        _require(isinstance(records, list) and len(records) <= limits['max_records'], 'records must be a bounded list')
        previous = report['start_ns']
        anchor = None
        values = []
        presents = ineligible = skipped = 0
        for index, row in enumerate(records):
            _require(isinstance(row, dict), f'record {index} must be an object')
            at = _uint(row.get('at_ns'), f'record {index}.at_ns')
            _require(at >= previous, f'record {index} has a non-monotonic timestamp')
            previous = at
            kind = row.get('kind')
            if kind == 'successful_present_return':
                _object(row, ('at_ns', 'kind', 'eligible', 'ineligible_reason', 'interval_ns'), f'record {index}')
                _require(type(row['eligible']) is bool, 'eligible must be boolean')
                interval = row['interval_ns']
                if interval is not None:
                    _uint(interval, 'interval_ns')
                presents += 1
                if row['eligible']:
                    _require(row['ineligible_reason'] is None, 'eligible present cannot have an exclusion reason')
                    expected = None if anchor is None else at - anchor
                    _require(interval == expected, f'record {index}: interval does not match its eligible anchor')
                    anchor = at
                else:
                    _require(row['ineligible_reason'] in REASONS and interval is None,
                             'ineligible present must have a known reason and no interval')
                    ineligible += 1
                    anchor = None
                if interval is not None:
                    values.append(interval)
            elif kind in ('boundary', 'skipped_frame'):
                fields = ('at_ns', 'kind', 'reason') + (('resets_interval_anchor',) if kind == 'skipped_frame' else ())
                _object(row, fields, f'record {index}')
                _require(isinstance(row['reason'], str) and row['reason'] in REASONS, 'unknown boundary reason')
                if kind == 'skipped_frame':
                    _require(row['resets_interval_anchor'] is False, 'ordinary retries must retain the interval anchor')
                    skipped += 1
                else:
                    anchor = None
            elif kind == 'window_context':
                _object(row, ('at_ns', 'kind', 'context'), f'record {index}')
                _window(row['context'])
                anchor = None
            else:
                raise ValueError(f'unknown record kind: {kind!r}')
        _require(report['last_observed_ns'] == previous, 'last_observed_ns does not match retained events')
        if 'cpu_frame_stages' in report:
            _cpu_frame_stages(report['cpu_frame_stages'], report)
        for name, expected in [('successful_present_count', presents), ('ineligible_present_count', ineligible),
                               ('skipped_frame_count', skipped)]:
            _require(report[name] == expected, f'{name} differs from retained records')
        summary = report['summary']
        _object(summary, ('interval_count', 'total_interval_ns', 'min_ns', 'max_ns', 'p50_ns',
                          'p95_ns', 'p99_ns', 'percentile_method'), 'summary')
        values.sort()
        expected = {'interval_count': len(values), 'total_interval_ns': sum(values),
                    'min_ns': values[0] if values else None, 'max_ns': values[-1] if values else None}
        for p in (50, 95, 99):
            expected[f'p{p}_ns'] = values[(len(values) * p + 99) // 100 - 1] if values else None
        for key, value in expected.items():
            if summary[key] is not None:
                _uint(summary[key], key)
            _require(summary[key] == value, f'{key} differs from retained intervals')
        _require(summary['percentile_method'] == METHOD, 'unsupported percentile_method')
        status = report['status']
        _object(status, ('state', 'error'), 'status')
        failure = report['incomplete_at_ns']
        if status['state'] == 'complete':
            _require(failure is None and status['error'] is None and bool(values), 'contradictory complete status')
        elif status['state'] == 'incomplete':
            _require(failure is not None and isinstance(status['error'], str) and bool(status['error'].strip()),
                     'incomplete status needs its failure timestamp and error')
        else:
            raise ValueError('unknown capture status')
        # The observer stops immediately, but PerformanceSession preserves the
        # earlier F8 request while awaiting one final present. These are distinct
        # boundaries: never substitute the request time for completion time.
        latest = max(previous, failure) if failure is not None else previous
        requested, stopped = report['stop_requested_ns'], report['stopped_at_ns']
        if stopped is not None:
            _require(stopped >= max(latest, requested),
                     'stopped_at_ns precedes an observed event or stop request')
        else:
            # Both observer stop regressions and session callbacks that precede
            # a pending stop request can make completion time unavailable.
            _require(failure is not None and (requested < latest
                     or failure < max(previous, requested)),
                     'missing stopped_at_ns without contradictory clock evidence')
        if status['state'] == 'complete':
            _require(stopped is not None and requested >= report['start_ns'],
                     'complete capture needs valid request and stop boundaries')
            if stopped > requested:
                _require(records and records[-1]['kind'] == 'successful_present_return'
                         and records[-1]['at_ns'] == stopped,
                         'deferred stop needs its final successful present')
                _require(all(row['at_ns'] <= requested for row in records[:-1]
                             if row['kind'] == 'successful_present_return'),
                         'deferred stop retained a present after the requested final frame')
    except (TypeError, RecursionError, OverflowError) as error:
        raise ValueError(f'malformed performance report: {error}') from error


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field: {key}')
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f'non-finite JSON number: {value}')


def read_report(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('report must not be a symlink')
    with path.open('rb') as source:
        data = source.read(MAX_REPORT_BYTES + 1)
    _require(len(data) <= MAX_REPORT_BYTES, 'report exceeds 512 MiB')
    try:
        report = json.loads(data.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_constant)
        validate_report(report)
        return report
    except (UnicodeError, RecursionError) as error:
        raise ValueError(f'invalid performance JSON: {error}') from error


def summarize_report(report_path, output_path=None):
    """Print a validated summary; incomplete capture remains incomplete."""
    try:
        report = read_report(report_path)
        result = {key: value for key, value in report.items() if key not in ('records', 'summary', 'status', 'cpu_frame_stages')}
        if 'cpu_frame_stages' in report:
            result['cpu_frame_stages'] = _cpu_stage_summary(report['cpu_frame_stages'], report['records'])
        result.update(report['summary'])
        result.update(status=report['status']['state'], error=report['status']['error'],
                      retained_record_count=len(report['records']),
                      scope='Retained CPU wall-clock evidence only; no GPU, hardware or performance-pass verdict.')
        text = json.dumps(result, indent=2, allow_nan=False) + '\n'
        if output_path is not None:
            write_text_exclusive(output_path, text, create_parents=True)
        print(text, end='')
        return 0
    except (OSError, ValueError) as error:
        print(f'Validation error: {error}', file=sys.stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report_path', type=Path)
    parser.add_argument('--report', type=Path, help='Write a new summary, never overwrite')
    args = parser.parse_args(argv)
    return summarize_report(args.report_path, args.report)


if __name__ == '__main__':
    raise SystemExit(main())
