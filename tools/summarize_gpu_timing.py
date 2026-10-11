#!/usr/bin/env python3
"""Validate optional frame GPU timing against exact primary bytes and CPU attempt joins."""
import argparse
from collections import Counter
import math
from pathlib import Path
import json
import re
import sys

from exclusive_output import write_text_exclusive
import summarize_frame_performance as frames
from summarize_cpu_substages import read_json

SCHEMA = 'rust_duty_frame_gpu_timing_v1'
MEASUREMENT = 'frame_command_buffer_gpu_elapsed_ns'
SCOPE = ('GPU timestamps around the main ordered frame command buffer; excludes other submissions, '
         'CPU work, surface acquisition, present/scan-out and trailing timestamp resolve/readback; '
         'backend/driver timestamp ordering and precision apply')
UNAVAILABLE = {'not_submitted', 'disabled', 'device_features_not_enabled', 'invalid_timestamp_period',
               'ring_full', 'map_failed', 'abandoned_before_submit', 'pending_at_stop',
               'submission_rejected', 'validation_unconfirmed_at_stop', 'stopped'}
NUMERIC = ('start_ticks', 'end_ticks', 'timestamp_period_ns', 'elapsed_ns')


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def validate(sidecar, report, report_sha256):
    frames.validate_report(report)
    frames._finite_tree(sidecar)
    frames._object(sidecar, ('schema', 'measurement', 'scope', 'frame_report_sha256',
                            'accounting_state', 'error', 'session', 'limits', 'availability',
                            'feature_negotiation', 'samples'), 'GPU timing sidecar')
    for name, expected in [('schema', SCHEMA), ('measurement', MEASUREMENT), ('scope', SCOPE),
                           ('frame_report_sha256', report_sha256)]:
        frames._require(sidecar[name] == expected, 'GPU timing binding differs: ' + name)
    frames._require(isinstance(report_sha256, str) and re.fullmatch('[0-9a-f]{64}', report_sha256),
                    'Expected exact primary SHA-256')
    complete = sidecar['accounting_state'] == 'complete'
    frames._require((complete and sidecar['error'] is None) or
                    (sidecar['accounting_state'] == 'incomplete' and isinstance(sidecar['error'], str)
                     and 0 < len(sidecar['error']) <= 4096), 'Invalid GPU accounting state')
    session = frames._uint(sidecar['session'], 'GPU session')
    frames._require(session > 0, 'GPU session must be nonzero')
    frames._object(sidecar['limits'], ('max_attempts', 'ring_slots'), 'GPU limits')
    frames._require(sidecar['limits']['max_attempts'] == report['limits']['max_records']
                    and type(sidecar['limits']['max_attempts']) is int,
                    'GPU attempt bound differs from primary')
    frames._require(type(sidecar['limits']['ring_slots']) is int and sidecar['limits']['ring_slots'] == 4,
                    'GPU ring bound differs')
    features = sidecar['feature_negotiation']
    frames._object(features, ('adapter_supports_required_features', 'device_features_enabled'), 'GPU features')
    frames._require(all(type(value) is bool for value in features.values()), 'Feature facts must be boolean')
    frames._require(not features['device_features_enabled'] or features['adapter_supports_required_features'],
                    'Device cannot enable unsupported timestamp features')
    adapter = report['identity']['runtime_observed']['actual_adapter']
    frames._require(isinstance(adapter, dict) and adapter.get('gpu_timestamps_requested') is True,
                    'Primary runtime did not explicitly request GPU timestamps')
    frames._require(type(adapter.get('gpu_timestamp_features_enabled')) is bool
                    and adapter['gpu_timestamp_features_enabled'] == features['device_features_enabled'],
                    'Primary device timestamp features contradict the GPU sidecar')
    availability = sidecar['availability']
    frames._require(isinstance(availability, dict), 'GPU availability must be an object')
    available = availability.get('state') == 'available'
    frames._object(availability, ('state', 'timestamp_period_ns') if available else ('state',), 'GPU availability')
    if available:
        frames._require(features['device_features_enabled'] and positive(availability['timestamp_period_ns']),
                        'Available GPU timing needs enabled features and a positive period')
    else:
        frames._require(availability['state'] in ('disabled', 'device_features_not_enabled',
                        'invalid_timestamp_period', 'initialization_failed', 'allocation_failed'),
                        'Unknown GPU availability')
        if availability['state'] == 'invalid_timestamp_period':
            frames._require(features['device_features_enabled'], 'Invalid period requires enabled features')
        if availability['state'] == 'device_features_not_enabled':
            frames._require(not features['device_features_enabled'], 'Missing-feature status contradicts device')
        if availability['state'] in ('initialization_failed', 'allocation_failed'):
            frames._require(not complete, 'Failed GPU initialization cannot have complete accounting')
    samples = sidecar['samples']
    frames._require(isinstance(samples, list) and len(samples) <= sidecar['limits']['max_attempts'],
                    'GPU attempt capacity exceeded')
    parents = {row['record_index'] for row in report.get('cpu_frame_stages', {}).get('samples', [])}
    joined = []
    for attempt, sample in enumerate(samples):
        frames._object(sample, ('session', 'attempt', 'record_index', 'status', *NUMERIC), 'GPU sample')
        frames._uint(sample['session'], 'Sample session')
        frames._uint(sample['attempt'], 'Sample attempt')
        frames._require(sample['session'] == session and sample['attempt'] == attempt,
                        'GPU sample session/attempt differs or is reordered')
        index = sample['record_index']
        record = None
        if index is None:
            frames._require(not complete, 'Complete GPU accounting requires every CPU join')
        else:
            frames._uint(index, 'GPU CPU record index')
            frames._require(index in parents and (not joined or index > joined[-1]),
                            'GPU join must name a unique ordered retained CPU attempt')
            joined.append(index)
            record = report['records'][index]
            frames._require(record['kind'] in ('successful_present_return', 'skipped_frame') or
                            (record['kind'] == 'boundary' and record['reason'] in ('surface_error', 'shutdown')),
                            'GPU join does not name a terminal CPU attempt')
        status = sample['status']
        frames._require(isinstance(status, str), 'GPU sample status must be text')
        if status in ('measured', 'invalid_timestamp_order'):
            frames._require(available, 'Unavailable timer cannot publish GPU ticks')
            start = frames._uint(sample['start_ticks'], 'Start ticks')
            end = frames._uint(sample['end_ticks'], 'End ticks')
            period = sample['timestamp_period_ns']
            frames._require(positive(period) and period == availability['timestamp_period_ns'],
                            'GPU timestamp period differs')
            frames._require(record is None or record['kind'] != 'skipped_frame',
                            'Skipped surface attempt cannot contain a submitted GPU span')
            if status == 'measured':
                frames._require(end >= start and type(sample['elapsed_ns']) in (int, float)
                                and sample['elapsed_ns'] == float(end - start) * period,
                                'GPU elapsed value differs from integer tick subtraction')
            else:
                frames._require(end < start and sample['elapsed_ns'] is None,
                                'Invalid-order sample must retain reversed ticks without a duration')
        else:
            frames._require(status in UNAVAILABLE and all(sample[name] is None for name in NUMERIC),
                            'Unavailable GPU sample cannot contain ticks or zero-filled duration')
            if status not in ('not_submitted', 'device_features_not_enabled', 'invalid_timestamp_period', 'disabled'):
                frames._require(available, 'GPU lifecycle status requires an available timer')
            if status in ('device_features_not_enabled', 'invalid_timestamp_period', 'disabled'):
                frames._require(availability['state'] == status, 'Sample availability differs from timer')
    if complete:
        frames._require(set(joined) == parents, 'GPU samples omit or add retained CPU attempts')
    return sidecar


