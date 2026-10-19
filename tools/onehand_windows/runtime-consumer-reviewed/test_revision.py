"""Tiny non-native C1-C4 regressions. Synthetic receipts confer no production authority."""
import copy,json,tempfile,unittest
from pathlib import Path,PureWindowsPath
from types import SimpleNamespace
import build_closure as bc
import consumer,evidence,pinned_math as p,runtime_context as rc,retirement
from test_runtime_consumer import CC,M
import test_runtime_consumer as tests

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return rc.record(path)

class SourceClosure(unittest.TestCase):
    def test_nested_target_and_git_not_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for folder in ('target','src/target','nested/.git'):
                f=root/folder/'included.rs';f.parent.mkdir(parents=True);f.write_text('one')
            before=rc.inventory(root,CC)
            self.assertEqual(set(before),{'target/included.rs','src/target/included.rs','nested/.git/included.rs'})
            (root/'src/target/included.rs').write_text('two');self.assertNotEqual(before,rc.inventory(root,CC))
    def test_metadata_must_belong_to_actual_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);manifest=root/'Cargo.toml';manifest.write_text('tiny');src=root/'lib.rs';src.write_text('tiny')
            metadata={'packages':[{'id':'test','manifest_path':str(manifest),'targets':[{'name':'test','kind':['lib'],'src_path':str(src)}]}],'resolve':{'nodes':[{'id':'test','dependencies':[]}]}}
            files=rc.inventory(root,CC);self.assertEqual(len(bc.validate_metadata(metadata,[(root,files)],CC)),1)
            for omitted in ('Cargo.toml','lib.rs'):
                with self.subTest(omitted=omitted),self.assertRaises(ValueError):bc.validate_metadata(metadata,[(root,{k:v for k,v in files.items() if k!=omitted})],CC)
    def test_ambiguous_dependency_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);f=root/'file';f.write_text('x');files=rc.inventory(root,CC)
            with self.assertRaises(ValueError):bc.membership(f,[(root,files),(root,files)],CC)
    def test_windows_drive_depinfo(self):
        self.assertEqual(bc.dep_info_paths(br'C:\build\sample.d: C:\source\main.rs C:\source\target\extra.rs' + b'\n'),['C:\\source\\main.rs','C:\\source\\target\\extra.rs'])
    def test_escaped_space_continuation_and_empty_rules(self):
        self.assertEqual(bc.dep_info_paths(b'out: source\\ with\\ spaces.rs \\\n nested/target/a.rs\nsource\\ with\\ spaces.rs:\n'),['nested/target/a.rs','source with spaces.rs'])
    def test_depinfo_control_or_missing_paths_rejected(self):
        for raw in (b'out: $(outside)',b'out: a\x00b',b'invalid',b'out:\n'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):bc.dep_info_paths(raw)

