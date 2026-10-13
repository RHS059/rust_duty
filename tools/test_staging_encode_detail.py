"""Independent staging v4 evidence tests; synthetic rows, no GPU execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import summarize_cpu_encode_detail as reader
import test_resident_encode_detail as resident
import test_summarize_cpu_encode_detail as historical


FIELDS = (
    'staging_buffer_allocations', 'staging_buffer_reuses',
    'staging_buffer_allocated_bytes', 'staging_copy_bytes',
    'staging_queue_write_calls', 'staging_queue_write_bytes',
    'staging_fallback_arenas', 'staging_retained_bytes',
    'staging_pending_buffers', 'staging_map_failures',
)
GAUGES = ('staging_retained_bytes', 'staging_pending_buffers')
U64_MAX = 2**64 - 1
CAPACITY = 64 * 1024 * 1024


def fixture():
    control = list(resident.fixture())
    control[2].update(schema='rust_duty_cpu_encode_detail_v4',
                      staging_policy='bounded_staging_v1',
                      interpretation=reader.INTERPRETATION_V4)
    counters(control).update(dict.fromkeys(FIELDS, 0))
    # Existing 120 vertex + 6 index + 64 uniform bytes become 192 copied
    # bytes. Packing also aligns source slice offsets, within 256 capacity.
    counters(control).update(staging_buffer_allocations=1,
                             staging_buffer_allocated_bytes=256,
                             staging_copy_bytes=192,
                             staging_retained_bytes=256,
                             staging_pending_buffers=1)
    return control


def counters(control):
    return control[2]['samples'][0]['details']['counters']


def arenas(control, count, uncached=0):
    counters(control).update(upload_arenas=count, vertex_bytes=120 * count,
                             index_bytes=6 * count, uniform_bytes=64 * count,
                             gpu_buffer_allocations=3 * count, gpu_buffer_reuses=0,
                             gpu_buffer_allocated_bytes=200 * count,
                             transform_binding_allocations=count,
                             uncached_upload_arenas=uncached)


class StagingEncodeDetailTests(unittest.TestCase):
    def summarize(self, control):
        return reader.summarize(control[2], control[1], control[0], control[4])

    def test_complete_cold_frame_preserves_distinct_source_destination_and_resident_counts(self):
        control = fixture()
        before = copy.deepcopy(control)
        summary = self.summarize(control)
        self.assertEqual(control, before)
        self.assertEqual(summary['schema'], 'rust_duty_cpu_encode_detail_v4')
        self.assertEqual(summary['staging_policy'], 'bounded_staging_v1')
        self.assertEqual(summary['diagnostic_status'], 'complete')
        self.assertEqual(summary['summarized_attempts'], 1)
        self.assertEqual(set(summary['gauges']), set(GAUGES))
        self.assertEqual(set(summary['counters']), set(resident.V3_COUNTERS + FIELDS) - set(GAUGES))
        for field in ('staging_buffer_allocations', 'gpu_buffer_allocations',
                      'resident_buffer_allocations', 'staging_copy_bytes'):
            self.assertEqual(summary['counters'][field]['total'], counters(control)[field])
        self.assertIn('timestamps start after staged copies and exclude them', summary['scope'])

    def test_warm_source_reuse_is_an_observation_with_zero_new_source_allocations(self):
        control = fixture()
        counters(control).update(staging_buffer_allocations=0, staging_buffer_reuses=1,
                                 staging_buffer_allocated_bytes=0)
        summary = self.summarize(control)
        self.assertEqual(summary['counters']['staging_buffer_reuses']['p50'], 1)
        self.assertEqual(summary['counters']['staging_buffer_allocations']['p50'], 0)
        self.assertEqual(summary['gauges']['staging_pending_buffers']['p50'], 1)

    def test_whole_arena_fallback_can_coexist_with_eight_older_pending_chunks(self):
        control = fixture()
        counters(control).update(staging_buffer_allocations=0, staging_buffer_allocated_bytes=0,
                                 staging_copy_bytes=0, staging_queue_write_calls=3,
                                 staging_queue_write_bytes=192, staging_fallback_arenas=1,
                                 staging_retained_bytes=CAPACITY, staging_pending_buffers=8)
        summary = self.summarize(control)
        self.assertEqual(summary['counters']['staging_fallback_arenas']['total'], 1)
        self.assertEqual(summary['gauges']['staging_pending_buffers']['max'], 8)

    def test_mixed_copy_and_whole_group_queue_write_routes(self):
        control = fixture()
        arenas(control, 2)
        counters(control).update(staging_queue_write_calls=3,
                                 staging_queue_write_bytes=192, staging_fallback_arenas=1)
        self.assertEqual(self.summarize(control)['counters']['staging_copy_bytes']['total'], 192)

    def test_immutable_uncached_arenas_and_resident_uploads_are_outside_staging_pool(self):
        control = fixture()
        arenas(control, 2, uncached=1)
        self.assertEqual(self.summarize(control)['counters']['staging_buffer_allocations']['total'], 1)
        control[2]['upload_policy'] = 'immutable_per_frame_v1'
        arenas(control, 2, uncached=2)
        counters(control).update(dict.fromkeys(FIELDS, 0))
        summary = self.summarize(control)
        self.assertEqual(summary['counters']['staging_copy_bytes']['total'], 0)
        self.assertEqual(summary['counters']['resident_draws']['total'], 5)

    def test_empty_arena_frame_may_retain_old_pending_ownership(self):
        control = fixture()
        arenas(control, 0)
        counters(control).update(dict.fromkeys(FIELDS, 0))
        counters(control).update(staging_retained_bytes=512, staging_pending_buffers=2)
        summary = self.summarize(control)
        self.assertEqual(summary['counters']['staging_buffer_allocations']['total'], 0)
        self.assertEqual(summary['gauges']['staging_retained_bytes']['max'], 512)

    def test_queue_write_policy_has_no_pooled_source_observations(self):
        control = fixture()
        control[2]['staging_policy'] = 'queue_write_staging_v1'
        counters(control).update(dict.fromkeys(FIELDS, 0))
        counters(control).update(staging_queue_write_calls=3,
                                 staging_queue_write_bytes=192, staging_fallback_arenas=1)
        self.assertEqual(self.summarize(control)['staging_policy'], 'queue_write_staging_v1')
        for changes in ({'staging_retained_bytes': 256},
                        {'staging_retained_bytes': 256, 'staging_pending_buffers': 1}):
            bad = copy.deepcopy(control)
            counters(bad).update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(bad)
        bad = fixture()
        bad[2]['staging_policy'] = 'queue_write_staging_v1'
        with self.assertRaises(ValueError):
            self.summarize(bad)

    def test_eight_source_chunks_and_exact_capacity_bound_are_inclusive(self):
        control = fixture()
        arenas(control, 8)
        counters(control).update(staging_buffer_allocations=8,
                                 staging_buffer_allocated_bytes=2048,
                                 staging_copy_bytes=1536, staging_retained_bytes=CAPACITY,
                                 staging_pending_buffers=8)
        self.assertEqual(self.summarize(control)['gauges']['staging_retained_bytes']['max'], CAPACITY)
        for changes in ({'staging_pending_buffers': 9}, {'staging_retained_bytes': CAPACITY + 8}):
            bad = copy.deepcopy(control)
            counters(bad).update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(bad)

    def test_missing_extra_and_invalid_schema_policy_fields_fail_closed(self):
        for value in (None, True, 'unknown', 'bounded_reuse_v1'):
            bad = fixture()
            bad[2]['staging_policy'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.summarize(bad)
        for mutate in (lambda d: d.pop('staging_policy'),
                       lambda d: d.update(unobserved_copy_time=0),
                       lambda d: d.update(schema='rust_duty_cpu_encode_detail_v5'),
                       lambda d: d.update(interpretation=reader.INTERPRETATION)):
            bad = fixture()
            mutate(bad[2])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.summarize(bad)
        for name in FIELDS:
            bad = fixture()
            del counters(bad)[name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                self.summarize(bad)
        bad = fixture()
        counters(bad)['staging_driver_allocations'] = 0
        with self.assertRaises(ValueError):
            self.summarize(bad)

    def test_every_staging_observation_is_an_exact_u64_even_on_partial_rows(self):
        for name in FIELDS:
            for value in (True, -1, 1.0, '1', None, U64_MAX + 1, float('inf')):
                bad = fixture()
                bad[2]['samples'][0]['details'].update(state='incomplete', error='upload_interrupted')
                counters(bad)[name] = value
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.summarize(bad)

    def test_complete_rows_reject_missing_duplicate_or_partial_routes(self):
        for changes in ({'staging_buffer_allocations': 2}, {'staging_buffer_reuses': 1},
                        {'staging_fallback_arenas': 1}, {'staging_queue_write_calls': 1},
                        {'staging_queue_write_bytes': 4}, {'staging_copy_bytes': 0},
                        {'staging_buffer_allocations': 0, 'staging_buffer_allocated_bytes': 0,
                         'staging_copy_bytes': 0}):
            bad = fixture()
            counters(bad).update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(bad)

    def test_padded_odd_index_payload_is_exactly_preserved(self):
        for size in (0, 12, 188, 190, 191, 194, 196, 256):
            bad = fixture()
            counters(bad)['staging_copy_bytes'] = size
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.summarize(bad)
        control = fixture()
        counters(control).update(index_bytes=8)
        self.assertEqual(self.summarize(control)['counters']['staging_copy_bytes']['total'], 192)

    def test_uncached_payload_does_not_allow_overreporting_copied_bytes(self):
        bad = fixture()
        arenas(bad, 2, uncached=1)
        counters(bad).update(staging_copy_bytes=388, staging_buffer_allocated_bytes=512,
                             staging_retained_bytes=512)
        with self.assertRaises(ValueError):
            self.summarize(bad)

    def test_complete_capacity_cannot_lose_pending_or_newly_allocated_sources(self):
        for changes in ({'staging_buffer_allocated_bytes': 0},
                        {'staging_buffer_allocated_bytes': 255},
                        {'staging_buffer_allocated_bytes': 512},
                        {'staging_retained_bytes': 128}, {'staging_retained_bytes': 255},
                        {'staging_pending_buffers': 0}, {'staging_map_failures': 1}):
            bad = fixture()
            counters(bad).update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(bad)

    def test_partial_failures_keep_raw_observations_without_distribution(self):
        control = fixture()
        row = control[2]['samples'][0]['details']
        row.update(state='incomplete', error='staging_mapping_failed', spans=row['spans'][:1])
        counters(control).update(dict.fromkeys(FIELDS, U64_MAX))
        before = copy.deepcopy(control)
        summary = self.summarize(control)
        self.assertEqual(control, before)
        self.assertEqual(summary['diagnostic_status'], 'incomplete')
        self.assertEqual(summary['summarized_attempts'], 0)
        for name in FIELDS:
            value = summary['gauges' if name in GAUGES else 'counters'][name]
            self.assertEqual(value['sample_count'], 0)
            self.assertIsNone(value['p50'])
            if name in GAUGES:
                self.assertNotIn('total', value)
            else:
                self.assertEqual(value['total'], 0)

    def test_gauges_report_distributions_without_cumulative_memory_totals(self):
        control = fixture()
        historical.append_attempt(*control[:3])
        second = control[2]['samples'][1]['details']['counters']
        second.update(staging_buffer_allocations=0, staging_buffer_reuses=1,
                      staging_buffer_allocated_bytes=0,
                      staging_retained_bytes=512, staging_pending_buffers=2)
        control[3], control[4] = historical.rebind(*control[:3])
        summary = self.summarize(control)
        self.assertEqual(summary['counters']['staging_buffer_allocations']['total'], 1)
        self.assertEqual(summary['counters']['staging_buffer_reuses']['total'], 1)
        self.assertEqual(summary['counters']['staging_copy_bytes']['total'], 384)
        for name, low, high in (('staging_retained_bytes', 256, 512),
                                ('staging_pending_buffers', 1, 2)):
            observation = summary['gauges'][name]
            self.assertNotIn('total', observation)
            self.assertEqual(observation['sample_count'], 2)
            self.assertEqual(observation['p50'], low)
            self.assertEqual(observation['p95'], high)

    def test_incomplete_parent_cannot_promote_complete_staging_row(self):
        for parent in ('substage', 'primary'):
            control = fixture()
            if parent == 'substage':
                control[1]['samples'][0]['details'].update(state='incomplete', error='unterminated_substage')
            else:
                control[0].update(incomplete_at_ns=205,
                                  status={'state': 'incomplete', 'error': 'synthetic failure'})
                control[3], control[4] = historical.rebind(*control[:3])
            with self.subTest(parent=parent):
                summary = self.summarize(control)
                self.assertEqual(summary['summarized_attempts'], 0)
                self.assertIsNone(summary['gauges']['staging_retained_bytes']['max'])

    def test_skipped_failed_and_ineligible_attempts_do_not_enter_staging_distributions(self):
        for kind, eligible in (('successful_present_return', False), ('skipped_frame', True),
                               ('boundary', True)):
            control = fixture()
            historical.append_attempt(*control[:3], kind, eligible)
            control[2]['samples'][1]['details']['counters']['staging_retained_bytes'] = CAPACITY
            control[3], control[4] = historical.rebind(*control[:3])
            with self.subTest(kind=kind):
                summary = self.summarize(control)
                self.assertEqual(summary['retained_attempts'], 2)
                self.assertEqual(summary['summarized_attempts'], 1)
                self.assertEqual(summary['gauges']['staging_retained_bytes']['max'], 256)

    def test_historical_v1_v2_v3_keep_their_original_fields_and_interpretation(self):
        for factory in (historical.fixture, historical.v2_fixture, resident.fixture):
            control = factory()
            before = copy.deepcopy(control)
            summary = self.summarize(control)
            self.assertEqual(control, before)
            self.assertNotIn('staging_policy', summary)
            self.assertNotIn('gauges', summary)
            self.assertTrue(set(FIELDS).isdisjoint(summary['counters']))
            for addition in ('staging_policy', 'staging_counter', 'interpretation'):
                bad = copy.deepcopy(control)
                if addition == 'staging_policy':
                    bad[2]['staging_policy'] = 'bounded_staging_v1'
                elif addition == 'staging_counter':
                    counters(bad)['staging_buffer_allocations'] = 0
                else:
                    bad[2]['interpretation'] = reader.INTERPRETATION_V4
                with self.subTest(schema=control[2]['schema'], addition=addition), self.assertRaises(ValueError):
                    self.summarize(bad)

    def test_raw_primary_byte_hash_must_match_both_parent_bound_sidecars(self):
        control = fixture()
        raw = (json.dumps(control[0], indent=2) + '\r\n').encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        self.assertNotEqual(digest, control[4])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frames.json'
            path.write_bytes(raw)
            primary, observed = reader.read_json(path)
            self.assertEqual(observed, digest)
            for repaired in ((), (1,), (2,)):
                bad = copy.deepcopy(control)
                for index in repaired:
                    bad[index]['frame_report_sha256'] = digest
                with self.subTest(repaired=repaired), self.assertRaises(ValueError):
                    reader.validate(bad[2], bad[1], primary, observed)
            control[1]['frame_report_sha256'] = control[2]['frame_report_sha256'] = digest
            self.assertEqual(reader.summarize(control[2], control[1], primary, observed)['summarized_attempts'], 1)
            self.assertEqual(path.read_bytes(), raw)

    def test_retained_attempt_join_and_narrow_encode_parent_remain_strict(self):
        for target in (1, 2):
            bad = fixture()
            bad[target]['samples'][0]['record_index'] = 0
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.summarize(bad)
        bad = fixture()
        bad[2]['samples'][0]['details']['spans'][-1].update(ended_at_ns=166, duration_ns=6)
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.summarize(bad)

    def test_duplicate_raw_staging_field_is_rejected_before_schema_validation(self):
        original = json.dumps(fixture()[2])
        raw = original.replace('"staging_copy_bytes": 192',
                               '"staging_copy_bytes": 192, "staging_copy_bytes": 0')
        self.assertNotEqual(raw, original)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'detail.json'
            path.write_bytes(raw.encode('utf-8'))
            with self.assertRaises(ValueError):
                reader.read_json(path)


if __name__ == '__main__':
    unittest.main()