def summarize(sidecar, report, report_sha256):
    validate(sidecar, report, report_sha256)
    complete = sidecar['accounting_state'] == 'complete' and report['status']['state'] == 'complete'
    counts = Counter(sample['status'] for sample in sidecar['samples'])
    eligible = []
    unavailable = 0
    for sample in sidecar['samples']:
        if sample['record_index'] is None:
            continue
        record = report['records'][sample['record_index']]
        if record['kind'] == 'successful_present_return' and record['eligible'] and record['interval_ns'] is not None:
            if sample['status'] == 'measured':
                eligible.append(sample['elapsed_ns'])
            else:
                unavailable += 1
    values = sorted(eligible) if complete else []
    percentile = lambda p: values[math.ceil(p * len(values)) - 1] if values else None
    return {'schema': 'rust_duty_gpu_timing_summary_v1', 'frame_report_sha256': report_sha256,
            'state': 'complete' if complete else 'incomplete', 'availability': sidecar['availability'],
            'status_counts': dict(counts), 'measured_eligible_count': len(values),
            'unavailable_eligible_count': unavailable, 'p50_ns': percentile(.5),
            'p95_ns': percentile(.95), 'p99_ns': percentile(.99),
            'scope': SCOPE + '; eligible retained-present subset only; missing samples may bias this subset. No FPS, scan-out, or target-performance verdict.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frames', type=Path)
    parser.add_argument('sidecar', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        report, digest = read_json(args.frames)
        sidecar, _ = read_json(args.sidecar)
        result = summarize(sidecar, report, digest)
        text = json.dumps(result, indent=2, allow_nan=False) + '\n'
        if args.output is not None:
            write_text_exclusive(args.output, text)
        print(text, end='')
        return 0 if result['state'] == 'complete' else 1
    except (OSError, ValueError) as error:
        print('GPU timing validation error: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
