#!/usr/bin/env python3
"""Validate CPU encode-detail evidence against exact frame and substage reports."""
import argparse
import json
from pathlib import Path

from exclusive_output import write_text_exclusive
import summarize_cpu_substages as substages
import summarize_frame_performance as frames

SCHEMA = 'rust_duty_cpu_encode_detail_v1'
MEASUREMENT = 'cpu_wall_clock_nested_encode_phase_ns'
INTERPRETATION = ('CPU call durations nested inside encode_submit and renderer_submit, not GPU time. '
                  'Parent and child durations must not be added. Missing or incomplete phases are '
                  'unavailable; counters on incomplete rows are observed partial values, not complete frame totals.')
PHASES = ('frame_plan', 'geometry_upload', 'command_encoding', 'encoder_finish', 'queue_submit')
COUNTERS = ('prepared_draws', 'text_characters', 'upload_arenas', 'vertex_bytes', 'index_bytes',
            'uniform_bytes', 'draw_calls', 'render_passes', 'texture_cache_misses', 'pipeline_cache_misses')
MAX_ERROR_BYTES = 256
# Reuse the exact-byte bounded reader, duplicate-key rejection and finite-number
# checks used by the existing sidecar. No second read or reserialized hash.
read_json = substages.read_json
INSTANCE_SCHEMA = 'rust-duty-wgpu-instance-descriptor/v1'
INSTANCE_FLAGS = {'debug': 1, 'validation': 2, 'gpu_based_validation': 16,
                  'validation_indirect_call': 32}


def validate_instance_descriptor(primary):
    adapter = primary['identity']['runtime_observed']['actual_adapter']
    frames._require(isinstance(adapter, dict), 'encode details require adapter instance descriptor metadata')
    descriptor = adapter.get('instance_descriptor')
    frames._object(descriptor, ('schema', 'wgpu_version', 'flags_bits', *INSTANCE_FLAGS,
                                'application_debug_assertions', 'environment_overrides_applied'),
                   'instance descriptor')
    frames._require(descriptor['schema'] == INSTANCE_SCHEMA and descriptor['wgpu_version'] == '30.0.1',
                    'unsupported instance descriptor schema or wgpu version')
    bits = frames._uint(descriptor['flags_bits'], 'instance descriptor flags_bits', 255)
    for name, mask in INSTANCE_FLAGS.items():
        frames._require(type(descriptor[name]) is bool and descriptor[name] == bool(bits & mask),
                        'instance descriptor flag differs from flags_bits: ' + name)
    frames._require(type(descriptor['application_debug_assertions']) is bool,
                    'application_debug_assertions must be boolean')
    frames._require(descriptor['environment_overrides_applied'] is False,
                    'instance descriptor environment overrides must be false')


def validate(detail, substage, primary, primary_digest):
    """Validate all three contracts and join every retained CPU frame attempt."""
    frames._require(isinstance(primary_digest, str) and len(primary_digest) == 64
                    and all(character in '0123456789abcdef' for character in primary_digest),
                    'primary digest must be a lowercase SHA-256 hex string')
    substages.validate(substage, primary, primary_digest)
    validate_instance_descriptor(primary)
    frames._finite_tree(detail)
    frames._object(detail, ('schema', 'measurement', 'interpretation', 'frame_report_sha256',
                            'frame_status', 'samples'), 'CPU encode detail sidecar')
    for field, expected in (('schema', SCHEMA), ('measurement', MEASUREMENT),
                            ('interpretation', INTERPRETATION),
                            ('frame_report_sha256', primary_digest),
                            ('frame_status', primary['status'])):
        frames._require(detail[field] == expected, 'CPU encode detail binding differs: ' + field)
    samples = detail['samples']
    frames._require(isinstance(samples, list) and len(samples) == len(substage['samples']),
                    'encode samples must exactly match retained substage attempts')
    previous_index = -1
    for sample, child, parent in zip(samples, substage['samples'],
                                     primary['cpu_frame_stages']['samples']):
        frames._object(sample, ('record_index', 'details'), 'encode sample')
        index = frames._uint(sample['record_index'], 'encode record index')
        frames._require(previous_index < index == child['record_index'] == parent['record_index'],
                        'encode record indexes must match distinct ordered retained attempts')
        previous_index = index
        details = sample['details']
        frames._object(details, ('state', 'error', 'spans', 'counters'), 'encode details')
        complete = details['state'] == 'complete'
        error = details['error']
        frames._require((complete and error is None)
                        or (details['state'] == 'incomplete' and isinstance(error, str)
                            and bool(error.strip()) and len(error.encode('utf-8')) <= MAX_ERROR_BYTES),
                        'invalid encode diagnostic state')
        counters = details['counters']
        frames._object(counters, COUNTERS, 'encode counters')
        for name in COUNTERS:
            frames._uint(counters[name], 'encode counter ' + name)
        spans = details['spans']
        frames._require(isinstance(spans, list) and len(spans) <= len(PHASES),
                        'encode phase capacity exceeded')
        frames._require(not complete or len(spans) == len(PHASES),
                        'complete encode details require all five phases')
        renderer_parent = parent['spans']['renderer_submit']
        encode_parents = [span for span in child['details']['spans']
                          if span['stage'] == 'encode_submit']
        encode_parent = encode_parents[0] if encode_parents else None
        frames._require(not complete or (renderer_parent is not None and encode_parent is not None),
                        'complete encode details require renderer_submit and encode_submit parents')
        # An interrupted parent call can lack its closing pair while child calls
        # have already completed. Keep those observations only as incomplete,
        # always bounded by the frame and every parent whose pair is available.
        bounds = [parent] + [outer for outer in (renderer_parent, encode_parent) if outer is not None]
        end = parent['started_at_ns']
        for position, span in enumerate(spans):
            frames._object(span, ('stage', 'started_at_ns', 'ended_at_ns', 'duration_ns'),
                           'encode phase span')
            frames._require(isinstance(span['stage'], str) and span['stage'] in PHASES,
                            'unknown CPU encode phase')
            frames._require(span['stage'] == PHASES[position], 'CPU encode phases out of order')
            begin = frames._uint(span['started_at_ns'], 'encode phase start')
            finish = frames._uint(span['ended_at_ns'], 'encode phase end')
            duration = frames._uint(span['duration_ns'], 'encode phase duration')
            frames._require(end <= begin <= finish, 'CPU encode phases must be disjoint and ordered')
            frames._require(duration == finish - begin, 'encode phase duration differs')
            for outer in bounds:
                outer_end = outer.get('ended_at_ns', outer.get('finished_at_ns'))
                frames._require(outer['started_at_ns'] <= begin and finish <= outer_end,
                                'CPU encode phase outside its frame or parent span')
            end = finish
    return detail


