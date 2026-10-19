"""Reviewer P1/P2/P3 CPU reproductions. No subprocess, asset or native work."""
import ast,copy,dataclasses,hashlib,json,shutil,sys,tempfile,unittest
from pathlib import Path,PureWindowsPath
from types import SimpleNamespace as N
from unittest.mock import patch
import numpy as np
import admission,native_stages,pinned_code,planner,process_evidence,transport_binding
from test_native_producer import ROOT,HERE,cc,fixture
SMOKE=ROOT/'onehand-runtime-20261016/windows-smoke-38871908839/files/test_windows_normal_bytes_and_argument_roundtrip/attempt'
def write(path,value):path.write_text(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n')
def ref(path):return {'path':path.name,'bytes':path.stat().st_size,'sha256':pinned_code.file_sha(path)}

class WindowsDescriptorRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=ROOT/'onehand-runtime-20261016/windows-runtime-consumer-v1';pins=json.loads((root/'PINS.json').read_text());known={}
        for name in ('pinned_math','runtime_context','evidence'):
            wanted=pins[name+'.py'];wanted=wanted['sha256'] if isinstance(wanted,dict) else wanted
            if pinned_code.file_sha(root/(name+'.py'))!=wanted:raise ValueError('frozen consumer repro source differs')
            known[name]=pinned_code.isolated_module(name,root/(name+'.py'),known)
        cls.pm=known['pinned_math'];cls.ev=known['evidence'];cls.math=cls.pm.load(ROOT)
        tree=ast.parse(pinned_code.fragments()['fragments']['source_rows']['source']);loop=next(n for n in tree.body if isinstance(n,ast.For))
        assignment=next(n for n in loop.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Subscript) and isinstance(n.targets[0].value,ast.Name) and n.targets[0].value.id=='rows')
        cls.assignment=compile(ast.Module(body=[assignment],type_ignores=[]),'exact-original-row-descriptor','exec')
    def rows(self,frames):
        win=PureWindowsPath(r'C:\private\session\candidates\candidate\native\source');env={'P':win,'rows':{},'sha':lambda p:hashlib.sha256(b'{}').hexdigest()}
        for i,f in enumerate(frames):env.update(f=f,rp=win/'sample-rows'/f'{i:04d}.json',sp=win/'skin-rows'/f'{i:04d}.npz');exec(self.assignment,env)
        return win,env['rows']
    def positive(self,frames):
        win,rows=self.rows(frames);original=copy.deepcopy(rows);self.assertTrue(all('\\' in r['row_path'] for r in rows.values()))
        native_stages.canonical_source_descriptors(rows,win,frames)
        for before,after in zip(original.values(),rows.values()):self.assertEqual({k:v for k,v in before.items() if not k.endswith('_path')},{k:v for k,v in after.items() if not k.endswith('_path')})
        pm=self.pm;ctx=N(cc=cc,pin=lambda r:N(sha256='a'*64))
        witness={'generated_source_sha256':'a'*64,'approved_source_sha256':cc.APPROVED_SHA,'rig_action':pm.ACTION,'rig_action_fingerprint':pm.ACTION_SHA,'camera_action':None,'camera_action_fingerprint':None,
            'source_rest_world':{str(i):np.eye(4).tolist() for i in range(148)},'hierarchy':{str(i):None for i in range(148)},'topology':{n:{'vertices':c} for n,c in zip(pm.SKINS,pm.COUNTS)},'projection':{'type':'PERSP','ray_directions':[[0.,0.,-1.]]*4},'frames':rows}
        with tempfile.TemporaryDirectory(dir=HERE) as td:
            root=Path(td)
            for row in rows.values():
                for key in ('row_path','skin_path'):path=root/row[key];path.parent.mkdir(exist_ok=True);path.write_bytes(b'{}')
            path=root/'source-samples.json';path.write_text(json.dumps(witness)+'\n');got,_=self.ev.source_index(ctx,self.math,path,frames);self.assertEqual(got,witness)
    def test_windows_export_to_actual_consumer(self):self.positive([1.,96.])
    def test_windows_nine_focus_to_actual_consumer(self):self.positive(list(cc.FOCUS))
    def test_windows_64row_chunk_to_actual_consumer(self):self.positive(json.loads((ROOT/'recovery/onehand-v6-integration-handoff/dense-times.json').read_text())[:64])
    def test_original_windows_descriptor_reproduction(self):
        win,rows=self.rows([1.]);self.assertEqual(rows['1.0']['row_path'],r'sample-rows\0000.json')
        self.assertEqual(pinned_code.fragments()['fragments']['source_rows']['source_sha256'],json.loads((HERE.parent/'windows-native-producer-v2/AUDITED_FRAGMENTS.json').read_text())['fragments']['source_rows']['source_sha256'])
    def test_adapter_rejects_traversal_wrong_index_arbitrary_replacement(self):
        for bad in ('../sample-rows/0000.json',r'sample-rows\0001.json','sample-rows/0000.json',r'sample-rows\..\0000.json',r'C:\private\0000.json','sample-rows//0000.json'):
            with self.subTest(bad=bad):
                win,rows=self.rows([1.]);rows['1.0']['row_path']=bad
                with self.assertRaises(ValueError):native_stages.canonical_source_descriptors(rows,win,[1.])
    def test_actual_helper_environment_has_bisect(self):
        ctx=fixture(HERE/'unused');ctx.raw['roots']['audited_source']=str(ROOT);env=native_stages.environment(ctx,object(),np,object())
        self.assertEqual(env['linear_value']([1.,2.],[0.,10.],1.25),2.5);self.assertNotIn('bpy',sys.modules)

class ProcessConsistencyRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctx=fixture(HERE/'unused');ctx.raw['roots']['process_adapter']=str(HERE.parent/'windows-process-adapter-v2');cls.adapter=transport_binding.verify_transport(ctx,production=False)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=HERE);self.root=Path(self.tmp.name)/'synthetic-attempt';shutil.copytree(SMOKE,self.root)
        self.records={n:json.loads((self.root/(n+'.json')).read_text()) for n in ('attempt','started','transport','terminal')};self.samples=[json.loads(s) for s in (self.root/'samples.jsonl').read_text().splitlines()]
        v=self.records['terminal'];self.expected={k:copy.deepcopy(v[k]) for k in ('command','cwd','host_binding','limits','supervisor_python','rows')};self.expected['executable']=copy.deepcopy(v['executable_before'])
    def tearDown(self):self.tmp.cleanup()
    def seal(self):
        path=self.root/'samples.jsonl';path.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in self.samples));r=ref(path)
        for name in ('transport','terminal'):self.records[name]['streams']['samples'].update(r,observed_bytes=r['bytes'],observed_sha256=r['sha256'])
        write(self.root/'attempt.json',self.records['attempt']);r=ref(self.root/'attempt.json')
        for n in ('started','transport','terminal'):self.records[n]['attempt']=copy.deepcopy(r)
        write(self.root/'started.json',self.records['started']);r=ref(self.root/'started.json')
        for n in ('transport','terminal'):self.records[n]['started_record']=copy.deepcopy(r)
        write(self.root/'transport.json',self.records['transport']);self.records['terminal']['transport_record']=ref(self.root/'transport.json')
        write(self.root/'terminal.json',self.records['terminal']);write(self.root/'terminal.sha256.json',ref(self.root/'terminal.json'))
    def verify(self):return process_evidence.verify_completed_process(self.adapter,self.root,self.expected)
    def test_actual_original_smoke_semantics_and_gap_report(self):
        before=pinned_code.file_sha(SMOKE/'terminal.json');got=process_evidence.verify_completed_process(self.adapter,SMOKE,self.expected)
        self.assertEqual(got['resources']['sample_count'],3);self.assertTrue(got['resources']['observed_gap_exceeds_requested_period']);self.assertEqual(before,pinned_code.file_sha(SMOKE/'terminal.json'))
    def test_valid_resealed_synthetic_fixture(self):self.seal();self.assertEqual(self.verify()['record']['exit_code'],0)
    def test_reviewer_combined_resealed_mutation(self):
        self.samples[0].update(rss_bytes=4*1024**3,free_bytes=0);self.records['terminal']['supervisor_python']['sha256']='f'*64;self.records['started']['command']=['wrong-predecessor-command'];self.seal()
        self.assertTrue(self.adapter.verify_attempt(self.root,require_completed=True)['completed'])
        with self.assertRaises(ValueError):self.verify()
    def test_exact_native_launcher_limits(self):
        l=planner.process_limits(self.adapter);self.assertEqual((l.sample_seconds,l.deadline_seconds,l.rss_bytes,l.disk_floor_bytes),(.2,1800.,3*1024**3,1024**3))
        self.assertEqual((l.stdout_mode,l.max_stdout_bytes,l.max_stderr_bytes),('bytes',4*1024**2,1024**2));self.expected['limits']=dataclasses.asdict(l);self.seal()
        with self.assertRaises(ValueError):self.verify()

    def test_resealed_started_attempt_reference_contradiction(self):
        self.seal();started=self.records['started'];started['attempt']['sha256']='f'*64;write(self.root/'started.json',started)
        self.records['transport']['started_record']=ref(self.root/'started.json');write(self.root/'transport.json',self.records['transport'])
        terminal=self.records['terminal'];terminal['started_record']=ref(self.root/'started.json');terminal['transport_record']=ref(self.root/'transport.json');write(self.root/'terminal.json',terminal);write(self.root/'terminal.sha256.json',ref(self.root/'terminal.json'))
        self.assertTrue(self.adapter.verify_attempt(self.root,require_completed=True)['completed'])
        with self.assertRaisesRegex(ValueError,'attempt predecessor'):self.verify()
    def test_resealed_transport_started_reference_contradiction(self):
        self.seal();self.records['transport']['started_record']['sha256']='f'*64;write(self.root/'transport.json',self.records['transport'])
        terminal=self.records['terminal'];terminal['transport_record']=ref(self.root/'transport.json');write(self.root/'terminal.json',terminal);write(self.root/'terminal.sha256.json',ref(self.root/'terminal.json'))
        self.assertTrue(self.adapter.verify_attempt(self.root,require_completed=True)['completed'])
        with self.assertRaisesRegex(ValueError,'started predecessor'):self.verify()