class RetainedPlans(unittest.TestCase):
    setUp=tests.Retirement.setUp
    tearDown=tests.Retirement.tearDown
    plan=tests.Retirement.plan
    def retain(self):
        path,h=self.plan()
        for rec in self.files:Path(rec['path']).unlink()
        journal=write(self.out/'retirement/chunk-000.plan.json',{'schema':'rust-duty-windows-raw-retirement-attempt/v1','binding':self.ctx.runtime_binding,'index':0,'runtime_receipt_sha256':self.value['runtime_receipt_sha256'],'verified_plan':rc.record(path),'authorization_ref':'synthetic-exact-plan-trace','retired_files':self.files,'passed':False})
        result={'schema':'rust-duty-windows-raw-retirement/v1','binding':self.ctx.runtime_binding,'passed':True,'index':0,'runtime_receipt_sha256':self.value['runtime_receipt_sha256'],'retired_files':self.files,'verified_plan':rc.record(path),'authorization_ref':'synthetic-exact-plan-trace','journal':journal,**retirement.FLAGS}
        target=self.out/'retirement/chunk-000.json';write(target,result);return path,target,result
    def test_retained_admission_does_not_read_deleted_raw(self):
        self.retain();self.assertTrue(retirement.verify_retired(self.ctx,self.report,0)['passed'])
    def test_original_plan_prevents_changed_current_chunk(self):
        plan,target,result=self.retain();before=p.sha(plan);self.report['substitution']=True;write(self.receipt,self.report)
        result['runtime_receipt_sha256']=p.sha(self.receipt);write(target,result)
        with self.assertRaises(ValueError):retirement.verify_retired(self.ctx,self.report,0)
        self.assertEqual(before,p.sha(plan))
    def test_every_preserved_file_rechecked(self):
        self.retain();Path(self.report['session']['path']).write_text('changed')
        with self.assertRaises(ValueError):retirement.verify_retired(self.ctx,self.report,0)
    def test_empty_journal_rejected_even_after_repin(self):
        plan,target,result=self.retain();result['journal']=write(Path(result['journal']['path']),{});write(target,result)
        with self.assertRaises(ValueError):retirement.verify_retired(self.ctx,self.report,0)
    def test_journal_authorization_and_plan_reference_exact(self):
        plan,target,result=self.retain();journal=p.read(result['journal']['path']);journal['authorization_ref']='another-plan';result['journal']=write(Path(result['journal']['path']),journal);write(target,result)
        with self.assertRaises(ValueError):retirement.verify_retired(self.ctx,self.report,0)
    def test_failed_retirement_never_accepted(self):
        plan,target,result=self.retain();write(target.with_suffix('.failed.json'),{'failed':True})
        with self.assertRaises(ValueError):retirement.verify_retired(self.ctx,self.report,0)
    def test_mutated_plan_schema_flags_or_preservation_rejected(self):
        for field,wrong in [('schema','wrong'),('binding',{}),('index',1),('passed',True),('independently_reconsumed',False),('preserved_files',[]),('runtime_deleted',True)]:
            with self.subTest(field=field):
                old=self.value[field];self.value[field]=wrong;path,h=self.plan()
                with self.assertRaises(ValueError):retirement.validate_authorized_plan(self.ctx,path,h,'trace')
                self.value[field]=old

class BundleInventory(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.ctx=SimpleNamespace(cc=CC,candidate_root=self.root,runtime_binding={'candidate':'synthetic'})
        ref={role:{'path':str(self.root/'contexts'/role),'sha256':'a'*64} for role in ('context','native_receipt','process_terminal')}
        self.value={'schema':'rust-duty-windows-runtime-inputs/v1','binding':self.ctx.runtime_binding,'kind':'chunk','index':0,'stages':{r:copy.deepcopy(ref) for r in evidence.INPUT_ROLES['chunk']}}
    def tearDown(self):self.tmp.cleanup()
    def admit(self):
        rec=write(self.root/'contexts/inputs.json',self.value);return evidence.input_bundle(self.ctx,rec['path'],rec['sha256'],'chunk',0)
    def test_exact_nonempty_role_inventory(self):self.assertEqual(self.admit(),self.value)
    def test_wrong_schema_kind_index_binding_rejected(self):
        for field,wrong in [('schema','wrong'),('kind','focus'),('index',66),('binding',{})]:
            with self.subTest(field=field):
                old=self.value[field];self.value[field]=wrong
                with self.assertRaises(ValueError):self.admit()
                self.value[field]=old
    def test_empty_missing_extra_stages_rejected(self):
        old=self.value['stages']
        for stages in ({},{'source':old['source']},{**old,'extra':old['source']}):
            self.value['stages']=stages
            with self.assertRaises(ValueError):self.admit()
    def test_reference_extra_key_rejected(self):
        self.value['stages']['source']['test_only']=True
        with self.assertRaises(ValueError):self.admit()
    def test_retained_entry_does_not_accept_empty_bundle(self):
        self.value['stages']={};rec=write(self.root/'contexts/inputs.json',self.value)
        with self.assertRaises(ValueError):consumer.verify_native_retained(self.ctx,{'index':0,'inputs':rec,'input_envelopes':{}})

class SourceDescriptor(unittest.TestCase):
    def test_posix_descriptor_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);frames={'1.0':{'source_frame':1.0}}
            for kind,folder,ext in [('row','sample-rows','json'),('skin','skin-rows','npz')]:
                f=root/folder/('0000.'+ext);f.parent.mkdir();f.write_bytes(b'synthetic-only');frames['1.0'][kind+'_path']=f.relative_to(root).as_posix();frames['1.0'][kind+'_sha256']=p.sha(f)
            witness={'generated_source_sha256':'b'*64,'approved_source_sha256':CC.APPROVED_SHA,'rig_action':p.ACTION,'rig_action_fingerprint':p.ACTION_SHA,'camera_action':None,'camera_action_fingerprint':None,'source_rest_world':{str(i):[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]] for i in range(148)},'hierarchy':{str(i):None for i in range(148)},'topology':{s:{'vertices':v} for s,v in zip(p.SKINS,p.COUNTS)},'projection':{'type':'PERSP','ray_directions':[[0,0,1]]*4},'frames':frames}
            ctx=SimpleNamespace(cc=CC,pin=lambda r:SimpleNamespace(sha256='b'*64));path=root/'source-samples.json';write(path,witness)
            self.assertEqual(evidence.source_index(ctx,M,path,[1.0])[0],witness)
            for wrong in (str(PureWindowsPath('sample-rows/0000.json')),'../sample-rows/0000.json','sample-rows//0000.json'):
                witness['frames']['1.0']['row_path']=wrong;write(path,witness)
                with self.assertRaises(ValueError):evidence.source_index(ctx,M,path,[1.0])


