#!/usr/bin/env python3
"""Validate CPU encode-detail evidence against exact frame and substage reports."""
import argparse
import json
from pathlib import Path

from exclusive_output import write_text_exclusive
import summarize_cpu_substages as substages
import summarize_frame_performance as frames

SCHEMA_V1 = 'rust_duty_cpu_encode_detail_v1'
SCHEMA_V2 = 'rust_duty_cpu_encode_detail_v2'
SCHEMA_V3 = 'rust_duty_cpu_encode_detail_v3'
SCHEMA_V4 = 'rust_duty_cpu_encode_detail_v4'
# Keep historical imports stable; select the exact counter contract from each
# input's schema rather than expanding v1 or fabricating unavailable values.
SCHEMA = SCHEMA_V1
UPLOAD_POLICIES = ('bounded_reuse_v1', 'immutable_per_frame_v1')
MEASUREMENT = 'cpu_wall_clock_nested_encode_phase_ns'
INTERPRETATION = ('CPU call durations nested inside encode_submit and renderer_submit, not GPU time. '
                  'Parent and child durations must not be added. Missing or incomplete phases are '
                  'unavailable; counters on incomplete rows are observed partial values, not complete frame totals.')
INTERPRETATION_V4 = INTERPRETATION + (' In v4, geometry_upload includes pooled staging copies; encoder creation is aggregate residual before geometry_upload. Staging retained bytes and pending buffers are upload-exit gauges, not cumulative allocations.')
STAGING_POLICIES = ('bounded_staging_v1', 'queue_write_staging_v1')
PHASES = ('frame_plan', 'geometry_upload', 'command_encoding', 'encoder_finish', 'queue_submit')
COUNTERS_V1 = ('prepared_draws', 'text_characters', 'upload_arenas', 'vertex_bytes', 'index_bytes',
               'uniform_bytes', 'draw_calls', 'render_passes', 'texture_cache_misses', 'pipeline_cache_misses')
COUNTERS_V2 = COUNTERS_V1 + ('gpu_buffer_allocations', 'gpu_buffer_reuses',
                             'gpu_buffer_allocated_bytes', 'transform_binding_allocations',
                             'uncached_upload_arenas')
COUNTERS_V3 = COUNTERS_V2 + ('resident_draws', 'resident_rigid_draws', 'resident_skinned_draws', 'resident_vertex_bytes_uploaded', 'resident_index_bytes_uploaded', 'resident_uniform_bytes_uploaded', 'resident_cache_hits', 'resident_cache_misses', 'resident_transient_meshes', 'resident_buffer_allocations', 'resident_binding_allocations')
STAGING_FIELDS = ('staging_buffer_allocations', 'staging_buffer_reuses', 'staging_buffer_allocated_bytes', 'staging_copy_bytes', 'staging_queue_write_calls', 'staging_queue_write_bytes', 'staging_fallback_arenas', 'staging_retained_bytes', 'staging_pending_buffers', 'staging_map_failures')
COUNTERS_V4 = COUNTERS_V3 + STAGING_FIELDS
STAGING_GAUGES = ('staging_retained_bytes', 'staging_pending_buffers')
COUNTERS = COUNTERS_V1
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


def validate_upload_counters(counters, upload_policy):
    """Complete v2 attempts account for three destination buffers per arena.

    These are relationships between CPU observations, not exact payload sizes or
    driver allocation claims. Incomplete attempts must retain partial values.
    Python arithmetic stays exact even if intermediate sums exceed u64.
    """
    arenas = counters['upload_arenas']
    allocations = counters['gpu_buffer_allocations']
    reuses = counters['gpu_buffer_reuses']
    allocated_bytes = counters['gpu_buffer_allocated_bytes']
    bindings = counters['transform_binding_allocations']
    uncached = counters['uncached_upload_arenas']
    frames._require(allocations + reuses == 3 * arenas,
                    'complete v2 allocations and reuses must account for three buffers per arena')
    frames._require(uncached <= arenas,
                    'complete v2 uncached arenas exceed upload arenas')
    frames._require(allocations >= 3 * uncached and reuses <= 3 * (arenas - uncached),
                    'complete v2 uncached arenas require three allocations and no reused buffers')
    frames._require(uncached <= bindings <= allocations and bindings <= arenas,
                    'complete v2 transform bindings contradict allocated buffers or upload arenas')
    frames._require((allocations == 0) == (allocated_bytes == 0)
                    and allocated_bytes >= 4 * allocations,
                    'complete v2 allocated bytes contradict nonempty destination allocations')
    if upload_policy == 'immutable_per_frame_v1':
        frames._require(allocations == 3 * arenas and reuses == 0
                        and bindings == uncached == arenas,
                        'complete v2 counters contradict immutable_per_frame_v1 upload policy')


