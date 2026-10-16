"""Tiny synthetic source-only tests. No native/Windows/Rust proof is produced."""
import ast,copy,hashlib,json,math,os,struct,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pinned_math as p
import runtime_context as rc
import transport,evidence,consumer,retirement
ROOT=p.HERE.parent.parent
CC=p.context_module(p.HERE.parent/'windows-candidate-context-v1')
M=p.load(ROOT)

def valid_context(base):
    protected=base/'protected';private=base/'private';candidate=private/'session'/'candidates'/'candidate'
    files={}
    excluded={'baseline','original_delta','canonical','source_grid','reference_replay','reference_index','reference_equivalence','sampler','transport_review','transport_smoke','transport_smoke_summary'}
    fixed={'baseline':CC.BASE_SHA,'original_delta':CC.DELTA_SHA,'canonical':CC.CANONICAL_SHA,'source_grid':CC.GRID_SHA}
    for role in rc.FILES:
        path=(protected if role in excluded else candidate)/role
        if role in ('vra','vrs','vrm'):path=candidate/'runtime'/('asset.'+role)
        if role=='manifest':path=candidate/'runtime'/'manifest.json'
        if role.startswith('reference_'):path=protected/'reference'/role
        files[role]={'path':str(path),'sha256':fixed.get(role,hashlib.sha256(role.encode()).hexdigest())}
    host={'runner_id':'runner','run_id':'run','system':'Windows','release':'11','version':'10.0.1','machine':'AMD64','build_sha256':files['host_binding']['sha256']}
    return {'schema':rc.SCHEMA,'mode':CC.MODE,'candidate_id':'candidate','session_id':'session','private_root':str(private),'roots':{r:str(protected/r) for r in rc.ROOTS},'files':files,'host':host,'lineage':{'approved_source_sha256':CC.APPROVED_SHA,'source_package_pins_sha256':CC.SOURCE_PINS_SHA,'action_hashes':{r:p.ACTION_SHA for r in ('legacy','complete','metadata','auxiliary')},'static_state_sha256':'d'*64},'invariants':copy.deepcopy(CC.INVARIANTS),'dependencies':{'context_pins_sha256':p.CONTEXT_PINS_SHA,'consumer_pins_sha256':'c'*64,'producer_pins_sha256':'d'*64,'transport_pins_sha256':transport.V2_PINS_SHA,'runtime_environment_sha256':'e'*64}}

def context(value):
    path=Path(value['private_root'])/value['session_id']/'candidates'/value['candidate_id']/'contexts'/'runtime.json'
    return rc.RuntimeContext(value,CC,path)

def row(frame,index=None):
    v={'source_frame':frame,'time_seconds':(frame-1)/60,'errors':{k:0. for k in p.ERROR_KEYS},'per_source_skin_maxima_m':{s:0. for s in p.SKINS},'visible':[True,True,False],'actor_visibility_checks':3,'source_skin_observations':10234,'visible_source_rigid_observations':10,'canonical_bone_observations':72,'passed':True}
    if index is not None:v['global_sample_index']=index
    return v

