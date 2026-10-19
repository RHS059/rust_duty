"""Authored walking distribution fails closed and preserves the frozen43 pack."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import package_game as package

ROOT = Path(__file__).resolve().parents[1]


class WalkDistributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for folder in (package.ASSET_DIR, package.WALK_DIR):
            shutil.copytree(ROOT / folder, self.root / folder)
        (self.root / 'assets/animations.cfg').write_text('regular_walk.asset=walk/asset.vra\nregular_walk.clip=normal_walk_r1\n')

    def test_exact_walk_preserves43_and_materializes_skin(self):
        skin = self.root / package.WALK_DIR / 'asset.vrs'
        skin.unlink(missing_ok=True)
        report = package.verify_walk(self.root)
        self.assertEqual(report['original_clips_preserved'], 43)
        package.materialize(self.root, include_walk=True)
        self.assertEqual(skin.stat().st_size, 16663274)

    def test_conversion_binds_source_and_native_clock(self):
        path = self.root / package.WALK_DIR / 'conversion.json'
        original = path.read_text()
        for key, value in (('authoring_master_sha256', 'wrong'),
                           ('source_fbx_sha256', 'wrong'),
                           ('native_fps', [30, 1]), ('source_take', 'wrong')):
            with self.subTest(field=key):
                data = json.loads(original); data[key] = value
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'walk conversion/source metadata'):
                    package.verify_walk(self.root)
        path.write_text(original)
        package.verify_walk(self.root)

    def test_delivery_does_not_require_numerical_parity_report(self):
        path = self.root / package.WALK_DIR / 'parity.json'
        path.unlink(missing_ok=True)
        expected = package.verify_walk(self.root)
        path.write_text('not a numerical parity report')
        self.assertEqual(package.verify_walk(self.root), expected)

    def test_source_change_requires_regeneration(self):
        source = self.root / 'assets/authoring/locomotion/locomotion.blend'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'new source')
        with self.assertRaisesRegex(ValueError, 'committed Blender source'):
            package.verify_walk(self.root)

    def test_no_unsupported_asset_binding(self):
        (self.root / 'assets/animations.cfg').write_text('regular_walk.asset=../private/asset.vra\n')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            package.walk_bound(self.root)

    def test_missing_walk_companion_blocks_package(self):
        (self.root / package.WALK_DIR / 'asset.vra').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            package.verify_walk(self.root)
