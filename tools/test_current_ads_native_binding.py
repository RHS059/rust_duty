"""Synthetic negative controls for source-to-issued-input binding, not GPU proof."""
from copy import deepcopy
import unittest

from PIL import Image

import current_ads_native_binding as current
from compare_source_visibility import compare, BACKGROUND, EXTENT
from test_compare_source_visibility import frame as image_frame, image_for


def fixture(role='dx12'):
    matrix = [current._float_bits(value) for value in (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)]
    texture = {'kind': 'rgba8', 'width': 1, 'height': 1, 'rgba8_sha256': 'a' * 64,
               'sampler': {'filter': 'linear', 'wrap_x': 'clamp', 'wrap_y': 'clamp'}}
    meshes = []
    for kind, visible, digest in [('skin', True, '1'), ('rigid', True, '2'), ('rigid', False, '3')]:
        meshes.append({'kind': kind, 'mesh': 1 if digest == '3' else 0, 'triangles': 1,
                       'visible': visible, 'opacity_bits': current._float_bits(1),
                       'triangle_stream_sha256': current.hashlib.sha256((digest * 64).encode()).hexdigest(),
                       'triangle_chunk_sha256': [current.hashlib.sha256((digest * 64).encode()).hexdigest()],
                       'texture': deepcopy(texture),
                       'view_projection_bits': matrix[:], 'model_bits': matrix[:],
                       'upload_transform_bits': matrix[:] if role == 'dx12' else None})
    row = {'frame': 7, 'source_triangles': 3, 'hidden_source_triangles': 1,
           'expected_draw_inventory': meshes,
           'meshes': [{'kind': m['kind'], 'mesh': m['mesh'], 'triangles': 1, 'opacity': 1,
                       'state': 'enumerated' if m['visible'] else 'source_actor_hidden'} for m in meshes]}
    state = {'topology': 'triangle-list', 'viewport': [0, 0, 960, 540], 'scissor': [0, 0, 960, 540],
             'depth_range_bits': [0, current._float_bits(1)], 'depth_test': True, 'depth_write': True,
             'depth_compare': 'less-equal', 'blend': 'alpha',
             'color_blend': ['src-alpha', 'one-minus-src-alpha', 'add'],
             'alpha_blend': ['one', 'one-minus-src-alpha', 'add'], 'cull': 'none',
             'front_face': 'ccw', 'color_write': 'rgba', 'sample_count': 1,
             'clip_depth': 'zero-to-one' if role == 'dx12' else 'minus-one-to-one', 'depth_clamp': False,
             'fragment': 'straight', 'target_format': 'rgba8unorm',
             'observed_gl': None if role == 'dx12' else {'verified': True}}
    if role == 'windows-legacy':
        state['observed_gl'] = {'verified': True, 'program': 3, 'viewport': [0, 0, 960, 540],
            'scissor': [0, 0, 960, 540], 'scissor_enabled': False, 'depth_test': True,
            'depth_write': True, 'depth_write_mask': True, 'depth_compare': 0x0203,
            'cull': False, 'blend_enabled': True, 'blend_rgb': [0x0302, 0x0303, 0x8006],
            'blend_alpha': [1, 0x0303, 0x8006], 'color_mask': [1] * 4, 'front_face': 0x0901,
            'depth_clamp': False, 'alpha_to_coverage': False, 'sample_coverage': False,
            'rasterizer_discard': False, 'depth_range_bits': [0, current._float_bits(1)],
            'shaders': current.shader_identities(), 'material_id': 1,
            'material_binding': 'created-owned-material-selected-then-flushed',
            'uniforms': [{'name': name, 'gl_type': kind, 'size': 1} for name, kind in
                         [('Model', 35676), ('Projection', 35676), ('Texture', 35678)]],
            'attributes': [{'name': name, 'gl_type': kind, 'size': 1} for name, kind in
                           [('color0', 35666), ('position', 35665), ('texcoord', 35664)]]}
    witness_state = deepcopy(state)
    witness_state.update(depth_test=False, depth_write=False, depth_compare='always',
        blend='opaque', color_blend=None, alpha_blend=None, fragment='associate-straight')
    if role == 'windows-legacy':
        witness_state['observed_gl'].update(depth_test=False, depth_write=False,
            blend_enabled=False, shaders=current.shader_identities(True))
    witness_projection = [current._float_bits(v) for v in
        (2 / 960, 0, 0, 0, 0, -2 / 540, 0, 0, 0, 0, -1, 0, -1, 1, 0, 1)]
    witness_upload = witness_projection[:] if role == 'dx12' else None
    if witness_upload is not None:
        witness_upload[10], witness_upload[14] = current._float_bits(-.5), current._float_bits(.5)
    witness_draw = {'triangle_count': 644, 'triangle_sha256': current.witness_triangles(7, 'a' * 64),
        'view_projection_bits': witness_projection, 'model_bits': matrix[:],
        'upload_transform_bits': witness_upload, 'texture': deepcopy(texture), 'state': witness_state}
    witness_draw['texture']['rgba8_sha256'] = current.hashlib.sha256(bytes([255] * 4)).hexdigest()
    draws = [{**{key: m[key] for key in ('view_projection_bits', 'model_bits',
                                       'upload_transform_bits', 'texture')}, 'triangle_count': 1,
              'state': deepcopy(state)} for m in meshes if m['visible']]
    row['expected_ordered_draw_input_sha256'] = current.ordered_draw_input_sha256(
        [(meshes[0], ['1' * 64]), (meshes[1], ['2' * 64])])
    receipt = {'schema': current.SCHEMA, 'capture_identity': 'a' * 64, 'frame_index': 7,
               'backend': current.source.BACKENDS[role][1], 'capture_path': '0007.png',
               'capture_sha256': 'b' * 64, 'target': {'resource_id': 3, 'width': 960, 'height': 540, 'depth': True},
               'witness_exclusion': [0, 0, 64, 22], 'witness_count': 1, 'triangle_count': 2,
               'draws': draws, 'submission_complete': True, 'capture_complete': True,
               'ordered_draw_input_sha256': row['expected_ordered_draw_input_sha256'],
               'events': [{'kind': 'clear', 'rgba_bits': [current._float_bits(v) for v in (.14, .19, .24, 1)],
                           'depth_bits': current._float_bits(1)}, {'kind': 'draw', 'draw_index': 0},
                          {'kind': 'draw', 'draw_index': 1}, {'kind': 'witness', 'draw': witness_draw}, {'kind': 'capture'}]}
    return row, deepcopy(receipt)


