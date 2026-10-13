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


if __name__ == '__main__':
    unittest.main()