def validate_resident_counters(counters):
    count = counters['resident_draws']
    misses = counters['resident_cache_misses']
    snapshots = 2 if count else 0
    frames._require(counters['resident_buffer_allocations'] == 2 * misses + snapshots
                    and counters['resident_binding_allocations'] == snapshots,
                    'resident allocations contradict cold geometry and per-submission snapshots')
    frames._require(count == counters['resident_rigid_draws'] + counters['resident_skinned_draws']
                    and count == misses + counters['resident_cache_hits']
                    and count <= counters['prepared_draws'], 'resident draw accounting mismatch')
    frames._require(counters['resident_transient_meshes'] <= misses, 'resident transient meshes exceed cold meshes')
    for name, minimum in (('resident_vertex_bytes_uploaded', 32), ('resident_index_bytes_uploaded', 8)):
        frames._require((counters[name] == 0) == (misses == 0)
                        and counters[name] >= misses * minimum and counters[name] % 4 == 0,
                        'resident cold upload bytes contradict misses')
    uniform = counters['resident_uniform_bytes_uploaded']
    frames._require((uniform == 0) == (count == 0) and uniform >= count * 240 + (16384 if count else 0) and uniform % 4 == 0,
                    'resident snapshot bytes contradict draws')



def validate_staging_counters(counters, policy):
    """Complete cached arenas use one whole-group source route before submit.

    Immutable uncached arenas and resident uploads are outside this source pool.
    Pending/retained observations are bounded upload-exit gauges. No relationship
    interprets them as total driver memory or silently completes partial rows.
    """
    groups = counters['upload_arenas'] - counters['uncached_upload_arenas']
    allocated = counters['staging_buffer_allocations']
    reused = counters['staging_buffer_reuses']
    fallback = counters['staging_fallback_arenas']
    pooled = allocated + reused
    copied = counters['staging_copy_bytes']
    written = counters['staging_queue_write_bytes']
    retained = counters['staging_retained_bytes']
    pending = counters['staging_pending_buffers']
    new_bytes = counters['staging_buffer_allocated_bytes']
    frames._require(groups >= 0 and pooled + fallback == groups,
                    'staging routes do not match cached nonempty arenas')
    frames._require(counters['staging_queue_write_calls'] == 3 * fallback,
                    'staging fallback must write all three arena buffers')
    frames._require((copied == 0) == (pooled == 0) and copied >= pooled * 12 and copied % 4 == 0
                    and (written == 0) == (fallback == 0) and written >= fallback * 12 and written % 4 == 0,
                    'staging payload bytes contradict routes')
    frames._require((new_bytes == 0) == (allocated == 0) and new_bytes >= allocated * 8
                    and new_bytes % 8 == 0 and new_bytes <= retained <= 64 * 1024 * 1024
                    and retained % 8 == 0 and pooled <= pending <= 8
                    and retained >= pending * 8 and copied <= retained,
                    'staging live capacity or pending ownership contradicts bounds')
    frames._require(counters['staging_map_failures'] == 0,
                    'complete staging upload cannot contain a map failure')
    payload = counters['vertex_bytes'] + counters['index_bytes'] + counters['uniform_bytes']
    frames._require(copied + written <= payload + 2 * counters['upload_arenas'],
                    'staging transfers exceed padded arena payloads')
    if counters['uncached_upload_arenas'] == 0:
        padding = copied + written - payload
        frames._require(0 <= padding <= 2 * groups and padding % 2 == 0,
                        'staging transfers do not preserve complete padded payloads')
    if policy == 'queue_write_staging_v1':
        frames._require(not any((allocated, reused, new_bytes, copied, retained, pending)),
                        'pooled staging observations contradict queue-write policy')


