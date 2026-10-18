"""Tiny actual Windows Python-leaf regression before Blender/Rust installation.

This proves only the orchestration/owned-process receipt boundary. It is not
native animation, resource certification, runtime parity, or game admission.
"""
import argparse,hashlib,json,os,platform,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).absolute().parent
sys.path.insert(0,str(ROOT))
import workflow_core as w
import owned_commands
import verify_freeze

TRANSPORT_SHA='d9ef5486cbd7d80ec8d4c9d37c556ff7d13d8dc0147cbd7e6244a4154ca79751'
PRODUCER_SHA='ed4cf3ff99e94b8c86e4239c083689d4b86ef082ab08033719df0788a509033a'

def load_dependencies(adapter_root,producer_root):
    w.package(adapter_root,TRANSPORT_SHA,'transport')
    w.package(producer_root,PRODUCER_SHA)
    adapter=w.modules(adapter_root,('windows_job','owned_process')).owned_process
    producer=w.modules(producer_root,('pinned_code','process_evidence'))
    return adapter,producer.process_evidence

def run(output,event_commit):
    w.require(sys.platform=='win32' and platform.system()=='Windows','actual Windows command regression required')
    identity=verify_freeze.verify(ROOT)
    layout=w.strict_json(ROOT/'controller-layout.template.json')
    adapter,evidence=load_dependencies(ROOT.parent/layout['roots']['process_adapter'],ROOT.parent/layout['roots']['native_producer'])
    output=w.ordinary(output)
    w.require(not output.exists(),'fresh command regression output required')
    candidate=output/'session'/'candidates'/'contract'
    candidate.mkdir(parents=True)
    environment={'SystemRoot':os.environ['SystemRoot'],'PYTHONDONTWRITEBYTECODE':'1'}
    host={'runner_id':'source-command-contract','run_id':event_commit,
          **{k:getattr(platform,k)() for k in ('system','release','version','machine')},
          'build_sha256':w.digest({'scope':'synthetic command contract only','python':w.file_pin(sys.executable)})}
    command=[sys.executable,'-I','-B','-c',"import time; time.sleep(0.6); print('owned-command-contract')"]
    result=owned_commands.Commands(adapter,host,candidate,environment,evidence.verify_completed_process).run('python-contract',command,candidate)
    w.require(Path(result['stdout']['path']).read_bytes().replace(b'\r\n',b'\n')==b'owned-command-contract\n','contract output differs')
    return {'schema':'rust-duty-onehand-command-contract/v1','passed':True,
            'event_commit':event_commit,'orchestration_pins_sha256':identity['pins_sha256'],
            'process_terminal_sha256':result['terminal']['sha256'],
            'generic_python_subprocess_performed':True,'native_animation_execution_performed':False,
            'animation_proof':False,'private_raw_outputs_uploaded':False}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--event-commit',required=True);p.add_argument('--output',required=True);p.add_argument('--summary',required=True)
    a=p.parse_args(argv)
    try:value=run(a.output,a.event_commit)
    except Exception as exc:
        value={'schema':'rust-duty-onehand-command-contract/v1','passed':False,
               'event_commit':a.event_commit,'error_type':type(exc).__name__,
               'error_sha256':hashlib.sha256(str(exc).encode()).hexdigest(),
               'animation_proof':False,'private_raw_outputs_uploaded':False}
    w.write_new(a.summary,value,cap=128*1024)
    print(json.dumps(value,sort_keys=True));return 0 if value['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
