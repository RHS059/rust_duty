"""Tiny CPU-only contract tests. No native tool, assets or network; separate regressions use tiny local Git objects."""
import ast,contextlib,copy,hashlib,io,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import workflow_core as w
import checkout_bytes as checkout
import build_rust
import orchestrate
import host_tools

class SmallFixture(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def put(self,name,raw=b'x'):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);return p

class Files(SmallFixture):
    def test_exact_lf_and_crlf_distinct(self):
        p=self.put('x.py',b'line\n');h=w.sha(p);p.write_bytes(b'line\r\n')
        with self.assertRaises(ValueError):w.pin(p,h)
    def test_duplicate_json(self):
        with self.assertRaises(ValueError):w.strict_json(self.put('x.json',b'{"x":1,"x":2}'))
    def test_nonfinite_json(self):
        with self.assertRaises(ValueError):w.strict_json(self.put('x.json',b'{"x":NaN}'))
    def test_json_cap(self):
        with self.assertRaises(ValueError):w.strict_json(self.put('x.json',b'{}'),1)
    def test_no_overwrite(self):
        p=self.put('x.json')
        with self.assertRaises(FileExistsError):w.write_new(p,{})
    def test_byte_exact_output(self):
        p=self.root/'new.json';fp=w.write_new(p,{'z':1});self.assertEqual(p.read_bytes(),b'{"z":1}\n');self.assertEqual(fp,w.file_pin(p))
    def test_path_traversal(self):
        with self.assertRaises(ValueError):w.ordinary(self.root/'..'/'x')
    def test_windows_alias(self):
        for name in ('CON','x.','x ','a:stream','COM1.txt'):
            with self.assertRaises(ValueError):w.ordinary(self.root/name)
    def test_symlink(self):
        p=self.put('source');link=self.root/'link';link.symlink_to(p)
        with self.assertRaises(ValueError):w.ordinary(link)
    def test_hardlink_role_alias(self):
        p=self.put('source');other=self.root/'other';os.link(p,other)
        with self.assertRaises(ValueError):w.unique_roles({'a':w.file_pin(p),'b':w.file_pin(other)})
    def test_inventory_includes_nested_target_git(self):
        self.put('src/target/input.rs');self.put('src/.git/input.rs');self.assertEqual(set(w.inventory(self.root/'src')),{'target/input.rs','.git/input.rs'})
    def test_package_byte_check(self):
        p=self.put('a.py',b'pass\n');manifest=self.put('PINS.json',json.dumps({'a.py':w.sha(p)}).encode());w.package(self.root,w.sha(manifest));p.write_bytes(b'pass\r\n')
        with self.assertRaises(ValueError):w.package(self.root,w.sha(manifest))
    def test_protected_companion_names(self):
        p=self.put('a.blend');
        with self.assertRaises(ValueError):w.materialize_companion(p,self.root/'copy.blend')
    def test_small_synthetic_companion_copy(self):
        p=self.put('a/asset.vrs');target=self.root/'b'/'asset.vrs';target.parent.mkdir();fp=w.materialize_companion(p,target);self.assertEqual(fp['sha256'],w.sha(p))
    def test_missing_review_pin_is_hard_block(self):
        value=w.strict_json(w.HERE/'reviewed-dependencies.json');value['reference_index_sha256']=None
        with patch.object(orchestrate,'strict_json',return_value=value):
            with self.assertRaises(ValueError):orchestrate.reviewed_dependencies()
    def test_missing_sha(self):
        for value in (None,'','0'*63,'A'*64,True):
            with self.assertRaises(ValueError):w.sha_value(value)
    def test_inventory_rejects_empty_source(self):
        with self.assertRaises(ValueError):w.inventory(self.root)
    def test_hash_only_failure(self):
        secret='PRIVATE-RAW-VERTEX-999';s=orchestrate.summary({},error=ValueError(secret));self.assertNotIn(secret,json.dumps(s));self.assertEqual(s['error_sha256'],hashlib.sha256(secret.encode()).hexdigest())

    def test_private_cli_output_never_reaches_public_stdout(self):
        public=io.StringIO();secret='PRIVATE-RAW-VERTEX-999'
        with contextlib.redirect_stdout(public):status=w.private_call(self.root/'logs',lambda:print(secret))
        self.assertIsNone(status);self.assertEqual(public.getvalue(),'');self.assertIn(secret,(self.root/'logs'/'stdout.log').read_text())
    def test_private_cli_failure_preserves_logs(self):
        def fail():print('private failure');raise ValueError('failure')
        with self.assertRaises(ValueError):w.private_call(self.root/'logs',fail)
        self.assertEqual((self.root/'logs'/'stdout.log').read_text(),'private failure\n')
    def test_private_cli_log_cap(self):
        with self.assertRaises(ValueError):w.private_call(self.root/'logs',lambda:print('x'*(1024**2+1)))

