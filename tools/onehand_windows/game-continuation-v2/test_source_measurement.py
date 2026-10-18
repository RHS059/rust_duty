"""Source-only inventory regression tests; synthetic Git fixtures, no native work."""
import contextlib,copy,hashlib,io,json,os,shutil,subprocess,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import continuation_core as c
import game_source as s
import prepare_game_spec as helper
import measure_source_spec as m
HERE=Path(__file__).resolve().parent

class Fixture(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).absolute();self.git=Path(shutil.which('git')).absolute()
  self.repo=self.root/'game';self.jump=self.root/'jump';self.output=self.root/'evidence';self.output.mkdir();self.git_output=self.root/'github-output';self.git_output.touch()
  self.revision=self.make_repo(self.repo,{**{n:'original '+n+'\n' for n in s.ROOT_FILES},'src/lib.rs':'// original test source\n'})
  self.jump_revision=self.make_repo(self.jump,{m.JUMP_PATH:'synthetic source bytes only\n'})
  self.patches=contextlib.ExitStack()
  for module in (m,s,helper):self.patches.enter_context(patch.object(module,'JUMP_REF',self.jump_revision))
  event={'pull_request':{'head':{'sha':self.revision,'repo':{'full_name':m.REPOSITORY}},'base':{'repo':{'full_name':m.REPOSITORY}}}}
  self.event=self.root/'event.json';self.event.write_text(json.dumps(event))
  self.env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':m.REPOSITORY,'GITHUB_EVENT_NAME':'pull_request','PROOF_COMMIT':self.revision,'GITHUB_JOB':m.JOB,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'2','GITHUB_SHA':'1'*40,'GITHUB_WORKFLOW_SHA':'2'*40,'GITHUB_WORKFLOW_REF':m.REPOSITORY+'/.github/workflows/onehand-windows-proof.yml@refs/pull/78/merge','RUNNER_NAME':'fixture-runner','RUNNER_OS':'Windows','RUNNER_ARCH':'X64','GITHUB_EVENT_PATH':str(self.event)}
 def tearDown(self):self.patches.close();self.temp.cleanup()
 def make_repo(self,root,files):
  root.mkdir()
  for name,data in files.items():p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data if isinstance(data,bytes) else data.encode())
  def git(*args):return subprocess.check_output([str(self.git),'-C',str(root),*args],stderr=subprocess.PIPE)
  git('init','--quiet');git('add','.')
  hooks=self.root/'empty-hooks';hooks.mkdir(exist_ok=True)
  git('-c','core.hooksPath='+str(hooks),'-c','commit.gpgsign=false','-c','user.name=Source Test','-c','user.email=source-test@example.invalid','commit','--quiet','-m','source-only fixture')
  return git('rev-parse','HEAD').decode().strip()
 def prepare(self):
  args=['prepare_game_spec.py','--git',str(self.git),'--repository',str(self.repo),'--revision',self.revision,'--jump-repository',str(self.jump),'--output',str(self.output/m.SPEC)]
  with patch.object(sys,'argv',args),contextlib.redirect_stdout(io.StringIO()):helper.main()
  return c.read(self.output/m.SPEC)
 def audit(self,spec):return m.audit_spec(spec,self.git,self.repo,self.revision,self.jump)
 def export_fixture(self,change=None):
  import export_source_inventory as exporter
  payload={exporter.PREFIX+p.name:p.read_bytes() for p in HERE.iterdir() if p.is_file()}
  if change:change(payload,exporter.PREFIX)
  repo=self.root/'export-repo';revision=self.make_repo(repo,payload)
  return repo,revision
 def invoke_export(self,repo,revision,*extra):
  return subprocess.run([sys.executable,'-I','-B',str(HERE/'export_source_inventory.py'),'--git',str(self.git),'--repository',str(repo),'--event-commit',revision,'--package-pins-sha256',c.sha(HERE/'PINS.json'),'--output',str(self.root/'exported'),*extra],capture_output=True,timeout=30)
 def test_export_bootstrap_copies_exact_git_bytes(self):
  repo,revision=self.export_fixture();result=self.invoke_export(repo,revision)
  self.assertEqual(result.returncode,0,result.stdout);self.assertEqual(result.stderr,b'')
  for p in HERE.iterdir():
   if p.is_file():self.assertEqual(p.read_bytes(),(self.root/'exported'/p.name).read_bytes())
  self.assertFalse(json.loads(result.stdout)['native_admission_enabled_by_measurement'])
 def test_export_bootstrap_rejects_missing_package_member(self):
  repo,revision=self.export_fixture(lambda files,prefix:files.pop(prefix+'prepare_game_spec.py'));result=self.invoke_export(repo,revision)
  self.assertEqual(result.returncode,1);self.assertEqual(result.stderr,b'');self.assertFalse((self.root/'exported').exists());self.assertFalse(json.loads(result.stdout)['passed'])
 def test_export_bootstrap_rejects_forged_package_member(self):
  repo,revision=self.export_fixture(lambda files,prefix:files.update({prefix+'prepare_game_spec.py':b'private-marker'}));result=self.invoke_export(repo,revision)
  self.assertEqual(result.returncode,1);self.assertEqual(result.stderr,b'');self.assertNotIn('private-marker',result.stdout.decode());self.assertFalse((self.root/'exported').exists())
 def test_export_bootstrap_rejects_wrong_event_commit(self):
  repo,revision=self.export_fixture();result=self.invoke_export(repo,'0'*40)
  self.assertEqual(result.returncode,1);self.assertEqual(result.stderr,b'');self.assertFalse((self.root/'exported').exists())
 def test_export_bootstrap_unknown_mode_is_hash_only(self):
  repo,revision=self.export_fixture();result=self.invoke_export(repo,revision,'--private-marker')
  self.assertEqual(result.returncode,1);self.assertEqual(result.stderr,b'');self.assertNotIn('private-marker',result.stdout.decode());self.assertFalse((self.root/'exported').exists())
 def test_exact_export_and_independent_payload_reread(self):
  spec=self.prepare();stats=self.audit(spec);self.assertEqual(stats['files'],len(s.ROOT_FILES)+2);self.assertEqual(stats['jump']['ref'],self.jump_revision)
  for row in spec['files']:
   repo=self.jump if row['ref']==self.jump_revision else self.repo
   actual=(repo/row['repository_path']).read_bytes();self.assertEqual(row['sha256'],hashlib.sha256(actual).hexdigest());self.assertEqual(row['bytes'],len(actual))
 def test_partial_inventory_rejected(self):
  spec=self.prepare();spec['files'].pop(0)
  with self.assertRaises(ValueError):self.audit(spec)
 def test_forged_payload_sha_rejected(self):
  spec=self.prepare();spec['files'][0]['sha256']='0'*64
  with self.assertRaisesRegex(ValueError,'SHA256'):self.audit(spec)
 def test_forged_blob_id_rejected(self):
  spec=self.prepare();spec['files'][0]['git_blob_sha1']='0'*40
  with self.assertRaises(ValueError):self.audit(spec)
 def test_wrong_source_revision_rejected(self):
  spec=self.prepare();spec['revision']='0'*40
  with self.assertRaises(ValueError):self.audit(spec)
 def test_wrong_jump_ref_or_destination_rejected(self):
  for key,value in [('ref','3'*40),('destination','elsewhere.blend')]:
   spec=self.prepare() if not (self.output/m.SPEC).exists() else c.read(self.output/m.SPEC)
   next(r for r in spec['files'] if r['ref']==self.jump_revision)[key]=value
   with self.assertRaises(ValueError):self.audit(spec)
 def test_missing_jump_rejected(self):
  spec=self.prepare();spec['files']=[r for r in spec['files'] if r['ref']!=self.jump_revision]
  with self.assertRaises(ValueError):self.audit(spec)
 def test_duplicate_inventory_rejected(self):
  spec=self.prepare();spec['files'].append(copy.deepcopy(spec['files'][0]))
  with self.assertRaises(ValueError):self.audit(spec)
 def test_unknown_inventory_field_rejected(self):
  spec=self.prepare();spec['claimed_proof']=True
  with self.assertRaises(ValueError):self.audit(spec)
 def test_source_and_jump_checkout_heads_bound(self):
  got=m.git_identity(self.git,self.repo,self.revision,self.jump);self.assertEqual(got['game_source_commit'],self.revision);self.assertEqual(got['jump_source_commit'],self.jump_revision)
  with self.assertRaises(ValueError):m.git_identity(self.git,self.repo,'0'*40,self.jump)
  with self.assertRaises(ValueError):m.git_identity(self.git,self.repo,self.revision,self.repo)
 def test_actual_event_payload_bound(self):
  result=m.github_identity(self.env,self.revision);self.assertEqual(result['event_payload_sha256'],c.sha(self.event));self.assertEqual(result['run_id'],'123');self.assertEqual(result['run_attempt'],'2')
  event=json.loads(self.event.read_text());event['pull_request']['head']['sha']='0'*40;self.event.write_text(json.dumps(event))
  with self.assertRaises(ValueError):m.github_identity(self.env,self.revision)
 def test_environment_identity_mismatches_rejected(self):
  for key,value in [('GITHUB_REPOSITORY','other/repo'),('PROOF_COMMIT','0'*40),('GITHUB_RUN_ID',''),('GITHUB_RUN_ATTEMPT','0'),('GITHUB_JOB','other'),('RUNNER_NAME',''),('RUNNER_OS','Linux'),('GITHUB_WORKFLOW_SHA','branch'),('GITHUB_WORKFLOW_REF','unbound')]:
   with self.assertRaises(ValueError,msg=key):m.github_identity({**self.env,key:value},self.revision)
 def test_fork_payload_rejected(self):
  event=json.loads(self.event.read_text());event['pull_request']['head']['repo']['full_name']='foreign/fork';self.event.write_text(json.dumps(event))
  with self.assertRaises(ValueError):m.github_identity(self.env,self.revision)
 def test_complete_mocked_controller_retains_source_only_scope(self):
  # Host/tool observations are explicit test doubles. This is not Windows evidence.
  args=types.SimpleNamespace(git=str(self.git),repository=str(self.repo),event_commit=self.revision,jump_repository=str(self.jump),output_directory=str(self.output),github_output=str(self.git_output))
  package_sha=c.sha(HERE/'PINS.json');tools={'fixture_only':True}
  with patch.object(m.sys,'platform','win32'),patch.object(m.platform,'system',return_value='Windows'),patch.object(m,'observe_tools',return_value=tools),contextlib.redirect_stdout(io.StringIO()):receipt=m.run(args,HERE,package_sha,self.env)
  self.assertFalse(receipt['independently_accepted']);self.assertFalse(receipt['native_admission_enabled_by_measurement']);self.assertFalse(receipt['blender_or_cargo_launched']);self.assertFalse(receipt['candidate_generated']);self.assertFalse(receipt['raw_source_uploaded'])
  self.assertEqual(receipt['spec']['path'],m.SPEC);self.assertEqual(receipt['spec']['sha256'],c.sha(self.output/m.SPEC));self.assertEqual(receipt['actions']['event_head_commit'],self.revision)
  self.assertEqual(set(p.name for p in self.output.iterdir()),{m.SPEC,m.RECEIPT});self.assertIn('source_inventory_measured=true',self.git_output.read_text())
  self.assertNotIn(str(self.root),(self.output/m.RECEIPT).read_text())
 def test_inventory_changed_during_independent_audit_rejected(self):
  args=types.SimpleNamespace(git=str(self.git),repository=str(self.repo),event_commit=self.revision,jump_repository=str(self.jump),output_directory=str(self.output),github_output=str(self.git_output))
  original=m.audit_spec
  def mutate(*args):
   stats=original(*args);(self.output/m.SPEC).write_text('{}');return stats
  with patch.object(m.sys,'platform','win32'),patch.object(m.platform,'system',return_value='Windows'),patch.object(m,'observe_tools',return_value={}),patch.object(m,'audit_spec',side_effect=mutate),contextlib.redirect_stdout(io.StringIO()):
   with self.assertRaisesRegex(ValueError,'inventory changed'):m.run(args,HERE,c.sha(HERE/'PINS.json'),self.env)
  self.assertFalse((self.output/m.RECEIPT).exists());self.assertEqual(self.git_output.read_text(),'')
 def test_preexisting_output_rejected(self):
  (self.output/m.SPEC).write_text('{}')
  args=types.SimpleNamespace(git=str(self.git),repository=str(self.repo),event_commit=self.revision,jump_repository=str(self.jump),output_directory=str(self.output),github_output=None)
  with patch.object(m.sys,'platform','win32'),patch.object(m.platform,'system',return_value='Windows'),patch.object(m,'observe_tools',return_value={}):
   with self.assertRaisesRegex(ValueError,'fresh'):m.run(args,HERE,c.sha(HERE/'PINS.json'),self.env)

