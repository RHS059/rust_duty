#!/usr/bin/env python3
"""Frozen owner-run fresh proof coordinator. Plans unless explicitly --run.

No artistic changes, graphics, parallel native jobs, threshold changes, builds or
publication. Only exact validated temporary source rows are explicitly retired.
The parent coordinator authorized that narrowly bounded retirement workflow.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
sys.dont_write_bytecode=True
from onehand_r2_common import *
import verify_onehand_r2 as parity
import run_chunk_r2 as chunks

PIN_PATH=HERE/'implementation-pins.json'
RESERVE=1024**3
ALLOWANCE=32*1024**2
PHASES=('source_fbx','rigid_source','rust_cpu','retirement_plan','retire')
NATIVE_LOCK=ROOT/'native-owner.lock'
STAGE_TIMEOUT_SECONDS=1800


@contextmanager
def exclusive_native_owner(path=NATIVE_LOCK):
    """Same exclusive-create protocol as the native owner; never steal a lock."""
    path=Path(path);token={'pid':os.getpid(),'started_unix':time.time(),'proof_root':str(WORK)}
    with path.open('x') as stream:
        json.dump(token,stream);stream.flush();os.fsync(stream.fileno())
        inode=os.fstat(stream.fileno()).st_ino
    try:
        yield token
    finally:
        require(path.exists() and not path.is_symlink() and path.stat().st_ino==inode,
                'native owner lock was removed/replaced; leave foreign lock untouched')
        require(read(path)==token,'native owner lock contents changed; leave untouched')
        path.unlink()


def session_digest():
    return sha(HERE/'session.json')


def durable_json(path,value):
    path=Path(path)
    require(path.resolve().is_relative_to(HERE),'coordinator output outside runtime-parity')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')
        stream.flush();os.fsync(stream.fileno())


def capacity(additional=ALLOWANCE,free=None):
    free=shutil.disk_usage(WORK).free if free is None else free
    require(type(free) is int and free>=RESERVE+additional,
            f'capacity floor: need {RESERVE+additional} bytes, have {free}')
    return free


def require_pins(expected,expected_session):
    pin(PIN_PATH,expected)
    pins=read(PIN_PATH)
    require(pins.get('schema')=='rust-duty-onehand-r2-implementation-pins/v1','r2 implementation pin schema differs')
    for relative,digest_value in pins['files'].items():pin(bounded(ROOT,relative),digest_value)
    load_candidate()
    pin(HERE/'session.json',expected_session)
    return pins


def command_plan(index,blender):
    frames(index)
    py=sys.executable
    common=[py,str(HERE/'verify_onehand_r2.py')]
    return [
        ('source_fbx',[py,str(HERE/'run_chunk_r2.py'),'--blender',str(blender),'--chunk-index',str(index),'--run']),
        ('rigid_source',[py,str(WORK/'native-rigid-v2/run_rigid.py'),'chunk','--blender',str(blender),
                         '--chunk-index',str(index),'--frame1-sha256',FRAME1_SHA,'--run']),
        ('rust_cpu',common+['consume','--chunk-index',str(index),'--rigid-chunk',str(WORK/'chunks'/f'chunk-{index:03d}'/'rigid-samples.json'),
                            '--rigid-process',str(WORK/'logs'/f'rigid-v2-chunk-{index:03d}'/'process-receipt.json')]),
        ('retirement_plan',common+['retire','--chunk-index',str(index)]),
        ('retire',common+['retire','--chunk-index',str(index),'--execute'])]


def validate_start(index,session):
    require(type(index) is int and 0<=index<=66,'fresh proof starts at a chunk from0 through66')
    parity.require_runtime_focus(session)
    chunks.previous_complete(index,session,HERE/'session.json')
    for current in range(index,67):
        for path in (WORK/'chunks'/f'chunk-{current:03d}',WORK/'logs'/f'chunk-{current:03d}',
                     WORK/'logs'/f'rigid-v2-chunk-{current:03d}',parity.report_path(current),
                     parity.retirement_path(current)):
            require(not path.exists(),'partial/existing future work requires coordinator inspection: '+str(path))
    require(not (HERE/'aggregate.json').exists(),'preserve existing aggregate')


class Runner:
    def __init__(self,directory,pins_sha,expected_session):
        self.directory=Path(directory);self.pins_sha=pins_sha;self.expected_session=expected_session
        self.directory.mkdir(parents=True,exist_ok=False)
        self.progress=self.directory/'progress.jsonl'
    def event(self,value):
        value={'unix':time.time(),**value}
        with self.progress.open('a') as stream:
            stream.write(json.dumps(value,separators=(',',':'),allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())
        print(json.dumps(value,separators=(',',':'),allow_nan=False),flush=True)
    def process(self,command,log):
        started=time.time();capacity();code=None;reserve_failure=None;timed_out=False
        environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        with Path(log).open('xb') as output:
            # A dedicated process group contains only this stage and its children.
            with subprocess.Popen(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,
                                  env=environment,start_new_session=True) as child:
                try:
                    while child.poll() is None:
                        if shutil.disk_usage(WORK).free<RESERVE or time.time()-started>STAGE_TIMEOUT_SECONDS:
                            timed_out=time.time()-started>STAGE_TIMEOUT_SECONDS
                            reserve_failure='stage timed out' if timed_out else '1 GiB floor crossed; stopped only this stage process group'
                            os.killpg(child.pid,signal.SIGTERM)
                            try:child.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                os.killpg(child.pid,signal.SIGKILL);child.wait()
                            break
                        time.sleep(1)
                    code=child.wait()
                finally:
                    if child.poll() is None:
                        os.killpg(child.pid,signal.SIGTERM)
                        try:child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid,signal.SIGKILL);child.wait()
            output.flush();os.fsync(output.fileno())
        return {'exit_code':code,'started_unix':started,'finished_unix':time.time(),
                'reserve_failure':reserve_failure,'timed_out':timed_out,'remaining_bytes':shutil.disk_usage(WORK).free}
    def stage(self,index,label,command,validator):
        require_pins(self.pins_sha,self.expected_session);capacity()
        tag=f'chunk-{index:03d}' if index is not None else 'aggregate'
        directory=self.directory/tag;directory.mkdir(exist_ok=True)
        start=directory/(label+'.started.json');receipt=directory/(label+'.receipt.json');log=directory/(label+'.log')
        require(not any(p.exists() for p in (start,receipt,log)),'refuse re-execution or overwrite of a partial stage')
        durable_json(start,{'chunk_index':index,'stage':label,'command':command,'pins_sha256':self.pins_sha,
                            'session_sha256':session_digest(),'started_unix':time.time(),'free_bytes':capacity()})
        self.event({'state':'started','chunk_index':index,'stage':label,'command':command})
        result={'command':command,'chunk_index':index,'stage':label,'passed':False,'validation':None}
        try:
            result.update(self.process(command,log))
            result['log']=parity.file_record(log)
            require(result['exit_code']==0 and result['reserve_failure'] is None,'stage process failed or reserve floor crossed')
            capacity(0);require_pins(self.pins_sha,self.expected_session)
            result['validation']=validator(log)
            result['passed']=True
        except BaseException as exc:
            result['error']=type(exc).__name__+': '+str(exc)
            if log.is_file():result['log']=parity.file_record(log)
            durable_json(receipt,result)
            self.event({'state':'failed','chunk_index':index,'stage':label,'receipt':str(receipt),'error':result['error']})
            raise
        durable_json(receipt,result)
        self.event({'state':'passed','chunk_index':index,'stage':label,'receipt_sha256':sha(receipt),
                    'remaining_bytes':result['remaining_bytes'],'validation':result['validation']})
        return result


def validate_native(index,session):
    path=safe_output(f'chunks/chunk-{index:03d}');fbx_sha=session['files']['fbx']['sha256']
    source,invariants=parity.source_index(path/'source-samples.json',frames(index),session['invariants_sha256'])
    parity.validate_export(path/'export-receipt.json',fbx_sha,frames(index),'sample',index)
    fbx=parity.validate_fbx(path/'fresh-import-parity.json',index,fbx_sha,sha(path/'source-samples.json'),sha(path/'export-receipt.json'))
    for label in ('sample','verify'):parity.process_record(WORK/'logs'/f'chunk-{index:03d}'/(label+'.exit.json'),blender=True)
    return {'source_fbx_passed':True,'source_samples_sha256':sha(path/'source-samples.json'),
            'fresh_import_sha256':sha(path/'fresh-import-parity.json'),'samples':len(frames(index)),
            'fbx_maxima':fbx['maxima'],'projection_ray_error':fbx['camera_projection_ray_error']}


def validate_rigid(index,session):
    path=safe_output(f'chunks/chunk-{index:03d}')/'rigid-samples.json'
    baseline=read(check_record_path(session['files']['rigid_frame1']))
    result=parity.rigid_chunk(path,index,baseline);receipt=parity.rigid_receipt(path,'chunk',index)
    for field,value in {'verification_method':'exact_float64_and_topology_bytes_vs_verified_frame1',
                        'frame1_witness_sha256':FRAME1_SHA}.items():
        require(result.get(field)==value,'optimized independent rigid witness differs: '+field)
        require(read(receipt['path']).get(field)==value,'optimized rigid receipt differs: '+field)
    parity.process_record(WORK/'logs'/f'rigid-v2-chunk-{index:03d}'/'process-receipt.json',blender=True)
    return {'independent_rigid_passed':True,'samples':len(frames(index)),'witness_sha256':sha(path),'receipt_sha256':receipt['sha256']}


def check_record_path(record):return parity.check_record(record)


def validate_cpu(index,session):
    report=read(parity.report_path(index));parity.validate_cpu_report(report,index,session,session_digest())
    return {'actual_rust_passed':True,'receipt_sha256':sha(parity.report_path(index)),
            'samples':report['samples'],'summary':report['summary']}


def inspect_retirement(index,session,log):
    value=read(log);require(value.pop('plan_only',None) is True,'explicit non-mutating retirement plan missing')
    expected=parity.retirement_plan(index,read(parity.report_path(index)),session,session_digest())
    require(value==expected,'printed retirement plan differs from freshly validated exact allow-list')
    require(value.get('passed') is False,'retirement plan must not claim deletion already happened')
    require(len(value['retired_files'])==2*len(frames(index)),'retirement allow-list count differs')
    return {'inspected':True,'plan_sha256':sha(log),'runtime_receipt_sha256':value['runtime_receipt_sha256'],
            'raw_files':len(value['retired_files']),'raw_bytes':sum(r['bytes'] for r in value['retired_files'])}


def validate_retired(index,session,plan_log):
    report=read(parity.report_path(index));parity.validate_cpu_report(report,index,session,session_digest())
    marker=read(parity.retirement_path(index));plan=read(plan_log)
    require(marker.get('passed') is True and marker.get('retired_files')==plan['retired_files'], 'retired files differ from inspected plan')
    require(marker.get('runtime_receipt_sha256')==sha(parity.report_path(index)), 'retirement actual-CPU receipt differs')
    require(marker.get('source_sha256')==SOURCE_SHA and marker.get('grid_sha256')==GRID_SHA,'retirement identity differs')
    require(not any(Path(row['path']).exists() for row in marker['retired_files']),'raw retirement partial')
    for row in marker['preserved_files']:parity.check_record(row)
    parity.load_session(HERE/'session.json');capacity(0)
    return {'retired':True,'retirement_sha256':sha(parity.retirement_path(index)),
            'runtime_receipt_sha256':sha(parity.report_path(index)),'raw_files':len(marker['retired_files'])}


def run_chunk(index,session,blender,runner):
    plans=command_plan(index,blender)
    validators={
        'source_fbx':lambda log:validate_native(index,session),
        'rigid_source':lambda log:validate_rigid(index,session),
        'rust_cpu':lambda log:validate_cpu(index,session),
        'retirement_plan':lambda log:inspect_retirement(index,session,log),
        'retire':lambda log:validate_retired(index,session,runner.directory/f'chunk-{index:03d}'/'retirement_plan.log'),
    }
    with exclusive_native_owner() as owner:
        runner.event({'state':'native_lock_acquired','chunk_index':index,'owner':owner})
        for label,command in plans[:2]:runner.stage(index,label,command,validators[label])
    runner.event({'state':'native_lock_released','chunk_index':index})
    for label,command in plans[2:]:runner.stage(index,label,command,validators[label])
    marker=parity.retirement_path(index);report=parity.report_path(index)
    checkpoint={'chunk_index':index,'passed':True,'session_sha256':session_digest(),
                'runtime_receipt_sha256':sha(report),'retirement_sha256':sha(marker),
                'samples':len(frames(index)),'skin_observations':len(frames(index))*10234}
    durable_json(runner.directory/f'chunk-{index:03d}'/'checkpoint.json',checkpoint)
    runner.event({'state':'chunk_complete',**checkpoint})
    return checkpoint


def validate_aggregate(session):
    actual=read(HERE/'aggregate.json')
    reports=[read(parity.report_path(i)) for i in range(67)]
    expected=parity.aggregate_reports(reports,session,session_digest())
    expected['chunk_receipts']=[parity.file_record(parity.report_path(i)) for i in range(67)]
    expected['focused_runtime_receipt']=parity.file_record(HERE/'focused-runtime.json')
    expected['rust_loading_preflight']=parity.file_record(parity.loading_path())
    require(actual==expected,'final aggregate differs from all independently revalidated receipts')
    return {'complete':True,'aggregate_sha256':sha(HERE/'aggregate.json'),'chunks':67,'samples':4240,
            'skin_observations':43392160,'summary':actual['summary']}


def execute(start,session,blender,runner):
    completed=[]
    for index in range(start,67):
        completed.append(run_chunk(index,session,blender,runner))
    result=runner.stage(None,'aggregate',[sys.executable,str(HERE/'verify_onehand_r2.py'),'aggregate'],
                        lambda log:validate_aggregate(session))
    return {'schema':'rust-duty-onehand-serial-completion/v2','passed':True,'completed_chunk_indices':list(range(start,67)),
            'session_sha256':session_digest(),'aggregate':result['validation'],'finished_unix':time.time()}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--blender',type=Path,required=True);p.add_argument('--pins-sha256',required=True)
    p.add_argument('--session-sha256',required=True)
    p.add_argument('--start-chunk',type=int,default=0);p.add_argument('--run',action='store_true')
    a=p.parse_args(argv);runner=None
    try:
        require(a.blender.is_absolute(),'inspected absolute Blender path required')
        require_pins(a.pins_sha256,a.session_sha256);session=parity.load_session(HERE/'session.json')
        require(sha(a.blender)==session['processes']['export']['record']['blender_sha256'],'Blender binary differs from admitted export')
        validate_start(a.start_chunk,session);capacity()
        directory=HERE/'serial-r2'/f'from-{a.start_chunk:03d}'
        require(not directory.exists(),'existing serial run preserved; inspect failure or use next fully retired boundary')
        plan={'run_requested':a.run,'start_chunk':a.start_chunk,'last_chunk':66,'chunks':67-a.start_chunk,
              'session_sha256':session_digest(),'pins_sha256':a.pins_sha256,'serial':True,'reserve_bytes':RESERVE,
              'native_owner_lock':str(NATIVE_LOCK),'native_lock_scope':'each source/FBX/rigid sequence, exclusive create; never steal',
              'stage_timeout_seconds':STAGE_TIMEOUT_SECONDS,'first_chunk_commands':command_plan(a.start_chunk,a.blender),'log_directory':str(directory),
              'retirement':'explicit exact CPU-pass allow-list, only new raw row files, after durable plan inspection',
              'final_aggregate_requires':{'chunks':67,'samples':4240,'skin_observations':43392160}}
        print(json.dumps(plan,indent=2),flush=True)
        if not a.run:return 0
        runner=Runner(directory,a.pins_sha256,a.session_sha256);durable_json(directory/'execution.json',plan)
        result=execute(a.start_chunk,session,a.blender,runner)
        durable_json(directory/'completion.json',result);runner.event({'state':'complete',**result});return 0
    except BaseException as exc:
        failure={'passed':False,'complete':False,'error':type(exc).__name__+': '+str(exc),'stopped_unix':time.time()}
        if runner is not None:
            durable_json(runner.directory/'failure.json',failure);runner.event({'state':'stopped',**failure})
        print(json.dumps(failure),file=sys.stderr,flush=True);return 1

if __name__=='__main__':raise SystemExit(main())
