"""JUMP distribution binds source, canonical walk44 and native Rust parity."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import package_game as package
from jump_landing_patch import PATCH_PROVENANCE

ROOT = Path(__file__).resolve().parents[1]


class JumpDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / package.JUMP_DIR / 'manifest.json').exists():
            raise unittest.SkipTest('JUMP build outputs are required; complete-game CI produces them')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for folder in (package.ASSET_DIR, package.WALK_DIR, package.JUMP_DIR):
            shutil.copytree(ROOT / folder, self.root / folder)
        (self.root / 'assets/animations.cfg').write_text('jump.asset=jump/asset.vra\n')

    def test_preserves_walk44_and_binds_three_clips(self):
        report = package.verify_jump(self.root)
        self.assertEqual(report['original_clips_preserved'], 44)
        self.assertEqual(report['clip_count'], 47)
        self.assertGreaterEqual(report['parity_samples'], 75)
        self.assertEqual(report['source_action_patch'], PATCH_PROVENANCE)

    def test_compressed_vra_materializes_exact_verified_runtime_bytes(self):
        vra = self.root / package.JUMP_DIR / 'asset.vra'
        expected = json.loads((self.root / package.JUMP_DIR / 'manifest.json').read_text())['files']['asset.vra']
        vra.unlink(missing_ok=True)
        package.materialize(self.root, include_jump=True)
        import hashlib
        self.assertEqual(vra.stat().st_size, expected['bytes'])
        self.assertEqual(hashlib.sha256(vra.read_bytes()).hexdigest(), expected['sha256'])

    def test_raw_companions_cannot_hide_corrupt_compressed_transports(self):
        for name in ('asset.vra.gz', 'asset.vrs.gz'):
            path = self.root / package.JUMP_DIR / name
            original = path.read_bytes()
            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaisesRegex(ValueError, 'compressed companion SHA-256'):
                package.verify_jump(self.root)
            path.write_bytes(original)

    def test_cache_requires_transports_but_raw_only_package_does_not(self):
        (self.root / package.JUMP_DIR / 'asset.vra.gz').unlink()
        package.verify_jump(self.root)
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_jump(self.root, require_transports=True)

    def test_matching_rust_parity_required_for_every_clip(self):
        for clip in package.JUMP_CLIPS:
            path = self.root / package.JUMP_DIR / f'parity-{clip}.json'
            original = path.read_text(); data = json.loads(original)
            data['asset_sha256'] = 'wrong'
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'Rust parity'):
                package.verify_jump(self.root)
            path.write_text(original)

    def test_source_change_requires_regeneration(self):
        source = self.root / 'assets/authoring/jump/halcyon_jump.blend'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'committed Blender source'):
            package.verify_jump(self.root)

    def test_manifest_cannot_change_loop_or_duration(self):
        path = self.root / package.JUMP_DIR / 'manifest.json'
        data = json.loads(path.read_text()); data['jump_clips'][0]['loop'] = True
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'JUMP manifest'):
            package.verify_jump(self.root)

    def test_missing_companion_blocks_package(self):
        (self.root / package.JUMP_DIR / 'asset.vra').unlink(missing_ok=True)
        (self.root / package.JUMP_DIR / 'asset.vra.gz').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_jump(self.root)

    def test_unsupported_package_binding_rejected(self):
        (self.root / 'assets/animations.cfg').write_text('jump.asset=../private/asset.vra\n')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            package.jump_bound(self.root)

    def test_stale_or_failed_seam_evidence_blocks_packaging(self):
        path = self.root / package.JUMP_DIR / 'runtime-seams.json'
        original = path.read_text()
        for key, value in [('asset_sha256', 'stale'), ('passed', False), ('checks', [])]:
            data = json.loads(original); data[key] = value
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'seam/hold evidence'):
                package.verify_jump(self.root)
        path.write_text(original)
        package.verify_jump(self.root)

    def test_wrong_source_action_crop_or_density_blocks_cached_pack(self):
        manifest = self.root / package.JUMP_DIR / 'manifest.json'
        original = manifest.read_text()
        data = json.loads(original); data['jump_clips'][0]['action'] = 'jump_takeoff_r6'
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'JUMP manifest'):
            package.verify_jump(self.root)
        manifest.write_text(original)
        path = self.root / package.JUMP_DIR / 'conversion-jump_takeoff.json'
        original = path.read_text()
        for key, value in [('native_crop', [1,12]), ('imported_frame_offset', 1),
                           ('timing_policy', {'subdivisions': 1, 'samples': 12})]:
            data = json.loads(original); data[key] = value; path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'Rust parity'):
                package.verify_jump(self.root)
        path.write_text(original)
        package.verify_jump(self.root)

    def test_old_r7_or_changed_patch_manifest_is_rejected(self):
        path = self.root / package.JUMP_DIR / 'manifest.json'
        original = path.read_text()
        variants = []
        old_schema = json.loads(original)
        old_schema['schema'] = 'rust-duty-authored-jump-distribution/v1'
        variants.append(old_schema)
        old_action = json.loads(original)
        old_action['jump_clips'][2]['action'] = 'jump_land_r7'
        variants.append(old_action)
        missing = json.loads(original)
        missing['source'].pop('action_patch')
        variants.append(missing)
        for key in PATCH_PROVENANCE:
            wrong = json.loads(original)
            wrong['source']['action_patch'][key] = 'changed'
            variants.append(wrong)
        for data in variants:
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'JUMP manifest'):
                package.verify_jump(self.root)
        path.write_text(original)
        package.verify_jump(self.root)

    def test_every_parity_report_binds_approved_action_patch(self):
        for clip in package.JUMP_CLIPS:
            path = self.root / package.JUMP_DIR / f'parity-{clip}.json'
            original = path.read_text()
            for patch in (None, {}, {'candidate_action': 'jump_land_r7'}):
                data = json.loads(original)
                data['source_action_patch'] = patch
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'Rust parity'):
                    package.verify_jump(self.root)
            path.write_text(original)
        package.verify_jump(self.root)

    def test_changed_keys_boundaries_and_trough_have_direct_parity_samples(self):
        path = self.root / package.JUMP_DIR / 'parity-jump_land.json'
        original = path.read_text()
        for frame in (4., 4.5, 5., 5.0625, 5.5, 6., 6.0625, 6.5, 7., 12.):
            data = json.loads(original)
            data['records'] = [r for r in data['records'] if r['native_frame'] != frame]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'changed-interval source/Rust parity'):
                package.verify_jump(self.root)
        path.write_text(original)
        package.verify_jump(self.root)

    def test_spaced_manifest_key_still_requires_jump_assets(self):
        config = self.root / 'assets/animations.cfg'
        config.write_text('jump.asset = jump/asset.vra\n')
        self.assertTrue(package.jump_bound(self.root))
        self.assertTrue(package.walk_bound(self.root))
        config.write_text('jump.asset = jump/asset.vra\njump.asset=jump/asset.vra\n')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            package.jump_bound(self.root)