class BootstrapTests(unittest.TestCase):
 def invoke(self,*args):
  sha=c.sha(HERE/'PINS.json')
  return subprocess.run([sys.executable,'-I','-B',str(HERE/'execute_continuation.py'),'--package-pins-sha256',sha,*args],capture_output=True,timeout=30)
 def test_unknown_mode_is_hash_only_failure(self):
  result=self.invoke('--unknown-mode','private-marker');self.assertEqual(result.returncode,1);self.assertEqual(result.stderr,b'');value=json.loads(result.stdout)
  self.assertIs(value['passed'],False);self.assertIs(value['source_inventory_measured'],False);self.assertEqual(len(value['error_sha256']),64);self.assertNotIn('private-marker',result.stdout.decode())
 def test_partial_measurement_is_safe_failure(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).absolute();result=self.invoke('--measure-source','--output-directory',str(root))
   self.assertEqual(result.returncode,1);self.assertEqual(result.stderr,b'');self.assertEqual(set(p.name for p in root.iterdir()),{'game-source-spec-failure.json'});value=json.loads((root/'game-source-spec-failure.json').read_text());self.assertIs(value['game_capture_performed'],False);self.assertNotIn(str(root),result.stdout.decode())
 def test_combined_modes_rejected(self):
  result=self.invoke('--source-tests','--measure-source');self.assertEqual(result.returncode,1);self.assertEqual(result.stderr,b'');self.assertFalse(json.loads(result.stdout)['passed'])
 def test_fixed_jump_constant_has_no_cli_override(self):
  self.assertEqual(m.JUMP_REF,'e9317f90ea171976306e2f17c111325d948ea357')
  with self.assertRaises(ValueError):m.main(['--jump-ref','branch'],HERE,c.sha(HERE/'PINS.json'))
 def test_original_spec_helper_is_byte_identical(self):
  self.assertEqual(c.sha(HERE/'prepare_game_spec.py'),'9e173611d376a0dca3ae1806fba146b6be41614f555fa755a5246d5326a5ae01')
if __name__=='__main__':unittest.main(verbosity=2)