class CompilerInputs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'source';self.target=self.root/'target';self.candidate=self.root/'candidate'
        self.source.mkdir();self.target.mkdir();self.candidate.mkdir();(self.source/'Cargo.toml').write_text('synthetic');(self.source/'main.rs').write_text('synthetic');self.sampler=self.target/'sample.exe';self.sampler.write_bytes(b'not-a-native-executable')
        self.metadata={'packages':[{'id':'pkg','manifest_path':str(self.source/'Cargo.toml'),'targets':[{'name':'sample','kind':['example'],'src_path':str(self.source/'main.rs')}]}],'resolve':{'nodes':[{'id':'pkg','dependencies':[]}]}}
        self.closures=[(self.source,rc.inventory(self.source,CC))];self.ctx=SimpleNamespace(cc=CC,candidate_root=self.candidate,root=lambda role:self.source)
        self.artifact={'reason':'compiler-artifact','package_id':'pkg','target':self.metadata['packages'][0]['targets'][0],'filenames':[str(self.sampler)],'executable':str(self.sampler)}
        self.out_dir=self.target/'build/pkg/out';self.out_dir.mkdir(parents=True);self.generated=self.out_dir/'generated.rs';self.generated.write_bytes(b'synthetic generated source')
        self.messages=self.candidate/'cargo.jsonl';self.messages.write_text('\n'.join(json.dumps(r) for r in [self.artifact,{'reason':'build-script-executed','out_dir':str(self.out_dir)},{'reason':'build-finished','success':True}])+'\n')
        self.build={'command':['synthetic cargo only'], 'source_tree_sha256':p.digest(self.closures[0][1]),'dependency_closure':{'synthetic':True},'sampler':rc.record(self.sampler),'build_process':write(self.candidate/'build-process.json',{'stdout':rc.record(self.messages)})}
        producer={'schema':'rust-duty-cargo-generated-inputs/v1','build_process':self.build['build_process'],'source_tree_sha256':self.build['source_tree_sha256'],'dependency_closure_sha256':p.digest(self.build['dependency_closure']),'out_dir':str(self.out_dir),'outputs':[rc.record(self.generated)]}
        self.producer_path=self.candidate/'generated-producer.json';producer_rec=write(self.producer_path,producer)
        self.dep=self.target/'sample.d';self.dep.write_text('out: '+str(self.source/'main.rs')+' '+str(self.generated)+'\n')
        self.report={'schema':'rust-duty-rust-compiler-input-closure/v1','command_sha256':p.digest(self.build['command']),'source_tree_sha256':self.build['source_tree_sha256'],'dependency_closure_sha256':p.digest(self.build['dependency_closure']),'cargo_messages':rc.record(self.messages),'invocations':[{'artifact_sha256':p.digest(self.artifact),'dep_info':rc.record(self.dep),'generated_inputs':[{'file':rc.record(self.generated),'producer':producer_rec}]}]}
    def tearDown(self):self.tmp.cleanup()
    def admit(self):
        self.build['compiler_inputs']=write(self.candidate/'compiler-inputs.json',self.report);return bc.verify(self.ctx,self.build,self.closures,self.metadata,self.target)
    def test_complete_synthetic_closure_validator_only(self):self.assertEqual(self.admit(),self.report)
    def test_unaccounted_generated_input_rejected(self):
        self.report['invocations'][0]['generated_inputs']=[]
        with self.assertRaises(ValueError):self.admit()
    def test_uninventoried_compiler_include_rejected(self):
        outside=self.root/'outside.rs';outside.write_text('outside');self.dep.write_text('out: '+str(self.source/'main.rs')+' '+str(outside)+'\n');self.report['invocations'][0]['dep_info']=rc.record(self.dep);self.report['invocations'][0]['generated_inputs']=[]
        with self.assertRaises(ValueError):self.admit()
    def test_wrong_out_dir_producer_rejected(self):
        producer=p.read(self.producer_path);producer['out_dir']=str(self.target);self.report['invocations'][0]['generated_inputs'][0]['producer']=write(self.producer_path,producer)
        with self.assertRaises(ValueError):self.admit()
    def test_wrong_build_process_producer_rejected(self):
        producer=p.read(self.producer_path);producer['build_process']=write(self.candidate/'other-build.json',{'stdout':rc.record(self.messages)});self.report['invocations'][0]['generated_inputs'][0]['producer']=write(self.producer_path,producer)
        with self.assertRaises(ValueError):self.admit()
    def test_crate_root_mandatory(self):
        self.dep.write_text('out: '+str(self.generated)+'\n');self.report['invocations'][0]['dep_info']=rc.record(self.dep)
        with self.assertRaises(ValueError):self.admit()
    def test_all_artifacts_covered(self):
        self.report['invocations']=[]
        with self.assertRaises(ValueError):self.admit()
    def test_sampler_must_be_actual_cargo_output(self):
        self.build['sampler']['path']=str(self.target/'foreign.exe')
        with self.assertRaises(ValueError):self.admit()


class StageIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.ctx=SimpleNamespace(cc=CC,candidate_root=self.root,binding={'candidate':'synthetic'},root=lambda role:self.root)
        context=write(self.root/'contexts/source.json',{'stage_id':'source-chunk-000'})
        native=write(self.root/'native/source-chunk-000/receipt.json',{'synthetic':True});terminal=write(self.root/'process/source-chunk-000/terminal.json',{'synthetic':True})
        self.ref={k:{q:v[q] for q in ('path','sha256')} for k,v in [('context',context),('native_receipt',native),('process_terminal',terminal)]}
        self.value={'schema':'rust-duty-windows-native-stage/v1','stage':'source-chunk','index':0,'context_file_sha256':context['sha256'],'binding':self.ctx.binding,'passed':True,'source_saved':False,'rendered':False,'cross_platform_float64_equality_proved':False,'runtime_equivalence_proved':False,'artistic_approval':False,'activation_authorized':False}
    def tearDown(self):self.tmp.cleanup()
    def admit(self):
        from unittest.mock import patch
        # API stand-in only tests consumer's additional identity boundary.
        with patch.object(evidence,'producer',return_value=SimpleNamespace(verify_stage=lambda *a:self.value)):
            return evidence.stage(self.ctx,self.ref,'source-chunk',0)
    def test_synthetic_identity_boundary(self):self.assertEqual(self.admit()[0],self.value)
    def test_wrong_stage_index_or_envelope_claim_rejected(self):
        for field,wrong in [('schema','wrong'),('stage','chunk-import'),('index',1),('passed',False),('rendered',True),('context_file_sha256','f'*64),('binding',{})]:
            with self.subTest(field=field):
                old=self.value[field];self.value[field]=wrong
                with self.assertRaises(ValueError):self.admit()
                self.value[field]=old
    def test_terminal_path_not_laundered(self):
        terminal=write(self.root/'process/foreign/terminal.json',{'synthetic':True});self.ref['process_terminal']={k:terminal[k] for k in ('path','sha256')}
        with self.assertRaises(ValueError):self.admit()
    def test_native_receipt_path_not_laundered(self):
        native=write(self.root/'native/foreign/receipt.json',{'synthetic':True});self.ref['native_receipt']={k:native[k] for k in ('path','sha256')}
        with self.assertRaises(ValueError):self.admit()

if __name__=='__main__':unittest.main(verbosity=2)
