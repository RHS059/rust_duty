"""Four WIP HIP clips append to immutable walk44 and fail closed in packaging."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import zlib
import tempfile
import unittest
import package_game as package

ROOT = Path(__file__).resolve().parents[1]
BINDINGS = '\n'.join([
    'regular_walk.asset=directional/asset.vra',
    'regular_walk.clip=normal_walk_r1',
    *(f'regular_walk.direction.{direction}={clip}' for direction, clip in zip(
        ('forward', 'backward', 'left', 'right'), package.DIRECTIONAL_CLIPS)),
]) + '\n'


class DirectionalBindingTests(unittest.TestCase):
    def test_explicit_complete_binding_retains_canonical_walk_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'assets').mkdir()
            config = root / 'assets/animations.cfg'
            config.write_text(BINDINGS)
            self.assertTrue(package.directional_bound(root))
            self.assertTrue(package.walk_bound(root))
            config.write_text(BINDINGS.replace('regular_walk.direction.left=hip_strafe_left_r1\n', ''))
            with self.assertRaisesRegex(ValueError, 'directional clip bindings'):
                package.directional_bound(root)
            config.write_text('ads.asset=ads/asset.vra\n')
            self.assertTrue(package.walk_bound(root))
            self.assertFalse(package.directional_bound(root))
            config.write_text('regular_walk.asset=../private/asset.vra\n')
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                package.directional_bound(root)


class DirectionalDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifacts = Path(os.environ.get('RUST_DUTY_DIRECTIONAL_TEST_ASSETS', ROOT / package.DIRECTIONAL_DIR))
        if not (cls.artifacts / 'manifest.json').exists():
            raise unittest.SkipTest('Directional build outputs are required; complete-game CI produces them')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for folder in (package.ASSET_DIR, package.WALK_DIR):
            shutil.copytree(ROOT / folder, self.root / folder)
        shutil.copytree(self.artifacts, self.root / package.DIRECTIONAL_DIR)
        (self.root / 'assets/animations.cfg').write_text(BINDINGS)

    def test_exact48_preserves44_and_materializes_compressed_companions(self):
        folder = self.root / package.DIRECTIONAL_DIR
        manifest = json.loads((folder / 'manifest.json').read_text())
        for name in ('asset.vra', 'asset.vrs'):
            (folder / name).unlink(missing_ok=True)
        report = package.materialize(self.root, include_directional=True)['directional']
        self.assertEqual(report['clip_count'], 48)
        self.assertEqual(report['original_clips_preserved'], 44)
        self.assertEqual(report['parity_samples'], 100)
        for name in ('asset.vra', 'asset.vrs'):
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), manifest['files'][name]['sha256'])

    def test_manifest_rejects_missing_clip_wrong_duration_and_old_payload_claim(self):
        path = self.root / package.DIRECTIONAL_DIR / 'manifest.json'
        original = path.read_text()
        for mutate in (
                lambda value: value['clip_names'].pop(),
                lambda value: value['directional_clips'][0].update(duration=1.),
                lambda value: value['preservation'].update(original_walk_vra_sha256='wrong')):
            value = json.loads(original)
            mutate(value)
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'directional manifest|walk44'):
                package.verify_directional(self.root)
        path.write_text(original)

    def test_every_parity_report_must_bind_final48_and_source(self):
        for clip in package.DIRECTIONAL_CLIPS:
            path = self.root / package.DIRECTIONAL_DIR / f'parity-{clip}.json'
            original = path.read_text()
            value = json.loads(original)
            value['asset_sha256'] = 'intermediate-pack-is-not-final48'
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'Rust parity'):
                package.verify_directional(self.root)
            path.write_text(original)

    def test_rehashed_valid_payload_cannot_modify_old44_bytes(self):
        folder = self.root / package.DIRECTIONAL_DIR
        manifest_path = folder / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        old = (self.root / package.WALK_DIR / 'asset.vra').read_bytes()
        data = bytearray((folder / 'asset.vra').read_bytes())
        # Last old clip byte is an actor visibility flag: keep the VRA valid,
        # but prove preservation is checked independently of manifest hashes.
        data[len(old) - 1] ^= 1
        struct.pack_into('<I', data, 16, zlib.crc32(data[24:]))
        (folder / 'asset.vra').write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        manifest['files']['asset.vra']['sha256'] = digest
        manifest['repository_transport']['asset.vra']['decoded_sha256'] = digest
        (folder / 'asset.vra.gz').unlink()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'original walk44 clip bytes'):
            package.verify_directional(self.root)

    def test_missing_directional_companion_blocks_packaging(self):
        folder = self.root / package.DIRECTIONAL_DIR
        (folder / 'asset.vra').unlink(missing_ok=True)
        (folder / 'asset.vra.gz').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_directional(self.root)

    def test_source_change_requires_regeneration(self):
        source = self.root / 'assets/authoring/locomotion_directional/halcyon_hip_directional_r1.blend'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'committed Blender source'):
            package.verify_directional(self.root)

    def test_raw_companions_cannot_hide_corrupt_transport(self):
        path = self.root / package.DIRECTIONAL_DIR / 'asset.vra.gz'
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaisesRegex(ValueError, 'compressed companion SHA-256'):
            package.verify_directional(self.root)

    def test_cache_requires_transport_but_raw_only_distribution_does_not(self):
        folder = self.root / package.DIRECTIONAL_DIR
        for name in ('asset.vra.gz', 'asset.vrs.gz'):
            (folder / name).unlink()
        package.verify_directional(self.root)
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_directional(self.root, require_transports=True)

    def test_stage_retains_walk44_and_ads47_with_directional48(self):
        if not (ROOT / package.GENERATED_DIR / 'manifest.json').exists() or not (ROOT / package.ADS_DIR / 'manifest.json').exists():
            self.skipTest('Complete generated reload and ADS build outputs required')
        for folder in (package.GENERATED_DIR, package.ADS_DIR):
            shutil.copytree(ROOT / folder, self.root / folder)
        # Production manifest also carries reload and ADS selections; this test
        # explicitly replaces just the walking binding, independent of rollout.
        config = (ROOT / 'assets/animations.cfg').read_text()
        config = '\n'.join(line for line in config.splitlines()
                           if not line.startswith('regular_walk.asset=')
                           and not line.startswith('regular_walk.clip=')
                           and not line.startswith('regular_walk.direction.')) + '\n' + BINDINGS
        (self.root / 'assets/animations.cfg').write_text(config)
        for relative in (*package.NOTICES, *package.BUILD_FILES, 'docs/ANIMATION_SLOTS.md', 'target/release/vector-range'):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'packaging fixture')
        destination = self.root / 'staged'
        package.stage(self.root, 'target/release/vector-range', destination, require_generated=True)
        for folder, verifier in ((package.WALK_DIR, package.verify_walk),
                                 (package.ADS_DIR, package.verify_ads),
                                 (package.DIRECTIONAL_DIR, package.verify_directional)):
            self.assertTrue((destination / folder / 'asset.vra').is_file())
            self.assertFalse((destination / folder / 'asset.vra.gz').exists())
            verifier(destination)
