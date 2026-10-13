"""Current-certificate boundary tests. Synthetic receipts are never native proof."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import current_ads_profile_binding as current
import revalidate_ads_offset as leaf


class CurrentProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'current-profile.json'
        self.path.write_text(json.dumps({'schema': current.SCHEMA}))
        self.packet = current.source.BoundSourcePacket()

    def test_unbound_external_boolean_cannot_become_a_profile(self):
        with self.assertRaisesRegex(ValueError, 'not established'):
            leaf.bounded_profile_summary({'bounded_ads_profile_established': True})

    def test_current_schema_dispatch_preserves_independent_anchors_and_original_logs(self):
        profile = object.__new__(current.BoundCurrentAdsProfile)
        object.__setattr__(profile, 'source_packet', self.packet)
        with patch.object(current, 'bind_current_ads_profile', return_value=profile) as bind, \
                patch.object(leaf.finite_profile, 'bind_finite_ads_profile') as old:
            result = leaf.bind_bounded_profile(self.packet, self.root / 'source-packet.json',
                                               self.path, 'a' * 64, self.root / 'offset')
        self.assertIs(result, profile)
        self.assertFalse(old.called)
        self.assertEqual(bind.call_args.kwargs['expected_class_sha256'], 'a' * 64)
        self.assertEqual(bind.call_args.kwargs['native_runtime_logs'],
            {role: self.root / 'offset/logs' / (role + '-capture/stderr.log') for role in current.source.ROLES})

    def test_descriptor_cannot_refresh_its_own_hash_or_supply_missing_fields(self):
        def call(anchor):
            return current.bind_current_ads_profile(source_packet=self.packet,
                source_packet_path=self.root / 'source-packet.json', reviewed_class=self.path,
                expected_class_sha256=anchor, native_runtime_logs={})
        for anchor in ('', 'f' * 64):
            with self.subTest(anchor=anchor), self.assertRaises(ValueError):
                call(anchor)
        with self.assertRaisesRegex(ValueError, 'manifest'):
            call(current.source.shared._read_regular(self.path))

    def test_current_shader_proof_is_semantic_and_rejects_changed_transform_or_discard(self):
        shader = (Path(__file__).resolve().parents[1] / 'src/render/mesh.wgsl').read_bytes()
        current.verify_shader_semantics(shader)
        current.verify_shader_semantics(shader + b'\n// unrelated renderer commentary\n')
        for before, after in ((b'transform.mvp * vec4<f32>(input.position,1.0)', b'vec4<f32>(0.,0.,0.,1.)'),
                              (b'@location(0) position: vec3<f32>', b'@location(3) position: vec3<f32>'),
                              (b'@location(0) uv: vec2<f32>', b'@location(2) uv: vec2<f32>'),
                              (b'@group(1) @binding(0) var color_texture', b'@group(2) @binding(0) var color_texture'),
                              (b'return textureSample(color_texture,color_sampler,input.uv) * input.color;',
                               b'discard; return vec4<f32>(0.);')):
            with self.assertRaisesRegex(ValueError, 'operation graph'):
                current.verify_shader_semantics(shader.replace(before, after))

    def test_typed_current_profile_rechecks_immutable_frame_and_scope(self):
        original = {'frame': 7, 'source': {'matrix': [1, 0, 0, 1]}}
        self.packet.rows_by_role = {'dx12': {7: original}, 'windows-legacy': {}}
        self.packet.capture_binding = {'source': 'synthetic'}
        self.packet.verify_frame_binding = Mock(return_value=original)
        self.packet.verify_unchanged = Mock()
        ledger = current.source.BoundSourcePacket()
        ledger._remember(self.path)
        summary = {'bounded_ads_profile_established': True, 'capture_binding': deepcopy(self.packet.capture_binding)}
        profile = current.BoundCurrentAdsProfile(self.packet, ledger, {'dx12': {7: deepcopy(original)}},
            {'dx12': {7: current._snapshot(original)}}, summary, self.path, {})
        profile.verify_unchanged()
        self.assertEqual(profile.verify_frame_binding(self.root / '0007.png', 'dx12', 7), original)
        with self.assertRaisesRegex(ValueError, 'scope'):
            profile.verify_frame_binding(self.root / '0008.png', 'dx12', 8)
        original['source']['matrix'][0] = 0
        with self.assertRaisesRegex(ValueError, 'mutation'):
            profile.verify_unchanged()

    def test_extra_or_changed_current_evidence_is_not_ignored(self):
        self.packet.capture_binding = {}
        profile = current.BoundCurrentAdsProfile(self.packet, current.source.BoundSourcePacket(), {}, {},
            {'capture_binding': {}}, self.path, {})
        (self.root / 'unbound.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'file set'):
            profile.verify_unchanged()


class CurrentVisibleTraceTests(unittest.TestCase):
    """Exact subset checks over synthetic source records, not native evidence."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.visible = [7, 9]
        self.manifest = {'traces': {'dx12': 'dx12-trace.jsonl'},
                         'fallback_frames': {'dx12': [6, 7, 8, 9]}}
        self.header = {'schema': current.gl.TRACE_SCHEMA, 'backend_profile': 'dx12: synthetic',
                       'requested_frames': [6, 7, 8, 9], 'expected_frames': 553}
        self.raw_rows = {frame: ('{"frame":%d,"matrix":[0.1234567890123456789],'
                                '"color":[80,90,100,255]}' % frame) for frame in (6, 7, 8, 9)}
        (self.root / 'dx12-trace.jsonl').write_text(json.dumps(self.header) + '\n' +
            '\n'.join(self.raw_rows.values()) + '\n', encoding='utf-8')
        self.trace_rows = current.gl.rows_by_frame(
            list(current.gl.records(self.root / 'dx12-trace.jsonl'))[1:], 'synthetic source')
        self.subset_header = {**self.header, 'requested_frames': self.visible}
        self.write_subset()
        (self.root / 'dx12-visible-frames.json').write_text(json.dumps(self.visible), encoding='utf-8')

    def write_subset(self, *, header=None, frames=None, raw_rows=None):
        header = self.subset_header if header is None else header
        frames = self.visible if frames is None else frames
        raw_rows = self.raw_rows if raw_rows is None else raw_rows
        (self.root / 'dx12-visible-trace.jsonl').write_text(json.dumps(header) + '\n' +
            '\n'.join(raw_rows[frame] for frame in frames) + '\n', encoding='utf-8')

    def bind(self):
        current._bind_visible_trace(current.source.BoundSourcePacket(), self.root,
                                    self.manifest, self.trace_rows, self.visible)

    def test_exact_subset_preserves_decimal_source_values(self):
        self.bind()
        value = self.trace_rows[7]['matrix'][0]
        self.assertEqual(str(value), '0.1234567890123456789')
        path = self.root / 'dx12-visible-trace.jsonl'
        path.write_text(path.read_text().replace('0.1234567890123456789', '0.12345678901234568'))
        with self.assertRaisesRegex(ValueError, 'source row'):
            self.bind()

    def test_changed_matrix_or_color_cannot_use_otherwise_matching_source_rows(self):
        for original, replacement in (('[0.1234567890123456789]', '[0]'),
                                      ('[80,90,100,255]', '[0,0,0,255]')):
            with self.subTest(replacement=replacement):
                rows = dict(self.raw_rows)
                rows[7] = rows[7].replace(original, replacement)
                self.write_subset(raw_rows=rows)
                with self.assertRaisesRegex(ValueError, 'source row'):
                    self.bind()

    def test_missing_extra_duplicate_or_reordered_visible_rows_fail(self):
        for frames in ([7], [7, 8, 9], [7, 7, 9], [9, 7]):
            with self.subTest(frames=frames):
                self.write_subset(frames=frames)
                with self.assertRaises(ValueError):
                    self.bind()

    def test_header_must_change_only_requested_frames(self):
        for field, value in (('backend_profile', 'opengl: synthetic'),
                             ('expected_frames', 1), ('requested_frames', [7])):
            with self.subTest(field=field):
                self.write_subset(header={**self.subset_header, field: value})
                with self.assertRaisesRegex(ValueError, 'trace header'):
                    self.bind()
        self.write_subset(header={**self.subset_header, 'unbound_field': True})
        with self.assertRaisesRegex(ValueError, 'trace header'):
            self.bind()

    def test_selection_must_match_visible_rows_exactly(self):
        path = self.root / 'dx12-visible-frames.json'
        for selected in ([7], [7, 8, 9], [9, 7], [7, 7, 9], [True, 9], [7.0, 9]):
            with self.subTest(selected=selected):
                path.write_text(json.dumps(selected), encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.bind()


class CurrentWarpFragmentEvidenceTests(unittest.TestCase):
    """Synthetic native-report controls preserve the former fragment obligations."""
    def setUp(self):
        self.source = {'required_contrast_runs': [[10000, 2]], 'required_contrast_samples': 2}
        mask = bytearray(960 * 540)
        mask[10000:10002] = bytes([1, 1])
        self.result = {'checked_required_mask_sha256': current.hashlib.sha256(mask).hexdigest(),
                       'source_triangles': 3, 'color_probe_triangles': 1,
                       'color_probe_covered_sample_memberships': 2,
                       **{key: 'a' * 64 for key in ('source_frame_sha256', 'draws_sha256',
                           'color_observations_sha256', 'coverage_sha256')}}

    def test_complete_source_required_mask_and_positive_fragment_evidence_pass(self):
        current._bind_warp_fragment_evidence(self.result, self.source)

    def test_missing_or_shrunken_checked_required_mask_fails(self):
        for digest in (None, 'b' * 64):
            with self.subTest(digest=digest), self.assertRaisesRegex(ValueError, 'required mask'):
                current._bind_warp_fragment_evidence(
                    {**self.result, 'checked_required_mask_sha256': digest}, self.source)
        mask = bytearray(960 * 540)
        mask[10000] = 1
        with self.assertRaisesRegex(ValueError, 'required mask'):
            current._bind_warp_fragment_evidence(
                {**self.result, 'checked_required_mask_sha256': current.hashlib.sha256(mask).hexdigest()},
                self.source)
        with self.assertRaisesRegex(ValueError, 'sample count'):
            current._bind_warp_fragment_evidence(self.result,
                {**self.source, 'required_contrast_samples': 1})

    def test_missing_zero_or_untyped_native_fragment_counts_fail(self):
        for key in ('source_triangles', 'color_probe_triangles', 'color_probe_covered_sample_memberships'):
            for value in (None, 0, -1, True, 1.0):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    current._bind_warp_fragment_evidence({**self.result, key: value}, self.source)

    def test_native_observation_hashes_cannot_be_missing_or_malformed(self):
        for key in ('source_frame_sha256', 'draws_sha256', 'color_observations_sha256', 'coverage_sha256'):
            for value in (None, '', 'x' * 64):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    current._bind_warp_fragment_evidence({**self.result, key: value}, self.source)


if __name__ == '__main__':
    unittest.main()