class Materialization(SmallFixture):
    def row(self,raw=b'line\n'):
        return {'ref':'a'*40,'repository_path':'tools/x.py','destination':'code/x.py','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'kind':'original-source'}
    def manifest(self,row=None):return {'schema':'rust-duty-onehand-byte-materialization/v1','files':[row or self.row()]}
    def test_exact_bytes(self):
        out=self.root/'out';value=checkout.materialize(self.manifest(),out,lambda *_:b'line\n');self.assertEqual((out/'code/x.py').read_bytes(),b'line\n');self.assertFalse(value['checkout_filters_used'])
    def test_empty_original_source_is_preserved(self):
        row=self.row(b'');checkout.materialize(self.manifest(row),self.root/'out',lambda *_:b'');self.assertEqual((self.root/'out/code/x.py').read_bytes(),b'')
    def test_windows_reserved_destination(self):
        for name in ('CON','a.','COM1.txt','x/hidden '):
            row=self.row();row['destination']=name
            with self.assertRaises(ValueError):checkout.validate_manifest(self.manifest(row))
    def test_materialization_disk_floor(self):
        with patch.object(checkout.shutil,'disk_usage',return_value=SimpleNamespace(free=1024)):
            with self.assertRaises(ValueError):checkout.materialize(self.manifest(),self.root/'out',lambda *_:b'line\n')
    def test_crlf_rejected(self):
        with self.assertRaises(ValueError):checkout.materialize(self.manifest(),self.root/'out',lambda *_:b'line\r\n')
    def test_no_mutable_refs(self):
        r=self.row();r['ref']='main'
        with self.assertRaises(ValueError):checkout.validate_manifest(self.manifest(r))
    def test_no_raw_geometry(self):
        for suffix in ('.blend','.fbx','.vra','.npz','.bin'):
            r=self.row();r['destination']='x'+suffix
            with self.assertRaises(ValueError):checkout.validate_manifest(self.manifest(r))
    def test_no_fake_public_base(self):
        r=self.row();r['kind']='existing-public-baseline'
        with self.assertRaises(ValueError):checkout.validate_manifest(self.manifest(r))
    def test_no_fake_canonical(self):
        r=self.row();r['kind']='existing-public-canonical'
        with self.assertRaises(ValueError):checkout.validate_manifest(self.manifest(r))
    def test_duplicate_destination(self):
        m=self.manifest();m['files'].append(dict(m['files'][0]))
        with self.assertRaises(ValueError):checkout.validate_manifest(m)
    def test_preserve_existing_root(self):
        with self.assertRaises(ValueError):checkout.materialize(self.manifest(),self.root,lambda *_:b'line\n')
    def test_traversal(self):
        for path in ('../x','a/../x','/x','a\\x','a:stream','a//x'):
            with self.assertRaises(ValueError):checkout.relative(path)
    def test_unicode_spaces(self):
        r=self.row();r['destination']='original source/é.py';out=self.root/'out';checkout.materialize(self.manifest(r),out,lambda *_:b'line\n');self.assertEqual((out/'original source/é.py').read_bytes(),b'line\n')

class BuildClosure(SmallFixture):
    def test_exact_depinfo_preferred(self):
        source=self.root/'source';source.mkdir();crate=self.put('source/src/lib.rs');a=self.put('target/thing-123.d',b'a');b=self.put('target/other.d',b'b')
        artifact={'target':{'src_path':str(crate),'name':'thing'},'filenames':[str(self.root/'target/libthing-123.rlib')]}
        self.assertEqual(build_rust.select_dep_info(artifact,[a,b],source,lambda raw:[str(crate)]),a)
    def test_ambiguous_depinfo_blocks(self):
        source=self.root/'source';source.mkdir();crate=self.put('source/lib.rs');a=self.put('a.d');b=self.put('b.d');artifact={'target':{'src_path':str(crate),'name':'thing'},'filenames':[]}
        with self.assertRaises(ValueError):build_rust.select_dep_info(artifact,[a,b],source,lambda _: [str(crate)])
    def test_missing_depinfo_blocks(self):
        crate=self.put('lib.rs');artifact={'target':{'src_path':str(crate),'name':'thing'},'filenames':[]}
        with self.assertRaises(ValueError):build_rust.select_dep_info(artifact,[],self.root,lambda _:[])
    def test_failed_cargo_blocks(self):
        p=self.put('cargo.jsonl',b'{"reason":"build-finished","success":false}\n')
        with self.assertRaises(ValueError):build_rust.cargo_events(p)
    def test_successful_cargo_stream(self):
        p=self.put('cargo.jsonl',b'{"reason":"build-finished","success":true}\n');self.assertEqual(len(build_rust.cargo_events(p)),1)
    def test_empty_out_dir_is_not_fabricated_producer(self):
        source=self.root/'source';source.mkdir();target=self.root/'target';target.mkdir();out=target/'empty';out.mkdir();candidate=self.root/'candidate';candidate.mkdir()
        proc=self.put('candidate/process.json',json.dumps({'stdout':{'path':'x'}}).encode())
        build={'command':['cargo'],'source_tree_sha256':'a'*64,'dependency_closure':{}}
        report=build_rust.compiler_report(build,w.record(proc),[{'reason':'build-script-executed','out_dir':str(out)}],target,source,lambda _:[],candidate)
        self.assertEqual(report['invocations'],[]);self.assertFalse((candidate/'build').exists())
    def test_generated_input_binds_whole_build(self):
        source=self.root/'source';source.mkdir();crate=self.put('source/lib.rs');target=self.root/'target';target.mkdir();gen=self.put('target/out/generated.rs');dep=self.put('target/code.d');candidate=self.root/'candidate';candidate.mkdir();proc=self.put('candidate/process.json',json.dumps({'stdout':{'path':'cargo.jsonl'}}).encode())
        artifact={'reason':'compiler-artifact','target':{'src_path':str(crate),'name':'code'},'filenames':[str(target/'code.exe')]}
        build={'command':['cargo'],'source_tree_sha256':'a'*64,'dependency_closure':{}}
        report=build_rust.compiler_report(build,w.record(proc),[artifact,{'reason':'build-script-executed','out_dir':str(gen.parent)}],target,source,lambda _:[str(crate),str(gen)],candidate)
        generated=report['invocations'][0]['generated_inputs'][0];value=w.strict_json(generated['producer']['path']);self.assertEqual(value['build_process'],w.record(proc));self.assertEqual(value['schema'],'rust-duty-cargo-generated-inputs/v1');self.assertNotIn('command',value)

class Schedule(unittest.TestCase):
    def test_222_native_stages(self):self.assertEqual(len(w.sequence()),222)
    def test_control_precedes_dense(self):self.assertEqual(w.sequence()[:4],(('control-export',None),('control-full',None),('control-bounded',None),('export',None)))
    def test_exact_twelve_blocks(self):self.assertEqual([i for n,i in w.sequence() if n=='block'],list(range(12)))
    def test_all67_triplets(self):
        for n in ('source-chunk','chunk-import','rigid-chunk'):self.assertEqual([i for s,i in w.sequence() if s==n],list(range(67)))
    def test_focus_separate(self):self.assertEqual(sum(s=='source-focus' for s,_ in w.sequence()),1)
    def test_no_renderer_or_retirement(self):self.assertFalse(any('render' in s or 'retire' in s for s,_ in w.sequence()))
    def test_no_global_pin_mutation(self):
        tree=ast.parse((w.HERE/'orchestrate.py').read_bytes())
        for node in ast.walk(tree):
            if isinstance(node,ast.Assign):
                self.assertFalse(any(isinstance(t,ast.Attribute) and t.attr.startswith('REVIEWED_') for t in node.targets))
    def test_installer_vendor_failure_closed(self):
        text=(w.HERE/'install_official_blender.ps1').read_text();self.assertIn('no secondary-manifest fallback',text);self.assertLess(text.index('$matches.Count -ne 1'),text.index('Invoke-WebRequest ($root + $name)'))
    def test_workflow_only_hash_summary(self):
        text=(w.HERE/'onehand-windows-proof.yml').read_text();self.assertEqual(text.count('actions/upload-artifact'),3);self.assertIn('/proof/public-evidence/summary.json',text);self.assertNotIn('actions/cache',text);self.assertIn('persist-credentials: false',text)
    def test_no_real_work_ran_in_source_tests(self):
        tree=ast.parse(Path(__file__).read_bytes());self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('Popen','run','system') for n in ast.walk(tree)))