class Identity(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.raw=valid_context(self.base)
    def tearDown(self):self.tmp.cleanup()
    def test_schema_only_valid(self):self.assertIs(context(self.raw).validate().raw,self.raw)
    def test_production_gate_requires_actual_dependencies(self):
        self.raw['dependencies']['transport_pins_sha256']='0'*64
        with self.assertRaises(ValueError):context(self.raw).require_production()
    def test_unknown_field(self):
        self.raw['test_only']=True
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_missing_role(self):
        del self.raw['files']['sampler']
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_old_source_laundering(self):
        self.raw['files']['generated_source']['sha256']=CC.APPROVED_SHA
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_old_elf_laundering(self):
        self.raw['files']['sampler']['sha256']=rc.OLD_ELF
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_mixed_candidate_role(self):
        self.raw['files']['actual_fbx']['path']=self.raw['files']['actual_fbx']['path'].replace('/candidate/','/other/')
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_mixed_session(self):
        self.raw['files']['generated_source']['path']=self.raw['files']['generated_source']['path'].replace('/session/','/other/')
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_role_alias(self):
        self.raw['files']['actual_fbx']['path']=self.raw['files']['vra']['path']
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_hardlink_alias(self):
        a=Path(self.raw['files']['generated_source']['path']);b=Path(self.raw['files']['actual_fbx']['path']);a.parent.mkdir(parents=True);a.write_bytes(b'x');os.link(a,b)
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_symlink_component(self):
        a=Path(self.raw['files']['generated_source']['path']);a.parent.mkdir(parents=True);a.symlink_to(self.base/'absent')
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_threshold_override(self):
        self.raw['invariants']['matrix_position_strict_max']=.001
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_partial_grid_count_override(self):
        self.raw['invariants']['source_samples']=64
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_bool_count_override(self):
        self.raw['invariants']['actors']=True
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_context_hash_changes_build_or_asset(self):
        a=context(self.raw).context_sha256;self.raw['files']['sampler']['sha256']='f'*64;self.assertNotEqual(a,context(self.raw).context_sha256)
    def test_host_linux_rejected(self):
        self.raw['host']['system']='Linux'
        with self.assertRaises(ValueError):context(self.raw).validate()
    def test_current_host_not_claimed_by_schema(self):
        with self.assertRaises(ValueError):context(self.raw).host.require_current_host()
    def test_missing_payloads_not_accepted(self):
        with self.assertRaises(ValueError):context(self.raw).verify_files()

class Math(unittest.TestCase):
    def test_extractions_exact_source_and_ast(self):
        self.assertIsNotNone(M.Checker);self.assertIsNotNone(M.FrozenMap);self.assertIsNotNone(M.scan_vra)
    def test_no_old_identity_global(self):
        self.assertNotIn('SOURCE_SHA',M.__dict__);self.assertNotIn('SAMPLER_SHA',M.__dict__)
    def test_frozen_bidirectional_mapping(self):
        a=np.array([[0.,0,0],[1.,0,0],[0.,0,0]]);b=np.array([[1.,0,0],[0.,0,0]])
        frozen=M.FrozenMap.establish(a,b);self.assertEqual(frozen.value['forward'],[1,0,1]);self.assertEqual(frozen.value['reverse'],[1,0]);self.assertEqual(frozen.error(a,b),0.)
    def test_frozen_mapping_no_rematch(self):
        a=np.array([[0.,0,0],[1.,0,0]]);f=M.FrozenMap.establish(a,a)
        self.assertGreater(f.error(a[::-1],a),.9)
    def test_frame1_only_mapping(self):
        with self.assertRaises(ValueError):M.FrozenMap({'kind':'frame1-bidirectional','frame':2})
    def test_mapping_strict_threshold(self):
        with self.assertRaises(ValueError):M.FrozenMap({'kind':'frame1-bidirectional','frame':1,'actual_count':1,'expected_count':1,'forward':[0],'reverse':[0],'initial_error_m':1e-4})
    def test_summary_same_maxima(self):
        r=[row(1.),row(2.)];r[1]['errors']['skin_world_m']=.00009
        x=M.summarize(r);self.assertEqual(x['maxima']['skin_world_m'],.00009);self.assertEqual(x['worst']['skin_world_m']['source_frame'],2.);self.assertEqual(x['skin_vertex_observations'],20468)
    def test_exact_threshold_not_accepted(self):
        r=row(1.);r['errors']['skin_world_m']=1e-4
        with self.assertRaises(ValueError):M.summarize([r])
    def test_nonfinite_not_accepted(self):
        r=row(1.);r['errors']['skin_world_m']=float('nan')
        with self.assertRaises(ValueError):M.summarize([r])
    def test_per_skin_threshold(self):
        r=row(1.);r['per_source_skin_maxima_m'][p.SKINS[1]]=1e-4
        with self.assertRaises(ValueError):M.summarize([r])
    def test_skin_count_not_weakened(self):
        r=row(1.);r['source_skin_observations']=1
        with self.assertRaises(ValueError):M.summarize([r])
    def test_canonical_count_not_weakened(self):
        r=row(1.);r['canonical_bone_observations']=71
        with self.assertRaises(ValueError):M.summarize([r])
    def test_focus_nine_four_offkeys(self):
        self.assertEqual(len(p.FOCUS),9);self.assertEqual([f for f in p.FOCUS if f*256!=int(f*256)],p.FOCUS[1::2]);self.assertEqual(M.summarize([row(f) for f in p.FOCUS])['skin_vertex_observations'],92106)
    def test_partial_runtime_grid(self):
        with self.assertRaises(ValueError):M.validate_runtime_times([0.0])
    def test_real_fixed_grid(self):
        path=ROOT/'recovery/onehand-v6-integration-handoff/dense-times.json';p.pin(path,p.GRID_SHA);self.assertEqual(len(p.read(path)),4240)
    def test_reordered_runtime_records(self):
        with self.assertRaises(ValueError):consumer.validate_records(M,[row(2.),row(1.)],[1.,2.])
    def test_ray_boundary_strict(self):
        v={'payload':{'passed':True,'source_sha256':'a'*64,'fbx_sha256':'b'*64,'samples':9,'sample_frames':p.FOCUS,'skin_vertex_samples':92106,'source_total_bones_including_helpers':148,'runtime_support_verified':False,'independent_grid_sha256':p.GRID_SHA,'off_key_source_frames':p.FOCUS[1::2],'checks':{k:True for k in p.FBX_CHECKS},'maxima':{k:0. for k in p.FBX_KEYS},'camera_projection_ray_error':1e-5}}
        ctx=SimpleNamespace(pin=lambda r:SimpleNamespace(sha256='a'*64 if r=='generated_source' else 'b'*64))
        with self.assertRaisesRegex(p.Error,'ray strict'):evidence.source_fbx(ctx,M,v,p.FOCUS)

class Stream(unittest.TestCase):
    def test_exact_fake_stream(self):self.assertEqual(transport.exact_rows(iter([{'i':0},{'i':1}]),2,lambda i,r:r['i']),[0,1])
    def test_early_fake_stream(self):
        with self.assertRaisesRegex(p.Error,'ended early'):transport.exact_rows(iter([{}]),2,lambda i,r:r)
    def test_extra_fake_stream(self):
        with self.assertRaisesRegex(p.Error,'extra'):transport.exact_rows(iter([{},{}]),1,lambda i,r:r)
    def test_nonobject_fake_stream(self):
        with self.assertRaises(ValueError):transport.exact_rows(iter([[]]),1,lambda i,r:r)
    def test_callback_error_propagates(self):
        def fail(i,r):raise RuntimeError('consumer failed')
        with self.assertRaisesRegex(RuntimeError,'consumer failed'):transport.exact_rows(iter([{}]),1,fail)
    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):p.loads('{"x":1,"x":2}')
    def test_nonfinite_json_rejected(self):
        with self.assertRaises(ValueError):p.loads('{"x":NaN}')
    def test_leaf_exact_argv(self):
        ctx=SimpleNamespace(pin=lambda r:SimpleNamespace(path=Path('/sampler.exe' if r=='sampler' else '/asset.vra')))
        self.assertEqual(transport.command(ctx,[1.,96.]),['/sampler.exe','/asset.vra',p.ACTION,'0.0',repr(95/60),'--clamp'])
    def test_time_reorder_rejected(self):
        with self.assertRaises(ValueError):transport.command(None,[2.,1.])
    def test_v2_integrity_only(self):
        mod=transport.load(p.HERE.parent/'windows-process-adapter-v2');limits=transport.limits(mod,64);self.assertEqual(limits.rss_bytes,3*1024**3);self.assertEqual(limits.deadline_seconds,1800);self.assertEqual(limits.sample_seconds,.2);self.assertEqual(limits.max_rows,64);self.assertEqual(limits.max_row_bytes,16*1024**2)

