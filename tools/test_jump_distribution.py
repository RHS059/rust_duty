"""JUMP delivery binds source, native timing and unchanged canonical walk44."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import package_game as package
from jump_landing_patch import PATCH_PROVENANCE
from distribution_test_fixtures import add_test_transports

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
        self.assertEqual(report['clips'], list(package.JUMP_CLIPS))
        manifest = json.loads((self.root / package.JUMP_DIR / 'manifest.json').read_text())
        self.assertEqual(report['source_sha256'], manifest['source']['sha256'])
        self.assertEqual(report['source_action_patch'], PATCH_PROVENANCE)

    def test_compressed_vra_materializes_exact_verified_runtime_bytes(self):
        vra = self.root / package.JUMP_DIR / 'asset.vra'
        expected = add_test_transports(self.root, package.JUMP_DIR)['files']['asset.vra']
        package.verify_jump(self.root, require_transports=True)
        vra.unlink(missing_ok=True)
        package.materialize(self.root, include_jump=True)
        self.assertEqual(vra.stat().st_size, expected['bytes'])
        self.assertEqual(hashlib.sha256(vra.read_bytes()).hexdigest(), expected['sha256'])

    def test_raw_companions_cannot_hide_corrupt_compressed_transports(self):
        add_test_transports(self.root, package.JUMP_DIR)
        package.verify_jump(self.root, require_transports=True)
        for name in ('asset.vra.gz', 'asset.vrs.gz'):
            path = self.root / package.JUMP_DIR / name
            original = path.read_bytes()
            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaisesRegex(ValueError, 'compressed companion SHA-256'):
                package.verify_jump(self.root)
            path.write_bytes(original)

    def test_cache_requires_transports_but_raw_only_package_does_not(self):
        add_test_transports(self.root, package.JUMP_DIR)
        package.verify_jump(self.root, require_transports=True)
        for name in ('asset.vra.gz', 'asset.vrs.gz'):
            (self.root / package.JUMP_DIR / name).unlink()
        package.verify_jump(self.root)
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_jump(self.root, require_transports=True)

    def test_every_conversion_binds_source_and_native_clock(self):
        for clip in package.JUMP_CLIPS:
            path = self.root / package.JUMP_DIR / f'conversion-{clip}.json'
            original = path.read_text()
            for key, value in (('authoring_master_sha256', 'wrong'),
                               ('source_fbx_sha256', 'wrong'),
                               ('native_fps', [30, 1]), ('source_take', 'wrong')):
                with self.subTest(clip=clip, field=key):
                    data = json.loads(original); data[key] = value
                    path.write_text(json.dumps(data))
                    with self.assertRaisesRegex(ValueError, 'JUMP conversion/source metadata'):
                        package.verify_jump(self.root)
            path.write_text(original)
        package.verify_jump(self.root)

    def test_source_change_requires_regeneration(self):
        source = self.root / 'assets/authoring/jump/halcyon_jump.blend'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'committed Blender source'):
            package.verify_jump(self.root)

    def test_manifest_cannot_change_loop_or_duration(self):
        path = self.root / package.JUMP_DIR / 'manifest.json'
        original = path.read_text()
        for index in range(len(package.JUMP_CLIPS)):
            for key, value in (('loop', True), ('duration', 2.)):
                with self.subTest(clip=index, field=key):
                    data = json.loads(original); data['jump_clips'][index][key] = value
                    path.write_text(json.dumps(data))
                    with self.assertRaisesRegex(ValueError, 'JUMP manifest'):
                        package.verify_jump(self.root)

    def test_missing_companion_blocks_package(self):
        (self.root / package.JUMP_DIR / 'asset.vra').unlink(missing_ok=True)
        (self.root / package.JUMP_DIR / 'asset.vra.gz').unlink(missing_ok=True)
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_jump(self.root)

    def test_unsupported_package_binding_rejected(self):
        (self.root / 'assets/animations.cfg').write_text('jump.asset=../private/asset.vra\n')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            package.jump_bound(self.root)

    def test_delivery_does_not_require_numerical_parity_or_seam_reports(self):
        paths = [self.root / package.JUMP_DIR / name for name in
                 ('runtime-seams.json', *(f'parity-{clip}.json' for clip in package.JUMP_CLIPS))]
        for path in paths:
            path.unlink(missing_ok=True)
        expected = package.verify_jump(self.root)
        for path in paths:
            path.write_text('not a numerical parity or seam report')
        self.assertEqual(package.verify_jump(self.root), expected)

    def test_wrong_source_action_crop_or_density_blocks_cached_pack(self):
        manifest = self.root / package.JUMP_DIR / 'manifest.json'
        original = manifest.read_text()
        data = json.loads(original); data['jump_clips'][0]['action'] = 'jump_takeoff_r6'
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'JUMP manifest'):
            package.verify_jump(self.root)
        manifest.write_text(original)
        for clip, end in zip(package.JUMP_CLIPS, (12, 24, 29)):
            path = self.root / package.JUMP_DIR / f'conversion-{clip}.json'
            original = path.read_text()
            for key, value in (
                    ('native_crop', [1, end]), ('imported_frame_offset', 1),
                    ('timing_policy', {'subdivisions': 1, 'samples': (end - 1) * 8 + 1}),
                    ('timing_policy', {'subdivisions': 8, 'samples': end})):
                with self.subTest(clip=clip, field=key, value=value):
                    data = json.loads(original); data[key] = value; path.write_text(json.dumps(data))
                    with self.assertRaisesRegex(ValueError, 'JUMP conversion/source metadata'):
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

    def test_missing_conversion_metadata_blocks_delivery(self):
        for clip in package.JUMP_CLIPS:
            path = self.root / package.JUMP_DIR / f'conversion-{clip}.json'
            original = path.read_text()
            path.unlink()
            with self.subTest(clip=clip):
                with self.assertRaisesRegex(ValueError, 'required distribution file missing'):
                    package.verify_jump(self.root)
            path.write_text(original)
        package.verify_jump(self.root)

    def test_rehashed_invalid_vra_still_fails_binary_validation(self):
        folder = self.root / package.JUMP_DIR
        path = folder / 'manifest.json'
        manifest = json.loads(path.read_text())
        data = bytearray(package.companion_bytes(self.root, 'asset.vra', manifest, package.JUMP_DIR))
        data[0] ^= 1
        (folder / 'asset.vra').write_bytes(data)
        (folder / 'asset.vra.gz').unlink(missing_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        manifest['files']['asset.vra']['sha256'] = digest
        manifest['repository_transport']['asset.vra']['decoded_sha256'] = digest
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'VRA magic/version'):
            package.verify_jump(self.root)

    def test_spaced_manifest_key_still_requires_jump_assets(self):
        config = self.root / 'assets/animations.cfg'
        config.write_text('jump.asset = jump/asset.vra\n')
        self.assertTrue(package.jump_bound(self.root))
        self.assertTrue(package.walk_bound(self.root))
        config.write_text('jump.asset = jump/asset.vra\njump.asset=jump/asset.vra\n')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            package.jump_bound(self.root)
