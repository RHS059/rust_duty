"""B1 correction regressions adapted from the independently pinned review.
Tiny copied/resealed fixtures only; no native child and no production admission.
"""
import copy,dataclasses,json,shutil,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path[:0]=[str(HERE),str(ROOT/'windows-native-producer-v4')]
import transport,pinned_math as p,runtime_context as rc,process_evidence
CC=p.context_module(ROOT/'windows-candidate-context-v2')
SMOKE=ROOT/'windows-smoke-38871908839/files/test_windows_normal_bytes_and_argument_roundtrip/attempt'
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n')
def ref(path):return {'path':path.name,'bytes':path.stat().st_size,'sha256':p.sha(path)}

class PairedProcessBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.candidate=Path(self.tmp.name);self.root=self.candidate/'process/runtime-test';shutil.copytree(SMOKE,self.root)
        self.records={n:p.read(self.root/(n+'.json')) for n in ('attempt','started','transport','terminal')};self.samples=[p.loads(s) for s in (self.root/'samples.jsonl').read_bytes().splitlines()]
        self.adapter=transport.load(ROOT/'windows-process-adapter-v2');self.frames=[1.];self.environment={'SystemRoot':r'C:\Windows'}
        sampler=self.candidate/'sampler.exe';sampler.write_bytes(b'CPU-synthetic-only-never-executed');vra=self.candidate/'asset.vra'
        python=self.candidate/'python.exe';python.write_bytes(b'CPU-synthetic-supervisor-never-executed')
        supervisor={**self.records['terminal']['supervisor_python'],'path':str(python),'sha256':p.sha(python),'bytes':python.stat().st_size}
        for value in self.records.values():value['supervisor_python']=copy.deepcopy(supervisor)
        host_file=self.candidate/'host.json';write(host_file,{'tools':{'python':{k:supervisor[k] for k in ('path','sha256')}}})
        paths={'sampler':sampler,'vra':vra,'host_binding':host_file};shas={k:p.sha(f) if f.exists() else 'b'*64 for k,f in paths.items()};shas['rust_build']='a'*64
        def pin(role):return N(path=paths.get(role,self.candidate/(role+'.json')),sha256=shas[role],verify=lambda:paths[role])
        self.ctx=N(cc=CC,candidate_root=self.candidate,host=N(runner_id='synthetic-runner',run_id='synthetic-run',expected_host=self.records['terminal']['host_binding']['observed_host']),context_sha256='c'*64,owner_lock=self.candidate/'owner.lock',root=lambda role:ROOT/({'process_adapter':'windows-process-adapter-v2','native_producer':'windows-native-producer-v4'}[role]),pin=pin,raw={'dependencies':{'producer_pins_sha256':rc.SELECTED_PRODUCER_PINS_SHA}})
        command=transport.command(self.ctx,self.frames);host=self.adapter.HostBinding(**transport.binding(self.ctx,self.environment)).record();limits=dataclasses.asdict(transport.limits(self.adapter,1))
        for record in self.records.values():record.update(command=command,cwd=str(self.candidate),host_binding=copy.deepcopy(host),limits=copy.deepcopy(limits))
        identity={**self.records['terminal']['executable_before'],'path':str(sampler),'sha256':p.sha(sampler),'bytes':sampler.stat().st_size}
        for name in ('started','transport','terminal'):self.records[name]['executable_before']=copy.deepcopy(identity)
        for name in ('transport','terminal'):self.records[name]['executable_after']=copy.deepcopy(identity)
        self.records['started']['initial_free_bytes']=2*1024**3
        term=self.records['terminal'];self.expected={k:copy.deepcopy(term[k]) for k in ('command','cwd','host_binding','limits','supervisor_python','rows')};self.expected['executable']=identity
    def tearDown(self):self.tmp.cleanup()
    def seal(self):
        sample=self.root/'samples.jsonl';data=''.join(json.dumps(s,separators=(',',':'))+'\n' for s in self.samples);sample.write_text(data.rstrip('\n') if getattr(self,'drop_final_newline',False) else data);sr=ref(sample)
        for n in ('transport','terminal'):self.records[n]['streams']['samples'].update(sr,observed_bytes=sr['bytes'],observed_sha256=sr['sha256'])
        write(self.root/'attempt.json',self.records['attempt']);ar=ref(self.root/'attempt.json')
        for n in ('started','transport','terminal'):self.records[n]['attempt']=copy.deepcopy(ar)
        write(self.root/'started.json',self.records['started']);st=ref(self.root/'started.json')
        for n in ('transport','terminal'):self.records[n]['started_record']=copy.deepcopy(st)
        write(self.root/'transport.json',self.records['transport']);self.records['terminal']['transport_record']=ref(self.root/'transport.json');write(self.root/'terminal.json',self.records['terminal']);write(self.root/'terminal.sha256.json',ref(self.root/'terminal.json'))
    def consumer(self):return transport.verify(self.ctx,self.frames,self.root,self.environment,p.sha(self.root/'terminal.json'))
    def producer(self):return process_evidence.verify_completed_process(self.adapter,self.root,self.expected)
    def test_positive_fixture_validates_both(self):
        self.seal();self.assertTrue(self.consumer()['completed']);self.assertTrue(self.producer()['record']['completed'])
    def check_gap(self,reason):
        self.seal()
        with self.assertRaises((ValueError,TypeError)):self.consumer()
        with self.assertRaises((ValueError,TypeError)):self.producer()
    def test_started_wrong_command_rejected_by_consumer(self):
        self.records['started']['command']=['contradictory-command'];self.check_gap('started command contradicts terminal')
    def test_attempt_wrong_context_rejected_by_consumer(self):
        self.records['attempt']['host_binding']['context_sha256']='e'*64;self.check_gap('attempt context contradicts admitted context')
    def test_transport_wrong_supervisor_rejected_by_consumer(self):
        self.records['transport']['supervisor_python']['sha256']='e'*64;self.check_gap('transport supervisor contradicts admitted host')
    def test_negative_elapsed_rejected_by_consumer(self):
        self.samples[0]['elapsed_seconds']=-.5;self.check_gap('negative resource elapsed time')
    def test_samples_after_process_end_rejected_by_consumer(self):
        self.samples[-1]['elapsed_seconds']=10.;self.check_gap('resource sample later than process duration')
    def test_terminal_deadline_overrun_rejected_by_consumer(self):
        self.records['terminal']['duration_seconds']=1800.;self.check_gap('terminal deadline reached despite success')
    def test_terminal_nonfinite_duration_rejected_by_consumer(self):
        self.records['terminal']['duration_seconds']=float('inf')
        self.seal()
        with self.assertRaises(RuntimeError):self.consumer()
    def test_extra_resource_field_rejected_by_consumer(self):
        self.samples[0]['untracked']=True;self.check_gap('resource row not exact schema')
    def test_rss_after_exit_rejected_by_consumer(self):
        self.samples[0]['rss_bytes']=None;self.check_gap('RSS observed again after exited-child null sample')
    def test_boolean_sample_count_rejected_by_consumer(self):
        self.samples=self.samples[:1]
        for name in ('transport','terminal'):self.records[name].update(sample_count=True,peak_sampled_rss_bytes=self.samples[0]['rss_bytes'])
        self.check_gap('boolean sample count accepted as integer one')
    def test_incomplete_final_resource_line_rejected_by_consumer(self):
        self.drop_final_newline=True;self.check_gap('last resource record lacks required newline')
    def test_producer_reports_observed_scheduling_gap_honestly(self):
        self.samples[-1]['elapsed_seconds']=.5
        for name in ('transport','terminal'):self.records[name].update(process_duration_seconds=.5,duration_seconds=.6)
        self.seal();resources=self.consumer()['retained_process_validation'];self.assertEqual(resources,self.producer()['resources']);self.assertGreater(resources['maximum_observed_gap_including_edges_seconds'],.2);self.assertTrue(resources['observed_gap_exceeds_requested_period']);self.assertIn('not a continuous-memory or real-time guarantee',resources['scope'])
    def test_empty_initial_memory_reserve_rejected_by_consumer(self):
        self.records['started']['initial_available_bytes']=0;self.check_gap('initial available-memory guard contradicted')

    def test_shared_reader_failure_is_not_bypassed(self):
        from unittest.mock import patch
        import evidence
        self.seal();api=evidence.producer(self.ctx)
        with patch.object(api,'verify_completed_process',side_effect=RuntimeError('shared-reader-rejected')),patch.object(evidence,'producer',return_value=api):
            with self.assertRaisesRegex(RuntimeError,'shared-reader-rejected'):self.consumer()
    def test_external_terminal_pin_required(self):
        self.seal()
        with self.assertRaises(ValueError):transport.verify(self.ctx,self.frames,self.root,self.environment)
    def test_wrong_expected_sampler_length_rejected(self):
        self.records['terminal']['executable_before']['bytes']+=1
        for n in ('started','transport'):self.records[n]['executable_before']['bytes']+=1
        for n in ('transport','terminal'):self.records[n]['executable_after']['bytes']+=1
        self.check_gap('actual expected sampler length')
    def test_wrong_expected_supervisor_length_rejected(self):
        for value in self.records.values():value['supervisor_python']['bytes']+=1
        self.seal()
        with self.assertRaises(ValueError):self.consumer()
    def test_actual_original_successful_windows_fixture_unchanged(self):
        expected_sha='2c1ac9ea61b7e9d8efa89f05bf9514f4fb5f50f8b7a8f9e19c0cb952c0e96acf';p.pin(SMOKE/'terminal.json',expected_sha)
        original=p.read(SMOKE/'terminal.json');expected={k:original[k] for k in ('command','cwd','host_binding','limits','supervisor_python','rows')};expected['executable']=original['executable_before']
        import evidence
        result=evidence.producer(self.ctx).verify_completed_process(self.adapter,SMOKE,expected)
        self.assertTrue(result['record']['completed']);self.assertEqual(result['resources']['sample_count'],3);self.assertEqual(result['resources']['requested_sample_period_seconds'],.02)
        self.assertIn('not a continuous-memory or real-time guarantee',result['resources']['scope']);p.pin(SMOKE/'terminal.json',expected_sha)
    def test_selected_producer_and_historical_review_pins(self):
        review=ROOT/'windows-proof-pair-review-v1';p.pin(review/'PINS.json',rc.PRODUCER_REVIEW_PINS_SHA);p.pin(review/'REVIEW.md',rc.PRODUCER_REVIEW_DOCUMENT_SHA)
        p.pin(ROOT/'windows-native-producer-v4/PINS.json',rc.SELECTED_PRODUCER_PINS_SHA)
        self.assertEqual(transport.limits(self.adapter,1).sample_seconds,.2)

if __name__=='__main__':unittest.main(verbosity=2)
