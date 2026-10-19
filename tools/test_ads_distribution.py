"""ADS delivery binds source, native timing and unchanged canonical walk44."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import package_game as package
from distribution_test_fixtures import add_test_transports

ROOT = Path(__file__).resolve().parents[1]


class AdsDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / package.ADS_DIR / 'manifest.json').exists():
            raise unittest.SkipTest('ADS build outputs are required; complete-game CI produces them')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for folder in (package.ASSET_DIR, package.WALK_DIR, package.ADS_DIR):
            shutil.copytree(ROOT / folder, self.root / folder)
        (self.root / 'assets/animations.cfg').write_text('ads.asset=ads/asset.vra\n')

    def test_preserves_walk44_and_binds_three_clips(self):
        report = package.verify_ads(self.root)
        self.assertEqual(report['original_clips_preserved'], 44)
        self.assertEqual(report['clip_count'], 47)
        self.assertEqual(report['clips'], list(package.ADS_CLIPS))
        manifest = json.loads((self.root / package.ADS_DIR / 'manifest.json').read_text())
        self.assertEqual(report['source_sha256'], manifest['source']['sha256'])

    def test_compressed_vra_materializes_exact_verified_runtime_bytes(self):
        vra = self.root / package.ADS_DIR / 'asset.vra'
        expected = add_test_transports(self.root, package.ADS_DIR)['files']['asset.vra']
        vra.unlink(missing_ok=True)
        package.materialize(self.root, include_ads=True)
        self.assertEqual(vra.stat().st_size, expected['bytes'])
        self.assertEqual(hashlib.sha256(vra.read_bytes()).hexdigest(), expected['sha256'])

    def test_raw_companions_cannot_hide_corrupt_compressed_transports(self):
        add_test_transports(self.root, package.ADS_DIR)
        package.verify_ads(self.root, require_transports=True)
        for name in ('asset.vra.gz', 'asset.vrs.gz'):
            path = self.root / package.ADS_DIR / name
            original = path.read_bytes()
            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaisesRegex(ValueError, 'compressed companion SHA-256'):
                package.verify_ads(self.root)
            path.write_bytes(original)

    def test_cache_requires_transports_but_raw_only_package_does_not(self):
        add_test_transports(self.root, package.ADS_DIR)
        folder = self.root / package.ADS_DIR
        raw = folder / 'asset.vra'
        # Construct the raw-only package from verified transport bytes rather
        # than depending on whether this checkout was previously materialized.
        raw.unlink(missing_ok=True)
        manifest = json.loads((folder / 'manifest.json').read_text())
        raw.write_bytes(package.companion_bytes(self.root, 'asset.vra', manifest, package.ADS_DIR))
        self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), manifest['files']['asset.vra']['sha256'])
        (folder / 'asset.vra.gz').unlink()
        package.verify_ads(self.root)
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_ads(self.root, require_transports=True)
        raw.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_ads(self.root)

    def test_every_conversion_binds_source_and_native_clock(self):
        for clip in package.ADS_CLIPS:
            path = self.root / package.ADS_DIR / f'conversion-{clip}.json'
            original = path.read_text()
            for key, value in (('authoring_master_sha256', 'wrong'),
                               ('source_fbx_sha256', 'wrong'),
                               ('native_fps', [30, 1]), ('source_take', 'wrong')):
                with self.subTest(clip=clip, field=key):
                    data = json.loads(original); data[key] = value
                    path.write_text(json.dumps(data))
                    with self.assertRaisesRegex(ValueError, 'ADS conversion/source metadata'):
                        package.verify_ads(self.root)
            path.write_text(original)
        package.verify_ads(self.root)

    def test_delivery_does_not_require_numerical_parity_reports(self):
        paths = [self.root / package.ADS_DIR / f'parity-{clip}.json' for clip in package.ADS_CLIPS]
        for path in paths:
            path.unlink(missing_ok=True)
        expected = package.verify_ads(self.root)
        for path in paths:
            path.write_text('not a numerical parity report')
        self.assertEqual(package.verify_ads(self.root), expected)

    def test_source_change_requires_regeneration(self):
        source = self.root / 'assets/authoring/ads/ads.blend'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'committed Blender source'):
            package.verify_ads(self.root)

    def test_manifest_cannot_change_loop_or_duration(self):
        path = self.root / package.ADS_DIR / 'manifest.json'
        original = path.read_text()
        for index in range(len(package.ADS_CLIPS)):
            for key, value in (('loop', index != 1), ('duration', 2.)):
                with self.subTest(clip=index, field=key):
                    data = json.loads(original); data['ads_clips'][index][key] = value
                    path.write_text(json.dumps(data))
                    with self.assertRaisesRegex(ValueError, 'ADS manifest'):
                        package.verify_ads(self.root)

    def test_missing_companion_blocks_package(self):
        (self.root / package.ADS_DIR / 'asset.vra').unlink(missing_ok=True)
        (self.root / package.ADS_DIR / 'asset.vra.gz').unlink(missing_ok=True)
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_ads(self.root)

    def test_unsupported_package_binding_rejected(self):
        (self.root / 'assets/animations.cfg').write_text('ads.asset=../private/asset.vra\n')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            package.ads_bound(self.root)
