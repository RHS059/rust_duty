"""ADS distribution binds source, canonical walk44 and native Rust parity."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import package_game as package

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
        self.assertGreaterEqual(report['parity_samples'], 75)

    def test_compressed_vra_materializes_exact_verified_runtime_bytes(self):
        vra = self.root / package.ADS_DIR / 'asset.vra'
        expected = json.loads((self.root / package.ADS_DIR / 'manifest.json').read_text())['files']['asset.vra']
        vra.unlink(missing_ok=True)
        package.materialize(self.root, include_ads=True)
        import hashlib
        self.assertEqual(vra.stat().st_size, expected['bytes'])
        self.assertEqual(hashlib.sha256(vra.read_bytes()).hexdigest(), expected['sha256'])

    def test_raw_companions_cannot_hide_corrupt_compressed_transports(self):
        for name in ('asset.vra.gz', 'asset.vrs.gz'):
            path = self.root / package.ADS_DIR / name
            original = path.read_bytes()
            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaisesRegex(ValueError, 'compressed companion SHA-256'):
                package.verify_ads(self.root)
            path.write_bytes(original)

    def test_cache_requires_transports_but_raw_only_package_does_not(self):
        (self.root / package.ADS_DIR / 'asset.vra.gz').unlink()
        package.verify_ads(self.root)
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_ads(self.root, require_transports=True)

    def test_matching_rust_parity_required_for_every_clip(self):
        for clip in package.ADS_CLIPS:
            path = self.root / package.ADS_DIR / f'parity-{clip}.json'
            original = path.read_text(); data = json.loads(original)
            data['asset_sha256'] = 'wrong'
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'Rust parity'):
                package.verify_ads(self.root)
            path.write_text(original)

    def test_source_change_requires_regeneration(self):
        source = self.root / 'assets/authoring/ads/ads.blend'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'committed Blender source'):
            package.verify_ads(self.root)

    def test_manifest_cannot_change_loop_or_duration(self):
        path = self.root / package.ADS_DIR / 'manifest.json'
        data = json.loads(path.read_text()); data['ads_clips'][0]['loop'] = True
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'ADS manifest'):
            package.verify_ads(self.root)

    def test_missing_companion_blocks_package(self):
        (self.root / package.ADS_DIR / 'asset.vra').unlink(missing_ok=True)
        (self.root / package.ADS_DIR / 'asset.vra.gz').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_ads(self.root)

    def test_unsupported_package_binding_rejected(self):
        (self.root / 'assets/animations.cfg').write_text('ads.asset=../private/asset.vra\n')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            package.ads_bound(self.root)
