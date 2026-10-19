"""Bounded source/negative-contract tests. No compiler, game, Blender, or network."""
import copy,hashlib,json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import continuation_core as c
import game_source as s
import game_plan as plan
import verify_dx12 as v
import run_continuation as run
import build_game
H='1'*64;R='1'*40
class CoreTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).absolute()
 def tearDown(self):self.temp.cleanup()
 def test_pin_and_atomic_new(self):
  rec=c.write_new(self.root/'a.json',{'x':1});self.assertEqual(c.read(c.pin(rec['path'],rec['sha256'])),{'x':1})
  with self.assertRaises(FileExistsError):c.write_new(self.root/'a.json',{})
 def test_read_duplicate(self):
  p=self.root/'a';p.write_text('{"x":1,"x":2}')
  with self.assertRaises(ValueError):c.read(p)
 def test_read_nonfinite(self):
  p=self.root/'a';p.write_text('{"x":NaN}')
  with self.assertRaises(ValueError):c.read(p)
 def test_read_cap(self):
  p=self.root/'a';p.write_text('{}')
  with self.assertRaises(ValueError):c.read(p,cap=1)
 def test_pin_rejects_changed(self):
  p=self.root/'a';p.write_bytes(b'x')
  with self.assertRaises(ValueError):c.pin(p,H)
 def test_relative_files_rejected(self):
  with self.assertRaises(ValueError):c.regular('a')
 def test_package_verifies_every_byte(self):
  p=self.root/'x.py';p.write_text('pass\n');rec=c.write_new(self.root/'PINS.json',{'x.py':c.sha(p)})
  c.verify_package(self.root,rec['sha256']);p.write_text('fail\n')
  with self.assertRaises(ValueError):c.verify_package(self.root,rec['sha256'])
 def test_package_rejects_unlisted_cache(self):
  p=self.root/'x.py';p.write_text('pass\n');rec=c.write_new(self.root/'PINS.json',{'x.py':c.sha(p)});(self.root/'extra').write_text('x')
  with self.assertRaises(ValueError):c.verify_package(self.root,rec['sha256'])
 def test_public_pin_patch_requires_exact_none_once(self):
  receipt={'source_fbx_sha256':H,'runtime_source_proof_sha256':H,**{'asset_'+x+'_sha256':H for x in ('vra','vrs','vrm')}}
  out=c.patch_runtime_pins('before\n'+c.PIN_LINE+'\nafter\n',receipt)
  self.assertIn('Some(RuntimePins {',out);self.assertIn(c.digest(receipt),out)
  self.assertEqual(out.split('const APPROVED')[0],'before\n');self.assertTrue(out.endswith('\nafter\n'))
  for source in ('',c.PIN_LINE+c.PIN_LINE,out):
   with self.assertRaises(ValueError):c.patch_runtime_pins(source,receipt)
 def test_manifest_keeps_every_base_line(self):
  original='ready=assets/base.vra\nwalk.clip=walk\n';out=c.candidate_manifest(original,H)
  self.assertTrue(out.startswith(original));self.assertIn(c.ACTION,out);self.assertIn('high_mantle.receipt_sha256='+H,out)
 def test_manifest_rejects_existing_optional_activations(self):
  for prefix in ('high_mantle.','low_vault.','prone_entry.'):
   with self.assertRaises(ValueError):c.candidate_manifest(prefix+'asset=x\n',H)
 def test_admission_ref_is_relative_and_pinned(self):
  a=self.root/'admission.json';a.write_text('{}');p=self.root/'spec.json';p.write_text('{}')
  self.assertEqual(run.admitted_file(a,{'path':'spec.json','sha256':c.sha(p)}),p)
  for name in ('../spec.json',str(p),'x\\y','C:/x','NUL'):
   with self.assertRaises(ValueError):run.admitted_file(a,{'path':name,'sha256':H})
 def test_null_admission_fails_before_any_proof(self):
  a=c.write_new(self.root/'admission.json',{'schema':'rust-duty-onehand-game-continuation-admission/v1','enabled':False})
  with self.assertRaisesRegex(ValueError,'inactive'):run.admit(a['path'],a['sha256'],H,R)
 def test_enabled_requires_actual_independent_review(self):
  a=c.write_new(self.root/'admission.json',{'schema':'rust-duty-onehand-game-continuation-admission/v1','enabled':True,'package_pins_sha256':H,'orchestration_pins_sha256':c.ORCHESTRATION_SHA,'game_source_revision':R,'game_source_spec':None})
  with self.assertRaises(ValueError):run.admit(a['path'],a['sha256'],H,R)

