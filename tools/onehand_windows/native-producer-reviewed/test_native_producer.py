"""Small CPU fixtures; no Blender, subprocess, native job, build or private asset."""
import ast,bisect,copy,hashlib,json,math,os,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import extract_helpers,pinned_code,stage_context,admission,planner,native_stages,transport_binding
HERE=Path(__file__).absolute().parent;ROOT=HERE.parents[1];CONTEXT=ROOT/'onehand-runtime-20261016/windows-candidate-context-v1'
cc=pinned_code.load_context(CONTEXT)

def fixture(root,stage='export',index=None):
    private=root/'private';candidate=private/'session1/candidates/candidate1'
    files={r:{'path':str(candidate/'inputs'/r),'sha256':'a'*64} for r in stage_context.COMMON|stage_context.INPUTS[stage]}
    for r in ('baseline','original_delta','canonical','source_grid','reference_replay','reference_index','reference_equivalence','transport_review','transport_smoke','transport_smoke_summary'):files[r]['path']=str(root/'protected'/r)
    for r in ('reference_replay','reference_index','reference_equivalence'):files[r]['path']=str(root/'reference'/r)
    for r,v in {'baseline':cc.BASE_SHA,'original_delta':cc.DELTA_SHA,'canonical':cc.CANONICAL_SHA,'source_grid':cc.GRID_SHA}.items():files[r]['sha256']=v
    files['host_binding']['sha256']='b'*64
    roots={r:str(root/r) for r in stage_context.ROOTS};roots['context_package']=str(CONTEXT)
    d={'schema':stage_context.SCHEMA,'mode':cc.MODE,'candidate_id':'candidate1','session_id':'session1','private_root':str(private),'roots':roots,'files':files,
       'host':{'runner_id':'runner1','run_id':'run1','system':'Windows','release':'10','version':'10.0.synthetic','machine':'AMD64','build_sha256':'b'*64},
       'lineage':{'approved_source_sha256':cc.APPROVED_SHA,'source_package_pins_sha256':cc.SOURCE_PINS_SHA,'action_hashes':{k:'a'*64 for k in ('legacy','complete','metadata','auxiliary')},'static_state_sha256':'a'*64},
       'invariants':copy.deepcopy(cc.INVARIANTS),'stage':stage,'index':index,'stage_id':'stage1',
       'dependencies':{'context_pins_sha256':pinned_code.CONTEXT_PINS_SHA,'producer_pins_sha256':'c'*64,'transport_pins_sha256':transport_binding.TRANSPORT_PINS_SHA,'transport_review_sha256':transport_binding.REVIEW_ACCEPTANCE_SHA}}
    return stage_context.StageContext(d,cc,candidate/'contexts/stage1.json')

def math_env():
    e={'np':np,'math':math,'bisect':bisect,'hashlib':hashlib,'json':json,'struct':struct,'require':pinned_code.require,'KEY_CAP':4096}
    for name in ('array_hash','native_grid','selection','validate_arrays','linear_value'):pinned_code.execute(name,e)
    return e

