"""Exact dependency-only successor; no native process or source payload."""
from pathlib import Path
import hashlib,json,unittest
import pinned_code
from test_fragment_ast import original_pinned_code_sha
from test_rigid_json_cap import original_native_stages_sha
from test_native_producer import cc, fixture, HERE

class ProjectionDependency(unittest.TestCase):
    def test_context_v2_is_exact_selected_dependency(self):
        self.assertEqual(cc.SCHEMA, 'rust-duty-windows-candidate-context/v2')
        context=HERE.parent/'windows-context-preparation-v3'
        if not context.is_dir():context=HERE.parent/'context-v3'
        self.assertEqual(pinned_code.file_sha(context/'PINS.json'),
                         pinned_code.CONTEXT_PINS_SHA)
        self.assertNotEqual(cc.DELTA_SHA, cc.ORIGINAL_DELTA_SHA)
        ctx = fixture(HERE/'unused-projection-context')
        ctx.validate()
        self.assertEqual(ctx.pin('original_delta').sha256, cc.DELTA_SHA)

    def test_native_numeric_transport_and_lineage_files_are_byte_identical(self):
        old=json.loads((HERE/'HOST_BINDING_PREDECESSOR.json').read_bytes())['files']
        names=('AUDITED_FRAGMENTS.json','BOUNDARY_ADAPTATIONS.json',
               'extract_helpers.py','native_stages.py',
               'planner.py','process_evidence.py','stage_context.py','transport_binding.py')
        for name in names:self.assertEqual(original_native_stages_sha() if name=='native_stages.py' else hashlib.sha256((HERE/name).read_bytes()).hexdigest(),old[name],name)
        self.assertEqual(original_pinned_code_sha(),old['pinned_code.py'])

if __name__=='__main__':unittest.main(verbosity=2)
