"""Source-only successor checks; no Rust compiler or animation inputs."""
import ast,hashlib,json,unittest
from pathlib import Path
HERE=Path(__file__).absolute().parent

class SelectedSource(unittest.TestCase):
    def test_nine_reference_inputs_match_immutable_selection(self):
        value=json.loads((HERE/'SOURCE_CLOSURE.json').read_bytes());refs=json.loads((HERE/'RUST_REFERENCE_PINS.json').read_bytes())
        self.assertEqual(value['commit'],'c61dbd67039a4961d0c56f0a3c7e478c431d1ced')
        rows={r['path']:r['sha256'] for r in value['files']};self.assertEqual(len(rows),213)
        self.assertEqual(len(refs),9)
        for path,sha in refs.items():self.assertEqual(rows[path],sha,path)
        self.assertEqual(refs['src/lib.rs'],'dc74b9bbd4a88bf3fd5b58754751c2afc7ee397e72527bb64f419387da4ee99f')
        self.assertEqual(refs['examples/sample_viewmodel_clip.rs'],'82123dbb8be6db54a3780a2b18079a809738cd2559f89de7dcee0aac1d31e22b')
    def test_math_process_and_threshold_source_unchanged(self):
        manifest=json.loads((HERE/'PREDECESSOR_CODE_PINS.json').read_bytes())
        prior=HERE.parent/'windows-runtime-consumer-v4'
        for name,sha in manifest.items():
            self.assertEqual(hashlib.sha256((prior/name).read_bytes()).hexdigest(),sha,name)
            if name not in ('pinned_math.py','runtime_context.py'):
                self.assertEqual((HERE/name).read_bytes(),(prior/name).read_bytes(),name)
        # Only dependency identity wiring changes in these two original files.
        old=(prior/'pinned_math.py').read_text();new=(HERE/'pinned_math.py').read_text()
        import pinned_math as p
        self.assertEqual(old.replace("cee1e6fc907638c6eaa363fd301b722b145767ae1d19131519a53b9b74c9d378",p.CONTEXT_PINS_SHA),new)
        before=ast.parse((prior/'runtime_context.py').read_bytes());after=ast.parse((HERE/'runtime_context.py').read_bytes())
        class RestoreSelectionLabel(ast.NodeTransformer):
            def visit_Name(self,node):
                if node.id=='SELECTED_PRODUCER_PINS_SHA':node.id='REVIEWED_PRODUCER_PINS_SHA'
                return node
            def visit_Constant(self,node):
                if node.value=='selected producer/assembler dependency pins absent':node.value='reviewed producer/assembler admission pins absent'
                return node
        old_defs=[ast.dump(n,include_attributes=False) for n in before.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))]
        new_defs=[ast.dump(RestoreSelectionLabel().visit(n),include_attributes=False) for n in after.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))]
        self.assertEqual(old_defs,new_defs)
        self.assertEqual((HERE/'SOURCE_CLOSURE.json').read_bytes(),(prior/'SOURCE_CLOSURE.json').read_bytes())
        self.assertEqual((HERE/'RUST_REFERENCE_PINS.json').read_bytes(),(prior/'RUST_REFERENCE_PINS.json').read_bytes())
    def test_source_selection_never_claims_actual_windows_provenance(self):
        value=json.loads((HERE/'SOURCE_CLOSURE.json').read_bytes())
        self.assertFalse(value['actual_windows_provenance']);self.assertEqual(value['features'],[]);self.assertTrue(value['default_features'])

if __name__=='__main__':unittest.main()