class PublicationLayout(unittest.TestCase):
    def setUp(self):self.layout=json.loads((w.HERE/'PUBLICATION_LAYOUT.json').read_bytes())
    def test_unique_exact_repository_paths(self):
        paths=[r['repository_path'].casefold() for r in self.layout['files']];self.assertEqual(len(paths),len(set(paths)))
    def test_all_dependency_source_records_mapped(self):
        deps=json.loads((w.HERE/'DEPENDENCIES.json').read_bytes())['files'];rows={r['source']:r for r in self.layout['files'] if r['origin']=='dependency'}
        self.assertEqual(set(rows),set(deps))
        for name,row in rows.items():self.assertEqual((row['sha256'],row['bytes']),(deps[name]['sha256'],deps[name]['bytes']))
    def test_no_held_or_private_payloads(self):
        for row in self.layout['files']:
            self.assertNotIn(Path(row['repository_path']).suffix.lower(),('.blend','.fbx','.vra','.vrs','.vrm','.npz','.mp4','.zip'))
            self.assertNotEqual(Path(row['repository_path']).name,'original-delta.json')
        self.assertFalse(self.layout['private_or_held_payloads_included'])
    def test_workflow_and_all_frozen_context_bytes_have_routes(self):
        paths={r['repository_path'] for r in self.layout['files']};self.assertNotIn('.github/workflows/onehand-windows-proof.yml',paths);self.assertIn('tools/onehand_windows/.gitattributes',paths)
        context=[r for r in self.layout['files'] if r['repository_path'].startswith('tools/onehand_windows/context-v2/')];self.assertEqual(len(context),16)