class CurrentNativeBindingTests(unittest.TestCase):
    def verify(self, row, receipt, role='dx12'):
        return current.verify_receipt(row, receipt, role=role, frame=7,
                                      capture_identity='a' * 64, capture_sha256='b' * 64)

    def test_complete_input_binding_is_not_an_image_acceptance_verdict(self):
        for role in current.source.ROLES:
            result = self.verify(*fixture(role), role)
            self.assertTrue(result['native_input_binding_verified'])
            self.assertFalse(result['visibility_verified'])
            self.assertEqual(result['triangles'], 2)

    def test_ordered_input_codec_matches_native_golden_and_draw_splits(self):
        row, receipt = fixture()
        state = deepcopy(receipt['draws'][0])
        state['texture']['rgba8_sha256'] = current.hashlib.sha256(bytes([255] * 4)).hexdigest()
        self.assertEqual(current.draw_input_state_sha256(state),
            '07821c444dd5613337ff95c79afa993f95ab10a7c6df9fdcdc78f61e4c9361b2')
        hashes = ['1' * 64, '2' * 64, '1' * 64]
        whole = current.ordered_draw_input_sha256([(state, hashes)])
        split = current.ordered_draw_input_sha256([(state, hashes[:1]), (state, hashes[1:])])
        self.assertEqual(whole, split)
        for altered in (hashes[:-1], hashes[1:], list(reversed(hashes[:2]))):
            self.assertNotEqual(whole, current.ordered_draw_input_sha256([(state, altered)]))
        # Two independent expected meshes with identical state can share a draw.
        receipt['draws'][0]['triangle_count'] = 2
        receipt['draws'].pop()
        receipt['events'].pop(2)
        self.assertEqual(self.verify(row, receipt)['triangles'], 2)

    def test_source_and_native_inventory_size_is_bounded_by_chunks_and_draws(self):
        import json
        row, receipt = fixture()
        count = 98522
        mesh = row['expected_draw_inventory'][0]
        mesh.update(triangles=count, triangle_chunk_sha256=['1' * 64] * ((count + 255) // 256))
        self.assertLess(len(json.dumps(mesh)), 28000)
        self.assertNotIn('triangle_sha256', mesh)
        for draw in receipt['draws']:
            self.assertNotIn('triangle_sha256', draw)
            self.assertLess(len(json.dumps(draw)), 2000)
        self.assertEqual(len(receipt['events'][-2]['draw']['triangle_sha256']), 644)

    def test_missing_all_draws_and_partial_draws_fail(self):
        for remove in (slice(None), slice(0, 1)):
            row, receipt = fixture()
            del receipt['draws'][remove]
            with self.assertRaises(ValueError):
                self.verify(row, receipt)

    def test_shrunken_swapped_or_missing_triangle_is_rejected(self):
        for mutation in (lambda r: r.update(ordered_draw_input_sha256='9' * 64),
                         lambda r: r.update(ordered_draw_input_sha256=current.ordered_draw_input_sha256(
                             [(r['draws'][1], ['2' * 64]), (r['draws'][0], ['1' * 64])])),
                         lambda r: r.update(ordered_draw_input_sha256=current.ordered_draw_input_sha256(
                             [(r['draws'][0], ['1' * 64])]))):
            row, receipt = fixture()
            mutation(receipt)
            with self.assertRaises(ValueError):
                self.verify(row, receipt)

    def test_stale_or_swapped_frame_matrix_capture_and_identity_fail(self):
        mutations = [lambda r: r.update(frame_index=8), lambda r: r.update(capture_identity='c' * 64),
                     lambda r: r.update(capture_path='0008.png'), lambda r: r.update(capture_sha256='c' * 64)]
        for field in ('view_projection_bits', 'model_bits', 'upload_transform_bits'):
            mutations.append(lambda r, field=field: r['draws'][0][field].__setitem__(0, current._float_bits(.5)))
        for mutation in mutations:
            row, receipt = fixture()
            mutation(receipt)
            with self.assertRaises(ValueError):
                self.verify(row, receipt)

    def test_false_hidden_native_draw_cannot_remove_source_obligation(self):
        row, receipt = fixture()
        receipt['draws'].pop()
        receipt['triangle_count'] = 1
        receipt['events'].pop(2)
        with self.assertRaisesRegex(ValueError, 'missing or extra'):
            self.verify(row, receipt)

    def test_source_hidden_or_complete_mesh_inventory_tampering_fails(self):
        mutations = [lambda r: r['expected_draw_inventory'][1].update(visible=False),
                     lambda r: r['expected_draw_inventory'].pop(),
                     lambda r: r.update(source_triangles=2),
                     lambda r: r['expected_draw_inventory'][0].update(triangles=0),
                     lambda r: r['expected_draw_inventory'][0]['model_bits'].__setitem__(0, 0x7fc00000)]
        for mutation in mutations:
            row, receipt = fixture()
            mutation(row)
            with self.assertRaises(ValueError):
                self.verify(row, receipt)

    def test_unsupported_pipeline_texture_viewport_and_incomplete_submission_fail(self):
        mutations = [lambda r: r.update(submission_complete=False), lambda r: r.update(capture_complete=False),
                     lambda r: r['draws'][0]['state'].update(cull='back'),
                     lambda r: r['draws'][0]['state'].update(depth_write=False),
                     lambda r: r['draws'][0]['state'].update(viewport=[0, 0, 480, 270]),
                     lambda r: r['draws'][0]['texture'].update(rgba8_sha256='9' * 64)]
        for mutation in mutations:
            row, receipt = fixture()
            mutation(receipt)
            with self.assertRaises(ValueError):
                self.verify(row, receipt)

    def test_clear_after_draw_witness_only_and_repeated_capture_fail(self):
        for mutation in (lambda r: r['events'].reverse(), lambda r: r['events'].append({'kind': 'capture'}),
                         lambda r: r.update(witness_count=2)):
            row, receipt = fixture()
            mutation(receipt)
            with self.assertRaises(ValueError):
                self.verify(row, receipt)

    def test_witness_cannot_hide_arbitrary_extra_geometry_or_state(self):
        for mutation in (lambda d: d.clear(), lambda d: d['triangle_sha256'].__setitem__(0, '9' * 64),
                         lambda d: d['model_bits'].__setitem__(0, current._float_bits(.5)),
                         lambda d: d['state'].update(depth_test=True),
                         lambda d: d['state'].update(viewport=[0, 0, 64, 22])):
            row, receipt = fixture()
            mutation(receipt['events'][-2]['draw'])
            with self.assertRaises(ValueError):
                self.verify(row, receipt)

    def test_actual_gl_observation_is_closed_and_semantically_checked(self):
        for mutation in (lambda d: d.clear(), lambda d: d.update(verified=True, invented=1),
                         lambda d: d.update(cull=True), lambda d: d.update(depth_write_mask=False),
                         lambda d: d.update(blend_rgb=[1, 1, 1]),
                         lambda d: d['shaders'][0].update(source_sha256='9' * 64)):
            row, receipt = fixture('windows-legacy')
            mutation(receipt['draws'][0]['state']['observed_gl'])
            with self.assertRaises(ValueError):
                self.verify(row, receipt, 'windows-legacy')

    def test_bound_draws_cannot_excuse_blank_visible_frame_or_ambiguous_clipping(self):
        self.verify(*fixture())
        row = image_frame([[100 * 960 + 100, 8]])
        with self.assertRaisesRegex(ValueError, 'missing source-derived'):
            compare(Image.new('RGBA', EXTENT, BACKGROUND), row)
        row['unsupported_clip_triangles'] = 1
        with self.assertRaisesRegex(ValueError, 'clipping remains unresolved'):
            compare(image_for(row), row)


if __name__ == '__main__':
    unittest.main()
