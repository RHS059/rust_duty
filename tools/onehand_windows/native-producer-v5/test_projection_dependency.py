"""Exact dependency-only successor; no native process or source payload."""
from pathlib import Path
import unittest
import pinned_code
from test_native_producer import cc, fixture, HERE

class ProjectionDependency(unittest.TestCase):
    def test_context_v2_is_exact_selected_dependency(self):
        self.assertEqual(cc.SCHEMA, 'rust-duty-windows-candidate-context/v2')
        self.assertEqual(pinned_code.file_sha(HERE.parent/'windows-candidate-context-v2/PINS.json'),
                         pinned_code.CONTEXT_PINS_SHA)
        self.assertNotEqual(cc.DELTA_SHA, cc.ORIGINAL_DELTA_SHA)
        ctx = fixture(HERE/'unused-projection-context')
        ctx.validate()
        self.assertEqual(ctx.pin('original_delta').sha256, cc.DELTA_SHA)

    def test_all_native_numeric_and_process_files_are_byte_identical(self):
        old=HERE.parent/'windows-native-producer-v3'
        names=('AUDITED_FRAGMENTS.json','BOUNDARY_ADAPTATIONS.json','admission.py',
               'extract_helpers.py','launch_stage.py','native_entry.py','native_stages.py',
               'planner.py','process_evidence.py','stage_context.py','transport_binding.py')
        for name in names:self.assertEqual((HERE/name).read_bytes(),(old/name).read_bytes(),name)
        expected=(old/'pinned_code.py').read_text().replace(
            "cee1e6fc907638c6eaa363fd301b722b145767ae1d19131519a53b9b74c9d378",
            pinned_code.CONTEXT_PINS_SHA).replace('exact context v1 freeze required','exact context v2 freeze required')
        self.assertEqual((HERE/'pinned_code.py').read_text(),expected)

if __name__=='__main__':unittest.main(verbosity=2)
