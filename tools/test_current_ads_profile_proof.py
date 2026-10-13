"""Synthetic current-proof controls, never native observation or acceptance.

Every positive uses the actual public recomputation entry point and existing
clipping/fragment arithmetic. Invented source intervals/receipts only exercise
conditional source-proof validation; they provide no production/native evidence.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import current_ads_profile_proof as proof


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def vertex(x, y, w=1):
    return [[x, x], [y, y], [0, 0], [w, w]]


def domain(kind, mesh):
    return {'kind': kind, 'mesh': mesh, 'domain': {
        'checked_abstract_nodes': 100, 'positions': 3,
        'minimum_nonzero_dyadic_exponent': -96, 'maximum_rounded_magnitude_upper': 3.0,
        'unsupported_domain_nodes': 0, 'normal_or_exact_zero_no_overflow': True,
        'scope': 'Synthetic arithmetic-domain control, not native evidence'}}


def synthetic_header():
    return {**deepcopy(proof.source.HEADER_FIELDS), **proof.source.PROFILE_FIELDS,
            'backend_profile': proof.source.BACKEND_PROFILES['windows-legacy'],
            'profile_native_verified': False, 'backend_native_upload_identity_verified': False,
            'native_invocation_binding_verified': False,
            'profile_assumptions_independently_established': False,
            'sources': [{'vra': 'synthetic/asset.vra', 'companion_crc32': [1, 2],
                         'skin_meshes': 1, 'rigid_meshes': 2}]}


def synthetic_source(frame=17):
    return {'frame': frame, 'committed_tick': frame, 'time': 0.1, 'route': 'authored',
            'visual_ads': 0.5, 'ammo': 12, 'shots': 0, 'companion_catalog_vra': 'synthetic/asset.vra',
            'companion_crc32': [1, 2], 'source_triangles': 3, 'outside_bottom': 1,
            'hidden_source_triangles': 1, 'unclassified_triangles': 1,
            'classification': 'potentially_visible_unresolved', 'maximum_bottom_upper': 2.0,
            'meshes': [
                {'kind': 'skin', 'mesh': 0, 'triangles': 1, 'state': 'enumerated',
                 'outside_bottom': 1, 'unclassified': 0, 'maximum_bottom_upper': -0.1, 'opacity': 1.0},
                {'kind': 'rigid', 'mesh': 0, 'triangles': 1, 'state': 'enumerated',
                 'outside_bottom': 0, 'unclassified': 1, 'maximum_bottom_upper': 2.0, 'opacity': 1.0},
                {'kind': 'rigid', 'mesh': 1, 'triangles': 1, 'state': 'source_actor_hidden', 'opacity': 1.0}],
            'unsupported_clip_triangles': 0, 'possible_support_complete': True,
            'required_contrast_samples': 1, 'possible_samples': 1,
            'required_contrast_runs': [[270 * 960 + 480, 1]], 'possible_support_runs': [[270 * 960 + 480, 1]],
            'acceptance_verdict': None, 'native_gameplay': {'ammo': 12, 'clip': 'synthetic-ads'},
            'native_time': {'elapsed_seconds': 0.1, 'sampling_hz': 59.94}}


def synthetic_trace(frame=17, *, empty=False):
    row = synthetic_source(frame)
    identity = [bits(1.0 if i % 5 == 0 else 0.0) for i in range(16)]
    triangle = {'kind': 'rigid', 'mesh': 0, 'triangle': 0, 'indices': [0, 1, 2],
                'clip': [vertex(-0.1, -0.1), vertex(0.1, -0.1), vertex(0, 0.1)],
                'screen': [[[432.0, 432.0], [297.0, 297.0]],
                           [[528.0, 528.0], [297.0, 297.0]], [[480.0, 480.0], [243.0, 243.0]]],
                'colors': [[70, 70, 70, 255]] * 3, 'texture_bounds': [[255, 255]] * 3,
                'safe_contrast': True, 'projection_bits': identity, 'model_bits': identity,
                'position_bits': [[bits(x), bits(y), bits(0)] for x, y in [(-0.1, -0.1), (0.1, -0.1), (0, 0.1)]]}
    row.update(original_native_observations=False,
               geometry_domain=[domain('skin', 0), domain('rigid', 0)], triangle_trace=[triangle],
               triangle_partition=[
                   {'kind': 'skin', 'mesh': 0, 'triangles': 1, 'source_hidden': False, 'traced_runs': [],
                    'separated': [{'axis': 1, 'sign': 1, 'runs': [[0, 1]], 'maximum_plane_upper': -0.1}]},
                   {'kind': 'rigid', 'mesh': 0, 'triangles': 1, 'source_hidden': False,
                    'traced_runs': [[0, 1]], 'separated': []},
                   {'kind': 'rigid', 'mesh': 1, 'triangles': 1, 'source_hidden': True,
                    'traced_runs': [], 'separated': []}])
    if empty:
        row.update(classification='expected_empty_under_profile', outside_bottom=2,
                   unclassified_triangles=0, required_contrast_samples=0, possible_samples=0,
                   required_contrast_runs=[], possible_support_runs=[], triangle_trace=[], maximum_bottom_upper=-0.1)
        row['meshes'][1].update(outside_bottom=1, unclassified=0, maximum_bottom_upper=-0.1)
        row['triangle_partition'][1].update(traced_runs=[], separated=[
            {'axis': 1, 'sign': 1, 'runs': [[0, 1]], 'maximum_plane_upper': -0.1}])
    return row


def expected_from_trace(row):
    return {key: deepcopy(value) for key, value in row.items() if key not in proof.TRACE_EXTRAS}


def trace_header(frames):
    header = synthetic_header()
    return {**header, 'schema': proof.TRACE_SCHEMA, 'source_certificate_schema': header['schema'],
            'requested_frames': frames, 'original_native_observations': False}


def jsonl(path, records):
    path.write_text('\n'.join(json.dumps(row, default=float) for row in records) + '\n')


class SyntheticPureRecomputation(unittest.TestCase):
    def calculate(self, row=None, expected=None, *, frames=None):
        row = row or synthetic_trace()
        return proof.validate_gl_proof([expected or expected_from_trace(row)], [row],
            frames=[row['frame']] if frames is None else frames,
            expected_header=synthetic_header(), trace_header=trace_header([row['frame']]))

    def test_real_calculators_expand_possible_and_retain_required(self):
        result = self.calculate()
        row = result['frames'][0]
        self.assertEqual(row['required_runs'], [[259680, 1]])
        self.assertGreater(row['possible_samples'], 1)
        self.assertEqual(row['source_triangles'], 3)
        self.assertEqual(row['traced_triangles'], 1)
        self.assertEqual(row['strictly_separated_triangles'], 1)
        self.assertEqual(row['source_hidden_triangles'], 1)
        self.assertTrue(result['conditional_source_proof_complete'])
        self.assertTrue(result['source_catalog_checked'])
        self.assertGreater(result['fragment_frames'][0]['examined_overlapping_subtriangles'], 0)
        self.assertLessEqual(result['fragment_frames'][0]['max_retained_triangle_byte_bound'], 3)
        self.assertTrue(all(result[key] is False for key in proof.FALSE_FLAGS))
        self.assertIsNone(result['acceptance_verdict'])

    def test_actual_empty_frame_requires_complete_separated_partition(self):
        result = self.calculate(synthetic_trace(empty=True))
        self.assertEqual(result['frames'][0]['required_runs'], [])
        self.assertEqual(result['frames'][0]['possible_runs'], [])
        self.assertEqual(result['frames'][0]['strictly_separated_triangles'], 2)

    def test_native_draw_extension_is_not_a_geometry_claim(self):
        row = synthetic_trace()
        expected = expected_from_trace(row)
        expected['expected_draw_inventory'] = {'synthetic': 'validated by separate native binder'}
        with self.assertRaisesRegex(ValueError, 'trace lacks'):
            self.calculate(row, expected)
        row['expected_draw_inventory'] = deepcopy(expected['expected_draw_inventory'])
        self.assertTrue(self.calculate(row, expected)['conditional_source_proof_complete'])

    def test_full_source_state_checks_nested_gameplay_time_and_types(self):
        for field, key, value in [('native_gameplay', 'ammo', 11), ('native_gameplay', 'ammo', 12.0),
                                  ('native_time', 'sampling_hz', 60.0)]:
            row = synthetic_trace()
            expected = expected_from_trace(row)
            row[field][key] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'full current source state'):
                self.calculate(row, expected)

    def test_source_native_draw_header_marker_is_kept_out_of_geometry_identity(self):
        header = synthetic_header()
        header['native_draw_inventory_schema'] = 'rust-duty-native-visibility-receipt/v1'
        row = synthetic_trace()
        result = proof.validate_gl_proof([expected_from_trace(row)], [row], frames=[17],
            expected_header=header, trace_header={**trace_header([17]),
                'native_draw_inventory_schema': header['native_draw_inventory_schema']})
        self.assertFalse(result['trace_execution_binding_verified'])

    def test_missing_or_duplicate_selected_frame_fails(self):
        row = synthetic_trace()
        for rows in ([], [row, row]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                proof.validate_gl_proof([expected_from_trace(row)], rows, frames=[17])
        with self.assertRaisesRegex(ValueError, 'frame inventory differs'):
            self.calculate(frames=[17, 18])

    def test_missing_mesh_is_rejected_against_source_catalog(self):
        row = synthetic_trace()
        del row['meshes'][0]
        row.update(source_triangles=2, outside_bottom=0)
        with self.assertRaisesRegex(ValueError, 'source mesh inventory differs from catalog'):
            self.calculate(row)

    def test_missing_duplicate_and_hidden_mesh_domains_fail(self):
        for domains in ([domain('rigid', 0)], [domain('skin', 0), domain('rigid', 0), domain('rigid', 0)],
                        [domain('skin', 0), domain('rigid', 0), domain('rigid', 1)]):
            row = synthetic_trace()
            row['geometry_domain'] = domains
            with self.subTest(domains=domains), self.assertRaises(ValueError):
                self.calculate(row)

    def test_missing_triangle_and_partition_never_pass(self):
        for key in ('triangle_trace', 'triangle_partition'):
            row = synthetic_trace()
            del row[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.calculate(row)
        row = synthetic_trace()
        row['triangle_trace'] = []
        with self.assertRaisesRegex(ValueError, 'traced identities differ'):
            self.calculate(row)

    def test_duplicate_triangle_and_incomplete_or_overlapping_ledger_fail(self):
        mutations = [lambda r: r['triangle_trace'].append(deepcopy(r['triangle_trace'][0])),
                     lambda r: r['triangle_partition'][0].update(separated=[]),
                     lambda r: r['triangle_partition'][1]['separated'].append(
                         {'axis': 0, 'sign': 1, 'runs': [[0, 1]], 'maximum_plane_upper': -1.0})]
        for change in mutations:
            row = synthetic_trace(); change(row)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.calculate(row)

    def test_source_hidden_claim_is_checked_against_complete_expected_mesh_state(self):
        row = synthetic_trace()
        row['triangle_partition'][0]['source_hidden'] = True
        with self.assertRaisesRegex(ValueError, 'falsely hidden'):
            self.calculate(row)
        row = synthetic_trace()
        expected = expected_from_trace(row)
        row['meshes'][0]['state'] = 'source_actor_hidden'
        with self.assertRaisesRegex(ValueError, 'full current source state'):
            self.calculate(row, expected)

    def test_no_omitted_triangle_can_hide_behind_zero_nan_or_boolean_separator(self):
        for value in (0, float('nan'), True, 0.1):
            row = synthetic_trace()
            row['triangle_partition'][0]['separated'][0]['maximum_plane_upper'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.calculate(row)

    def test_shrunken_source_possible_mask_cannot_replace_current_expected(self):
        row = synthetic_trace()
        expected = expected_from_trace(row)
        row.update(possible_support_runs=[], possible_samples=0)
        with self.assertRaisesRegex(ValueError, 'full current source state'):
            self.calculate(row, expected)
        with self.assertRaisesRegex(ValueError, 'required support escapes'):
            self.calculate(row)

    def test_no_required_visible_frame_and_invented_required_pixel_fail(self):
        for new_runs in ([], [[100 * 960 + 300, 1]]):
            row = synthetic_trace()
            row['required_contrast_runs'] = new_runs
            row['required_contrast_samples'] = len(new_runs)
            row['possible_support_runs'] = new_runs
            row['possible_samples'] = len(new_runs)
            with self.subTest(runs=new_runs), self.assertRaisesRegex(ValueError, 'no retained required support'):
                self.calculate(row)

    def test_unresolved_clipping_is_fatal_not_silently_dropped(self):
        row = synthetic_trace()
        row['triangle_trace'][0]['clip'][0][3] = [0.0, 0.0]
        with self.assertRaisesRegex(ValueError, 'unresolved clipping'):
            self.calculate(row)

    def test_fragment_out_of_scope_is_fail_closed_on_real_entry(self):
        row = synthetic_trace()
        row['triangle_trace'][0]['colors'] = [[70, 70, 70, 254]] * 3
        row['triangle_trace'][0]['safe_contrast'] = False
        with self.assertRaisesRegex(ValueError, 'no retained required support'):
            self.calculate(row)
        row = synthetic_trace()
        row['triangle_trace'][0]['texture_bounds'] = [[250, 255]] * 3
        with self.assertRaisesRegex(ValueError, 'no retained required support'):
            self.calculate(row)

    def test_claimed_safe_contrast_cannot_make_background_triangle_visible(self):
        row = synthetic_trace()
        row['triangle_trace'][0]['colors'] = [[36, 48, 61, 255]] * 3
        with self.assertRaisesRegex(ValueError, 'contrast flag differs'):
            self.calculate(row)

    def test_unsupported_domain_and_missing_vertex_bits_fail(self):
        for field, value in [('normal_or_exact_zero_no_overflow', False), ('unsupported_domain_nodes', 1),
                             ('checked_abstract_nodes', 0), ('minimum_nonzero_dyadic_exponent', -127),
                             ('maximum_rounded_magnitude_upper', float('inf')), ('positions', 0)]:
            row = synthetic_trace(); row['geometry_domain'][0]['domain'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.calculate(row)
        row = synthetic_trace(); del row['triangle_trace'][0]['position_bits']
        with self.assertRaisesRegex(ValueError, 'position bits'):
            self.calculate(row)

    def test_promoted_native_flags_never_establish_conditional_or_native_pass(self):
        for field in ('profile_native_verified', 'native_fragment_profile_verified'):
            row = synthetic_trace(); row[field] = True
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'cannot be promoted'):
                self.calculate(row)
        row = synthetic_trace(); row['acceptance_verdict'] = 'passed'
        with self.assertRaisesRegex(ValueError, 'cannot be promoted'):
            self.calculate(row)


class SyntheticFileEntry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-current-gl-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trace = self.root / 'synthetic-trace.jsonl'
        self.expected = self.root / 'synthetic-expected.jsonl'
        self.receipt = self.root / 'synthetic-source-receipt.json'
        self.output = self.root / 'conditional-proof'
        self.frames = [17, 18]
        self.rows = [synthetic_trace(17), synthetic_trace(18, empty=True)]
        jsonl(self.trace, [trace_header(self.frames), *self.rows])
        expected = [synthetic_source(frame) for frame in range(553)]
        expected[18] = expected_from_trace(self.rows[1])
        jsonl(self.expected, [synthetic_header(), *expected])
        names = (proof.source.INPUTS | {'Cargo.toml', 'Cargo.lock', 'src/lib.rs',
                                       'examples/source_visibility_certificate.rs'})
        inventory = {name: {'bytes': 1, 'sha256': hashlib.sha256(b'synthetic source only').hexdigest()}
                     for name in names}
        self.receipt_value = {'schema': 'rust-duty-source-visibility-certificates-binding/v1',
            'inputs_and_implementation_before': inventory, 'inputs_and_implementation_after': deepcopy(inventory),
            'backend_reports': {'opengl': {'output': proof.digest(self.expected), 'exit_code': 0}},
            'acceptance_verdict': None, 'synthetic_fixture': True}
        self.anchor()

    def anchor(self):
        self.receipt.write_text(json.dumps(self.receipt_value) + '\n')
        self.sha = proof.digest(self.receipt)['sha256']

    def build(self):
        return proof.build_gl_proof(self.trace, self.expected, self.receipt, self.sha, self.frames, self.output)

    def test_actual_file_api_writes_conditional_files_and_keeps_live_immutability_check(self):
        result = self.build()
        self.assertEqual(result['frame_count'], 2)
        self.assertTrue(result['conditional_source_proof_complete'])
        self.assertFalse(result['profile_native_verified'])
        result.verify_unchanged()
        self.assertEqual(set(p.name for p in self.output.iterdir()), {'geometry.jsonl', 'fragment.json', 'proof.json'})
        saved = json.loads((self.output / 'proof.json').read_text())
        self.assertEqual(saved['trace_sha256'], proof.digest(self.trace)['sha256'])
        self.assertEqual(saved['source_receipt_sha256'], self.sha)
        self.assertGreater(saved['frames'][0]['possible_samples'], 1)
        self.assertFalse(saved['trace_execution_binding_verified'])

    def test_file_entry_rejects_late_receipt_mutation_during_actual_calculation(self):
        original = proof.geometry.vector_samples
        changed = False
        def mutate(poly):
            nonlocal changed
            value = original(poly)
            if not changed:
                self.receipt.write_text(self.receipt.read_text() + ' ')
                changed = True
            return value
        with patch.object(proof.geometry, 'vector_samples', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'inputs changed during calculation'):
                self.build()
        self.assertFalse(self.output.exists())

    def test_late_receipt_mutation_after_build_fails_verify_unchanged(self):
        result = self.build()
        self.receipt.write_text(self.receipt.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'input/output changed'):
            result.verify_unchanged()

    def test_late_possible_mask_shrink_rejected_in_memory_and_file(self):
        result = self.build()
        result['frames'][0]['possible_runs'] = []
        with self.assertRaisesRegex(ValueError, 'in-memory current GL proof changed'):
            result.verify_unchanged()
        result['frames'][0]['possible_runs'] = deepcopy(result._snapshot['frames'][0]['possible_runs'])
        saved = json.loads((self.output / 'proof.json').read_text())
        saved['frames'][0]['possible_runs'] = []
        (self.output / 'proof.json').write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, 'input/output changed'):
            result.verify_unchanged()

    def test_stale_or_self_refreshed_receipt_cannot_replace_independent_anchor(self):
        self.receipt_value['backend_reports']['opengl']['exit_code'] = 1
        self.receipt.write_text(json.dumps(self.receipt_value))
        with self.assertRaisesRegex(ValueError, 'independent SHA256 anchor'):
            self.build()

    def test_expected_digest_is_anchored_not_learned_from_trace(self):
        self.expected.write_text(self.expected.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'independently anchored source receipt'):
            self.build()

    def test_before_after_production_inventory_must_match_and_be_complete(self):
        del self.receipt_value['inputs_and_implementation_after']['Cargo.lock']
        self.anchor()
        with self.assertRaisesRegex(ValueError, 'before/after inventory'):
            self.build()
        del self.receipt_value['inputs_and_implementation_before']['Cargo.lock']
        self.anchor()
        with self.assertRaisesRegex(ValueError, 'inventory incomplete'):
            self.build()

    def test_duplicate_expected_frame_not_hidden_by_mapping(self):
        expected = [json.loads(line) for line in self.expected.read_text().splitlines()]
        expected.append(expected[-1])
        jsonl(self.expected, expected)
        self.receipt_value['backend_reports']['opengl']['output'] = proof.digest(self.expected)
        self.anchor()
        with self.assertRaisesRegex(ValueError, 'duplicate or invalid frame'):
            self.build()

    def test_duplicate_json_member_is_rejected(self):
        self.trace.write_text(self.trace.read_text().replace('"triangle": 0', '"triangle": 0, "triangle": 0', 1))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.build()

    def test_actual_cli_uses_same_calculation(self):
        frames_path = self.root / 'synthetic-frames.json'
        frames_path.write_text(json.dumps(self.frames))
        with patch('builtins.print'):
            self.assertEqual(proof.main(['--trace', str(self.trace), '--expected', str(self.expected),
                '--source-receipt', str(self.receipt), '--expected-receipt-sha256', self.sha,
                '--frames', str(frames_path), '--output-dir', str(self.output)]), 0)
        self.assertFalse(json.loads((self.output / 'proof.json').read_text())['acceptance_complete'])


if __name__ == '__main__':
    unittest.main()