class SourceTests(unittest.TestCase):
 def test_delivery_and_source_inputs_selected(self):
  for name in ('assets/README.md','assets/animations.cfg','assets/source/reload/current.blend','assets/authoring/ads/ads.blend','src/lib.rs','updater/Cargo.lock','tools/package_game.py','tests/support/combined_presentation_cases.rs'):self.assertTrue(s.selected(name),name)
 def test_private_and_other_candidate_inputs_excluded(self):
  for name in ('.git/config','assets/onehand/asset.vra','assets/prone/asset.vra','private/raw.blend','tools/onehand_windows/game-admission-v1/admission.json'):self.assertFalse(s.selected(name),name)
 def test_windows_unsafe_paths_rejected(self):
  for name in ('','../x','x/../y','x//y','x\\y','/a','C:/a','x.','CON','nul.txt','dir/aux','x '):
   with self.assertRaises(ValueError,msg=name):s.logical(name)
 def test_current_closure_not_stale(self):
  with patch.object(s,'tree',side_effect=[{'src/a':'a'},{'src/a':'b'}]):
   with self.assertRaisesRegex(ValueError,'event head'):s.current_closure('git','repo',R,'2'*40)
 def test_admission_commit_may_preserve_source_closure(self):
  with patch.object(s,'tree',return_value={'src/a':'a'}):self.assertEqual(s.current_closure('git','repo',R,'2'*40),{'src/a':'a'})
 def test_generated_destinations_bounded(self):
  build_game.staging_changes_allowed({'src/a':H},{'src/a':H,'assets/reload/asset.vra':H})
  for name in ('src/a','Cargo.lock','assets/animations.cfg','assets/onehand/asset.vra'):
   with self.assertRaises(ValueError):build_game.staging_changes_allowed({}, {name:H})
 def test_empty_blob_is_supported(self):
  with patch.object(s,'git_run',side_effect=[b'0\n',b'']):self.assertEqual(s.blob('git','repo',R,'x',0),b'')
 def test_large_blob_rejected_before_git(self):
  with patch.object(s,'git_run') as git:
   with self.assertRaises(ValueError):s.blob('git','repo',R,'x',129*1024**2)
   git.assert_not_called()

class PlanTests(unittest.TestCase):
 def test_fresh_offline_exact_game_target(self):
  command=plan.cargo_command('cargo','target','game')
  for word in ('--locked','--offline','--release','--no-default-features','audio,legacy-macroquad,wgpu-runtime','x86_64-pc-windows-msvc','vector-range'):self.assertIn(word,command)
  self.assertEqual(c.FEATURES,['audio','legacy-macroquad','wgpu-runtime'])
  self.assertEqual(command[command.index('--features')+1],','.join(c.FEATURES))
  self.assertEqual(command.count('--features'),1)
 def test_sampler_keeps_original_no_default_no_audio_scope(self):
  self.assertEqual(plan.cargo_command('cargo','target','sampler'),['cargo','build','--locked','--offline','--release','--message-format=json','--target','x86_64-pc-windows-msvc','--target-dir','target','--no-default-features','--example','sample_viewmodel_clip'])
 def test_unknown_build_target_rejected(self):
  with self.assertRaises(ValueError):plan.cargo_command('cargo','target','other')
 def test_base_plan_exact_families_and_validation_before_stage(self):
  source=Path.cwd()/'fixture-source';jobs=plan.generator_plan(source,Path.cwd()/'fixture-work','python','blender','sampler')
  staged=[j for j in jobs if 'stage' in j];self.assertEqual([j['stage']['kind'] for j in staged],list(plan.KINDS))
  self.assertTrue(all('check_generated_assets.py' in ' '.join(j['argv']) for j in staged))
  self.assertIn('--require-generated',jobs[-1]['argv']);self.assertEqual(jobs[0]['label'],'game-base-materialize')
  self.assertIn(str(source/'.jump-source/assets/authoring/jump'),next(j['argv'] for j in jobs if j['label']=='game-base-jump-export'))
 def test_capture_is_dx12_native_deterministic(self):
  for hz in (30,60):
   command=plan.capture_command('exe','manifest','settings','out',H,hz)
   for flag in ('--renderer=dx12','--force-fallback-adapter','--capture-native-window','--onehand-deterministic','--capture-hz='+str(hz)):self.assertIn(flag,command)
   self.assertFalse(any('reference-viewport' in x or '--renderer=gl' in x for x in command))
  with self.assertRaises(ValueError):plan.capture_command('exe','m','s','o',H,120)

