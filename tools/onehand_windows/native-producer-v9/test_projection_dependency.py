"""Exact dependency-only successor; no native process or source payload."""
from pathlib import Path
import ast,hashlib,json,unittest
import pinned_code
from test_fragment_ast import original_pinned_code_sha
from test_rigid_json_cap import original_native_stages_sha
from test_payload_only_inventory import OLD_INVENTORY_LINE, NEW_INVENTORY_BLOCK
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
        def adaptation(source):
            node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='verify_output_inventory')
            lines=source.splitlines(keepends=True)
            return {'ast_sha256':hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest(),
                    'source_sha256':hashlib.sha256(''.join(lines[node.lineno-1:node.end_lineno]).encode()).hexdigest()}
        current=(HERE/'admission.py').read_text()
        self.assertEqual(current.count(NEW_INVENTORY_BLOCK),1)
        predecessor=current.replace(NEW_INVENTORY_BLOCK,OLD_INVENTORY_LINE)
        declared=json.loads((HERE/'PAYLOAD_ONLY_PREDECESSOR.json').read_bytes())['files']
        self.assertEqual(hashlib.sha256(predecessor.encode()).hexdigest(),declared['admission.py'])
        boundary=json.loads((HERE/'BOUNDARY_ADAPTATIONS.json').read_bytes())
        self.assertEqual(boundary['adaptations']['admission.py:verify_output_inventory'],adaptation(current))
        # Reverse only the declared inventory adaptation. Every other byte of
        # the historical metadata must still reconstruct its exact frozen hash.
        boundary['adaptations']['admission.py:verify_output_inventory']=adaptation(predecessor)
        original_boundary=(json.dumps(boundary,sort_keys=True,indent=2)+'\n').encode()
        self.assertEqual(hashlib.sha256(original_boundary).hexdigest(),declared['BOUNDARY_ADAPTATIONS.json'])
        for name in names:
            observed=(original_native_stages_sha() if name=='native_stages.py' else
                      hashlib.sha256(original_boundary).hexdigest() if name=='BOUNDARY_ADAPTATIONS.json' else
                      hashlib.sha256((HERE/name).read_bytes()).hexdigest())
            self.assertEqual(observed,old[name],name)
        self.assertEqual(original_pinned_code_sha(),old['pinned_code.py'])

if __name__=='__main__':unittest.main(verbosity=2)
