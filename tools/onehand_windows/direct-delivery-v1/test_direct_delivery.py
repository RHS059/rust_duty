#!/usr/bin/env python3
"""Focused source-only regressions. Never executes Blender, Cargo or native jobs."""
import gzip,hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).absolute().parent))
import run_delivery,runtime_binding,materialize_inputs
from common import canonical,sha
HERE=Path(__file__).absolute().parent

class FakeCommands:
    def __init__(self,root,work,fail=None):self.root=root;self.work=work;self.fail=fail;self.labels=[]
    def run(self,label,argv,cwd,**kwargs):
        self.labels.append(label)
        if label==self.fail:raise RuntimeError('ordinary '+label+' failure')
        if label=='game-build':
            exe=self.work/'target'/run_delivery.TARGET/'release/vector-range.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'MZ-test-game')
            out=self.work/'cargo.jsonl';out.write_text(json.dumps({'reason':'compiler-artifact','target':{'name':'vector-range'},'executable':str(exe)})+'\n'+json.dumps({'reason':'build-finished','success':True})+'\n')
            return {'stdout':{'path':str(out)},'terminal':{'sha256':'1'*64}}
        if label=='game-package':
            folder=self.work/'delivery';folder.mkdir();(folder/'vector-range.exe').write_bytes((self.root/'vector-range.exe').read_bytes())
        return {}

class DirectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'root';self.root.mkdir();self.work=Path(self.temp.name)/'work';self.work.mkdir()
    def test_compile_and_package_need_no_proof_capture_or_sampler(self):
        c=FakeCommands(self.root,self.work)
        delivery,_=run_delivery.build_and_stage(self.root,self.work,'cargo.exe',c,{})
        self.assertTrue((delivery/'vector-range.exe').is_file())
        self.assertEqual(c.labels,['game-build','updater-fetch','updater-notices','game-package'])
        cmd=run_delivery.cargo_command('cargo.exe',self.work/'target')
        self.assertNotIn('--example',cmd);self.assertIn('vector-range',cmd)
    def test_failed_old_proof_and_capture_files_cannot_block_delivery(self):
        for name in ('aggregate.json','game-capture.json','compiler-inputs.json'):(self.work/name).write_text('{"passed":false}')
        c=FakeCommands(self.root,self.work)
        self.assertTrue(run_delivery.build_and_stage(self.root,self.work,'cargo.exe',c,{})[0].exists())
    def test_actual_compile_failure_stops_before_packaging(self):
        c=FakeCommands(self.root,self.work,'game-build')
        with self.assertRaisesRegex(RuntimeError,'ordinary game-build failure'):run_delivery.build_and_stage(self.root,self.work,'cargo.exe',c,{})
        self.assertEqual(c.labels,['game-build']);self.assertFalse((self.work/'delivery').exists())
    def test_actual_package_failure_propagates(self):
        c=FakeCommands(self.root,self.work,'game-package')
        with self.assertRaisesRegex(RuntimeError,'ordinary game-package failure'):run_delivery.build_and_stage(self.root,self.work,'cargo.exe',c,{})
    def test_unsuccessful_cargo_stream_is_not_accepted(self):
        path=self.work/'cargo.jsonl';path.write_text('{"reason":"build-finished","success":false}\n')
        with self.assertRaisesRegex(ValueError,'successful build'):run_delivery.game_executable(path)
    def test_stable_replace_overwrites_and_preserves_unrelated_manifest(self):
        source=self.work/'asset.vra';target=self.root/'asset.vra';source.write_bytes(b'new');target.write_bytes(b'old')
        runtime_binding.replace_file(source,target);runtime_binding.replace_file(source,target);self.assertEqual(target.read_bytes(),b'new')
        old='# default\nlow_vault.asset=low_vault/asset.vra\nprone_entry.asset=prone_entry/asset.vra\nhigh_mantle.asset=onehand/asset.vra\naudio=true\n'
        result=runtime_binding.bind_manifest(old,{'high_mantle.asset':'onehand/asset.vra'})
        self.assertEqual(result,old)
    def test_existing_runtime_receipt_need_no_numerical_proof_fields(self):
        folder=self.root/'assets/onehand';folder.mkdir(parents=True);src=self.root/'src';src.mkdir()
        for ext in ('vra','vrs','vrm'):(folder/('asset.'+ext)).write_bytes(ext.encode())
        receipt={'source_fbx_sha256':'1'*64,**{'asset_'+e+'_sha256':sha(folder/('asset.'+e)) for e in ('vra','vrs','vrm')}}
        path=folder/'runtime-receipt.json';path.write_bytes(canonical(receipt));before=path.read_bytes()
        (src/'authored_high_mantle.rs').write_text("const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = None;\n")
        cfg=self.root/'assets/animations.cfg';cfg.write_text('prone_entry.asset=prone_entry/asset.vra\n')
        first=runtime_binding.bind_existing(self.root);second=runtime_binding.bind_existing(self.root)
        self.assertEqual(len(first['changed_source_files']),2);self.assertEqual(second['changed_source_files'],[])
        self.assertEqual(path.read_bytes(),before);self.assertIn('prone_entry.asset=prone_entry/asset.vra',cfg.read_text());self.assertEqual(cfg.read_text().count('high_mantle.asset='),1)
    def test_corrupt_existing_runtime_hash_still_fails(self):
        folder=self.root/'assets/onehand';folder.mkdir(parents=True)
        for ext in ('vra','vrs','vrm'):(folder/('asset.'+ext)).write_bytes(ext.encode())
        (folder/'runtime-receipt.json').write_bytes(canonical({'source_fbx_sha256':'1'*64,**{'asset_'+e+'_sha256':'0'*64 for e in ('vra','vrs','vrm')}}))
        with self.assertRaisesRegex(ValueError,'identity differs'):runtime_binding.bind_existing(self.root)
    def test_active_workflow_has_no_legacy_admission_or_capture_steps(self):
        root=HERE.parents[2];workflow=root/'.github/workflows/onehand-windows-proof.yml'
        if not workflow.exists():workflow=HERE.parents[3]/'.github/workflows/onehand-windows-proof.yml'
        text=workflow.read_text()
        for token in ('run_proof.py','execute_continuation.py','preinstall_admission.py','game_capture_passed','sample_viewmodel_clip','compiler_report','verify_dx12','run_source_tests.py'):
            self.assertNotIn(token,text)
        self.assertIn('run_delivery.py',text);self.assertIn('actions/upload-artifact@v4',text)
    def test_optional_source_inputs_exclude_historical_proof_sources(self):
        value=json.loads((HERE/'source-inputs.json').read_text())
        self.assertFalse(any(row['destination'].startswith(('hash-only-reference/','runtime-consumer-reviewed/')) for row in value['files']))
    def test_runtime_loader_preserves_clock_but_removes_numerical_proof_requirement(self):
        root=HERE.parents[2];source=root/'src/authored_high_mantle.rs'
        if not source.exists():source=HERE.parents[3]/'src/authored_high_mantle.rs'
        before=source.read_text().split('#[cfg(test)]')[0]
        for token in ('pins.proof','verification_sample_count','skin_vertex_observations','runtime_source_proof_sha256'):self.assertNotIn(token,before)
        self.assertIn('95. / 60.',before);self.assertIn('SUBDIVISIONS: usize = 256',before)
if __name__=='__main__':unittest.main(verbosity=2)