class ControllerSnapshots(SmallFixture):
    def fake(self):
        candidate=self.root/'private'/'session'/'candidates'/'candidate';candidate.mkdir(parents=True)
        fixed=self.put('input.json',b'{}');files={'generated_source':w.file_pin(fixed),'actual_fbx':w.file_pin(fixed)}
        holder={}
        def read(path,expected,package):
            raw=w.strict_json(w.pin(path,expected));holder['raw']=raw
            return SimpleNamespace(path=path,output=candidate/'native'/raw['stage_id'],binding={'candidate':'same'})
        def launch(ctx,env):
            self.assertEqual(env,{'SYSTEMROOT':'Windows'});return {'output_files':{}}
        native=SimpleNamespace(stage_context=SimpleNamespace(COMMON={'generated_source'},INPUTS={'source-chunk':{'actual_fbx'}},ROOTS={'context_package'},SCHEMA='stage-schema',StageContext=SimpleNamespace(read=read)),launch_stage=SimpleNamespace(launch=launch),admission=SimpleNamespace(receipt_ref=lambda ctx:{'context':w.file_pin(ctx.path)}))
        cc=SimpleNamespace(MODE='fresh-Windows-production',INVARIANTS={'samples':4240})
        config={'candidate_id':'candidate','session_id':'session','private_root':str(self.root/'private'),'roots':{'context_package':str(self.root/'package')},'native_environment':{'SYSTEMROOT':'Windows'}}
        pipeline=orchestrate.Pipeline(config,{'native_producer_pins_sha256':'a'*64},SimpleNamespace(cc=cc,native=native),candidate,None,files,{'host':'fixed'},None);pipeline.lineage={'approved':'b'*64}
        return pipeline,holder
    def test_successor_snapshots_do_not_rewrite_predecessor(self):
        p,h=self.fake()
        with patch.object(host_tools,'verify_embedded',return_value={}):p.native('source-chunk',0)
        path=p.candidate/'contexts/source-chunk-000.json';before=path.read_bytes();p.files['actual_fbx']={'path':str(self.root/'other'),'sha256':'c'*64}
        with patch.object(host_tools,'verify_embedded',return_value={}):p.native('source-chunk',1)
        self.assertEqual(path.read_bytes(),before);self.assertNotEqual(h['raw']['files']['actual_fbx'],json.loads(before)['files']['actual_fbx'])
    def test_same_stage_reentry_rejected(self):
        p,h=self.fake()
        with patch.object(host_tools,'verify_embedded',return_value={}):
            p.native('source-chunk',0)
            with self.assertRaises(FileExistsError):p.native('source-chunk',0)
    def test_missing_predecessor_blocks_before_context(self):
        p,h=self.fake();del p.files['actual_fbx']
        with self.assertRaises(ValueError):p.native('source-chunk',0)
        self.assertFalse((p.candidate/'contexts').exists())
    def test_stage_extra_binds_local_source_samples(self):
        p,h=self.fake();p.p.native.stage_context.INPUTS['source-chunk'].add('source_samples');sample=self.put('local-oracle.json')
        with patch.object(host_tools,'verify_embedded',return_value={}):p.native('source-chunk',2,{'source_samples':w.file_pin(sample)})
        self.assertEqual(h['raw']['files']['source_samples'],w.file_pin(sample))
    def test_same_candidate_gate_binds_all_predecessor_pins(self):
        p,h=self.fake();path=self.put('ctx.json');ref={'context':w.file_pin(path)}
        p.stages={('control-export',None):(SimpleNamespace(binding={'a':1}),{},ref),('control-full',None):(SimpleNamespace(binding={'a':1}),{},ref),('control-bounded',None):(SimpleNamespace(binding={'a':1,'actual_fbx_sha256':'a'*64}),{},ref)}
        seen=[];p.p.native.admission.verify_gate=lambda path,sha,package:seen.append(w.strict_json(w.pin(path,sha)))
        fp=p.gate('control',list(p.stages));self.assertEqual(seen[0]['stages'],[ref]*3);self.assertEqual(seen[0]['binding'],{'a':1});self.assertEqual(fp,p.files['control_gate'])

if __name__=='__main__':unittest.main()
