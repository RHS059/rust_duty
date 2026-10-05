#!/usr/bin/env python3
"""Validate and summarize retained CPU present-return intervals, read-only."""

import argparse
import json
import math
from pathlib import Path
import sys


SCHEMA = 'rust_duty_frame_performance_v1'
MEASUREMENT = 'cpu_wall_clock_successful_present_return_interval_ns'
METHOD = 'nearest_rank_ceil_p_times_n_no_interpolation'
INTERPRETATION = 'CPU wall-clock intervals between successful present returns; not GPU time, display cadence or simulation time.'
COUNT_SCOPE = 'retained events only; incomplete capture does not assert counts for unobserved activity'
BASIS = 'This observer does not authenticate hardware evidence.'
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


def validate_report(report):
    """Check the actual v1 producer schema and recompute every retained statistic."""
    try:
        _finite_tree(report)
        _object(report, ('schema', 'measurement', 'clock', 'interpretation', 'identity', 'status',
                         'start_ns', 'stop_requested_ns', 'stopped_at_ns', 'last_observed_ns',
                         'incomplete_at_ns', 'limits', 'successful_present_count',
                         'ineligible_present_count', 'skipped_frame_count', 'count_scope', 'summary', 'records'), 'report')
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
        data = source.read(128 * 1024 * 1024 + 1)
    _require(len(data) <= 128 * 1024 * 1024, 'report exceeds 128 MiB')
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
        result = {key: value for key, value in report.items() if key not in ('records', 'summary', 'status')}
        result.update(report['summary'])
        result.update(status=report['status']['state'], error=report['status']['error'],
                      retained_record_count=len(report['records']),
                      scope='Retained CPU wall-clock evidence only; no GPU, hardware or performance-pass verdict.')
        text = json.dumps(result, indent=2, allow_nan=False) + '\n'
        if output_path is not None:
            destination = Path(output_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('x', encoding='utf-8') as output:
                output.write(text)
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
