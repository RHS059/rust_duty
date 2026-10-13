"""Independent v3 resident counters; synthetic evidence, never a GPU timing test."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import summarize_cpu_encode_detail as reader
import test_summarize_cpu_encode_detail as historical


RESIDENT_COUNTERS = (
    'resident_draws', 'resident_rigid_draws', 'resident_skinned_draws',
    'resident_vertex_bytes_uploaded', 'resident_index_bytes_uploaded',
    'resident_uniform_bytes_uploaded', 'resident_cache_hits',
    'resident_cache_misses', 'resident_transient_meshes',
    'resident_buffer_allocations', 'resident_binding_allocations',
)
V3_COUNTERS = historical.V2_COUNTERS + RESIDENT_COUNTERS
U64_MAX = 2**64 - 1


def fixture():
    primary, substages, detail, raw, digest = historical.v2_fixture()
    detail.update(schema='rust_duty_cpu_encode_detail_v3',
                  resident_policy='vertex_lit_skin_v1')
    counters = detail['samples'][0]['details']['counters']
    # Two cold triangles (32/80-byte vertices), then three shared-geometry hits.
    # One rigid and one skin palette occupy distinct 16 KiB ranges; five draw
    # snapshots have 256-byte offsets and a 240-byte final binding.
    counters.update(prepared_draws=8, draw_calls=8,
                    resident_draws=5, resident_rigid_draws=2,
                    resident_skinned_draws=3, resident_vertex_bytes_uploaded=336,
                    resident_index_bytes_uploaded=16,
                    resident_uniform_bytes_uploaded=34_032,
                    resident_cache_hits=3, resident_cache_misses=2,
                    resident_transient_meshes=1,
                    resident_buffer_allocations=6, resident_binding_allocations=2)
    return primary, substages, detail, raw, digest


class ResidentEncodeDetailTests(unittest.TestCase):
    def summarize(self, control):
        primary, substages, detail, _, digest = control
        return reader.summarize(detail, substages, primary, digest)

    def test_complete_mixed_frame_has_separate_resident_and_arena_accounting(self):
        control = fixture()
        before = copy.deepcopy(control)
        result = self.summarize(control)
        self.assertEqual(control, before)
        self.assertEqual(result['schema'], 'rust_duty_cpu_encode_detail_v3')
        self.assertEqual(result['resident_policy'], 'vertex_lit_skin_v1')
        self.assertEqual(result['upload_policy'], 'bounded_reuse_v1')
        self.assertEqual(result['diagnostic_status'], 'complete')
        self.assertEqual(result['summarized_attempts'], 1)
        self.assertEqual(set(result['counters']), set(V3_COUNTERS))
        observed = control[2]['samples'][0]['details']['counters']
        for name in V3_COUNTERS:
            self.assertEqual(result['counters'][name]['total'], observed[name])
        # Resident buffers are deliberately absent from the old three-per-arena
        # count. A complete mixed frame must not reinterpret that older field.
        self.assertEqual(result['counters']['gpu_buffer_allocations']['total'], 3)
        self.assertEqual(result['counters']['vertex_bytes']['total'], 120)

    def test_warm_resident_frame_has_observed_zero_geometry_uploads(self):
        control = fixture()
        counters = control[2]['samples'][0]['details']['counters']
        counters.update(resident_vertex_bytes_uploaded=0, resident_index_bytes_uploaded=0,
                        resident_cache_misses=0, resident_cache_hits=5,
                        resident_transient_meshes=0, resident_buffer_allocations=2)
        result = self.summarize(control)
        for name in ('resident_vertex_bytes_uploaded', 'resident_index_bytes_uploaded'):
            self.assertEqual(result['counters'][name]['sample_count'], 1)
            self.assertEqual(result['counters'][name]['p50'], 0)
        self.assertEqual(result['counters']['resident_uniform_bytes_uploaded']['p50'], 34_032)
        self.assertEqual(result['counters']['resident_buffer_allocations']['p50'], 2)
        self.assertEqual(result['counters']['resident_binding_allocations']['p50'], 2)

    def test_complete_cpu_only_v3_frame_records_real_resident_zeroes(self):
        control = fixture()
        control[2]['samples'][0]['details']['counters'].update(dict.fromkeys(RESIDENT_COUNTERS, 0))
        result = self.summarize(control)
        for name in RESIDENT_COUNTERS:
            self.assertEqual(result['counters'][name]['sample_count'], 1)
            self.assertEqual(result['counters'][name]['min'], 0)

    def test_cpu_reference_policy_requires_complete_resident_zeroes(self):
        control = fixture()
        control[2]['resident_policy'] = 'cpu_vertex_reference_v1'
        # The original mixed counters are internally consistent; this must fail
        # specifically because the declared source policy is CPU-only.
        with self.assertRaisesRegex(ValueError, 'CPU reference policy'):
            self.summarize(control)
        control[2]['samples'][0]['details']['counters'].update(dict.fromkeys(RESIDENT_COUNTERS, 0))
        result = self.summarize(control)
        self.assertEqual(result['resident_policy'], 'cpu_vertex_reference_v1')
        self.assertEqual(result['summarized_attempts'], 1)
        self.assertEqual(result['counters']['resident_draws']['p50'], 0)
        control[2]['samples'][0]['details'].update(state='incomplete', error='encode_not_observed', spans=[])
        result = self.summarize(control)
        self.assertEqual(result['summarized_attempts'], 0)
        self.assertIsNone(result['counters']['resident_draws']['p50'])

    def test_existing_immutable_arena_policy_is_independent_of_resident_caching(self):
        control = fixture()
        control[2]['upload_policy'] = 'immutable_per_frame_v1'
        control[2]['samples'][0]['details']['counters'].update(
            uncached_upload_arenas=1, gpu_buffer_allocated_bytes=192)
        self.assertEqual(self.summarize(control)['counters']['resident_cache_hits']['total'], 3)

    def test_historical_schemas_never_gain_fabricated_resident_fields(self):
        for factory in (historical.fixture, historical.v2_fixture):
            control = factory()
            before = copy.deepcopy(control)
            result = self.summarize(control)
            self.assertEqual(control, before)
            self.assertNotIn('resident_policy', result)
            self.assertTrue(set(RESIDENT_COUNTERS).isdisjoint(result['counters']))

    def test_policy_and_schema_fields_are_closed_for_each_version(self):
        for key, value in (('resident_policy', None), ('resident_policy', 'cpu_fallback'),
                           ('resident_policy', True), ('schema', 'rust_duty_cpu_encode_detail_v4')):
            control = fixture()
            control[2][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.summarize(control)
        for factory in (historical.fixture, historical.v2_fixture):
            control = factory()
            control[2]['resident_policy'] = 'vertex_lit_skin_v1'
            with self.subTest(schema=control[2]['schema']), self.assertRaises(ValueError):
                self.summarize(control)
        control = fixture()
        del control[2]['resident_policy']
        with self.assertRaises(ValueError):
            self.summarize(control)

    def test_every_resident_field_is_required_and_unknown_fields_are_rejected(self):
        for name in RESIDENT_COUNTERS:
            control = fixture()
            del control[2]['samples'][0]['details']['counters'][name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.summarize(control)
        control = fixture()
        control[2]['samples'][0]['details']['counters']['resident_gpu_nanoseconds'] = 1
        with self.assertRaises(ValueError):
            self.summarize(control)

    def test_every_resident_counter_is_an_exact_unsigned_u64_even_when_partial(self):
        for name in RESIDENT_COUNTERS:
            for value in (True, -1, 1.0, '1', None, U64_MAX + 1, float('inf')):
                control = fixture()
                row = control[2]['samples'][0]['details']
                row.update(state='incomplete', error='encode_incomplete')
                row['counters'][name] = value
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.summarize(control)

    def test_complete_resident_draw_relationships_are_checked(self):
        for changes in (
            {'resident_rigid_draws': 1},
            {'resident_skinned_draws': 4},
            {'resident_cache_hits': 2},
            {'resident_cache_misses': 3},
            {'prepared_draws': 4},
            {'resident_transient_meshes': 3},
        ):
            control = fixture()
            control[2]['samples'][0]['details']['counters'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(control)

    def test_complete_cold_and_snapshot_byte_contradictions_are_rejected(self):
        for changes in (
            {'resident_vertex_bytes_uploaded': 0},
            {'resident_index_bytes_uploaded': 0},
            {'resident_vertex_bytes_uploaded': 7},
            {'resident_index_bytes_uploaded': 7},
            {'resident_uniform_bytes_uploaded': 0},
            {'resident_uniform_bytes_uploaded': 1199},
            {'resident_cache_misses': 0, 'resident_cache_hits': 5,
             'resident_transient_meshes': 0},
        ):
            control = fixture()
            control[2]['samples'][0]['details']['counters'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(control)
        control = fixture()
        counters = control[2]['samples'][0]['details']['counters']
        counters.update(dict.fromkeys(RESIDENT_COUNTERS, 0))
        counters['resident_uniform_bytes_uploaded'] = 240
        with self.assertRaises(ValueError):
            self.summarize(control)

    def test_v3_does_not_weaken_existing_arena_allocation_relationships(self):
        for changes in ({'gpu_buffer_reuses': 1}, {'gpu_buffer_allocated_bytes': 0},
                        {'transform_binding_allocations': 2}, {'uncached_upload_arenas': 2}):
            control = fixture()
            control[2]['samples'][0]['details']['counters'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(control)

    def test_minimum_resident_snapshot_includes_the_required_palette_binding(self):
        control = fixture()
        counters = control[2]['samples'][0]['details']['counters']
        # The smallest accepted rigid triangle may repeat its one vertex index.
        counters.update(resident_draws=1, resident_rigid_draws=1,
                        resident_skinned_draws=0, resident_vertex_bytes_uploaded=32,
                        resident_index_bytes_uploaded=8,
                        resident_uniform_bytes_uploaded=16_384 + 240,
                        resident_cache_hits=0, resident_cache_misses=1,
                        resident_transient_meshes=0, resident_buffer_allocations=4)
        self.assertEqual(self.summarize(control)['summarized_attempts'], 1)
        for changes in (
            {'resident_uniform_bytes_uploaded': 240},
            {'resident_uniform_bytes_uploaded': 16_383 + 240},
            {'resident_uniform_bytes_uploaded': 16_384 + 241},
            {'resident_vertex_bytes_uploaded': 28},
            {'resident_vertex_bytes_uploaded': 33},
            {'resident_index_bytes_uploaded': 4},
            {'resident_index_bytes_uploaded': 9},
        ):
            changed = copy.deepcopy(control)
            changed[2]['samples'][0]['details']['counters'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(changed)

    def test_complete_resident_allocations_account_for_snapshots_and_cold_meshes(self):
        for changes in (
            {'resident_buffer_allocations': 4},  # Omits the two snapshot buffers.
            {'resident_buffer_allocations': 2},  # Omits the two cold mesh pairs.
            {'resident_buffer_allocations': 7},
            {'resident_binding_allocations': 0},
            {'resident_binding_allocations': 1},
            {'resident_binding_allocations': 3},
        ):
            control = fixture()
            control[2]['samples'][0]['details']['counters'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(control)
        for name in ('resident_buffer_allocations', 'resident_binding_allocations'):
            control = fixture()
            counters = control[2]['samples'][0]['details']['counters']
            counters.update(dict.fromkeys(RESIDENT_COUNTERS, 0))
            counters[name] = 1
            with self.subTest(empty_frame_counter=name), self.assertRaises(ValueError):
                self.summarize(control)

    def test_partial_resident_observations_are_retained_but_never_summarized(self):
        control = fixture()
        row = control[2]['samples'][0]['details']
        row.update(state='incomplete', error='encode_incomplete', spans=row['spans'][:2])
        row['counters'].update(dict.fromkeys(RESIDENT_COUNTERS, U64_MAX))
        before = copy.deepcopy(control)
        result = self.summarize(control)
        self.assertEqual(control, before)
        self.assertEqual(result['diagnostic_status'], 'incomplete')
        self.assertEqual(result['summarized_attempts'], 0)
        for name in RESIDENT_COUNTERS:
            self.assertEqual(result['counters'][name]['sample_count'], 0)
            self.assertEqual(result['counters'][name]['total'], 0)
            self.assertIsNone(result['counters'][name]['p50'])

    def test_complete_child_is_suppressed_by_incomplete_substage_or_primary(self):
        for parent in ('substage', 'primary'):
            control = list(fixture())
            if parent == 'substage':
                control[1]['samples'][0]['details'].update(state='incomplete', error='unterminated_substage')
            else:
                control[0].update(incomplete_at_ns=205,
                                  status={'state': 'incomplete', 'error': 'synthetic failure'})
                control[3], control[4] = historical.rebind(*control[:3])
            with self.subTest(parent=parent):
                result = self.summarize(control)
                self.assertEqual(result['summarized_attempts'], 0)
                self.assertIsNone(result['counters']['resident_draws']['p95'])

    def test_failed_skipped_and_ineligible_rows_do_not_join_valid_resident_totals(self):
        for kind, eligible in (('successful_present_return', False), ('skipped_frame', True),
                               ('boundary', True)):
            control = list(fixture())
            historical.append_attempt(*control[:3], kind, eligible)
            control[2]['samples'][1]['details']['counters']['resident_uniform_bytes_uploaded'] = U64_MAX - 3
            control[3], control[4] = historical.rebind(*control[:3])
            with self.subTest(kind=kind):
                result = self.summarize(control)
                self.assertEqual(result['retained_attempts'], 2)
                self.assertEqual(result['summarized_attempts'], 1)
                self.assertEqual(result['counters']['resident_uniform_bytes_uploaded']['total'], 34_032)

    def test_attempt_order_and_both_parent_hashes_remain_required(self):
        for target in ('detail_hash', 'substage_hash', 'detail_index', 'substage_index'):
            control = fixture()
            if target.endswith('hash'):
                control[2 if target.startswith('detail') else 1]['frame_report_sha256'] = '0' * 64
            else:
                control[2 if target.startswith('detail') else 1]['samples'][0]['record_index'] = 0
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.summarize(control)

    def test_reformatted_primary_needs_exact_new_bytes_in_both_sidecars(self):
        primary, substages, detail, _, old_digest = fixture()
        raw = (json.dumps(primary, indent=2) + '\r\n').encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        self.assertNotEqual(digest, old_digest)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frames.json'
            path.write_bytes(raw)
            decoded, observed_digest = reader.read_json(path)
            self.assertEqual(observed_digest, digest)
            for repair in ((), ('detail',), ('substage',)):
                child, encode = copy.deepcopy((substages, detail))
                if 'detail' in repair:
                    encode['frame_report_sha256'] = digest
                if 'substage' in repair:
                    child['frame_report_sha256'] = digest
                with self.subTest(repair=repair), self.assertRaises(ValueError):
                    reader.validate(encode, child, decoded, observed_digest)
            substages['frame_report_sha256'] = detail['frame_report_sha256'] = digest
            self.assertEqual(reader.summarize(detail, substages, decoded, digest)['summarized_attempts'], 1)
            self.assertEqual(path.read_bytes(), raw)

    def test_resident_rows_remain_inside_narrow_encode_parent(self):
        control = fixture()
        final = control[2]['samples'][0]['details']['spans'][-1]
        final.update(ended_at_ns=166, duration_ns=6)
        # Still inside the renderer parent but one ns beyond encode_submit.
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.summarize(control)

    def test_resident_totals_use_exact_integers_beyond_one_u64(self):
        control = list(fixture())
        historical.append_attempt(*control[:3])
        for sample in control[2]['samples']:
            sample['details']['counters']['resident_uniform_bytes_uploaded'] = U64_MAX - 3
        control[3], control[4] = historical.rebind(*control[:3])
        counts = self.summarize(control)['counters']['resident_uniform_bytes_uploaded']
        self.assertEqual(counts['sample_count'], 2)
        self.assertEqual(counts['total'], 2 * (U64_MAX - 3))
        self.assertEqual(counts['p50'], U64_MAX - 3)
        self.assertEqual(json.loads(json.dumps(counts))['total'], 2 * (U64_MAX - 3))

    def test_raw_reader_rejects_duplicate_resident_fields_before_validation(self):
        detail = fixture()[2]
        raw = json.dumps(detail).replace('"resident_draws": 5',
                                         '"resident_draws": 5, "resident_draws": 0')
        self.assertNotEqual(raw, json.dumps(detail))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'detail.json'
            path.write_bytes(raw.encode('utf-8'))
            with self.assertRaises(ValueError):
                reader.read_json(path)


if __name__ == '__main__':
    unittest.main()