class SourceEquivalence(unittest.TestCase):
    def test_exact_34_fragments(self):self.assertEqual(extract_helpers.extract(ROOT),pinned_code.fragments())
    def test_original_pins(self):self.assertTrue(pinned_code.verify_originals(ROOT)['files'])
    def test_context_freeze(self):self.assertEqual(pinned_code.file_sha(CONTEXT/'PINS.json'),pinned_code.CONTEXT_PINS_SHA)
    def test_all_compile(self):
        for name in pinned_code.fragments()['fragments']:compile(pinned_code.fragment_tree(name),name,'exec')
    def test_only_three_relocations(self):
        d=pinned_code.fragments()['fragments'];changed=[]
        for n,r in d.items():
            if ast.dump(ast.parse(r['source']),include_attributes=False)!=ast.dump(pinned_code.fragment_tree(n),include_attributes=False):changed.append(n)
        self.assertEqual(set(changed),{'import_window','import_exact_grid'});self.assertEqual(sum(r['remove_legacy_search_path'] for r in d.values()),2);self.assertEqual(sum(r['replace_recipe_identity'] for r in d.values()),1)
    def test_no_historical_source_identity(self):
        for name in pinned_code.fragments()['fragments']:self.assertNotIn('SOURCE_SHA',{n.id for n in ast.walk(pinned_code.fragment_tree(name)) if isinstance(n,ast.Name)})
    def test_full_history_before_storage(self):
        s=pinned_code.fragments()['fragments']['import_window']['source'];self.assertLess(s.index('converted = imp._convert_fbx_time_to_blender_time'),s.index('values[indices]'));self.assertIn('full_transform_sequence_preserved_before_selection',s)
    def test_exact_export_settings(self):
        t=ast.parse((ROOT/'onehand-runtime-20261016-r2/native-dense/dense_contract.py').read_bytes());n=next(n for n in t.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='SETTINGS' for x in n.targets));e={};exec(compile(ast.Module(body=[n],type_ignores=[]),'settings','exec'),e);self.assertEqual(e['SETTINGS'],native_stages.SETTINGS)
    def test_no_bpy_planning(self):self.assertNotIn('bpy',sys.modules)
    def test_no_native_save_render_calls(self):
        for n in ('native_entry.py','native_stages.py','launch_stage.py'):
            s=(HERE/n).read_text();self.assertNotIn('bpy.ops.wm.save',s);self.assertNotIn('bpy.ops.render',s);self.assertNotIn('subprocess.',s)
    def test_all_source_parses(self):
        for p in HERE.glob('*.py'):ast.parse(p.read_bytes(),filename=str(p))

class WindowCpu(unittest.TestCase):
    def setUp(self):self.e=math_env()
    def test_exact_12_windows_2051_max(self):
        counts=[];ranges=[]
        for i in range(12):
            lo=i*2048;hi=min(lo+2048,24320);p=self.e['selection']([1+k/256 for k in range(lo,hi+1)],256);counts.append(p['retained_key_count']);ranges.append((lo,hi));self.assertEqual(p['full_key_count'],24321)
        self.assertEqual(max(counts),2051);self.assertEqual(ranges[-1][1],24320);self.assertTrue(all(a[1]==b[0] for a,b in zip(ranges,ranges[1:])))
    def test_focus_nine_four_offkeys(self):
        f=list(cc.FOCUS);self.assertEqual(len(f),9);self.assertEqual(sum(x*256!=int(x*256) for x in f),4);self.assertTrue(all(x in self.e['selection'](f,256)['allowed_evaluation_frames'] for x in f))
    def test_exact4240_67chunks(self):
        p=ROOT/'recovery/onehand-v6-integration-handoff/dense-times.json';self.assertEqual(pinned_code.file_sha(p),cc.GRID_SHA);f=json.loads(p.read_text());self.assertEqual(len(f),4240);chunks=[f[i:i+64] for i in range(0,len(f),64)];self.assertEqual(len(chunks),67);self.assertEqual(sum(chunks,[]),f)
    def test_all_raw_keys64_and256(self):
        for n in (64,256):
            f=self.e['native_grid'](n).astype(np.float64);t=np.rint(f*46186158000/60).astype(np.int64);self.assertEqual(self.e['validate_arrays'](t,np.zeros(len(t)),n)['key_count'],95*n+1)
    def test_no_slicing(self):
        with self.assertRaises(ValueError):self.e['validate_arrays'](np.arange(2),np.zeros(2),256)
    def test_bad_flags(self):
        n=64;f=self.e['native_grid'](n).astype(np.float64);t=np.rint(f*46186158000/60).astype(np.int64)
        with self.assertRaises(ValueError):self.e['validate_arrays'](t,np.zeros(len(t)),n,[0])
    def test_nonfinite(self):
        n=64;f=self.e['native_grid'](n).astype(np.float64);t=np.rint(f*46186158000/60).astype(np.int64);v=np.zeros(len(t));v[-1]=np.nan
        with self.assertRaises(ValueError):self.e['validate_arrays'](t,v,n)
    def test_clock_order_rejects(self):
        for f,n in [([2,1],256),([1,1],256),([0,1],256),([1,96.1],256),([1,96],128)]:
            with self.assertRaises(ValueError):self.e['selection'](f,n)
    def test_linear_math(self):self.assertEqual(self.e['linear_value']([1,2],[0,10],1.25),2.5)

