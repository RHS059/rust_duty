"""CPU/source-only regressions, including tiny local Git object fixtures."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
import checkout_bytes as c
import preinstall_admission as a
import source_checkout as s
import workflow_core as w

class Admission(unittest.TestCase):
    def template(self):return {'schema':a.SCHEMA,'orchestration_pins_sha256':None,'proof_inputs':None,'controller_layout':None,'independent_review':None}
    def full(self):
        v=self.template();v['orchestration_pins_sha256']='a'*64
        for k in ('proof_inputs','controller_layout','independent_review'):v[k]={'ref':'b'*40,'repository_path':'tools/onehand_windows/'+k+'.json','sha256':'c'*64,'bytes':2}
        return v
    def test_missing_is_explicit_blocked(self):self.assertEqual(a.admission_state(None),'blocked-incomplete-admission')
    def test_all_null_is_explicit_blocked(self):self.assertEqual(a.admission_state(self.template()),'blocked-incomplete-admission')
    def test_partial_is_failure(self):
        v=self.template();v['orchestration_pins_sha256']='a'*64
        with self.assertRaises(ValueError):a.admission_state(v)
    def test_malformed_null_is_failure(self):
        v=self.template();v['schema']='different'
        with self.assertRaises(ValueError):a.admission_state(v)
    def test_no_bool_execution_flag(self):
        v=self.full();v['allow_execution']=True
        with self.assertRaises(ValueError):a.admission_state(v)
    def test_full_needs_actual_input_verification(self):self.assertEqual(a.admission_state(self.full()),'requires-full-input-verification')
    def test_no_mutable_reference(self):
        v=self.full();v['proof_inputs']['ref']='main'
        with self.assertRaises(ValueError):a.admission_state(v)
    def acceptance(self):return {'schema':'rust-duty-onehand-workflow-independent-acceptance/v2','decision':'accepted-for-guarded-native-proof','orchestration_pins_sha256':'a'*64,'reviewed_dependencies_sha256':'b'*64,'blocking_findings':[],'animation_proof':False}
    def test_exact_independent_acceptance(self):a.verify_acceptance(self.acceptance(),'a'*64,'b'*64)
    def test_independent_package_mismatch(self):
        with self.assertRaises(ValueError):a.verify_acceptance(self.acceptance(),'c'*64,'b'*64)
    def test_blocking_independent_finding(self):
        v=self.acceptance();v['blocking_findings']=['unresolved']
        with self.assertRaises(ValueError):a.verify_acceptance(v,'a'*64,'b'*64)
    def test_review_cannot_claim_animation(self):
        v=self.acceptance();v['animation_proof']=True
        with self.assertRaises(ValueError):a.verify_acceptance(v,'a'*64,'b'*64)
    def test_expected_fetch_hash_not_observed(self):
        row={'ref':'a'*40,'repository_path':'x','bytes':2,'sha256':hashlib.sha256(b'{}').hexdigest()}
        self.assertEqual(a.checked_fetch(row,lambda *_:b'{}'),b'{}')
        with self.assertRaises(ValueError):a.checked_fetch(row,lambda *_:b'[]')

class RealGit(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir();self.git=shutil.which('git');self.assertTrue(self.git,'Git required for commit-type regression')
        self.env=dict(os.environ);self.env.update(GIT_AUTHOR_NAME='Synthetic Source Test',GIT_AUTHOR_EMAIL='source-test@example.invalid',GIT_COMMITTER_NAME='Synthetic Source Test',GIT_COMMITTER_EMAIL='source-test@example.invalid')
        self.command('init','--quiet');self.blob=self.command('hash-object','-w','--stdin',data=b'fixture\n').decode().strip();self.tree=self.command('mktree',data=('100644 blob '+self.blob+'\tx.py\n').encode()).decode().strip();self.commit=self.command('commit-tree',self.tree,data=b'synthetic source only\n').decode().strip()
    def tearDown(self):self.tmp.cleanup()
    def command(self,*args,data=None):return subprocess.run([self.git,'-C',str(self.repo),*args],input=data,capture_output=True,check=True,timeout=30,env=self.env).stdout
    def test_actual_commit_blob_roundtrip(self):self.assertEqual(c.git_blob_reader(self.git,self.repo)(self.commit,'x.py',8),b'fixture\n')
    def test_tree_cannot_masquerade_as_commit(self):
        with self.assertRaisesRegex(ValueError,'actual Git commit'):c.git_blob_reader(self.git,self.repo)(self.tree,'x.py',8)
    def test_blob_cannot_masquerade_as_commit(self):
        with self.assertRaisesRegex(ValueError,'actual Git commit'):c.git_blob_reader(self.git,self.repo)(self.blob,'x.py',8)
    def test_annotated_tag_rejected(self):
        raw=f'object {self.commit}\ntype commit\ntag synthetic\ntagger Synthetic <source-test@example.invalid> 1 +0000\n\nsynthetic\n'.encode();tag=self.command('hash-object','-w','-t','tag','--stdin',data=raw).decode().strip()
        with self.assertRaisesRegex(ValueError,'actual Git commit'):c.git_blob_reader(self.git,self.repo)(tag,'x.py',8)
    def commit_admission(self,value):
        path=self.repo/a.ADMISSION_PATH;path.parent.mkdir(parents=True);path.write_text(json.dumps(value));self.command('add','--',a.ADMISSION_PATH);tree=self.command('write-tree').decode().strip();return self.command('commit-tree',tree,data=b'synthetic admission only\n').decode().strip()
    def admission_cli(self,commit):
        work=self.root/'work';summary=self.root/'summary.json';outputs=self.root/'outputs.txt'
        run=subprocess.run([sys.executable,'-I','-B',str(w.HERE/'preinstall_admission.py'),'--git',self.git,'--repository',str(self.repo),'--event-commit',commit,'--work-root',str(work),'--summary',str(summary),'--github-output',str(outputs)],capture_output=True,timeout=30)
        return run,json.loads(summary.read_bytes()),outputs,work
    def test_missing_admission_cli_is_blocked_source_wip(self):
        run,value,outputs,work=self.admission_cli(self.commit);self.assertEqual(run.returncode,0,run.stdout);self.assertEqual(value['status'],'blocked-incomplete-admission');self.assertEqual(outputs.read_text(),'native_ready=false\n');self.assertFalse(value['animation_proof']);self.assertFalse((work/'full-materialized').exists())
    def test_null_admission_cli_is_blocked_source_wip(self):
        commit=self.commit_admission(Admission().template());run,value,outputs,work=self.admission_cli(commit);self.assertEqual(run.returncode,0,run.stdout);self.assertEqual(value['status'],'blocked-incomplete-admission');self.assertFalse((work/'full-materialized').exists())
    def test_partial_admission_cli_fails(self):
        v=Admission().template();v['orchestration_pins_sha256']='a'*64;commit=self.commit_admission(v);run,value,outputs,work=self.admission_cli(commit);self.assertEqual(run.returncode,1);self.assertEqual(value['status'],'failed');self.assertFalse(outputs.exists());self.assertFalse((work/'full-materialized').exists())
    def test_source_export_rejects_tree_event(self):
        with self.assertRaisesRegex(ValueError,'actual Git commit'):s.export(self.git,self.repo,self.tree,'x.py',1024)

class Workflow(unittest.TestCase):
    def test_same_repo_pr_event_with_real_stack_base(self):
        text=(w.HERE/'onehand-windows-proof.yml').read_text();self.assertIn('  pull_request:',text);self.assertIn('aella/combined-authored-transitions-20261016',text);self.assertIn('head.repo.full_name == github.repository',text);self.assertIn('ref: ${{ github.event.pull_request.head.sha }}',text);self.assertNotIn('workflow_dispatch:',text);self.assertNotIn('vars.',text)
    def test_tests_before_admission_before_installers(self):
        text=(w.HERE/'onehand-windows-proof.yml').read_text();self.assertLess(text.index('run_source_tests.py'),text.index('preinstall_admission.py'));self.assertLess(text.index('preinstall_admission.py'),text.index('install_official_blender.ps1'));self.assertEqual(text.count("if: ${{ steps.admission.outputs.native_ready == 'true' }}"),5)
    def test_source_test_report_has_no_animation_claim(self):
        text=(w.HERE/'run_source_tests.py').read_text();self.assertIn("'animation_proof':False",text);self.assertIn("'source_test_only':True",text);self.assertNotIn('reviewed_dependencies()',text)
    def test_bootstrap_hashes_match_actual_helpers(self):
        text=(w.HERE/'onehand-windows-proof.yml').read_text()
        for name in ('source_checkout.py','checkout_bytes.py'):self.assertIn(hashlib.sha256((w.HERE/name).read_bytes()).hexdigest(),text)
        self.assertEqual(s.MATERIALIZER_SHA,hashlib.sha256((w.HERE/'checkout_bytes.py').read_bytes()).hexdigest())

if __name__=='__main__':unittest.main()