class Aggregate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.out=Path(cls.tmp.name);(cls.out/'session.json').write_bytes(b'session')
        cls.grid=p.read(ROOT/'recovery/onehand-v6-integration-handoff/dense-times.json');cls.ctx=SimpleNamespace(output=cls.out,runtime_binding={'candidate':'synthetic-only'},grid=lambda:cls.grid)
        cls.session={'correspondence_sha256':'c'*64};cls.reports=[]
        for index in range(67):
            frames=cls.grid[index*64:(index+1)*64];rows=[row(f,index*64+i) for i,f in enumerate(frames)]
            cls.reports.append({'schema':consumer.SCHEMA,'kind':'chunk','binding':cls.ctx.runtime_binding,'passed':True,'activation_authorized':False,'index':index,'source_frames':frames,'samples':len(frames),'correspondence_sha256':'c'*64,'thresholds':p.THRESHOLDS,'full_grid_parity':False,'session':{'sha256':p.sha(cls.out/'session.json')},'focus':{'sha256':'f'*64},'records':rows,'summary':M.summarize(rows),'source_fbx':{'maxima':{k:0. for k in p.FBX_KEYS},'camera_projection_ray_error':0.}})
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_all4240_67_counts(self):
        result=consumer.aggregate_records(self.ctx,M,self.reports,self.session,'f'*64);self.assertEqual(result['summary']['skin_vertex_observations'],43392160);self.assertEqual(result['chunks'],67);self.assertEqual(result['source_fbx_bone_observations'],627520)
    def test_partial66_rejected(self):
        with self.assertRaises(ValueError):consumer.aggregate_records(self.ctx,M,self.reports[:-1],self.session,'f'*64)
    def test_last_chunk16(self):self.assertEqual(self.reports[-1]['samples'],16)
    def test_mixed_focus_rejected(self):
        reports=copy.deepcopy(self.reports);reports[20]['focus']['sha256']='a'*64
        with self.assertRaises(ValueError):consumer.aggregate_records(self.ctx,M,reports,self.session,'f'*64)
    def test_mixed_candidate_rejected(self):
        reports=copy.deepcopy(self.reports);reports[2]['binding']={'candidate':'other'}
        with self.assertRaises(ValueError):consumer.aggregate_records(self.ctx,M,reports,self.session,'f'*64)
    def test_duplicate_chunk_rejected(self):
        reports=self.reports.copy();reports[2]=reports[1]
        with self.assertRaises(ValueError):consumer.aggregate_records(self.ctx,M,reports,self.session,'f'*64)
    def test_focus_not_counted(self):
        reports=self.reports+[self.reports[0]]
        with self.assertRaises(ValueError):consumer.aggregate_records(self.ctx,M,reports,self.session,'f'*64)
    def test_aggregate_ray_threshold(self):
        reports=copy.deepcopy(self.reports);reports[3]['source_fbx']['camera_projection_ray_error']=1e-5
        with self.assertRaises(ValueError):consumer.aggregate_records(self.ctx,M,reports,self.session,'f'*64)