class ContextCpu(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory(dir=HERE);self.root=Path(self.tmp.name);self.ctx=fixture(self.root)
    def tearDown(self):self.tmp.cleanup()
    def reject(self,change):
        d=copy.deepcopy(self.ctx.raw);change(d)
        with self.assertRaises(ValueError):stage_context.StageContext(d,cc,self.ctx.path).validate()
    def test_all_stage_roles(self):
        for s in stage_context.INPUTS:fixture(self.root,s,0 if s in ('source-chunk','rigid-chunk','chunk-import','block') else None).validate()
    def test_unknown_field(self):self.reject(lambda d:d.update(skip=True))
    def test_wrong_lineage(self):self.reject(lambda d:d['lineage'].update(approved_source_sha256='0'*64))
    def test_generated_laundering(self):self.reject(lambda d:d['files']['generated_source'].update(sha256=cc.APPROVED_SHA))
    def test_wrong_clock(self):self.reject(lambda d:d['invariants'].update(subdivisions=64))
    def test_bool_count(self):self.reject(lambda d:d['invariants'].update(actors=True))
    def test_extra_role(self):self.reject(lambda d:d['files'].update(approved=d['files']['generated_source']))
    def test_missing_role(self):self.reject(lambda d:d['files'].pop('authored_admission'))
    def test_alias(self):self.reject(lambda d:d['files']['generated_source'].update(path=d['files']['target_replay']['path']))
    def test_foreign_candidate(self):self.reject(lambda d:d['files']['generated_source'].update(path=str(self.root/'private/foreign/generated.blend')))
    def test_private_overlap(self):self.reject(lambda d:d['roots'].update(audited_source=d['private_root']))
    def test_bad_hash(self):self.reject(lambda d:d['files']['generated_source'].update(sha256='A'*64))
    def test_reserved_path(self):self.reject(lambda d:d['files']['generated_source'].update(path=d['files']['generated_source']['path']+'/CON'))
    def test_ads(self):self.reject(lambda d:d['files']['generated_source'].update(path=d['files']['generated_source']['path']+':data'))
    def test_foreign_context(self):
        with self.assertRaises(ValueError):stage_context.StageContext(self.ctx.raw,cc,self.root/'context.json').validate()
    def test_read_existing_output(self):
        self.ctx.output.mkdir(parents=True);self.ctx.transport_output.mkdir(parents=True);self.ctx.validate()
        with self.assertRaises(ValueError):self.ctx.validate(fresh=True)
    def test_symlink(self):
        p=self.ctx.pin('generated_source').path;p.parent.mkdir(parents=True);t=self.root/'target';t.write_text('x');p.symlink_to(t)
        with self.assertRaises(ValueError):self.ctx.validate()
    def test_hardlink(self):
        p=self.ctx.pin('generated_source').path;p.parent.mkdir(parents=True);p.write_text('x');os.link(p,self.ctx.pin('target_replay').path)
        with self.assertRaises(ValueError):self.ctx.validate()
    def test_block_index(self):
        for i in (-1,12,True,None):
            with self.assertRaises(ValueError):fixture(self.root,'block',i).validate()
    def test_distinct_binding(self):self.assertEqual(self.ctx.binding['generated_source_sha256'],'a'*64);self.assertEqual(self.ctx.binding['approved_source_sha256'],cc.APPROVED_SHA)
    def test_actual_host_rejects_linux(self):
        with self.assertRaises(ValueError):self.ctx.host.require_current_host()
    def test_fixture_no_real_inputs(self):
        with self.assertRaises((ValueError,FileNotFoundError)):self.ctx.verify_files()
    def test_plan_inert_exact_argv(self):
        h={'tools':{'blender':{'path':str(self.root/'Blender/blender.exe'),'sha256':'d'*64}}};p=self.ctx.pin('host_binding').path;p.parent.mkdir(parents=True);p.write_text(json.dumps(h));self.ctx.raw['files']['host_binding']['sha256']=pinned_code.file_sha(p);self.ctx.path.parent.mkdir();self.ctx.path.write_text(json.dumps(self.ctx.raw));v=planner.plan(self.ctx)
        self.assertFalse(v['will_launch']);self.assertEqual(v['argv'][1:9],['--background','--factory-startup','--disable-autoexec','--threads','1','--python-exit-code','1','--python']);self.assertNotIn('bpy',sys.modules)

class RigidPacking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.m=pinned_code.isolated_module('rigid_bytes',ROOT/'onehand-runtime-20261016-r2/native-rigid-v2/rigid_bytes.py',{})
    def test_signed_zero(self):
        v=np.array([[0.,0.,0.],[1,0,0],[0,1,0]]);a=self.m.canonical_buffers(v,[0],[3],[0,1,2]);v[0,0]=-0.;self.assertNotEqual(a,self.m.canonical_buffers(v,[0],[3],[0,1,2]))
    def test_full_topology(self):
        a=self.m.canonical_buffers([[0,0,0],[1,0,0],[0,1,0]],[0],[3],[0,1,2]);self.assertEqual(a.polygons(),[[0,1,2]]);self.assertEqual(len(a.vertices),72)
    def test_bad_topology(self):
        with self.assertRaises(ValueError):self.m.canonical_buffers([[0,0,0],[1,0,0],[0,1,0]],[0],[3],[0,1,3])
    def test_packing_fragment_exact(self):
        s=pinned_code.fragments()['fragments']['runtime_block']['source'];self.assertIn("struct.pack('<f', tick / 15360)",s);self.assertIn('vrview.validate_transform',s);self.assertIn('bytes(visibility)',s)

class AdmissionCpu(unittest.TestCase):
    def test_v2_pin(self):self.assertEqual(pinned_code.file_sha(ROOT/'onehand-runtime-20261016/windows-process-adapter-v2/PINS.json'),transport_binding.TRANSPORT_PINS_SHA)
    def test_source_review_no_windows_claim(self):
        p=ROOT/'onehand-runtime-20261016/windows-process-review-v2/REVIEW_FREEZE.json';self.assertEqual(pinned_code.file_sha(p),transport_binding.REVIEW_ACCEPTANCE_SHA);d=json.loads(p.read_text());self.assertFalse(d['actual_windows_executed']);self.assertFalse(d['production_animation_admitted'])
    def test_focus_strict_thresholds(self):
        class C:
            stage='focus-import'
            def frames(self):return list(cc.FOCUS)
        p={'samples':9,'sample_frames':list(cc.FOCUS),'skin_vertex_samples':92106,'source_total_bones_including_helpers':148,'checks':{n:True for n in admission.FOCUS_CHECKS},'maxima':{n:0. for n in native_stages.MAXIMA},'camera_projection_ray_error':0.,'off_key_source_frames':[f for f in cc.FOCUS if f*256!=int(f*256)]}
        admission.validate_payload(C(),p)
        for v in (1e-4,float('nan'),float('inf')):
            q=copy.deepcopy(p);q['maxima']['skin_world_m']=v
            with self.assertRaises(ValueError):admission.validate_payload(C(),q)
    def test_exact_check_inventory(self):self.assertEqual(len(admission.FOCUS_CHECKS),23)


class GateCpu(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory(dir=HERE);self.root=Path(self.tmp.name);self.ctx=fixture(self.root,'geometry')
    def tearDown(self):self.tmp.cleanup()
    def gate(self,kind,results):
        role={'control':'control_gate','focus':'focus_gate','conversion':'conversion_gate'}[kind]
        binding=dict(self.ctx.binding)
        if kind=='control':binding.pop('actual_fbx_sha256')
        data={'schema':'rust-duty-windows-native-gate/v1','kind':kind,'binding':binding,'stages':[{'fake':i} for i in range(len(results))]}
        p=self.ctx.candidate_root/(kind+'.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data))
        self.ctx.raw['files'][role]={'path':str(p),'sha256':pinned_code.file_sha(p)}
        with patch.object(admission,'verify_reference',side_effect=results):return admission._verify_context_gate(self.ctx,role)
    def control(self):
        b=dict(self.ctx.binding);b.pop('actual_fbx_sha256')
        return [{'stage':'control-export','binding':b,'output_files':{'animation.fbx':{'sha256':'f'*64}}},
                {'stage':'control-full','binding':b,'output_files':{'full-control.json':{'sha256':'e'*64}},'payload':{'fbx_sha256':'f'*64}},
                {'stage':'control-bounded','binding':b,'payload':{'full_import_control_sha256':'e'*64,'fbx_sha256':'f'*64}}]
    def focus(self):
        b=self.ctx.binding;old=dict(b);old.pop('actual_fbx_sha256')
        return [{'stage':'export','binding':old,'output_files':{'animation.fbx':{'sha256':'a'*64}}},
                {'stage':'source-focus','binding':b,'output_files':{'source-samples.json':{'sha256':'e'*64}}},
                {'stage':'focus-import','binding':b,'payload':{'source_oracle_sha256':'e'*64}}]
    def test_exact_control_links(self):self.assertEqual(self.gate('control',self.control())['kind'],'control')
    def test_wrong_full_oracle_rejected(self):
        r=self.control();r[2]['payload']['full_import_control_sha256']='d'*64
        with self.assertRaises(ValueError):self.gate('control',r)
    def test_wrong_control_fbx_rejected(self):
        r=self.control();r[2]['payload']['fbx_sha256']='d'*64
        with self.assertRaises(ValueError):self.gate('control',r)
    def test_export_earlier_binding_is_explicit(self):self.assertEqual(self.gate('focus',self.focus())['binding']['actual_fbx_sha256'],'a'*64)
    def test_wrong_export_fbx_rejected(self):
        r=self.focus();r[0]['output_files']['animation.fbx']['sha256']='d'*64
        with self.assertRaises(ValueError):self.gate('focus',r)
    def test_wrong_focus_oracle_rejected(self):
        r=self.focus();r[2]['payload']['source_oracle_sha256']='d'*64
        with self.assertRaises(ValueError):self.gate('focus',r)
    def test_mixed_candidate_rejected(self):
        r=self.focus();r[1]['binding']={**r[1]['binding'],'candidate_id':'foreign'}
        with self.assertRaises(ValueError):self.gate('focus',r)
    def test_complete_twelve_blocks(self):
        b=self.ctx.binding;r=[{'stage':'geometry','binding':b,'output_files':{'runtime/geometry-metadata.json':{'sha256':'e'*64}}}]
        r += [{'stage':'block','index':i,'binding':b,'payload':{'geometry_metadata_sha256':'e'*64}} for i in range(12)]
        self.assertEqual(len(self.gate('conversion',r)['stages']),13)
        r[12]['index']=10
        with self.assertRaises(ValueError):self.gate('conversion',r)
    def test_wrong_count_rejected(self):
        with self.assertRaises(ValueError):self.gate('control',self.control()[:1])
    def test_chronological_source_index_writer(self):
        p=self.root/'source.json';value={'frames':{'2.0':{},'10.0':{},'96.0':{}}};stage_context.write_new(p,value)
        self.assertEqual(list(json.loads(p.read_text())['frames']),['2.0','10.0','96.0'])
    def test_disk_floor_no_write(self):
        p=self.root/'output.json'
        with patch.object(stage_context.shutil,'disk_usage',return_value=type('D',(),{'free':1024**3-1})()):
            with self.assertRaises(ValueError):stage_context.write_new(p,{'x':1})
        self.assertFalse(p.exists())
    def test_no_overwrite(self):
        p=self.root/'output.json';p.write_text('old')
        with self.assertRaises(FileExistsError):stage_context.write_new(p,{'x':1})
        self.assertEqual(p.read_text(),'old')
    def test_source_review_alone_not_smoke(self):
        ctx=fixture(self.root);ctx.raw['roots']['process_adapter']=str(ROOT/'onehand-runtime-20261016/windows-process-adapter-v2')
        p=ROOT/'onehand-runtime-20261016/windows-process-review-v2/REVIEW_FREEZE.json';ctx.raw['files']['transport_review']={'path':str(p),'sha256':transport_binding.REVIEW_ACCEPTANCE_SHA}
        with self.assertRaises((ValueError,FileNotFoundError)):transport_binding.verify_transport(ctx,production=True)
    def test_actual_smoke_admission_readonly(self):
        ctx=fixture(self.root);ctx.raw['roots']['process_adapter']=str(ROOT/'onehand-runtime-20261016/windows-process-adapter-v2')
        paths={'transport_review':ROOT/'onehand-runtime-20261016/windows-process-review-v2/REVIEW_FREEZE.json',
               'transport_smoke':ROOT/'onehand-runtime-20261016/windows-smoke-38871908839/independent-audit.json',
               'transport_smoke_summary':ROOT/'onehand-runtime-20261016/windows-smoke-38871908839/files/test-summary.json'}
        for role,path in paths.items():ctx.raw['files'][role]={'path':str(path),'sha256':pinned_code.file_sha(path)}
        adapter=transport_binding.verify_transport(ctx,production=True)
        audit=json.loads(paths['transport_smoke'].read_text())
        for attempt in audit['attempts']:
            root=paths['transport_smoke_summary'].parent/attempt['test']/'attempt'
            self.assertEqual(pinned_code.file_sha(root/'terminal.json'),attempt['terminal_sha256'])
            actual=adapter.verify_attempt(root)
            self.assertEqual(actual['completed'],attempt['completed']);self.assertTrue(actual['cleanup_complete']);self.assertTrue(actual['windows_job_empty_verified'])
        self.assertNotIn('bpy',sys.modules)
    def test_integrity_loading_does_not_launch(self):
        ctx=fixture(self.root);ctx.raw['roots']['process_adapter']=str(ROOT/'onehand-runtime-20261016/windows-process-adapter-v2')
        module=transport_binding.verify_transport(ctx,production=False);self.assertTrue(callable(module.verify_attempt));self.assertNotIn('bpy',sys.modules)

class ControlBootstrapCpu(unittest.TestCase):
    def test_control_settings_only_step_differs(self):
        actual=native_stages.control_export_settings();expected={**native_stages.SETTINGS,'bake_anim_step':1/64}
        self.assertEqual(actual,expected);self.assertEqual(native_stages.SETTINGS['bake_anim_step'],1/256)
    def test_control_source_stage_and_endpoints(self):
        self.assertIn('control-export',stage_context.SOURCE_STAGES)
        with tempfile.TemporaryDirectory(dir=HERE) as td:
            ctx=fixture(Path(td),'control-export');ctx.validate();self.assertEqual(ctx.frames(),[1.,96.]);self.assertNotIn('control_fbx',ctx.raw['files'])
    def test_no_linux_control_sha_in_active_sources(self):
        for p in HERE.glob('*.py'):
            if p.name!='test_native_producer.py':self.assertNotIn('17608683c81465964b5890b4d9869774a0f35122cf62ebd6e564cedf1b1ddbe4',p.read_text())
    def test_control_raw_validates_all_curves(self):
        from types import SimpleNamespace as N,ModuleType
        tree=N(elems=[N(id=b'Objects',elems=[N(id=b'AnimationCurve',props=[i],elems=[N(id=k,props=[v]) for k,v in [(b'KeyTime',[1,2]),(b'KeyValueFloat',[0,1]),(b'KeyAttrFlags',[24836]),(b'KeyAttrRefCount',[6081])]]) for i in range(1379)])])
        module=ModuleType('io_scene_fbx');module.parse_fbx=N(parse=lambda path:(tree,7400));calls=[]
        def arrays(t,v,n,flags,refs):calls.append((n,flags,refs));return {'key_count':6081,'time_sha256':'a'*64,'value_sha256':'b'*64}
        e={'single_stack_fbx':N(inspect_stack=lambda *args:None),'validate_arrays':arrays}
        with patch.dict(sys.modules,{'io_scene_fbx':module}):result=native_stages.control_raw_grid(e,Path('synthetic.fbx'))
        self.assertEqual(len(calls),1379);self.assertEqual(result['key_count'],6081);self.assertEqual(result['subdivisions'],64);self.assertTrue(all(c[0]==64 for c in calls))

if __name__=='__main__':unittest.main(verbosity=2)