class CaptureTests(unittest.TestCase):
 def setUp(self):
  self.binding={'asset_sha256':H,'receipt_sha256':'2'*64,'return_seconds':.2}
  self.row={'kind':'frame','renderer_failed':False,'warning':v.KNOWN_BASE_WARNING,'high':{'seconds':.5},'candidate_visual':{'clip':c.ACTION,**{k:self.binding[k] for k in ('asset_sha256','receipt_sha256')},'renderer_failed':False,'warning':None,'pose':{'source_pose_seconds':.5}}}
  self.logs=['renderer requested=dx12 backend=Dx12 adapter='+v.WARP+'\nrenderer dx12_shader_compiler=Fxc\n']
  self.meta=[{'capture':'native window','requested':'dx12','backend':'Dx12','adapter':v.WARP,'width':1280,'height':720}]
 def test_candidate_actual_clip_and_pose(self):self.assertEqual(v.candidate_visual_rows([self.row],self.binding)['actual_sampled_frames'],1)
 def test_candidate_wrong_asset_receipt_clip(self):
  for key,value in [('clip','old'),('asset_sha256','3'*64),('receipt_sha256','4'*64),('warning','unexpected'),('renderer_failed',True)]:
   row=copy.deepcopy(self.row);row['candidate_visual'][key]=value
   with self.assertRaises(ValueError,msg=key):v.candidate_visual_rows([row],self.binding)
 def test_candidate_missing_or_wrong_pose(self):
  for value in (None,{'source_pose_seconds':.5001},{'source_pose_seconds':float('nan')},{'source_pose_seconds':True}):
   row=copy.deepcopy(self.row);row['candidate_visual']['pose']=value
   with self.assertRaises(ValueError):v.candidate_visual_rows([row],self.binding)
 def test_unknown_or_extended_main_warning_rejected(self):
  for warning in ('warning','',v.KNOWN_BASE_WARNING+'; optional admission failed'):
   row=copy.deepcopy(self.row);row['warning']=warning
   with self.assertRaises(ValueError):v.candidate_visual_rows([row],self.binding)
 def test_missing_candidate_or_main_failure_rejected(self):
  for key,value in [('candidate_visual',None),('renderer_failed',True)]:
   row=copy.deepcopy(self.row);row[key]=value
   with self.assertRaises(ValueError):v.candidate_visual_rows([row],self.binding)
 def test_actual_backend_pass(self):self.assertEqual(v.renderer_evidence(self.logs,self.meta)['backend'],'Dx12')
 def test_actual_backend_wrong_or_missing_rejected(self):
  for logs in ([],['renderer requested=gl backend=Gl adapter='+v.WARP],['renderer requested=dx12 backend=Vulkan adapter='+v.WARP]):
   with self.assertRaises(ValueError):v.renderer_evidence(logs,self.meta)
 def test_unknown_log_warning_rejected(self):
  for line in ('warning: unknown','error: bad','panic occurred','fallback to GL'):
   with self.assertRaises(ValueError):v.renderer_evidence(self.logs+[line],self.meta)
 def test_offscreen_or_wrong_metadata_rejected(self):
  for key,value in [('capture','offscreen'),('backend','Gl'),('requested','auto'),('adapter','GPU'),('width',1920),('height',0)]:
   meta=copy.deepcopy(self.meta);meta[0][key]=value
   with self.assertRaises(ValueError):v.renderer_evidence(self.logs,meta)
 def test_no_observations_rejected(self):
  with self.assertRaises(ValueError):v.candidate_visual_rows([],self.binding)
  with self.assertRaises(ValueError):v.renderer_evidence(self.logs,[])
 def test_original_strict_verifier_runs_first(self):
  original=types.SimpleNamespace(verify=lambda *args:(_ for _ in ()).throw(ValueError('strict original gate failed')))
  with self.assertRaisesRegex(ValueError,'strict original gate'):v.verify('/missing',self.binding,30,H,[],original)

class SameCandidateTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).absolute();self.files={}
  for role in ('vra','vrs','vrm','manifest','authored_admission','runtime_context','runtime_aggregate','rust_build'):
   p=self.root/role;p.write_bytes(role.encode());self.files[role]=types.SimpleNamespace(path=p,sha256=c.sha(p))
  self.binding={'candidate_id':'candidate-1','session_id':'run-123-attempt-2','generated_source_sha256':'3'*64,'actual_fbx_sha256':'4'*64,'runtime_context_sha256':self.files['runtime_context'].sha256}
  self.ctx=types.SimpleNamespace(runtime_binding=self.binding,raw={'candidate_id':'candidate-1','session_id':'run-123-attempt-2','private_root':str(self.root)},candidate_root=self.root/'run-123-attempt-2/candidates/candidate-1',pin=lambda role:self.files[role],context_sha256=self.files['runtime_context'].sha256,output=self.root/'proof')
  # Mirror serialized context bytes and the independent logical context digest.
  context_path=self.files['runtime_context'].path;context_path.write_bytes(c.canonical(self.ctx.raw))
  semantic=hashlib.sha256(json.dumps(self.ctx.raw,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
  self.files['runtime_context']=types.SimpleNamespace(path=context_path,sha256=c.sha(context_path))
  self.ctx.path=context_path;self.ctx.context_sha256=semantic;self.binding['runtime_context_sha256']=semantic
  self.ctx.output.mkdir();aggregate=self.ctx.output/'aggregate.json';aggregate.write_bytes(b'aggregate');self.files['runtime_aggregate']=types.SimpleNamespace(path=aggregate,sha256=c.sha(aggregate))
  self.env={'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'2','RUNNER_NAME':'runner-name'}
  self.cfg={'private_root':str(self.root),'session_id':'run-123-attempt-2','run_id':'run-123-attempt-2','candidate_id':'candidate-1','runner_id':'runner-'+hashlib.sha256(json.dumps('runner-name',sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]}
  self.ctx.host=types.SimpleNamespace(runner_id=self.cfg['runner_id'],run_id=self.cfg['run_id'])
  self.value={'schema':'rust-duty-onehand-private-capture-candidate/v1','binding':self.binding,'capture_ready_private_candidate':True,'target_source_to_rust_proved':True,'raw_private_evidence_runner_local':True,**{k:False for k in ('activation_authorized','game_capture_performed','game_capture_binding_reviewed','cross_platform_float64_equality_proved')},'runtime_assets':{k:{'path':str(self.files[k].path),'sha256':self.files[k].sha256} for k in ('vra','vrs','vrm','manifest')},**{k:{'path':str(self.files[k].path),'sha256':self.files[k].sha256} for k in ('runtime_context','runtime_aggregate','rust_build')},'approved_lineage_authored_admission':{'path':str(self.files['authored_admission'].path),'sha256':self.files['authored_admission'].sha256}}
 def tearDown(self):self.temp.cleanup()
 def test_same_live_identity_passes(self):c.validate_candidate(self.value,self.ctx,self.cfg,self.env)
 def test_foreign_run_attempt_or_runner_rejected(self):
  for key,value in [('GITHUB_RUN_ID','124'),('GITHUB_RUN_ATTEMPT','3'),('RUNNER_NAME','foreign')]:
   env={**self.env,key:value}
   with self.assertRaises(ValueError,msg=key):c.validate_candidate(self.value,self.ctx,self.cfg,env)
 def test_foreign_candidate_rejected(self):
  with self.assertRaises(ValueError):c.validate_candidate(self.value,self.ctx,{**self.cfg,'candidate_id':'other'},self.env)
 def test_foreign_asset_path_or_hash_rejected(self):
  for role in ('vra','vrs','vrm','manifest'):
   value=copy.deepcopy(self.value);value['runtime_assets'][role]['sha256']=H
   with self.assertRaises(ValueError,msg=role):c.validate_candidate(value,self.ctx,self.cfg,self.env)
   value=copy.deepcopy(self.value);value['runtime_assets'][role]['path']=str(self.root/'other')
   with self.assertRaises(ValueError,msg=role):c.validate_candidate(value,self.ctx,self.cfg,self.env)
 def test_changed_candidate_file_rejected(self):
  self.files['vra'].path.write_bytes(b'changed')
  with self.assertRaises(ValueError):c.validate_candidate(self.value,self.ctx,self.cfg,self.env)
 def test_foreign_context_runner_or_run_rejected(self):
  for key in ('runner_id','run_id'):
   old=getattr(self.ctx.host,key);setattr(self.ctx.host,key,'foreign')
   with self.assertRaises(ValueError,msg=key):c.validate_candidate(self.value,self.ctx,self.cfg,self.env)
   setattr(self.ctx.host,key,old)
 def test_foreign_controller_root_rejected(self):
  with self.assertRaises(ValueError):c.validate_candidate(self.value,self.ctx,{**self.cfg,'private_root':str(self.root/'other')},self.env)
 def test_foreign_build_or_authored_admission_path_rejected(self):
  for key in ('rust_build','approved_lineage_authored_admission'):
   value=copy.deepcopy(self.value);original=Path(value[key]['path']);other=self.root/('foreign-'+key);other.write_bytes(original.read_bytes());value[key]['path']=str(other)
   with self.assertRaises(ValueError,msg=key):c.validate_candidate(value,self.ctx,self.cfg,self.env)
 def test_prior_activation_claim_rejected(self):
  for key in ('activation_authorized','game_capture_performed','game_capture_binding_reviewed','cross_platform_float64_equality_proved'):
   value={**self.value,key:True}
   with self.assertRaises(ValueError,msg=key):c.validate_candidate(value,self.ctx,self.cfg,self.env)
 def test_high_receipt_keeps_approved_and_actual_identity_distinct(self):
  proof=types.SimpleNamespace(value=self.value,receipt={'sha256':'5'*64})
  receipt=c.high_receipt(proof)
  self.assertEqual(receipt['candidate_sha256'],c.APPROVED_SOURCE);self.assertEqual(receipt['approved_source_sha256'],c.APPROVED_SOURCE)
  self.assertEqual(receipt['generated_source_sha256'],self.binding['generated_source_sha256']);self.assertNotEqual(receipt['generated_source_sha256'],receipt['approved_source_sha256'])
  self.assertEqual(receipt['runtime_context_sha256'],self.ctx.context_sha256)
  self.assertEqual(receipt['runtime_source_proof_sha256'],self.files['runtime_aggregate'].sha256)
  self.assertEqual(receipt['runtime_manifest_sha256'],self.files['manifest'].sha256)
  self.assertEqual(receipt['candidate_receipt_sha256'],'5'*64)
  self.assertEqual(receipt['candidate_id'],self.cfg['candidate_id']);self.assertEqual(receipt['session_id'],self.cfg['session_id'])
  self.assertEqual(receipt['verification_sample_count'],4240);self.assertEqual(receipt['skin_vertex_observations'],43392160)
  self.assertEqual(receipt['candidate_frame_range'],[1,96]);self.assertEqual(receipt['native_crop'],[0,95]);self.assertEqual(receipt['subdivisions'],256)

 def test_context_file_and_semantic_hash_domains_are_distinct(self):
  raw=json.dumps(self.ctx.raw,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
  self.assertEqual(self.ctx.path.read_bytes(),raw+b'\n')
  self.assertEqual(self.ctx.context_sha256,hashlib.sha256(raw).hexdigest())
  self.assertEqual(self.value['runtime_context']['sha256'],hashlib.sha256(raw+b'\n').hexdigest())
  self.assertNotEqual(self.ctx.context_sha256,self.value['runtime_context']['sha256'])
  c.validate_candidate(self.value,self.ctx,self.cfg,self.env)
 def test_context_semantic_hash_cannot_replace_file_hash(self):
  value=copy.deepcopy(self.value);value['runtime_context']['sha256']=self.ctx.context_sha256
  with self.assertRaises(ValueError):c.validate_candidate(value,self.ctx,self.cfg,self.env)
 def test_foreign_same_byte_context_path_rejected(self):
  other=self.root/'foreign-context.json';other.write_bytes(self.ctx.path.read_bytes())
  self.assertEqual(c.sha(other),self.value['runtime_context']['sha256'])
  value=copy.deepcopy(self.value);value['runtime_context']['path']=str(other)
  with self.assertRaisesRegex(ValueError,'context receipt differs'):c.validate_candidate(value,self.ctx,self.cfg,self.env)
 def test_changed_context_bytes_rejected(self):
  self.ctx.path.write_bytes(self.ctx.path.read_bytes()+b' ')
  with self.assertRaises(ValueError):c.validate_candidate(self.value,self.ctx,self.cfg,self.env)
 def test_file_hash_cannot_replace_semantic_binding(self):
  value=copy.deepcopy(self.value);value['binding']['runtime_context_sha256']=value['runtime_context']['sha256']
  with self.assertRaisesRegex(ValueError,'candidate/context binding differs'):c.validate_candidate(value,self.ctx,self.cfg,self.env)
 def test_context_record_rejects_extra_fields(self):
  value=copy.deepcopy(self.value);value['runtime_context']['bytes']=self.ctx.path.stat().st_size
  with self.assertRaisesRegex(ValueError,'context receipt differs'):c.validate_candidate(value,self.ctx,self.cfg,self.env)
 def test_high_receipt_preserves_semantic_context_hash(self):
  proof=types.SimpleNamespace(value=self.value,receipt={'sha256':'5'*64})
  receipt=c.high_receipt(proof)
  self.assertEqual(receipt['runtime_context_sha256'],self.ctx.context_sha256)
  self.assertNotEqual(receipt['runtime_context_sha256'],self.value['runtime_context']['sha256'])


class FeatureContractTests(unittest.TestCase):
 def metadata(self):return {'packages':[{'id':'root','name':'vector-range'}],'resolve':{'root':'root','nodes':[{'id':'root','features':list(c.FEATURES)}]}}
 def artifact(self,features,target='vector-range',root='root'):
  return {'reason':'compiler-artifact','package_id':root,'features':features,'target':{'name':target},'executable':'actual-output.exe'}
 def test_game_metadata_preserves_explicit_audio_and_renderer(self):
  self.assertEqual(build_game.game_metadata_root(self.metadata()),'root')
 def test_game_metadata_rejects_missing_audio_or_renderer(self):
  for feature in c.FEATURES:
   metadata=self.metadata();metadata['resolve']['nodes'][0]['features'].remove(feature)
   with self.assertRaises(ValueError):build_game.game_metadata_root(metadata)
 def test_game_metadata_rejects_extra_duplicate_missing_feature_claims(self):
  for features in (None,[],c.FEATURES+['default'],c.FEATURES+['audio']):
   metadata=self.metadata();metadata['resolve']['nodes'][0]['features']=features
   with self.assertRaises(ValueError):build_game.game_metadata_root(metadata)
 def test_game_metadata_rejects_foreign_missing_or_duplicate_root(self):
  for mutate in (lambda m:m['resolve'].update(root=None),lambda m:m['packages'][0].update(name='foreign'),lambda m:m['resolve'].update(nodes=[]),lambda m:m['resolve']['nodes'].append(copy.deepcopy(m['resolve']['nodes'][0])),lambda m:m['packages'].append(copy.deepcopy(m['packages'][0]))):
   metadata=self.metadata();mutate(metadata)
   with self.assertRaises(ValueError):build_game.game_metadata_root(metadata)
 def test_actual_game_compiler_audio_features_pass(self):
  build_game.compiler_features([self.artifact(list(reversed(c.FEATURES)))],'root','vector-range',c.FEATURES)
 def test_actual_game_compiler_no_audio_is_rejected(self):
  with self.assertRaises(ValueError):build_game.compiler_features([self.artifact(['legacy-macroquad','wgpu-runtime'])],'root','vector-range',c.FEATURES)
 def test_actual_sampler_has_no_game_feature_claim(self):
  build_game.compiler_features([self.artifact([],'sample_viewmodel_clip')],'root','sample_viewmodel_clip',[])
  with self.assertRaises(ValueError):build_game.compiler_features([self.artifact(c.FEATURES,'sample_viewmodel_clip')],'root','sample_viewmodel_clip',[])
 def test_compiler_rejects_missing_extra_or_duplicate_features(self):
  for features in (None,[],c.FEATURES+['default'],c.FEATURES+['audio']):
   with self.assertRaises(ValueError):build_game.compiler_features([self.artifact(features)],'root','vector-range',c.FEATURES)
 def test_compiler_rejects_foreign_missing_or_duplicate_executable(self):
  for events in ([],[self.artifact(c.FEATURES,root='other')],[self.artifact(c.FEATURES,target='other')],[self.artifact(c.FEATURES),self.artifact(c.FEATURES)]):
   with self.assertRaises(ValueError):build_game.compiler_features(events,'root','vector-range',c.FEATURES)
 def test_every_root_artifact_requires_the_same_features(self):
  build_script=self.artifact([],'build-script-build');build_script['executable']=None
  with self.assertRaises(ValueError):build_game.compiler_features([build_script,self.artifact(c.FEATURES)],'root','vector-range',c.FEATURES)

if __name__=='__main__':unittest.main(verbosity=2)
