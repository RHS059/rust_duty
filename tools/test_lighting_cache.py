import json
from pathlib import Path
import tempfile
import unittest
from ensure_level_lighting import CODE, fresh, inputs, record

class LightingCacheTests(unittest.TestCase):
    def test_input_and_output_edits_invalidate_cached_bake(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in CODE:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('source')
            folder=root/'assets/levels/range';folder.mkdir(parents=True)
            output=folder/'lighting.bin';output.write_bytes(b'baked fixture')
            self.assertFalse(fresh(root,'range'))
            record(root,'range',inputs(root,'range'))
            self.assertTrue(fresh(root,'range'))
            output.write_bytes(b'damaged fixture')
            self.assertFalse(fresh(root,'range'))
            output.write_bytes(b'baked fixture')
            (root/CODE[0]).write_text('changed lighting algorithm')
            self.assertFalse(fresh(root,'range'))

    def test_source_race_cannot_be_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in CODE:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('source')
            before=inputs(root,'range')
            (root/CODE[0]).write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'changed during baking'):
                record(root,'range',before)

if __name__=='__main__':unittest.main()
