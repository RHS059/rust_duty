"""Independent synthetic vertex-probe retention and accounting regressions.

No GPU, compiler, authored asset or subprocess runs. Numerical disagreement is
retained as diagnostic evidence; it never changes the strict image verdict.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import run_resident_authored_contract as resident
import test_resident_authored_contract as parent


ROUTES = ('cpu_vertex_stage', 'current_vertex_stage',
          'historical_inverse_sqrt_vertex_stage')
SHADERS = {'production_resident_shader_sha256': 'src/render/resident.wgsl',
           'production_cpu_shader_sha256': 'src/render/mesh.wgsl',
           'probe_implementation_sha256': 'src/render/resident_vertex_probe.rs'}
HISTORICAL = {
    **{name: [[544, 257]] for name in ('ready-0', 'ready-1', 'ready-3',
                                      'manifest-0', 'manifest-12', 'manifest-24')},
    'walk-0': [[561, 238]], 'walk-3': [[561, 238]], 'walk-1': [[551, 253]],
    'ads-1': [[546, 246], [547, 246], [519, 261], [519, 263]],
    'reload-1': [[508, 233], [510, 233], [524, 233], [524, 234], [505, 270]],
}


class VertexProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source'
        self.directory = Path(self.temp.name) / 'probe'
        self.directory.mkdir()
        live = Path(resident.__file__).resolve().parents[1]
        for relative in (*SHADERS.values(), 'src/render/resident_vertex_probe.wgsl'):
            output = self.root / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes((live / relative).read_bytes())
        self.report = parent.fixture()
        self.rows = {}
        for case in self.report['cases']:
            points = copy.deepcopy(HISTORICAL.get(case['name'], []))
            samples = [{'source_vertex': i, 'clip_bits': [i, 0, 0, 0x3f800000],
                        'color_bits': [0x3f000000, 0x3e800000, 0x3f800000, 0x3f800000]}
                       for i in range(6)]
            draw = {'command': 0, 'kind': 'rigid', 'vertex_count': 6,
                    'triangle_corner_offsets': [0, 3],
                    'cpu_model_bits': parent.old.IDENTITY.copy(),
                    'resident_model_bits': parent.old.IDENTITY.copy(),
                    **{key: self.shader_hash(route, 'rigid', 6) for route, key in (
                        ('cpu', 'cpu_probe_shader_sha256'), ('current', 'current_probe_shader_sha256'),
                        ('historical', 'historical_probe_shader_sha256'))},
                    **{key: copy.deepcopy(samples) for key in ROUTES}}
            self.rows[case['name']] = {
                'schema': 'rust-duty-resident-vertex-probe/v1', 'case': case['name'],
                'source_receipt_sha256': parent.RECEIPT,
                'camera_bits': copy.deepcopy(self.report['camera']['view_projection_bits']),
                'metadata': copy.deepcopy(case['metadata']),
                **{key: resident.matrix.sha256(self.root / path) for key, path in SHADERS.items()},
                'representative_probe_shader_count': 3,
                'current_skin_probe_shader_sha256': self.shader_hash('current', 'skin', 3),
                'historical_skin_probe_shader_sha256': self.shader_hash('historical', 'skin', 3),
                'changed_pixel_count': 0, 'selection_limit_pixels': 16,
                'selection_limit_triangles_per_pixel': 2,
                'changed_pixels_not_selected': 0, 'requested_pixels_without_triangle': 0,
                'selection_complete': True,
                'pixels': [{'pixel': p, 'triangles': [
                    {'command': 0, 'corner': 0, 'cpu_depth': 0.25},
                    {'command': 0, 'corner': 3, 'cpu_depth': 0.5}]} for p in points],
                'draws': [draw] if points else [],
                'scope': 'synthetic diagnostic only',
            }
        self.result = {'schema': 'rust-duty-resident-vertex-probe-result/v1',
                       'source_receipt_sha256': parent.RECEIPT,
                       'image_gate_passed': True, 'probe_completed': True, 'errors': []}
        self.save()

    def shader_hash(self, route, kind, count):
        # Reconstruct retained WGSL bytes independently of the reader helper.
        filename = 'mesh.wgsl' if route == 'cpu' else 'resident.wgsl'
        source = (self.root / 'src/render' / filename).read_text(encoding='utf-8')
        if route == 'cpu':
            source = source.replace('@vertex fn vs_main', 'fn original_vs_main')
            inputs, entry = 'VertexInput', 'original_vs_main'
        else:
            if route == 'historical':
                source = source.replace('let reciprocal = 1.0 / sqrt(length_squared);',
                                        'let reciprocal = inverseSqrt(length_squared);', 1)
            source = source.replace('@vertex fn vs_rigid', 'fn original_vs_rigid')
            source = source.replace('@vertex fn vs_skin', 'fn original_vs_skin')
            inputs, entry = ('SkinInput', 'original_vs_skin') if kind == 'skin' else ('RigidInput', 'original_vs_rigid')
        template = (self.root / 'src/render/resident_vertex_probe.wgsl').read_text(encoding='utf-8')
        shader = source + '\n' + template.replace('__INPUT__', inputs).replace('__ENTRY__', entry).replace('__COUNT__', str(count))
        return resident.pair.controls.digest(shader.encode('utf-8'))

    def save(self):
        for name, row in self.rows.items():
            (self.directory / (name + '.json')).write_text(json.dumps(row) + '\n', encoding='utf-8')
        (self.directory / 'probe-result.json').write_text(json.dumps(self.result) + '\n', encoding='utf-8')

    def validate(self):
        return resident.validate_vertex_probe(self.directory, self.report, parent.RECEIPT, self.root)

    def reject(self, change):
        before = copy.deepcopy((self.rows, self.report, self.result))
        try:
            change()
            self.save()
            with self.assertRaises(ValueError):
                self.validate()
        finally:
            self.rows, self.report, self.result = before
            self.save()

    def test_equal_values_have_no_arithmetic_or_image_acceptance_inference(self):
        original = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        report = copy.deepcopy(self.report)
        result = self.validate()
        self.assertTrue(result['diagnostic_completed'])
        self.assertTrue(result['image_gate_passed'])
        self.assertEqual(result['selected_vertices'], len(HISTORICAL) * 6)
        self.assertTrue(all(value == 0 for key, value in result.items() if key.endswith('_differences')))
        self.assertNotIn('passed', result)
        self.assertEqual(self.report, report)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.directory.iterdir()})

    def test_clip_and_color_disagreements_count_independently_without_tolerance(self):
        draw = self.rows['ready-0']['draws'][0]
        draw[ROUTES[1]][0]['color_bits'][0] += 1
        draw[ROUTES[2]][1]['clip_bits'][0] = 0x7f800000
        draw[ROUTES[1]][2]['clip_bits'][1] = 0x7fc01234
        self.save()
        result = self.validate()
        self.assertEqual(result['current_clip_differences'], 1)
        self.assertEqual(result['current_color_differences'], 1)
        self.assertEqual(result['historical_clip_differences'], 1)
        self.assertEqual(result['historical_color_differences'], 0)
        self.assertEqual(result['normalization_clip_differences'], 2)
        self.assertEqual(result['normalization_color_differences'], 1)
        self.assertTrue(result['diagnostic_completed'])

    def test_failed_image_parent_stays_failed_after_complete_diagnostic(self):
        self.report['passed'] = self.result['image_gate_passed'] = False
        self.report['cases'][0].update(differing_pixels=1, maximum_channel_delta=3)
        self.rows['ready-0']['changed_pixel_count'] = 1
        self.save()
        result = self.validate()
        self.assertFalse(result['image_gate_passed'])
        self.assertTrue(result['diagnostic_completed'])
        with self.assertRaises(ValueError):
            resident.validate_report(self.report, parent.RECEIPT)

    def test_failed_parent_structural_validation_never_rewrites_original_verdict(self):
        report = copy.deepcopy(self.report)
        report['passed'] = False
        report['cases'][0].update(differing_pixels=18, maximum_channel_delta=3)
        before = copy.deepcopy(report)
        self.assertIs(resident.validate_probe_parent(report, parent.RECEIPT), report)
        self.assertEqual(report, before)
        with self.assertRaises(ValueError):
            resident.validate_report(report, parent.RECEIPT)

    def test_failed_parent_cannot_bypass_schema_pose_camera_resource_or_corner_guards(self):
        self.report['passed'] = self.result['image_gate_passed'] = False
        self.report['cases'][0].update(differing_pixels=1, maximum_channel_delta=3)
        self.rows['ready-0']['changed_pixel_count'] = 1
        for change in (lambda: self.report.update(schema='unrelated'),
                       lambda: self.report['camera'].update(extent=[1, 1]),
                       lambda: self.report['cases'][1]['metadata'].update(fraction_tenths=True),
                       lambda: self.report['cases'][0]['resident_stats'].update(binding_allocations=0),
                       lambda: self.report['cases'][0].update(expanded_equal=False),
                       lambda: self.report['cases'][0].update(foreground_pixels=0),
                       lambda: self.report['cases'][0].update(resident_paths=[2, 0, 0])):
            self.reject(change)

    def test_parent_pixel_counts_and_verdict_must_agree_exactly(self):
        for count, maximum in ((True, 1), (-1, 1), (960 * 540 + 1, 1),
                               (1, True), (1, -1), (1, 256), (1, 0), (0, 1), (1, 1)):
            with self.subTest(count=count, maximum=maximum):
                self.reject(lambda: self.report['cases'][0].update(
                    differing_pixels=count, maximum_channel_delta=maximum))
        self.reject(lambda: self.report.update(passed=1))
        self.reject(lambda: self.report.update(passed=False))

    def test_parent_receipt_and_ordered_case_inventory_are_bound(self):
        for change in (lambda: self.report.update(source_receipt_sha256='f' * 64),
                       lambda: self.report['cases'].pop(),
                       lambda: self.report['cases'].reverse()):
            self.reject(change)

    def test_result_status_types_and_parent_verdict_are_strict(self):
        for key, value in (('schema', 'wrong'), ('source_receipt_sha256', 'f' * 64),
                           ('image_gate_passed', False), ('image_gate_passed', 1),
                           ('probe_completed', False), ('probe_completed', 1),
                           ('errors', [{'case': 'ready-0', 'error': 'timeout'}])):
            with self.subTest(key=key, value=value):
                self.reject(lambda: self.result.update({key: value}))

    def test_case_metadata_camera_receipt_and_source_hashes_are_bound(self):
        for key, value in (('case', 'walk-0'), ('metadata', {}), ('camera_bits', [0] * 16),
                           ('source_receipt_sha256', 'b' * 64),
                           *[(key, 'f' * 64) for key in SHADERS]):
            with self.subTest(key=key):
                self.reject(lambda: self.rows['ready-0'].update({key: value}))
        path = self.root / SHADERS['production_resident_shader_sha256']
        path.write_bytes(path.read_bytes() + b'\n// changed\n')
        with self.assertRaises(ValueError):
            self.validate()

    def test_exact_regular_file_inventory_rejects_missing_extra_directory_and_symlink(self):
        file = self.directory / 'ready-0.json'
        content = file.read_bytes()
        file.unlink()
        with self.assertRaises(ValueError):
            self.validate()
        file.write_bytes(content)
        for directory in (False, True):
            path = self.directory / 'unexpected'
            path.mkdir() if directory else path.write_text('extra', encoding='utf-8')
            with self.assertRaises(ValueError):
                self.validate()
            path.rmdir() if directory else path.unlink()
        target = self.directory.parent / 'retained.json'
        target.write_bytes(content)
        file.unlink()
        try:
            file.symlink_to(target)
        except OSError:
            self.skipTest('host does not permit symlink creation')
        with self.assertRaises(ValueError):
            self.validate()

    def test_strict_json_rejects_duplicate_nonfinite_and_oversized_report(self):
        path = self.directory / 'ready-0.json'
        original = path.read_bytes()
        for bad in (b'{"schema":"a","schema":"b"}', b'{"depth":NaN}',
                    b'{"depth":Infinity}', b' ' * (2 * 1024 * 1024 + 1)):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):
                self.validate()
        path.write_bytes(original)

    def test_missing_samples_cannot_claim_complete_selection(self):
        def no_observations():
            self.report['passed'] = self.result['image_gate_passed'] = False
            self.report['cases'][0].update(differing_pixels=1, maximum_channel_delta=1)
            self.rows['ready-0'].update(changed_pixel_count=1, pixels=[], draws=[])
        self.reject(no_observations)
        for key, value in (('selection_complete', False), ('changed_pixels_not_selected', 1),
                           ('requested_pixels_without_triangle', 1), ('changed_pixel_count', True),
                           ('selection_limit_pixels', True), ('selection_limit_pixels', 17),
                           ('selection_limit_triangles_per_pixel', 3)):
            with self.subTest(key=key, value=value):
                self.reject(lambda: self.rows['ready-0'].update({key: value}))
        self.reject(lambda: self.rows['ready-0']['pixels'][0].update(triangles=[]))

    def test_pixel_and_triangle_boundaries_reject_types_duplicates_and_out_of_range(self):
        for point in ([True, 0], [960, 0], [0, 540], [-1, 0], [0, 0, 0]):
            self.reject(lambda: self.rows['ready-0']['pixels'][0].update(pixel=point))
        self.reject(lambda: self.rows['ready-0']['pixels'].append(copy.deepcopy(self.rows['ready-0']['pixels'][0])))
        for key, value in (('command', True), ('command', 2), ('corner', 1),
                           ('corner', 6), ('corner', -3), ('cpu_depth', True)):
            self.reject(lambda: self.rows['ready-0']['pixels'][0]['triangles'][0].update({key: value}))

    def test_draw_triangle_and_route_order_cannot_be_omitted_or_mismatched(self):
        for key, value in (('command', True), ('command', 2), ('vertex_count', 3),
                           ('vertex_count', 385), ('triangle_corner_offsets', [0, 0]),
                           ('triangle_corner_offsets', [0]), ('kind', 'unknown')):
            self.reject(lambda: self.rows['ready-0']['draws'][0].update({key: value}))
        self.reject(lambda: self.rows['ready-0']['draws'].clear())
        self.reject(lambda: self.rows['ready-0']['draws'][0][ROUTES[2]].reverse())
        self.reject(lambda: self.rows['ready-0']['draws'][0][ROUTES[0]].pop())

    def test_triangle_selection_order_is_bound_to_flattened_sample_order(self):
        self.reject(lambda: self.rows['ready-0']['draws'][0]['triangle_corner_offsets'].reverse())
        self.reject(lambda: self.rows['ready-0']['pixels'][0]['triangles'].reverse())
        def duplicate_triangle():
            triangles = self.rows['ready-0']['pixels'][0]['triangles']
            triangles[1] = copy.deepcopy(triangles[0])
        self.reject(duplicate_triangle)

    def test_uint_words_and_source_vertex_bounds_are_not_coerced(self):
        for route in ROUTES:
            for key, value in (('source_vertex', True), ('source_vertex', -1),
                               ('source_vertex', 6), ('clip_bits', [0] * 3),
                               ('color_bits', [0, False, 0, 0]),
                               ('clip_bits', [0, 0, 0, 2**32]),
                               ('color_bits', [0, 0, 0, 1.0])):
                with self.subTest(route=route, key=key, value=value):
                    self.reject(lambda: self.rows['ready-0']['draws'][0][route][0].update({key: value}))

    def test_unwritten_integer_pixels_reject_but_nonfinite_payload_bits_remain_observable(self):
        for route in ROUTES:
            self.reject(lambda: self.rows['ready-0']['draws'][0][route][0].update(color_bits=[2**32-1] * 4))
        sample = self.rows['ready-0']['draws'][0][ROUTES[1]][0]
        sample.update(clip_bits=[0x7fc01234, 0x7f800000, 0xff800000, 0],
                      color_bits=[0x7fc01234, 0, 0, 0])
        self.save()
        self.assertTrue(self.validate()['diagnostic_completed'])

    def test_generated_shader_hashes_bind_actual_route_count_and_template(self):
        for key in ('cpu_probe_shader_sha256', 'current_probe_shader_sha256', 'historical_probe_shader_sha256'):
            self.reject(lambda: self.rows['ready-0']['draws'][0].update({key: 'f' * 64}))
        self.reject(lambda: self.rows['ready-0']['draws'][0].update(
            current_probe_shader_sha256=self.shader_hash('current', 'rigid', 3)))
        template = self.root / 'src/render/resident_vertex_probe.wgsl'
        template.write_bytes(template.read_bytes() + b'\n// changed template\n')
        with self.assertRaises(ValueError):
            self.validate()

    def test_representative_shader_identity_matches_its_declared_count(self):
        for key, value in (('representative_probe_shader_count', 4),
                           ('current_skin_probe_shader_sha256', 'f' * 64),
                           ('historical_skin_probe_shader_sha256', 'f' * 64)):
            self.reject(lambda: self.rows['ready-0'].update({key: value}))

    def test_historical_requested_pixels_cannot_be_silently_omitted(self):
        self.reject(lambda: self.rows['ready-0'].update(pixels=[], draws=[]))
        self.reject(lambda: self.rows['reload-1']['pixels'].pop())

    def test_matrix_words_and_empty_selection_boundaries_are_explicit(self):
        for key in ('cpu_model_bits', 'resident_model_bits'):
            for value in ([0] * 15, [0] * 15 + [True], [0] * 15 + [2**32]):
                self.reject(lambda: self.rows['ready-0']['draws'][0].update({key: value}))
        self.assertEqual(self.rows['rigid-alpha-0']['pixels'], [])
        self.assertEqual(self.rows['rigid-alpha-0']['draws'], [])
        self.assertTrue(self.validate()['diagnostic_completed'])


if __name__ == '__main__':
    unittest.main()