def validate(detail, substage, primary, primary_digest):
    """Validate all three contracts and join every retained CPU frame attempt."""
    frames._require(isinstance(primary_digest, str) and len(primary_digest) == 64
                    and all(character in '0123456789abcdef' for character in primary_digest),
                    'primary digest must be a lowercase SHA-256 hex string')
    substages.validate(substage, primary, primary_digest)
    validate_instance_descriptor(primary)
    frames._finite_tree(detail)
    v4 = isinstance(detail, dict) and detail.get('schema') == SCHEMA_V4
    v3 = isinstance(detail, dict) and detail.get('schema') in (SCHEMA_V3, SCHEMA_V4)
    v2 = isinstance(detail, dict) and detail.get('schema') in (SCHEMA_V2, SCHEMA_V3, SCHEMA_V4)
    fields = ('schema', 'measurement', 'interpretation', 'frame_report_sha256',
              'frame_status', 'samples') + (('upload_policy',) if v2 else ()) + (('resident_policy',) if v3 else ()) + (('staging_policy',) if v4 else ())
    frames._object(detail, fields, 'CPU encode detail sidecar')
    frames._require(detail['schema'] in (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4),
                    'CPU encode detail binding differs: schema')
    if v2:
        frames._require(detail['upload_policy'] in UPLOAD_POLICIES,
                        'unsupported CPU encode upload_policy')
    if v3:
        frames._require(detail['resident_policy'] in ('vertex_lit_skin_v1', 'cpu_vertex_reference_v1'), 'unsupported resident_policy')
    if v4:
        frames._require(detail['staging_policy'] in STAGING_POLICIES, 'unsupported staging_policy')
    counter_names = COUNTERS_V4 if v4 else COUNTERS_V3 if v3 else COUNTERS_V2 if v2 else COUNTERS_V1
    for field, expected in (('measurement', MEASUREMENT),
                            ('interpretation', INTERPRETATION_V4 if v4 else INTERPRETATION),
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
        frames._object(counters, counter_names, 'encode counters')
        for name in counter_names:
            frames._uint(counters[name], 'encode counter ' + name)
        if v2 and complete:
            validate_upload_counters(counters, detail['upload_policy'])
        if v3 and complete:
            validate_resident_counters(counters)
            if detail['resident_policy'] == 'cpu_vertex_reference_v1':
                frames._require(all(counters[name] == 0 for name in COUNTERS_V3[len(COUNTERS_V2):]),
                                'resident observations contradict CPU reference policy')
        if v4 and complete:
            validate_staging_counters(counters, detail['staging_policy'])
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
    counter_names = COUNTERS_V4 if detail['schema'] == SCHEMA_V4 else COUNTERS_V3 if detail['schema'] == SCHEMA_V3 else COUNTERS_V2 if detail['schema'] == SCHEMA_V2 else COUNTERS_V1
    values = {phase: [] for phase in PHASES}
    counters = {name: [] for name in counter_names}
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
        for name in counter_names:
            counters[name].append(details['counters'][name])
    result = {'schema': detail['schema'], 'frame_report_sha256': primary_digest,
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
            'counters': {name: counter_statistics(counters[name]) for name in counter_names}}
    if detail['schema'] in (SCHEMA_V2, SCHEMA_V3, SCHEMA_V4):
        result['upload_policy'] = detail['upload_policy']
    if detail['schema'] in (SCHEMA_V3, SCHEMA_V4):
        result['resident_policy'] = detail['resident_policy']
    if detail['schema'] == SCHEMA_V4:
        result['staging_policy'] = detail['staging_policy']
        result['gauges'] = {name: result['counters'].pop(name) for name in STAGING_GAUGES}
        for observation in result['gauges'].values():
            del observation['total']
        result['scope'] += (' Geometry upload includes pooled staging copies; encoder creation is encode_submit residual before that phase. Staging gauges describe retained source capacity and pending sources at upload exit, not cumulative allocation totals. GPU command-span timestamps start after staged copies and exclude them.')
    return result


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
