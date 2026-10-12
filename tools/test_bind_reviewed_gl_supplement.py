"""Synthetic boundary controls; no private assets, native captures or GPU needed."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bind_reviewed_gl_supplement as binding


def encoded(value):
    return (json.dumps(value, default=float) + '\n').encode()


def digest(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


class ReviewedBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paths = {name: self.root / (name + '.json') for name in binding._REVIEWED_SHA256}
        self.header = {**deepcopy(binding.source.HEADER_FIELDS), **binding.source.PROFILE_FIELDS,
                       'backend_profile': binding.source.BACKEND_PROFILES['windows-legacy'],
                       **{key: False for key in binding.SOURCE_FALSE_FLAGS}}
        self.native = []
        for frame in range(553):
            self.native.append({'frame': frame, 'acceptance_verdict': None,
                                'possible_support_complete': True, 'unsupported_clip_triangles': 0,
                                'required_contrast_runs': [[2000, 4]], 'possible_support_runs': [[2000, 4]],
                                'required_contrast_samples': 4, 'possible_samples': 4,
                                'unclassified_triangles': 2, 'source_triangles': 3,
                                'outside_bottom': 1, 'hidden_source_triangles': 0,
                                'meshes': [{'kind': 'rigid', 'mesh': 0, 'triangles': 3}]})
        self.geometry, fragments = [], []
        for frame in binding.FRAME_IDS:
            triangles = []
            for index, support, robust, overlap in ((0, [[2000, 4]], [[2000, 3]], [[2000, 4]]),
                                                    (1, [[2002, 3]], [], [[2002, 2]])):
                triangles.append({'kind': 'rigid', 'mesh': 0, 'triangle': index,
                                  'variant_count': 1, 'colors': [[32, 48, 64, 255]] * 3,
                                  'texture_bounds': [[255, 255]] * 3,
                                  'subtriangles': [{'variant': 0, 'fan': [0, 1, 2],
                                                    'possible_runs': support, 'robust_runs': robust,
                                                    'required_overlap_runs': overlap}]})
            self.geometry.append({'frame': frame, 'triangles': triangles,
                                  'checks': {'native_geometry_profile_verified': False,
                                             'original_profile_flags_unchanged': True,
                                             'all_source_domain_nodes_supported': True,
                                             'local_native_masks_state_equal': True,
                                             'unresolved_clipping_triangles': 0, 'unresolved': [],
                                             'required_runs': [[2000, 3]], 'possible_runs': [[2000, 5]],
                                             'required_original': 4, 'required_retained': 3,
                                             'required_original_not_reproved': 1,
                                             'possible_original': 4, 'possible_additional': 1,
                                             'possible_generated': 5, 'possible_original_not_reproved': 0,
                                             'source_triangles_considered': 2}})
            fragments.append({'frame': frame, 'native_fragment_profile_verified': False,
                              'acceptance_verdict': None, 'required_runs': [[2000, 2]],
                              'removed_required_runs': [[2002, 1]],
                              'required_before_fragment': 3, 'required_after_fragment': 2,
                              'examined_overlapping_subtriangles': 2, 'unsafe_subtriangles': 1,
                              'max_retained_triangle_byte_bound': 2,
                              'triangles': [{'mesh': 0, 'triangle': 0, 'subtriangle': 0,
                                             'overlap_count': 3, 'cumulative_byte_bound': 2},
                                            {'mesh': 0, 'triangle': 1, 'subtriangle': 0,
                                             'overlap_count': 1, 'cumulative_byte_bound': 4,
                                             'unsafe_reason': 'exceeds_existing_three_byte_allowance'}]})
        self.fragment = {'schema': 'rust-duty-bounded-fragment-supplement/v1',
                         'input_header': deepcopy(binding.GEOMETRY_HEADER),
                         'frame_count': 50, 'native_fragment_profile_verified': False,
                         'acceptance_complete': False, 'frames': fragments,
                         'frames_with_retained_required_support': 50,
                         'frames_without_retained_required_support': []}
        self.receipt = {'schema': 'rust-duty-source-visibility-certificates-binding/v1',
                        'capture_context': asdict(binding.CAPTURE_CONTEXT),
                        'source_execution_context': asdict(binding.SOURCE_CONTEXT),
                        'source_base_commit': binding.CAPTURE_CONTEXT.source_commit,
                        'acceptance_verdict': None, 'backend_reports': {'opengl': {}}}
        self.save()
        self.addCleanup(patch.stopall)
        patch.object(binding, '_REVIEWED_COUNTS', (150, 100, 2, 100, 50)).start()

    def save(self):
        raw = b''.join(encoded(row) for row in [self.header, *self.native])
        self.paths['native_source'].write_bytes(raw)
        self.receipt['backend_reports']['opengl'] = {'output': digest(raw), 'header': self.header}
        self.paths['source_receipt'].write_bytes(encoded(self.receipt))
        raw = b''.join(encoded(row) for row in [binding.GEOMETRY_HEADER, *self.geometry])
        self.paths['geometry'].write_bytes(raw)
        self.fragment['input_sha256'] = digest(raw)['sha256']
        self.paths['fragment'].write_bytes(encoded(self.fragment))
        # Only the test producer authorizes fresh synthetic artifacts. Production
        # callers cannot replace the fixed review anchors through this API.
        self.anchors = {name: digest(path.read_bytes())['sha256'] for name, path in self.paths.items()}

    def bind(self, **kwargs):
        with patch.object(binding, '_REVIEWED_SHA256', self.anchors):
            return binding.bind_reviewed_gl_supplement(**self.paths,
                capture_context=kwargs.get('capture_context', binding.CAPTURE_CONTEXT),
                source_context=kwargs.get('source_context', binding.SOURCE_CONTEXT))

    def reject(self, pattern):
        self.save()
        with self.assertRaisesRegex(ValueError, pattern):
            self.bind()

    def test_exact_complete_inventory_remains_conditional_and_immutable(self):
        before = {name: path.read_bytes() for name, path in self.paths.items()}
        result = self.bind()
        self.assertEqual(tuple(row.frame for row in result.frames), binding.FRAME_IDS)
        self.assertEqual(result.frames[0].required_runs, ((2000, 2),))
        self.assertFalse(result.native_profile_binding_verified)
        self.assertFalse(result.native_geometry_profile_verified)
        self.assertFalse(result.native_fragment_profile_verified)
        self.assertFalse(result.acceptance_complete)
        self.assertIsNone(result.acceptance_verdict)
        with self.assertRaises(TypeError):
            bool(result)
        with self.assertRaises(FrozenInstanceError):
            result.frames[0].frame = 1
        result.verify_unchanged()
        self.assertEqual(before, {name: path.read_bytes() for name, path in self.paths.items()})

    def test_artifact_cannot_refresh_its_own_review_anchor(self):
        self.paths['fragment'].write_bytes(self.paths['fragment'].read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'reviewed SHA-256'):
            self.bind()

    def test_coordinated_geometry_fragment_omission_cannot_reanchor(self):
        anchors = self.anchors
        self.geometry[0]['triangles'].pop()
        self.fragment['frames'][0]['triangles'].pop()
        self.save()
        self.anchors = anchors
        with self.assertRaisesRegex(ValueError, 'reviewed SHA-256'):
            self.bind()

    def test_late_mutation_and_symlinks_are_rejected(self):
        result = self.bind()
        self.paths['geometry'].write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'late mutation'):
            result.verify_unchanged()
        self.save()
        original = self.paths['fragment']
        target = self.root / 'target.json'
        original.rename(target)
        original.symlink_to(target)
        with self.assertRaises(ValueError):
            self.bind()

    def test_wrong_context_and_untyped_context_are_rejected(self):
        for context in (binding.EvidenceContext('a' * 40, '37415102452', '1'),
                        asdict(binding.CAPTURE_CONTEXT)):
            with self.subTest(context=context), self.assertRaisesRegex(ValueError, 'capture context'):
                self.bind(capture_context=context)
        with self.assertRaisesRegex(ValueError, 'source context'):
            self.bind(source_context=binding.CAPTURE_CONTEXT)

    def test_receipt_context_cannot_substitute_current_verifier_context(self):
        self.receipt['capture_context']['run_id'] = '37436317774'
        self.reject('capture context')

    def test_missing_duplicate_extra_and_boolean_frames_are_rejected(self):
        original = deepcopy(self.fragment['frames'])
        for rows in (original[:-1], original[:-1] + [original[0]],
                     original + [dict(original[0], frame=21)], [dict(original[0], frame=True), *original[1:]]):
            self.fragment['frames'] = rows
            self.reject('frame inventory|invalid integer')
        self.fragment['frames'] = original
        self.geometry.pop()
        self.reject('incomplete reviewed frame inventory')

    def test_duplicate_geometry_frame_is_rejected(self):
        self.geometry[-1] = deepcopy(self.geometry[0])
        self.reject('duplicate or unexpected frame')

    def test_source_full_inventory_is_required(self):
        self.native.pop()
        self.reject('original source: incomplete')

    def test_wrong_extent_backend_and_profile_are_rejected(self):
        for key, value in (('extent', [960, 539]), ('backend_profile', binding.source.BACKEND_PROFILES['dx12']),
                           ('fragment_profile', 'error <= 4 bytes'), ('near', 0.02)):
            old = self.header[key]
            self.header[key] = value
            self.reject('native header')
            self.header[key] = old

    def test_native_false_flags_cannot_be_promoted_or_retyped(self):
        for value in (True, 0, None):
            self.header['profile_native_verified'] = value
            self.reject('native header/profile_native_verified')

    def test_supplement_profile_flags_and_verdict_remain_false_or_null(self):
        for target, key, value in ((self.geometry[0]['checks'], 'native_geometry_profile_verified', True),
                                   (self.fragment, 'acceptance_complete', True),
                                   (self.fragment['frames'][0], 'acceptance_verdict', True),
                                   (self.fragment['frames'][0], 'native_fragment_profile_verified', 0)):
            old = target[key]
            target[key] = value
            self.reject('differs')
            target[key] = old

    def test_duplicate_fields_and_nonfinite_json_are_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e9999}'):
            self.paths['fragment'].write_bytes(raw)
            self.anchors['fragment'] = digest(raw)['sha256']
            with self.assertRaisesRegex(ValueError, 'duplicate|non-finite'):
                self.bind()

    def test_malformed_overlap_and_extent_runs_are_rejected(self):
        for runs in ([[True, 1]], [[2000, 0]], [[2000, 2], [2001, 1]], [[960 * 540, 1]]):
            self.geometry[0]['checks']['required_runs'] = runs
            self.reject('invalid integer|overlapping, unsorted or out-of-extent')

    def test_required_cannot_expand_and_possible_cannot_shrink(self):
        self.geometry[0]['checks']['required_runs'] = [[2000, 5]]
        self.reject('required must narrow')
        self.geometry[0]['checks']['required_runs'] = [[2000, 3]]
        self.geometry[0]['checks']['possible_runs'] = [[2000, 3]]
        self.reject('possible must expand')

    def test_source_triangle_partition_and_mesh_inventory_are_required(self):
        self.native[17]['source_triangles'] = 4
        self.reject('complete source triangle partition')
        self.native[17]['outside_bottom'] = 2
        self.reject('source mesh inventory')

    def test_duplicate_or_unknown_geometry_triangle_rejected(self):
        self.geometry[0]['triangles'][1]['triangle'] = 0
        self.reject('duplicate or unknown source triangle')
        self.geometry[0]['triangles'][1]['triangle'] = 9
        self.reject('duplicate or unknown source triangle')

    def test_duplicate_subtriangle_fan_is_rejected(self):
        triangle = self.geometry[0]['triangles'][0]
        triangle['subtriangles'].append(deepcopy(triangle['subtriangles'][0]))
        self.reject('duplicate or unknown variant/fan')

    def test_missing_duplicate_and_unknown_fragment_triangle_rejected(self):
        rows = self.fragment['frames'][0]['triangles']
        original = deepcopy(rows)
        rows.pop()
        self.reject('incomplete overlapping fragment triangle inventory')
        rows[:] = original + [deepcopy(original[0])]
        self.reject('duplicate or unexpected fragment triangle')
        rows[:] = original
        rows[0]['subtriangle'] = 8
        self.reject('duplicate or unexpected fragment triangle')

    def test_unsafe_winner_must_remove_all_possible_overlap(self):
        row = self.fragment['frames'][0]
        row['required_runs'] = [[2000, 3]]
        row['required_after_fragment'] = 3
        row['removed_required_runs'] = []
        self.reject('complete unsafe-winner subtraction')

    def test_positive_retention_does_not_hide_unsafe_or_unresolved_bound(self):
        row = self.fragment['frames'][0]['triangles'][1]
        del row['unsafe_reason']
        self.reject('unsafe bound labeled safe')
        del row['cumulative_byte_bound']
        self.reject('unsafe bound labeled safe')

    def test_safe_fragment_requires_opaque_rigid_white_texture(self):
        triangle = self.geometry[0]['triangles'][0]
        triangle['texture_bounds'][0] = [0, 255]
        self.reject('safe triangle outside rigid opaque scope')

    def test_overlap_counts_and_positive_summaries_are_recomputed(self):
        self.fragment['frames'][0]['triangles'][0]['overlap_count'] = 1
        self.reject('fragment overlap')
        self.fragment['frames'][0]['triangles'][0]['overlap_count'] = 3
        self.fragment['frames_with_retained_required_support'] = True
        self.reject('positive-support summary')

    def test_fragment_input_header_and_hash_are_cross_bound(self):
        self.fragment['input_header']['native_profile_binding_verified'] = True
        self.reject('fragment header/input_header')
        self.fragment['input_header'] = deepcopy(binding.GEOMETRY_HEADER)
        self.save()
        document = json.loads(self.paths['fragment'].read_bytes())
        document['input_sha256'] = '0' * 64
        raw = encoded(document)
        self.paths['fragment'].write_bytes(raw)
        self.anchors['fragment'] = digest(raw)['sha256']
        with self.assertRaisesRegex(ValueError, 'input_sha256'):
            self.bind()


if __name__ == '__main__':
    unittest.main()