def mutate_results(t,key,value):
    for name in ('transport','terminal'):t.records[name][key]=copy.deepcopy(value)
MUTATIONS={
'rss_above_ceiling':lambda t:t.samples[0].update(rss_bytes=4*1024**3),
'disk_below_floor':lambda t:t.samples[0].update(free_bytes=0),
'negative_available':lambda t:t.samples[0].update(mem_available_bytes=-1),
'bool_rss':lambda t:t.samples[0].update(rss_bytes=True),
'all_null_rss':lambda t:[s.update(rss_bytes=None) for s in t.samples],
'rss_after_exit':lambda t:t.samples[0].update(rss_bytes=None),
'wrong_sample_count':lambda t:mutate_results(t,'sample_count',2),
'bool_sample_count':lambda t:mutate_results(t,'sample_count',True),
'decreasing_clock':lambda t:t.samples[1].update(elapsed_seconds=-.1),
'clock_beyond_duration':lambda t:t.samples[1].update(elapsed_seconds=1.),
'sample_deadline':lambda t:t.samples[1].update(elapsed_seconds=1800.),
'nonfinite_clock':lambda t:t.samples[1].update(elapsed_seconds=float('nan')),
'missing_resource_field':lambda t:t.samples[0].pop('free_bytes'),
'extra_resource_field':lambda t:t.samples[0].update(unchecked=1),
'wrong_peak':lambda t:mutate_results(t,'peak_sampled_rss_bytes',1),
'initial_available_guard':lambda t:t.records['started'].update(initial_available_bytes=0),
'initial_disk_guard':lambda t:t.records['started'].update(initial_free_bytes=1024**3),
'wrong_supervisor_all_predecessors':lambda t:[r['supervisor_python'].update(sha256='f'*64) for r in t.records.values()],
'supervisor_bytes':lambda t:[r['supervisor_python'].update(bytes=1) for r in t.records.values()],
'started_command':lambda t:t.records['started'].update(command=['contradiction']),
'attempt_cwd':lambda t:t.records['attempt'].update(cwd='C:\\wrong'),
 'transport_run':lambda t:t.records['transport']['host_binding'].update(run_id='wrong'),
'environment_all_predecessors':lambda t:[r['host_binding'].update(environment_sha256='f'*64) for r in t.records.values()],
'environment_keys_all_predecessors':lambda t:[r['host_binding'].update(environment_keys=['SystemRoot']) for r in t.records.values()],
'changed_context_all_predecessors':lambda t:[r['host_binding'].update(context_sha256='f'*64) for r in t.records.values()],
'changed_build_all_predecessors':lambda t:[r['host_binding'].update(build_sha256='f'*64) for r in t.records.values()],
'changed_host_all_predecessors':lambda t:[r['host_binding']['observed_host'].update(version='wrong') for r in t.records.values()],
'wrong_start_clock':lambda t:t.records['started'].update(started_unix=1.),
'wrong_child_pid':lambda t:t.records['started'].update(pid=1),
'wrong_backend':lambda t:t.records['started'].update(backend='posix'),
'wrong_executable':lambda t:t.records['started']['executable_before'].update(sha256='f'*64),
'wrong_transport_stream':lambda t:t.records['transport']['streams']['stdout'].update(sha256='f'*64),
'wrong_transport_sample_count':lambda t:t.records['transport'].update(sample_count=1),
'terminal_deadline':lambda t:t.records['terminal'].update(duration_seconds=1800.),
'negative_terminal_duration':lambda t:t.records['terminal'].update(duration_seconds=-1.),
'terminal_before_transport':lambda t:t.records['terminal'].update(duration_seconds=.01),
'process_duration_before_samples':lambda t:mutate_results(t,'process_duration_seconds',.01),
'resource_stop_claim':lambda t:t.records['transport'].update(resource_stop_reason='own_child_rss_ceiling'),
'transport_constructor_failure':lambda t:t.records['transport'].update(constructor_cleanup_complete=True),
'transport_not_started':lambda t:t.records['transport'].update(started=False),
'queue_peak_over_limit':lambda t:mutate_results(t,'queue_peak_bytes',2**40),
'extra_terminal_field':lambda t:t.records['terminal'].update(unchecked_override=True),
'terminal_limits_changed':lambda t:t.records['terminal']['limits'].update(sample_seconds=.1),
}
for name,mutation in MUTATIONS.items():
    def test(self,mutation=mutation):
        mutation(self);self.seal()
        with self.assertRaises((ValueError,TypeError)):self.verify()
    setattr(ProcessConsistencyRegression,'test_reject_'+name,test)

