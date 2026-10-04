"""Exact-byte cache discrimination; every miss still uses the real parser."""
from unittest import TestCase, mock
import json
import package_game
import test_ads_distribution
import vrview
import test_vrview
from vrview import ValidationMemo, validation_memo as memo


class ValidationMemoTests(TestCase):
    def test_success_reuses_only_identical_bytes_and_validator(self):
        cache = ValidationMemo(2)
        calls = []
        def validate(blob):
            calls.append(blob)
            return {'nested': [len(blob)]}
        first = cache.validated(validate, b'abc')
        first['nested'][0] = -1
        self.assertEqual(cache.validated(validate, b'abc'), {'nested': [3]})
        cache.validated(validate, b'abd')  # same size, different content
        self.assertEqual(calls, [b'abc', b'abd'])
        other = mock.Mock(return_value={'nested': [4]})
        self.assertEqual(cache.validated(other, b'abc'), {'nested': [4]})
        other.assert_called_once_with(b'abc')

    def test_failures_are_not_cached_and_inputs_are_snapshots(self):
        cache = ValidationMemo()
        invalid = mock.Mock(side_effect=ValueError('invalid binary'))
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'invalid binary'):
                cache.validated(invalid, b'bad')
        self.assertEqual(invalid.call_count, 2)
        data = bytearray(b'old')
        validate = mock.Mock(side_effect=lambda blob: blob.decode())
        self.assertEqual(cache.validated(validate, data), 'old')
        data[:] = b'new'
        self.assertEqual(cache.validated(validate, data), 'new')
        self.assertEqual(validate.call_count, 2)

    def test_bounded_lru_and_context_invalidation(self):
        cache = ValidationMemo(2)
        validate = mock.Mock(side_effect=lambda blob: len(blob))
        for blob in (b'a', b'b', b'a', b'c', b'b'):
            cache.validated(validate, blob)
        self.assertEqual(validate.call_count, 4)
        cache.validated(validate, b'b', context=('changed-validator',))
        self.assertEqual(validate.call_count, 5)
        self.assertLessEqual(len(cache._entries), 2)
        cache.clear()
        self.assertEqual(len(cache._entries), 0)


class RealParserMemoTests(TestCase):
    def setUp(self):
        memo.clear()
        fixture = test_vrview.AnimationTests()
        fixture.setUp()
        self.vra, self.vrs, self.vrm = fixture.pack()

    def test_summary_matches_real_decoder_and_decodes_once(self):
        pack = vrview.decode_vra(self.vra, vrs=self.vrs, vrm=self.vrm)
        with mock.patch.object(vrview, 'decode_vra', wraps=vrview.decode_vra) as decode:
            summary = vrview.validated_clip_summary(self.vra, vrs=self.vrs, vrm=self.vrm)
            self.assertEqual(summary, [{'name': c['name'], 'loop': c['loop'],
                'duration': c['frames'][-1]['time'], 'frame_count': len(c['frames'])}
                for c in pack['clips']])
            summary[0]['duration'] = -1
            self.assertEqual(vrview.validated_clip_summary(self.vra,
                vrs=self.vrs, vrm=self.vrm)[0]['duration'], 1.0)
            self.assertEqual(decode.call_count, 1)

    def test_warmed_summary_rejects_corruption_in_each_companion(self):
        blobs = [self.vra, self.vrs, self.vrm]
        vrview.validated_clip_summary(blobs[0], vrs=blobs[1], vrm=blobs[2])
        for index in range(3):
            changed = list(blobs)
            damaged = bytearray(changed[index])
            damaged[-1] ^= 1
            changed[index] = bytes(damaged)
            with self.subTest(index=index), self.assertRaises(ValueError):
                vrview.validated_clip_summary(changed[0], vrs=changed[1], vrm=changed[2])

    def test_changed_parser_identity_cannot_reuse_earlier_approval(self):
        vrview.validated_clip_summary(self.vra, vrs=self.vrs, vrm=self.vrm)
        with mock.patch.object(vrview, 'decode_vra', side_effect=ValueError('changed parser')):
            with self.assertRaisesRegex(ValueError, 'changed parser'):
                vrview.validated_clip_summary(self.vra, vrs=self.vrs, vrm=self.vrm)


class WarmPackagingMemoTests(TestCase):
    def setUp(self):
        test_ads_distribution.AdsDistributionTests.setUpClass()
        fixture = test_ads_distribution.AdsDistributionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        package_game.verify_ads(self.root)

    def test_fresh_metadata_source_and_transport_mode_after_warm_success(self):
        folder = self.root / package_game.ADS_DIR
        manifest = folder / 'manifest.json'
        original = manifest.read_text()
        altered = json.loads(original)
        altered['ads_clips'][0]['duration'] += 1
        manifest.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, 'ADS manifest'):
            package_game.verify_ads(self.root)
        manifest.write_text(original)
        parity = folder / 'parity-ads_entry_r1.json'
        original = parity.read_text()
        altered = json.loads(original)
        altered['passed'] = False
        parity.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, 'Rust parity'):
            package_game.verify_ads(self.root)
        parity.write_text(original)
        source = self.root / 'assets/authoring/ads/ads.blend'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'changed source after warm success')
        with self.assertRaisesRegex(ValueError, 'committed Blender source'):
            package_game.verify_ads(self.root)
        source.unlink()
        (folder / 'asset.vra.gz').unlink()
        package_game.verify_ads(self.root)
        with self.assertRaisesRegex(ValueError, 'missing'):
            package_game.verify_ads(self.root, require_transports=True)

    def test_same_size_file_replacement_after_warm_success(self):
        path = self.root / package_game.ADS_DIR / 'asset.vrm'
        original = path.read_bytes()
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            package_game.verify_ads(self.root)

    def test_symlink_replacement_after_warm_success(self):
        path = self.root / package_game.ADS_DIR / 'asset.vrm'
        saved = path.with_suffix('.original')
        path.rename(saved)
        try:
            path.symlink_to(saved)
        except OSError as error:
            self.skipTest(f'symlink creation unavailable: {error}')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            package_game.verify_ads(self.root)
