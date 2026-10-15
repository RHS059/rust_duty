import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import ensure_level_lighting as lighting
from ensure_level_lighting import check, fresh, inputs, record

LEVEL_DATA = ('assets/levels/cedar_junction/level.json', 'assets/levels/cedar_junction/meshes.bin')

class LightingCacheTests(unittest.TestCase):
    def fixture(self, root, level):
        for name in LEVEL_DATA:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('level data')
        folder=root/'assets/levels'/level;folder.mkdir(parents=True,exist_ok=True)
        output=folder/'lighting.bin';output.write_bytes(b'baked fixture')
        return output

    def test_output_level_data_and_version_edits_invalidate_cached_bake(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            output=self.fixture(root,'cedar_junction')
            self.assertFalse(fresh(root,'cedar_junction'))
            record(root,'cedar_junction',inputs(root,'cedar_junction'))
            self.assertTrue(fresh(root,'cedar_junction'))
            output.write_bytes(b'damaged fixture')
            self.assertFalse(fresh(root,'cedar_junction'))
            output.write_bytes(b'baked fixture')
            (root/LEVEL_DATA[1]).write_text('edited city meshes')
            self.assertFalse(fresh(root,'cedar_junction'))
            (root/LEVEL_DATA[1]).write_text('level data')
            self.assertTrue(fresh(root,'cedar_junction'))
            with mock.patch.object(lighting,'BAKE_VERSION',lighting.BAKE_VERSION+1):
                self.assertFalse(fresh(root,'cedar_junction'))

    def test_source_code_edits_do_not_invalidate_cached_bake(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root,'range')
            record(root,'range',inputs(root,'range'))
            source=root/'src/static_lighting.rs';source.parent.mkdir(parents=True);source.write_text('reformatted')
            self.assertTrue(fresh(root,'range'))

    def test_level_data_race_cannot_be_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root,'cedar_junction')
            before=inputs(root,'cedar_junction')
            (root/LEVEL_DATA[0]).write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'changed during baking'):
                record(root,'cedar_junction',before)

    def test_build_check_never_bakes_and_rejects_damaged_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for level in ('range','cedar_junction'):
                self.fixture(root,level)
                record(root,level,inputs(root,level))
            with mock.patch.object(lighting.subprocess,'run') as run:
                check(root)
                (root/LEVEL_DATA[1]).write_text('stale but intact')
                check(root)
                run.assert_not_called()
            (root/'assets/levels/range/lighting.bin').write_bytes(b'damaged')
            with self.assertRaisesRegex(SystemExit,'range'):
                check(root)

if __name__=='__main__':unittest.main()