class RetainedInventoryRegression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=HERE);self.root=Path(self.tmp.name);self.frames=[1.,2.];self.ctx=N(stage='source-chunk',output=self.root,cc=cc,frames=lambda:self.frames);files={};rows={}
        for i,f in enumerate(self.frames):
            row={'source_frame':f}
            for kind,folder,ext in (('row','sample-rows','json'),('skin','skin-rows','npz')):
                name=f'{folder}/{i:04d}.{ext}';path=self.root/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'{}');files[name]={'sha256':pinned_code.file_sha(path),'bytes':2};row[kind+'_path']=name;row[kind+'_sha256']=files[name]['sha256']
            rows[str(f)]=row
        path=self.root/'source-samples.json';path.write_text(json.dumps({'frames':rows})+'\n');files[path.name]={'sha256':pinned_code.file_sha(path),'bytes':path.stat().st_size};self.env={'output_files':files};self.retired={k:copy.deepcopy(v) for k,v in files.items() if k!='source-samples.json'}
    def tearDown(self):self.tmp.cleanup()
    def retire(self):
        for name in self.retired:(self.root/name).unlink()
    def test_default_requires_present_rows(self):
        admission.verify_output_inventory(self.ctx,self.env);self.retire()
        with self.assertRaises((ValueError,FileNotFoundError)):admission.verify_output_inventory(self.ctx,self.env)
    def test_retained_full_exact_inventory(self):self.retire();admission.verify_output_inventory(self.ctx,self.env,retired_files=self.retired)
    def test_retained_subset_rejected(self):
        self.retire();self.retired.pop(next(iter(self.retired)))
        with self.assertRaises(ValueError):admission.verify_output_inventory(self.ctx,self.env,retired_files=self.retired)
    def test_retained_wrong_hash_rejected(self):
        self.retire();self.retired[next(iter(self.retired))]['sha256']='f'*64
        with self.assertRaises(ValueError):admission.verify_output_inventory(self.ctx,self.env,retired_files=self.retired)
    def test_retained_wrong_bytes_rejected(self):
        self.retire();self.retired[next(iter(self.retired))]['bytes']=3
        with self.assertRaises(ValueError):admission.verify_output_inventory(self.ctx,self.env,retired_files=self.retired)
    def test_retained_source_index_rejected(self):
        self.retire();self.retired['source-samples.json']=self.env['output_files']['source-samples.json']
        with self.assertRaises(ValueError):admission.verify_output_inventory(self.ctx,self.env,retired_files=self.retired)
    def test_retained_other_stage_rejected(self):
        self.retire();self.ctx.stage='source-focus'
        with self.assertRaises(ValueError):admission.verify_output_inventory(self.ctx,self.env,retired_files=self.retired)
    def test_retained_present_file_rejected(self):
        with self.assertRaises(ValueError):admission.verify_output_inventory(self.ctx,self.env,retired_files=self.retired)
    def test_retained_extra_file_rejected(self):
        self.retire();(self.root/'untracked').write_bytes(b'x')
        with self.assertRaises(ValueError):admission.verify_output_inventory(self.ctx,self.env,retired_files=self.retired)
    def test_retained_traversal_rejected(self):
        self.retire();self.retired['../row.json']=self.retired.pop(next(iter(self.retired)))
        with self.assertRaises(ValueError):admission.verify_output_inventory(self.ctx,self.env,retired_files=self.retired)
    def test_public_adapters_share_full_verifier(self):
        with patch.object(admission,'_verify_stage',return_value={'tested':True}) as m:
            args=('context','a'*64,'package','b'*64,'c'*64);admission.verify_stage(*args);self.assertEqual(m.call_args.kwargs,{'_active':None})
            admission.verify_retained_stage(*args,retired_files=self.retired);self.assertEqual(m.call_args.kwargs,{'retired_files':self.retired})


