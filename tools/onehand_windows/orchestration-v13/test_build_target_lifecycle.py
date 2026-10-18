"""CPU-only real controller-flow regressions; no Cargo or native process starts."""
import hashlib,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import build_rust as b
import workflow_core as w

class CargoTargetOwnership(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).absolute()
    def test_new_directory_identity_and_empty_check(self):
        owner=b.FreshCargoTarget(self.root/'target');owner.verify();owner.require_empty('not empty')
    def test_existing_empty_directory_is_not_adopted(self):
        target=self.root/'target';target.mkdir()
        with self.assertRaisesRegex(ValueError,'fresh Cargo'):b.FreshCargoTarget(target)
        self.assertTrue(target.is_dir())
    def test_existing_files_are_retained(self):
        target=self.root/'target';target.mkdir();sentinel=target/'keep';sentinel.write_bytes(b'keep')
        with self.assertRaises(ValueError):b.FreshCargoTarget(target)
        self.assertEqual(sentinel.read_bytes(),b'keep')
    def test_regular_file_cannot_be_a_target(self):
        target=self.root/'target';target.write_bytes(b'keep')
        with self.assertRaises(ValueError):b.FreshCargoTarget(target)
        self.assertEqual(target.read_bytes(),b'keep')
    def test_existing_and_dangling_symlink_rejected(self):
        for index,name in enumerate(('existing','absent')):
            target=self.root/name
            if index==0:target.mkdir()
            alias=self.root/('alias'+str(index));alias.symlink_to(target,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'symlink/reparse'):b.FreshCargoTarget(alias)
    def test_replaced_empty_directory_rejected(self):
        owner=b.FreshCargoTarget(self.root/'target');owner.path.rename(self.root/'retained');owner.path.mkdir()
        with self.assertRaisesRegex(ValueError,'replaced'):owner.require_empty('not empty')
    def test_symlink_replacement_rejected(self):
        owner=b.FreshCargoTarget(self.root/'target');owner.path.rename(self.root/'retained');owner.path.symlink_to(self.root/'retained',target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink/reparse'):owner.verify()
    def test_nonempty_directory_rejected_without_cleanup(self):
        owner=b.FreshCargoTarget(self.root/'target');(owner.path/'.rustc_info.json').write_bytes(b'probe')
        with self.assertRaisesRegex(ValueError,'not empty'):owner.require_empty('not empty')
        self.assertEqual((owner.path/'.rustc_info.json').read_bytes(),b'probe')
    def test_environment_cannot_redirect_owned_target(self):
        owner=b.FreshCargoTarget(self.root/'target');commands=N(run=lambda *a,**k:self.fail('must not launch'))
        with self.assertRaisesRegex(ValueError,'environment differs'):owner.run(commands,'test',['unexecuted'],self.root,environment={'CARGO_TARGET_DIR':str(self.root/'other')})
    def test_overlapping_target_and_source_rejected(self):
        with self.assertRaisesRegex(ValueError,'overlap'):b.disjoint_build_roots([self.root/'source',self.root/'source/target'])

class BuildTargetLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).absolute();self.source=self.root/'source';self.source.mkdir()
        for name in ('Cargo.lock','Cargo.toml','main.rs'):(self.source/name).write_bytes(('synthetic '+name).encode())
        self.before=w.inventory(self.source);self.target=self.root/'target';self.preparation=self.root/'target-preparation';self.vendor=self.root/'vendor';self.home=self.root/'home';self.candidate=self.root/'candidate'
        tools=[]
        for name in ('cargo','rustc','manifest','linker'):
            path=self.root/name;path.write_bytes(('not executable '+name).encode());tools.append(w.record(path))
        cargo,rustc,manifest,linker=tools
        receipt=self.root/'toolchain.json';w.write_new(receipt,{'cargo':cargo,'rustc':rustc,'manifest':manifest,'toolchain':b.source_selection.TOOLCHAIN,'compiler_tools':[linker]})
        checkout=self.root/'checkout.json';w.write_new(checkout,{'files':[{'destination':'rust-source/'+name,'sha256':sha,'ref':b.source_selection.REVISION} for name,sha in self.before.items()]})
        self.config={'byte_checkout':w.file_pin(checkout),'rust':{'source_root':str(self.source),'target_directory':str(self.target),'vendor_root':str(self.vendor),'cargo_home':str(self.home),'source_revision':b.source_selection.REVISION,'features':[],'toolchain':b.source_selection.TOOLCHAIN,'distribution':'official-rustup','cargo':cargo['path'],'rustc':rustc['path'],'rustup_manifest':manifest['path'],'toolchain_receipt':str(receipt),'compiler_tool_files':[linker['path']]}}
        self.consumer=N(pinned_math=N(read=lambda _:self.before,HERE=self.root),build_closure=N(dep_info_paths=lambda _: [str(self.source/'main.rs')]))
        self.calls=[];self.hook=lambda label,env:None;self.probe_labels={'cargo-metadata'}
        self.commands=N(environment={'SYSTEMROOT':'synthetic-Windows'},run=self.command)
    def command(self,label,argv,cwd,*,environment,**kwargs):
        env=dict(environment);self.calls.append((label,list(argv),env,dict(kwargs)))
        folder=self.candidate/'process'/label;folder.mkdir(parents=True);out=folder/'stdout.bin';err=folder/'stderr.bin';terminal=folder/'terminal.json';err.write_bytes(b'');w.write_new(terminal,{'synthetic':True})
        raw=b'{}'
        if label=='rustc-version':raw=b'rustc synthetic\nrelease: 1.99.0\nhost: x86_64-pc-windows-msvc\n'
        elif label=='cargo-version':raw=b'cargo synthetic\n'
        elif label=='cargo-vendor':
            self.vendor.mkdir();(self.vendor/'lib.rs').write_bytes(b'synthetic vendor');raw=b'[source.crates-io]\nreplace-with="vendored-sources"\n'
        elif label=='cargo-build':
            target=Path(env['CARGO_TARGET_DIR']);self.assertEqual(target,self.target);self.assertEqual(list(target.iterdir()),[])
            sampler=target/'sample_viewmodel_clip.exe';sampler.write_bytes(b'nonexecutable fixture');(target/'sample_viewmodel_clip.d').write_bytes(b'synthetic depinfo')
            event={'reason':'compiler-artifact','target':{'name':'sample_viewmodel_clip','src_path':str(self.source/'main.rs')},'filenames':[str(sampler)],'executable':str(sampler)}
            raw=('\n'.join(json.dumps(row) for row in (event,{'reason':'build-finished','success':True}))+'\n').encode()
        if label in self.probe_labels:
            target=Path(env['CARGO_TARGET_DIR']);target.mkdir(parents=True,exist_ok=True);(target/(label+'.probe')).write_bytes(b'retained compiler probe')
        out.write_bytes(raw);self.hook(label,env)
        return {'stdout':w.record(out),'stderr':w.record(err),'terminal':w.file_pin(terminal)}
    def build(self):
        def selected(files,revision,features):
            self.assertEqual(files,self.before);self.assertEqual(revision,b.source_selection.REVISION);self.assertEqual(features,[])
        with patch.object(b.source_selection,'verify',side_effect=selected):return b.create_build(self.config,self.consumer,self.commands,self.candidate,{'host':'synthetic'})
    def test_metadata_probe_files_do_not_enter_actual_build_target(self):
        fp,sampler=self.build();result=w.strict_json(fp['path'])
        self.assertEqual([c[0] for c in self.calls],['rustc-version','cargo-version','cargo-vendor','cargo-metadata','cargo-build'])
        self.assertTrue((self.preparation/'cargo-metadata.probe').exists())
        self.assertEqual(result['target_directory'],str(self.target));self.assertEqual(result['dependency_closure']['roots'][0]['path'],str(self.vendor))
        self.assertEqual(len(result['dependency_closure']['roots']),1);self.assertEqual(result['source_files'],self.before)
        self.assertEqual(result['environment_sha256'],w.digest(self.calls[-1][2]))
        self.assertTrue(w.strict_json(result['build_process']['path'])['target_empty_before_build'])
        self.assertEqual(self.calls[-1][1][self.calls[-1][1].index('--target-dir')+1],str(self.target))
        self.assertEqual(w.sha(sampler['path']),sampler['sha256'])
    def test_all_preparation_commands_use_separate_same_owned_target(self):
        self.probe_labels={'rustc-version','cargo-version','cargo-vendor','cargo-metadata'};self.build()
        for label,argv,env,kwargs in self.calls[:-1]:
            self.assertEqual(env['CARGO_TARGET_DIR'],str(self.preparation));self.assertTrue((self.preparation/(label+'.probe')).is_file())
            self.assertEqual({k:v for k,v in env.items() if k!='CARGO_TARGET_DIR'},{k:v for k,v in self.calls[-1][2].items() if k!='CARGO_TARGET_DIR'})
        self.assertEqual(self.calls[-1][3],{'stdout_cap':64*1024**2,'reserve':2*w.GIB})
    def test_preexisting_preparation_directory_blocks_before_commands(self):
        self.preparation.mkdir();(self.preparation/'keep').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'fresh Rust'):self.build()
        self.assertEqual(self.calls,[]);self.assertEqual((self.preparation/'keep').read_bytes(),b'keep')
    def test_preexisting_final_directory_blocks_before_commands(self):
        self.target.mkdir()
        with self.assertRaisesRegex(ValueError,'fresh Rust'):self.build()
        self.assertEqual(self.calls,[])
    def test_source_overlap_with_derived_preparation_root_rejected(self):
        self.config['rust']['vendor_root']=str(self.preparation/'vendor')
        with self.assertRaisesRegex(ValueError,'overlap'):self.build()
        self.assertEqual(self.calls,[])
    def test_final_target_probe_contamination_keeps_exact_error_and_evidence(self):
        def hook(label,env):
            if label=='cargo-metadata':(self.target/'unexpected').write_bytes(b'keep')
        self.hook=hook
        with self.assertRaisesRegex(ValueError,'build target must be empty immediately before Cargo build') as caught:self.build()
        self.assertEqual(hashlib.sha256(str(caught.exception).encode()).hexdigest(),'da8f19c59c614a3b81a21f8dee101d3365af6b5140bcc58232bcf800e02bc238')
        self.assertEqual(self.calls[-1][0],'cargo-metadata');self.assertEqual((self.target/'unexpected').read_bytes(),b'keep')
    def replace(self,path,symlink=False):
        retained=path.with_name(path.name+'-retained');path.rename(retained)
        if symlink:path.symlink_to(retained,target_is_directory=True)
        else:path.mkdir()
    def test_replaced_final_target_blocks_before_build(self):
        self.hook=lambda label,env:self.replace(self.target) if label=='cargo-metadata' else None
        with self.assertRaisesRegex(ValueError,'replaced'):self.build()
        self.assertEqual(self.calls[-1][0],'cargo-metadata')
    def test_symlinked_final_target_blocks_before_build(self):
        self.hook=lambda label,env:self.replace(self.target,True) if label=='cargo-metadata' else None
        with self.assertRaisesRegex(ValueError,'symlink/reparse'):self.build()
        self.assertEqual(self.calls[-1][0],'cargo-metadata')
    def test_replaced_preparation_target_blocks_before_next_command(self):
        self.hook=lambda label,env:self.replace(self.preparation) if label=='cargo-vendor' else None
        with self.assertRaisesRegex(ValueError,'replaced'):self.build()
        self.assertEqual(self.calls[-1][0],'cargo-vendor')
    def test_symlinked_preparation_target_blocks_before_next_command(self):
        self.hook=lambda label,env:self.replace(self.preparation,True) if label=='cargo-vendor' else None
        with self.assertRaisesRegex(ValueError,'symlink/reparse'):self.build()
        self.assertEqual(self.calls[-1][0],'cargo-vendor')
    def test_source_mutation_during_preparation_blocks_before_build(self):
        self.hook=lambda label,env:(self.source/'main.rs').write_bytes(b'changed') if label=='cargo-metadata' else None
        with self.assertRaisesRegex(ValueError,'source changed during dependency preparation'):self.build()
        self.assertEqual(self.calls[-1][0],'cargo-metadata')
    def test_rerun_never_adopts_or_cleans_previous_roots(self):
        self.build();calls=len(self.calls);probe=(self.preparation/'cargo-metadata.probe').read_bytes()
        with self.assertRaisesRegex(ValueError,'fresh Rust'):self.build()
        self.assertEqual(len(self.calls),calls);self.assertEqual((self.preparation/'cargo-metadata.probe').read_bytes(),probe)

if __name__=='__main__':unittest.main(verbosity=2)