class Closure(unittest.TestCase):
    def test_complete_inventory_detects_extra_source(self):
        with tempfile.TemporaryDirectory() as x:
            root=Path(x);(root/'Cargo.toml').write_text('test');a=rc.inventory(root,CC);(root/'build.rs').write_text('changed');self.assertNotEqual(a,rc.inventory(root,CC))
    def test_inventory_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as x:
            root=Path(x);(root/'source.rs').symlink_to('/etc/hosts')
            with self.assertRaises(ValueError):rc.inventory(root,CC)
    def test_pe_rejects_elf(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'\x7fELF'+b'\0'*100);f.flush()
            with self.assertRaises(ValueError):rc.pe_x64(f.name)
    def test_pe_synthetic_header_only_not_proof(self):
        with tempfile.NamedTemporaryFile() as f:
            data=bytearray(90);data[:2]=b'MZ';struct.pack_into('<I',data,60,64);data[64:68]=b'PE\0\0';struct.pack_into('<H',data,68,0x8664);struct.pack_into('<H',data,86,2);struct.pack_into('<H',data,88,0x20b);f.write(data);f.flush();self.assertEqual(rc.pe_x64(f.name)['format'],'PE32+')
    def test_exact_available_windows_transport_smoke(self):
        roots={'transport_review':p.HERE.parent/'windows-process-review-v2/REVIEW_FREEZE.json','transport_smoke':p.HERE.parent/'windows-smoke-38871908839/independent-audit.json','transport_smoke_summary':p.HERE.parent/'windows-smoke-38871908839/files/test-summary.json'}
        ctx=SimpleNamespace(cc=CC,pin=lambda role:CC.FilePin(role,roots[role],p.sha(roots[role])))
        self.assertEqual(rc.verify_transport_smoke(ctx)['native_windows_test_count'],4)
    def test_no_process_or_global_mutation_in_math_extraction(self):
        fragments=p.read(p.HERE/'MATH_FRAGMENTS.json')
        names={name for group in fragments.values() for name in group['definitions']};self.assertFalse({'probe','helper','load_candidate','ParityChecker','runtime_camera','validate_control'}&names)