class BoundaryAuditRegression(unittest.TestCase):
    def test_exact_boundary_function_hashes(self):
        audit=json.loads((HERE/'BOUNDARY_ADAPTATIONS.json').read_text())
        self.assertFalse(audit['numeric_fragments_changed'])
        self.assertEqual(audit['unchanged_audited_fragments_sha256'],pinned_code.file_sha(HERE/'AUDITED_FRAGMENTS.json'))
        self.assertEqual((HERE/'AUDITED_FRAGMENTS.json').read_bytes(),(HERE.parent/'windows-native-producer-v2/AUDITED_FRAGMENTS.json').read_bytes())
        for key,value in audit['adaptations'].items():
            file,name=key.split(':');source=(HERE/file).read_text();lines=source.splitlines(keepends=True);node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(hashlib.sha256(''.join(lines[node.lineno-1:node.end_lineno]).encode()).hexdigest(),value['source_sha256'])
            self.assertEqual(hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest(),value['ast_sha256'])
    def test_prior_frozen_packages_unchanged(self):
        expected={'v1':'22adda32482a35a439f2ee9afc5b5fff6e44d4b418a8de171d69a530f7509144','v2':'aad2a9113d83d6cbc61dbcc580ff286c0b8a6cbfbd241526de0c642f2ca74d96'}
        for version,pin in expected.items():
            root=HERE.parent/('windows-native-producer-'+version);self.assertEqual(pinned_code.file_sha(root/'PINS.json'),pin)
            for file,want in json.loads((root/'PINS.json').read_text()).items():self.assertEqual(pinned_code.file_sha(root/file),want)
    def test_review_freeze_unchanged(self):self.assertEqual(pinned_code.file_sha(HERE.parent/'windows-native-producer-review-v2/REVIEW_FREEZE.json'),'a878a413cee0199abffcf5293948c3e3213fbbadf960b28e10331fd93aedd34a')

if __name__=='__main__':unittest.main(verbosity=2)
