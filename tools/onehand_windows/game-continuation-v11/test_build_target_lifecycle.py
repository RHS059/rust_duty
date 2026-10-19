"""CPU-only game build-flow tests with fake commands; no compiler/native launch.

The real build function, inventories, feature checks, receipts and target-owner
helper execute. Native PE/dep-info validators and unrelated asset generation are
separately covered by their existing suites and are synthetic here.
"""
import argparse,contextlib,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).absolute().parent))
import continuation_core as c
import build_game as g

ORCHESTRATION=None

class GameBuildTargetLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).absolute();self.game=self.root/'game';self.game.mkdir();self.source=self.game/'source';self.source.mkdir()
        self.w=ORCHESTRATION.workflow_core;self.b=ORCHESTRATION.build_rust
        for name in g.MATH_FILES:
            path=self.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('synthetic '+name).encode())
        (self.source/'src/authored_high_mantle.rs').write_text(c.PIN_LINE+'\n');(self.source/'assets').mkdir();(self.source/'assets/animations.cfg').write_text('ready=assets/base.vra\n')
        self.math=self.w.inventory(self.source)
        records={}
        for name in ('cargo','rustc','manifest','linker'):
            path=self.root/name;path.write_bytes(('nonexecutable '+name).encode());records[name]=self.w.record(path)
        toolchain=self.root/'toolchain.json';self.w.write_new(toolchain,{'cargo':records['cargo'],'rustc':records['rustc'],'compiler_tools':[records['linker']]})
        self.cfg={'native_environment':{'SYSTEMROOT':'synthetic-Windows','PATH':'synthetic-path'},'rust':{'cargo':records['cargo']['path'],'rustc':records['rustc']['path'],'toolchain_receipt':str(toolchain),'rustup_manifest':records['manifest']['path'],'compiler_tool_files':[records['linker']['path']]},'roots':{'blender_bundle':str(self.root/'nonexecuted-blender')}}
        assets={}
        for role in ('vra','vrs','vrm'):
            path=self.root/('asset.'+role);path.write_bytes(('synthetic '+role).encode());assets[role]=self.w.file_pin(path)
        self.proof=N(cfg=self.cfg,orchestration=ORCHESTRATION,packages=N(consumer=N(pinned_math=N(read=lambda _:self.math,HERE=self.root),build_closure=N(dep_info_paths=lambda _:[],verify=self.verify_closure),runtime_context=N(pe_x64=lambda _:None))),ctx=N(cc=N()),value={'runtime_assets':assets},receipt={'path':'synthetic','sha256':'a'*64})
        self.runtime_receipt={'source_fbx_sha256':'b'*64,'runtime_source_proof_sha256':'c'*64,**{'asset_'+role+'_sha256':rec['sha256'] for role,rec in assets.items()}}
        self.target=self.game/'target';self.preparation=self.game/'preparation-target';self.sampler=self.game/'sampler-target';self.vendor=self.game/'vendor'
        self.calls=[];self.closures=[];self.hook=lambda label,env:None;self.commands=N(run=self.command);self.real_generators=False
    def verify_closure(self,ctx,build,closures,metadata,target):
        self.assertEqual([root for root,files in closures],[self.source,self.vendor]);self.closures.append(target);return {}
    def command(self,label,argv,cwd,*,environment,**kwargs):
        env=dict(environment);self.calls.append((label,list(argv),env,dict(kwargs)))
        folder=self.game/'process'/label;folder.mkdir(parents=True);out=folder/'stdout.bin';err=folder/'stderr.bin';terminal=folder/'terminal.json';err.write_bytes(b'');self.w.write_new(terminal,{'synthetic':True});raw=b'{}'
        target=Path(env['CARGO_TARGET_DIR'])
        if label=='game-rustc-version':raw=b'rustc synthetic\nrelease: 1.99.0\nhost: x86_64-pc-windows-msvc\n'
        elif label=='game-cargo-vendor':
            self.vendor.mkdir();(self.vendor/'lib.rs').write_bytes(b'synthetic vendor');raw=b'[source.crates-io]\nreplace-with="vendored-sources"\n'
        elif label=='game-license-notices':
            notices=self.source/'updater/notices';notices.mkdir(parents=True)
            for name in ('THIRD_PARTY_UPDATER_LICENSES.txt','UPDATER_DEPENDENCIES.json'):(notices/name).write_bytes(b'synthetic permitted notices')
        elif label=='game-cargo-metadata':raw=json.dumps({'packages':[{'id':'root','name':'vector-range'}],'resolve':{'root':'root','nodes':[{'id':'root','features':c.FEATURES}]}}).encode()
        if label in ('game-base-sampler-build','game-cargo-build'):
            self.assertEqual(target,self.sampler if label=='game-base-sampler-build' else self.target);self.assertEqual(list(target.iterdir()),[])
            name='sample_viewmodel_clip' if label=='game-base-sampler-build' else 'vector-range';exe=target/(name+'.exe');exe.write_bytes(b'nonexecutable fixture')
            artifact={'reason':'compiler-artifact','package_id':'root','target':{'name':name},'features':[] if label=='game-base-sampler-build' else c.FEATURES,'executable':str(exe)}
            raw=('\n'.join(json.dumps(row) for row in (artifact,{'reason':'build-finished','success':True}))+'\n').encode()
        else:
            target.mkdir(parents=True,exist_ok=True);(target/(label+'.probe')).write_bytes(b'retained compiler probe')
        if self.real_generators:
            for step in g.generator_plan(self.source,self.game/'base-production',sys.executable,Path(self.cfg['roots']['blender_bundle'])/'blender.exe',self.sampler/'sample_viewmodel_clip.exe'):
                stage=step.get('stage')
                if stage and label=='game-base-'+stage['kind']+'-export':
                    produced=Path(stage['source']);produced.mkdir(parents=True);(produced/'asset.vra').write_bytes(b'synthetic generated runtime')
        out.write_bytes(raw);self.hook(label,env)
        return {'stdout':self.w.record(out),'stderr':self.w.record(err),'terminal':self.w.file_pin(terminal)}
    def build(self):
        # The single fake generator models all generator_plan calls' common
        # environment path; production still iterates the unchanged full plan.
        generators=contextlib.nullcontext() if self.real_generators else patch.object(g,'generator_plan',return_value=[{'label':'game-base-fixture','argv':['nonexecuted-generator']}])
        with generators,patch.object(g,'high_receipt',return_value=self.runtime_receipt),patch.object(self.b,'compiler_report',return_value={'synthetic':True}),patch.object(ORCHESTRATION.host_tools,'verify_embedded',return_value={}):
            return g.build(self.source,self.game,self.proof,self.commands,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'},{'source_revision':'a'*40})
    def test_full_sampler_and_game_flow_isolates_all_preparation_files(self):
        build,fp,env=self.build()
        self.assertEqual([call[0] for call in self.calls],['game-rustc-version','game-cargo-vendor','game-license-notices','game-cargo-metadata','game-base-sampler-build','game-base-fixture','game-cargo-build'])
        for label,argv,actual,kwargs in self.calls:
            expected=self.sampler if label=='game-base-sampler-build' else self.target if label=='game-cargo-build' else self.preparation
            self.assertEqual(actual['CARGO_TARGET_DIR'],str(expected))
            if expected==self.preparation:self.assertTrue((expected/(label+'.probe')).is_file())
            else:
                self.assertEqual(argv[argv.index('--target-dir')+1],str(expected));self.assertEqual(kwargs,{'stdout_cap':64*1024**2,'reserve':2*1024**3})
            self.assertEqual({k:v for k,v in actual.items() if k!='CARGO_TARGET_DIR'},{k:v for k,v in env.items() if k!='CARGO_TARGET_DIR'})
        self.assertEqual(self.closures,[self.sampler,self.target]);self.assertEqual(build['environment_sha256'],self.w.digest(env));self.assertEqual(build['features'],c.FEATURES)
        self.assertEqual(build['dependency_closure']['roots'][0]['path'],str(self.vendor));self.assertEqual(len(build['dependency_closure']['roots']),1)
        self.assertTrue(c.read(build['build_process']['path'])['target_empty_before_build'])
        self.assertTrue(c.read(c.read(build['base_sampler_build']['path'])['build_process']['path'])['target_empty_before_build'])
        self.assertFalse(build['game_capture_performed']);self.assertEqual(c.sha(fp['path']),fp['sha256'])
    def test_every_real_generator_plan_step_uses_preparation_target(self):
        self.real_generators=True;build,fp,env=self.build()
        plan=g.generator_plan(self.source,self.game/'base-production',sys.executable,Path(self.cfg['roots']['blender_bundle'])/'blender.exe',self.sampler/'sample_viewmodel_clip.exe')
        self.assertEqual(len(plan),13);self.assertEqual([p['label'] for p in build['base_companion_processes']],[step['label'] for step in plan])
        for step in plan:
            calls=[call for call in self.calls if call[0]==step['label']];self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][1],step['argv']);self.assertEqual(calls[0][2]['CARGO_TARGET_DIR'],str(self.preparation))
            self.assertTrue((self.preparation/(step['label']+'.probe')).is_file())
            if 'stage' in step:self.assertEqual((Path(step['stage']['destination'])/'asset.vra').read_bytes(),b'synthetic generated runtime')
        self.assertEqual(self.closures,[self.sampler,self.target]);self.assertEqual(self.calls[-1][0],'game-cargo-build')
    def test_nested_license_metadata_uses_preparation_environment(self):
        self.build();license_call=next(call for call in self.calls if call[0]=='game-license-notices')
        self.assertEqual(license_call[2]['CARGO_TARGET_DIR'],str(self.preparation));self.assertTrue((self.preparation/'game-license-notices.probe').is_file())
    def test_sampler_build_keeps_no_default_features_and_game_audio_exact(self):
        self.build();sampler=next(call[1] for call in self.calls if call[0]=='game-base-sampler-build');game=self.calls[-1][1]
        self.assertIn('--no-default-features',sampler);self.assertNotIn('--features',sampler);self.assertEqual(game[game.index('--features')+1],','.join(c.FEATURES));self.assertIn('audio',c.FEATURES)
    def assert_preexisting_rejected(self,path):
        path.mkdir();(path/'keep').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'fresh game Cargo'):self.build()
        self.assertEqual(self.calls,[]);self.assertEqual((path/'keep').read_bytes(),b'keep')
    def test_preexisting_preparation_target_rejected(self):self.assert_preexisting_rejected(self.preparation)
    def test_preexisting_final_target_rejected(self):self.assert_preexisting_rejected(self.target)
    def test_preexisting_sampler_target_rejected(self):self.assert_preexisting_rejected(self.sampler)
    def contaminate(self,target,label):
        self.hook=lambda actual,env:(target/'unexpected').write_bytes(b'keep') if actual==label else None
    def test_metadata_contamination_of_final_target_rejected(self):
        self.contaminate(self.target,'game-cargo-metadata')
        with self.assertRaisesRegex(ValueError,'game target must be empty before actual build'):self.build()
        self.assertEqual(self.calls[-1][0],'game-base-fixture');self.assertEqual((self.target/'unexpected').read_bytes(),b'keep')
    def test_generator_contamination_of_final_target_rejected(self):
        self.contaminate(self.target,'game-base-fixture')
        with self.assertRaisesRegex(ValueError,'game target must be empty before actual build'):self.build()
        self.assertEqual(self.calls[-1][0],'game-base-fixture');self.assertEqual((self.target/'unexpected').read_bytes(),b'keep')
    def test_metadata_contamination_of_sampler_target_rejected(self):
        self.contaminate(self.sampler,'game-cargo-metadata')
        with self.assertRaisesRegex(ValueError,'sampler target must be empty before actual build'):self.build()
        self.assertEqual(self.calls[-1][0],'game-cargo-metadata');self.assertEqual((self.sampler/'unexpected').read_bytes(),b'keep')
    def replace(self,path,symlink=False):
        retained=path.with_name(path.name+'-retained');path.rename(retained)
        if symlink:path.symlink_to(retained,target_is_directory=True)
        else:path.mkdir()
    def assert_replacement_rejected(self,target,at,symlink=False):
        self.hook=lambda label,env:self.replace(target,symlink) if label==at else None
        with self.assertRaisesRegex(ValueError,'symlink/reparse' if symlink else 'replaced'):self.build()
        self.assertNotIn('game-cargo-build',[call[0] for call in self.calls])
    def test_replaced_final_target_rejected(self):self.assert_replacement_rejected(self.target,'game-base-fixture')
    def test_symlinked_final_target_rejected(self):self.assert_replacement_rejected(self.target,'game-base-fixture',True)
    def test_replaced_sampler_target_rejected(self):self.assert_replacement_rejected(self.sampler,'game-cargo-metadata')
    def test_symlinked_sampler_target_rejected(self):self.assert_replacement_rejected(self.sampler,'game-cargo-metadata',True)
    def test_replaced_preparation_target_rejected(self):self.assert_replacement_rejected(self.preparation,'game-license-notices')
    def test_symlinked_preparation_target_rejected(self):self.assert_replacement_rejected(self.preparation,'game-license-notices',True)
    def test_source_changed_by_metadata_rejected_before_sampler(self):
        self.hook=lambda label,env:(self.source/'src/asset.rs').write_bytes(b'changed') if label=='game-cargo-metadata' else None
        with self.assertRaisesRegex(ValueError,'source/dependency changed during metadata preparation'):self.build()
        self.assertEqual(self.calls[-1][0],'game-cargo-metadata')
    def test_dependency_changed_by_metadata_rejected_before_sampler(self):
        self.hook=lambda label,env:(self.vendor/'lib.rs').write_bytes(b'changed') if label=='game-cargo-metadata' else None
        with self.assertRaisesRegex(ValueError,'source/dependency changed during metadata preparation'):self.build()
        self.assertEqual(self.calls[-1][0],'game-cargo-metadata')
    def test_same_candidate_retry_does_not_reuse_or_remove_outputs(self):
        self.build();calls=len(self.calls);old=(self.preparation/'game-cargo-metadata.probe').read_bytes()
        with self.assertRaisesRegex(ValueError,'fresh game Cargo'):self.build()
        self.assertEqual(len(self.calls),calls);self.assertEqual((self.preparation/'game-cargo-metadata.probe').read_bytes(),old)

def main():
    global ORCHESTRATION
    parser=argparse.ArgumentParser();parser.add_argument('--orchestration',required=True);args=parser.parse_args()
    ORCHESTRATION=c.load_orchestration(Path(args.orchestration).absolute())
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(GameBuildTargetLifecycle)
    discovered=suite.countTestCases()
    if discovered!=19:raise ValueError("exact nineteen game target lifecycle regressions required")
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return int(not result.wasSuccessful() or bool(result.skipped) or result.testsRun!=discovered)

if __name__=='__main__':raise SystemExit(main())