def counter_statistics(values):
    """Exact u64 observations with integer (unbounded aggregate) Python totals."""
    values = sorted(values)
    return {'sample_count': len(values), 'total': sum(values),
            'min': values[0] if values else None, 'max': values[-1] if values else None,
            **{f'p{p}': values[(len(values) * p + 99) // 100 - 1] if values else None
               for p in (50, 95, 99)}, 'percentile_method': frames.METHOD}


def summarize(detail, substage, primary, primary_digest):
    validate(detail, substage, primary, primary_digest)
    values = {phase: [] for phase in PHASES}
    counters = {name: [] for name in COUNTERS}
    incomplete = sum(sample['details']['state'] != 'complete' for sample in detail['samples'])
    incomplete_substages = sum(sample['details']['state'] != 'complete' for sample in substage['samples'])
    primary_complete = primary['status']['state'] == 'complete'
    summarized = 0
    for sample, child in zip(detail['samples'], substage['samples']):
        details = sample['details']
        record = primary['records'][sample['record_index']]
        if (not primary_complete or details['state'] != 'complete'
                or child['details']['state'] != 'complete'
                or record['kind'] != 'successful_present_return' or not record['eligible']
                or record['interval_ns'] is None):
            continue
        summarized += 1
        for span in details['spans']:
            values[span['stage']].append(span['duration_ns'])
        for name in COUNTERS:
            counters[name].append(details['counters'][name])
    return {'schema': SCHEMA, 'frame_report_sha256': primary_digest,
            'frame_status': primary['status'],
            'diagnostic_status': ('complete' if primary_complete and not incomplete
                                  and not incomplete_substages else 'incomplete'),
            'incomplete_detail_attempts': incomplete,
            'incomplete_substage_attempts': incomplete_substages,
            'retained_attempts': len(detail['samples']), 'summarized_attempts': summarized,
            'scope': ('Observed CPU encode phases and counters only for complete detail and substage '
                      'attempts on a complete primary capture, paired with eligible present intervals. '
                      'Incomplete rows retain partial counters in the evidence, never in distributions. '
                      'Missing observations are unavailable, not zero. Parent spans include child times; '
                      'do not add or subtract parent/child percentiles or infer GPU time. '
                      'No performance-pass verdict.'),
            'stages': {phase: {'parent': 'encode_submit',
                               'per_frame_total_ns': substages.statistics(values[phase])}
                       for phase in PHASES},
            'counters': {name: counter_statistics(counters[name]) for name in COUNTERS}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frames', type=Path)
    parser.add_argument('cpu_substages', type=Path)
    parser.add_argument('encode_detail', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        primary, digest = read_json(args.frames)
        substage, _ = read_json(args.cpu_substages)
        detail, _ = read_json(args.encode_detail)
        summary = summarize(detail, substage, primary, digest)
        text = json.dumps(summary, indent=2, allow_nan=False) + '\n'
        if args.output:
            write_text_exclusive(args.output, text)
        print(text, end='')
        return int(summary['diagnostic_status'] != 'complete')
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
        print('CPU encode detail validation failed: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
