"""CPU-only transport regressions using frozen real protocol implementations.

Only OwnedProcess execution is synthetic. No subprocess, native tool, private
asset, network, or claim of actual Windows execution is involved.
"""
import argparse,contextlib,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).absolute().parent))
import continuation_core as c

TRANSPORT_SHA='d9ef5486cbd7d80ec8d4c9d37c556ff7d13d8dc0147cbd7e6244a4154ca79751'
PRODUCER_SHA='8be8fd72f44e2baf160e5b86f01b835907396889dc78c4e811ff7818b7f3fd04'
ERROR_SHA='255c614ba75ddc6ba26bcb310ffa6f021ee9b7f27be300370ae5faa1974b8587'

def configure(orchestration,adapter,producer):
    global w,game_commands,real_adapter,evidence
    w=c.load_orchestration(Path(orchestration)).workflow_core
    w.package(Path(adapter),TRANSPORT_SHA,'transport');w.package(Path(producer),PRODUCER_SHA)
    real_adapter=w.modules(Path(adapter),('windows_job','owned_process')).owned_process
    evidence=w.modules(Path(producer),('pinned_code','process_evidence')).process_evidence
    game_commands=w.module('game_commands',Path(__file__).absolute().parent/'game_commands.py',{'workflow_core':w})

class GameCommandContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).absolute()
        self.candidate=self.root/'session/candidates/synthetic';self.candidate.mkdir(parents=True)
        self.python=self.root/'synthetic-python.exe';self.python.write_bytes(b'nonexecuted fixture')
        self.python_patch=patch.object(sys,'executable',str(self.python));self.python_patch.start()
        self.host={'runner_id':'synthetic','run_id':'contract','build_sha256':'a'*64,
                   'system':'Windows','release':'synthetic','version':'synthetic','machine':'AMD64'}
        self.environment={'SystemRoot':'C:\\Windows','contract_value':'space and Unicode é'}
    def tearDown(self):self.python_patch.stop();self.temp.cleanup()

    def command(self,mutation=None,environment=None,deadline_seconds=1800,validator=None):
        seen={}
        @contextlib.contextmanager
        def run(argv,cwd,limits,target,binding):
            target.mkdir();(target/'stdout.bin').write_bytes(b'');(target/'stderr.bin').write_bytes(b'')
            record={'completed':True,'windows_job_empty_verified':True,'command':argv,'cwd':str(cwd),'host_binding':binding.record()}
            if mutation:mutation(record)
            w.write_new(target/'terminal.json',record);seen.update(record=record,binding=binding,limits=limits)
            yield N(wait=lambda:None)
        def validate(adapter,target,expected):
            seen['expected']=expected
            evidence.exact(seen['record']['host_binding'],expected['host_binding'],'process host_binding')
            if validator:validator(adapter,target,expected)
        adapter=N(HostBinding=real_adapter.HostBinding,Limits=real_adapter.Limits,digest=real_adapter.digest,
                  OwnedProcess=N(run=run),verify_attempt=lambda *a,**k:seen['record'])
        result=game_commands.Commands(adapter,self.host,self.candidate,self.environment,validate).run(
            'synthetic',[sys.executable,'-I','-B','-c','pass'],self.candidate,
            environment=environment,deadline_seconds=deadline_seconds)
        return seen,result

    def test_exact_ci_error_is_old_transport_hash_domain_mismatch(self):
        with self.assertRaises(ValueError) as caught:
            evidence.exact({'environment_sha256':real_adapter.digest(self.environment)},
                           {'environment_sha256':w.digest(self.environment)},'process host_binding')
        self.assertEqual(hashlib.sha256(str(caught.exception).encode()).hexdigest(),ERROR_SHA)
    def test_expected_binding_matches_real_unchanged_adapter(self):
        seen,result=self.command()
        self.assertEqual(seen['expected']['host_binding'],seen['binding'].record())
        self.assertEqual(seen['expected']['host_binding']['environment_sha256'],real_adapter.digest(self.environment))
        self.assertEqual(result['environment_sha256'],w.digest(self.environment))
        self.assertNotEqual(result['environment_sha256'],real_adapter.digest(self.environment))
    def test_controller_command_context_hashes_remain_semantic(self):
        seen,result=self.command();context=w.strict_json(self.candidate/'contexts/synthetic-command.json')
        self.assertEqual(context['environment_sha256'],w.digest(self.environment))
        self.assertEqual(seen['binding'].context_sha256,w.digest(context))
        self.assertNotEqual(seen['binding'].context_sha256,real_adapter.digest(context))
        self.assertEqual(result['context'],w.file_pin(self.candidate/'contexts/synthetic-command.json'))
    def test_explicit_environment_override_uses_both_correct_domains(self):
        environment={**self.environment,'override':'different value'}
        seen,result=self.command(environment=environment)
        self.assertEqual(seen['binding'].environment,environment)
        self.assertEqual(seen['expected']['host_binding']['environment_sha256'],real_adapter.digest(environment))
        self.assertEqual(result['environment_sha256'],w.digest(environment))
        self.assertEqual(w.strict_json(self.candidate/'contexts/synthetic-command.json')['environment_sha256'],w.digest(environment))
    def test_capture_deadline_and_resource_limits_preserved(self):
        seen,_=self.command(deadline_seconds=600)
        self.assertEqual(seen['limits'].deadline_seconds,600)
        self.assertEqual(seen['limits'].rss_bytes,3*1024**3)
        self.assertEqual(seen['limits'].disk_floor_bytes,1024**3)
        self.assertEqual(seen['limits'].sample_seconds,.2)
        self.assertEqual(seen['expected']['limits']['deadline_seconds'],600)
    def test_default_deadline_preserved(self):
        seen,_=self.command();self.assertEqual(seen['limits'].deadline_seconds,1800)
    def test_mutated_environment_fingerprint_rejected(self):
        with self.assertRaisesRegex(ValueError,'process host_binding differs'):
            self.command(lambda r:r['host_binding'].update(environment_sha256='f'*64))
    def test_old_semantic_environment_hash_in_receipt_rejected(self):
        with self.assertRaisesRegex(ValueError,'process host_binding differs'):
            self.command(lambda r:r['host_binding'].update(environment_sha256=w.digest(self.environment)))
    def test_mutated_context_fingerprint_rejected(self):
        with self.assertRaisesRegex(ValueError,'process host_binding differs'):
            self.command(lambda r:r['host_binding'].update(context_sha256='f'*64))
    def test_authoritative_process_callback_failure_propagates(self):
        def reject(*args):raise ValueError('synthetic strict validator rejection')
        with self.assertRaisesRegex(ValueError,'strict validator rejection'):self.command(validator=reject)
    def test_noncompleted_or_nonempty_job_rejected(self):
        for key in ('completed','windows_job_empty_verified'):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError,'actual completed Windows owned command required'):
                    self.command(lambda r:r.update({key:False}))
                # Each rejected attempt must remain immutable; choose a fresh candidate.
                self.candidate=self.candidate.parent/(self.candidate.name+'-next');self.candidate.mkdir()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('orchestration','adapter','producer'):parser.add_argument('--'+name,required=True)
    args,rest=parser.parse_known_args()
    configure(args.orchestration,args.adapter,args.producer)
    unittest.main(argv=[sys.argv[0],*rest],verbosity=2)
