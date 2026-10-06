"""Finite-profile caller controls. Synthetic profiles are not native evidence."""
from copy import deepcopy
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import revalidate_ads_offset as leaf


PROFILE_IDENTITY = {'class_id': 'synthetic-caller-controls-only',
                    'reviewed_class_sha256': 'd' * 64,
                    'bounded_ads_profile_established': True,
                    'native_profile_binding_verified': False, 'acceptance_verdict': None}


def synthetic_profile(packet, row_factory=None):
    """Stub only reviewed evidence ingestion for caller/image orchestration tests.

    The real binder's separate controls establish the production evidence class.
    This object deliberately has no usable reviewed descriptor or native receipt.
    """
    profile = object.__new__(leaf.finite_profile.BoundFiniteAdsProfile)
    object.__setattr__(profile, 'source_packet', packet)
    object.__setattr__(profile, 'bounded_ads_profile_established', True)
    object.__setattr__(profile, 'summary', lambda: deepcopy(PROFILE_IDENTITY))
    object.__setattr__(profile, 'verify_unchanged', packet.verify_unchanged)
    object.__setattr__(profile, 'verify_frame_binding',
                       row_factory or (lambda path, role, index: deepcopy(packet.verify_frame_binding(path, role, index))))
    return profile


class FiniteProfileGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / '0017.png'
        self.bound = leaf.source_binding.BoundSourcePacket()
        self.original = {'frame': 17, 'classification': 'potentially_visible_unresolved',
                         'required_contrast_runs': [[96000, 2]], 'required_contrast_samples': 2,
                         'possible_support_runs': [[96000, 2]], 'possible_samples': 2,
                         'unsupported_clip_triangles': 0, 'possible_support_complete': True,
                         'unclassified_triangles': 1, 'profile_native_verified': False,
                         'acceptance_verdict': None}
        self.bound.verify_frame_binding = Mock(return_value=self.original)
        self.derived = deepcopy(self.original)
        self.derived.update(required_contrast_runs=[[96001, 1]], required_contrast_samples=1,
                            possible_support_runs=[[96000, 3]], possible_samples=3,
                            bounded_ads_profile_established=True)
        self.profile = synthetic_profile(self.bound, lambda *args: deepcopy(self.derived))
        self.folders = {role: self.root for role in leaf.ROLES}

    def image(self):
        image = Image.new('RGBA', leaf.authored.EXTENT, leaf.authored.BACKGROUND)
        image.putpixel((1, 100), (255, 255, 255, 255))
        image.putpixel((2, 100), (255, 255, 255, 255))
        image.save(self.path)

    def test_missing_or_untyped_profile_rejected_by_normal_fallback(self):
        for profile in (None, True, {'bounded_ads_profile_established': True}, Mock()):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'not established'):
                leaf.AdsOffsetFallback(self.bound, self.folders, profile=profile)

    def test_fresh_gl_pixels_use_separate_narrowed_and_expanded_row(self):
        self.image()
        unchanged = deepcopy(self.original)
        fallback = leaf.AdsOffsetFallback(self.bound, self.folders, profile=self.profile)
        result = fallback.verify_image(self.path, 'windows-legacy', 17, original_error=str(self.path) + ': coverage')
        self.assertEqual(result['required_contrast_samples'], 1)
        self.assertEqual(result['possible_samples'], 3)
        self.assertTrue(result['bounded_ads_profile_established'])
        self.assertFalse(result['native_profile_binding_verified'])
        self.assertIsNone(result['acceptance_verdict'])
        self.assertEqual(result['original_source_row'], unchanged)
        self.assertEqual(self.original, unchanged)
        self.assertEqual(result['compared_source_row'], self.derived)
        self.assertEqual(result['original_generic_failure'], 'coverage')

    def test_corrupted_fresh_capture_still_fails_after_profile_binding(self):
        self.image()
        fallback = leaf.AdsOffsetFallback(self.bound, self.folders, profile=self.profile)
        image = Image.open(self.path)
        image.putpixel((1, 100), leaf.authored.BACKGROUND)
        image.save(self.path)
        with self.assertRaisesRegex(ValueError, 'missing source-derived contrast'):
            fallback.verify_image(self.path, 'windows-legacy', 17, original_error='coverage')
        self.assertFalse(fallback.records['windows-legacy'])

    def test_profile_from_other_source_packet_rejected(self):
        other = leaf.source_binding.BoundSourcePacket()
        with self.assertRaisesRegex(ValueError, 'differs from bound source packet'):
            leaf.AdsOffsetFallback(other, self.folders, profile=self.profile)

    def test_diagnostic_requires_explicit_choice_and_preserves_conditional_flags(self):
        self.image()
        fallback = leaf.AdsOffsetFallback(self.bound, self.folders, conditional_diagnostic=True)
        with self.assertRaisesRegex(ValueError, 'missing source-derived contrast'):
            fallback.verify_image(self.path, 'windows-legacy', 17, original_error='coverage')
        with self.assertRaisesRegex(ValueError, 'cannot claim'):
            leaf.AdsOffsetFallback(self.bound, self.folders, profile=self.profile, conditional_diagnostic=True)

    def test_real_profile_scope_and_source_mutation_guards_reach_fallback(self):
        object.__delattr__(self.profile, 'verify_frame_binding')
        object.__setattr__(self.profile, '_rows', {role: {17: self.derived} for role in leaf.ROLES})
        object.__setattr__(self.profile, '_state',
                           {role: {17: leaf.finite_profile._canonical(self.original)} for role in leaf.ROLES})
        fallback = leaf.AdsOffsetFallback(self.bound, self.folders, profile=self.profile)
        with self.assertRaisesRegex(ValueError, 'outside reviewed finite ADS scope'):
            fallback.verify_image(self.root / '0018.png', 'windows-legacy', 18, original_error='coverage')
        self.original['required_contrast_samples'] = 0
        with self.assertRaisesRegex(ValueError, 'late current source row mutation'):
            fallback.verify_image(self.path, 'windows-legacy', 17, original_error='coverage')
        self.assertFalse(fallback.records['windows-legacy'])

    def test_normal_leaf_records_missing_profile_as_failure_before_native_reads(self):
        context = {'source_commit': 'a' * 40, 'run_id': '123', 'run_attempt': '1'}
        with patch.dict(os.environ, {'GITHUB_SHA': context['source_commit'], 'GITHUB_RUN_ID': '123',
                                     'GITHUB_RUN_ATTEMPT': '1'}):
            result = leaf.run(input_manifest=self.root / 'manifest.json',
                gameplay_shard=self.root / 'gameplay', offset_shard=self.root / 'offset',
                source_packet=self.root / 'packet/source-packet.json', source_receipt_sha256='b' * 64,
                capture_rustc_sha256='c' * 64, evidence=self.root / 'output',
                capture_context=context, verifier_context=context)
        self.assertFalse(result['passed'])
        self.assertFalse(result['bounded_ads_profile_established'])
        self.assertFalse(result['conditional_diagnostic'])
        self.assertIn('independently bound finite ADS profile', result['failure'])
        self.assertFalse(result['checks'])

    def test_binder_receives_independent_anchor_original_logs_and_packet(self):
        with patch.object(leaf.finite_profile, 'bind_finite_ads_profile', return_value=self.profile) as bind:
            actual = leaf.bind_bounded_profile(self.bound, self.root / 'source-packet.json',
                                              self.root / 'class.json', 'd' * 64, self.root / 'offset')
        self.assertIs(actual, self.profile)
        self.assertEqual(bind.call_args.kwargs['expected_class_sha256'], 'd' * 64)
        self.assertIs(bind.call_args.kwargs['source_packet'], self.bound)
        self.assertEqual(bind.call_args.kwargs['native_runtime_logs'],
                         {role: self.root / 'offset/logs' / f'{role}-capture/stderr.log' for role in leaf.ROLES})
        with self.assertRaisesRegex(ValueError, 'independently bound'):
            leaf.bind_bounded_profile(self.bound, self.path, None, None, self.root)


if __name__ == '__main__':
    unittest.main()