class Retirement(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();base=Path(self.tmp.name);self.root=base/'candidate';self.out=self.root/'runtime-proof';self.out.mkdir(parents=True);rawroot=self.root/'native'/'chunk0'
        self.ctx=SimpleNamespace(cc=CC,candidate_root=self.root,output=self.out,runtime_binding={'candidate':'synthetic-only'})
        self.files=[]
        for folder,name in [('sample-rows','0000.json'),('skin-rows','0000.npz')]:
            path=rawroot/folder/name;path.parent.mkdir(parents=True);path.write_bytes(b'synthetic');self.files.append(rc.record(path))
        def fixture(path,value):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return rc.record(path)
        self.report={'schema':consumer.SCHEMA,'kind':'chunk','index':0,'activation_authorized':False,'passed':True,'binding':self.ctx.runtime_binding,'raw_files':self.files,'source_frames':[1.]}
        self.report['source_index']=fixture(rawroot/'source-samples.json',{'frames':{'1.':{'source_frame':1.}}})
        for key in ('inputs','session','focus'):self.report[key]=fixture(self.out/(key+'.json'),{'synthetic':key})
        self.report['process']={'terminal':fixture(self.out/'terminal.json',{'synthetic':True})}
        self.receipt=self.out/'chunk-000.json';fixture(self.receipt,self.report)
        start=fixture(self.out/'retirement-plan-000.started.json',{'schema':consumer.SCHEMA,'kind':'retirement-plan','binding':self.ctx.runtime_binding,'passed':False,'started_unix':1.})
        self.value={'schema':'rust-duty-windows-raw-retirement-plan/v1','binding':self.ctx.runtime_binding,'index':0,'passed':False,'plan_only':True,'independently_reconsumed':True,'runtime_receipt_sha256':p.sha(self.receipt),'retired_files':self.files,'preserved_files':retirement.preserved_records(self.ctx,self.report,0),'started_receipt':start,**retirement.FLAGS}
    def tearDown(self):self.tmp.cleanup()
    def plan(self):
        path=self.out/'retirement-plan-000.json';path.write_text(json.dumps(self.value));return path,p.sha(path)
    def test_validation_is_nonmutating(self):
        path,h=self.plan();retirement.validate_authorized_plan(self.ctx,path,h,'synthetic-test-reference');self.assertTrue(all(Path(r['path']).exists() for r in self.files))
    def test_missing_authorization_reference_rejected(self):
        path,h=self.plan()
        with self.assertRaises(ValueError):retirement.validate_authorized_plan(self.ctx,path,h,'')
    def test_failed_chunk_cannot_retire(self):
        self.report['passed']=False;self.receipt.write_text(json.dumps(self.report));self.value['runtime_receipt_sha256']=p.sha(self.receipt);path,h=self.plan()
        with self.assertRaises(ValueError):retirement.validate_authorized_plan(self.ctx,path,h,'test')
    def test_changed_plan_hash_rejected(self):
        path,h=self.plan();path.write_text('{}')
        with self.assertRaises(ValueError):retirement.validate_authorized_plan(self.ctx,path,h,'test')
    def test_foreign_raw_injection_rejected(self):
        self.value['retired_files']=self.files+[rc.record(self.receipt)];path,h=self.plan()
        with self.assertRaises(ValueError):retirement.validate_authorized_plan(self.ctx,path,h,'test')
    def test_partial_missing_raw_rejected(self):
        Path(self.files[0]['path']).unlink();path,h=self.plan()
        with self.assertRaises(ValueError):retirement.validate_authorized_plan(self.ctx,path,h,'test')
    def test_hardlinked_raw_rejected(self):
        os.link(self.files[0]['path'],self.root/'alias');path,h=self.plan()
        with self.assertRaises(ValueError):retirement.validate_authorized_plan(self.ctx,path,h,'test')
    def test_changed_raw_rejected(self):
        Path(self.files[1]['path']).write_bytes(b'changed');path,h=self.plan()
        with self.assertRaises(ValueError):retirement.validate_authorized_plan(self.ctx,path,h,'test')

# Run the eight unchanged small original scanner tests. Explicitly omit the
# original real-private-asset/large-decoder test; no private fixture is read.
_original=ROOT/'onehand-runtime-20261016-r2/runtime-parity/test_bounded_vra.py'
p.pin(_original,p.read(p.HERE/'ORIGINAL_PINS.json')['onehand-runtime-20261016-r2/runtime-parity/test_bounded_vra.py'])
_tree=ast.parse(_original.read_text());_body=[]
for _node in _tree.body:
    if isinstance(_node,ast.FunctionDef) and _node.name in ('fixture','wrap','mutate'):_body.append(_node)
    elif isinstance(_node,ast.ClassDef) and _node.name=='BoundedVraTests':
        _node.body=[n for n in _node.body if not isinstance(n,ast.FunctionDef) or n.name!='test_old_real_vra_summary_equivalence_if_memory_allows'];_body.append(_node)
_ns={'__name__':__name__,'copy':copy,'json':json,'Path':Path,'struct':struct,'tempfile':tempfile,'unittest':unittest,'zlib':__import__('zlib'),'c':SimpleNamespace(G=M.G,HERE=p.HERE),'b':M,'D':M.G.vrview}
exec(compile(ast.Module(body=_body,type_ignores=[]),str(_original),'exec'),_ns)
BoundedVraTests=_ns['BoundedVraTests']

if __name__=='__main__':unittest.main()
