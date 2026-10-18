"""Separately authorized exact successful raw-row deletion, never automatic.

The calling coordinator must verify user authorization for this exact plan hash
before invoking execute. An authorization reference is a trace, not a signature
or a claim that this module can determine who authorized the operation.
"""
import os,uuid
from pathlib import Path
import pinned_math as p
from runtime_context import capacity,check_record,record

FLAGS={'original_source_deleted':False,'fbx_deleted':False,'runtime_deleted':False,'failed_evidence_deleted':False}

def authorization_trace(value):
    p.require(type(value) is str and 1<=len(value)<=512 and '\0' not in value,'separately verified authorization reference required')

def preserved_records(ctx,report,index):
    return [record(ctx.output/f'chunk-{index:03d}.json'),report['inputs'],report['source_index'],report['session'],report['focus'],report['process']['terminal']]

def validate_plan(ctx,path,expected_sha,index,report,*,raw_present):
    """Read-only identity admission; never treats an authorization trace as permission."""
    c=ctx.cc;path=c.ordinary(path,existing=True)
    p.exact(str(path),str(ctx.output/f'retirement-plan-{index:03d}.json'),'fixed verified plan path');p.pin(path,expected_sha)
    value=p.read(path)
    c.exact_keys(value,('schema','binding','index','passed','plan_only','independently_reconsumed','runtime_receipt_sha256','retired_files','preserved_files','started_receipt',*FLAGS),'retirement plan')
    for k,v in {'schema':'rust-duty-windows-raw-retirement-plan/v1','binding':ctx.runtime_binding,'index':index,'passed':False,'plan_only':True,'independently_reconsumed':True,**FLAGS}.items():p.exact(value[k],v,'retirement plan '+k)
    p.require(type(index) is int and 0<=index<67,'retirement chunk')
    chunk=ctx.output/f'chunk-{index:03d}.json';p.pin(chunk,value['runtime_receipt_sha256']);p.exact(p.read(chunk),report,'retirement current chunk unchanged')
    for k,v in {'schema':'rust-duty-windows-runtime-proof/v1','kind':'chunk','binding':ctx.runtime_binding,'index':index,'passed':True,'activation_authorized':False}.items():p.exact(report.get(k),v,'successful retirement chunk '+k)
    p.exact(value['retired_files'],report['raw_files'],'exact successful raw file list')
    p.exact(value['preserved_files'],preserved_records(ctx,report,index),'exact preserved receipt records')
    for rec in value['preserved_files']:check_record(rec,c,ctx.candidate_root)
    start=check_record(value['started_receipt'],c,ctx.output);p.exact(str(start),str(path.with_suffix('.started.json')),'fixed plan started path')
    started=p.read(start);c.exact_keys(started,('schema','kind','binding','passed','started_unix'),'plan started receipt')
    for k,v in {'schema':'rust-duty-windows-runtime-proof/v1','kind':'retirement-plan','binding':ctx.runtime_binding,'passed':False}.items():p.exact(started[k],v,'plan start '+k)
    p.require(p.finite_number(started['started_unix'],'start time')>=0,'invalid plan start time')
    p.require(not path.with_suffix('.failed.json').exists(),'failed plan evidence cannot authorize retirement')
    root=Path(report['source_index']['path']).parent;names=[];identities=[]
    for rec in value['retired_files']:
        c.exact_keys(rec,('path','sha256','bytes'),'raw record');c.sha(rec['sha256']);p.require(type(rec['bytes']) is int and rec['bytes']>0,'raw byte count')
        f=c.ordinary(rec['path'],existing=raw_present);p.require(f.parent in (root/'sample-rows',root/'skin-rows') and f.suffix in ('.json','.npz'),'only generated row/skin files');names.append(str(f))
        if raw_present:
            check_record(rec,c,root);info=f.stat();p.require(info.st_nlink==1,'hardlinked raw row refused');identities.append((info.st_dev,info.st_ino))
        else:p.require(not f.exists(),'retired raw file unexpectedly present')
    p.require(len(names)==2*len(report['source_frames']) and len(set(names))==len(names),'exact unique raw row count')
    if raw_present:p.require(len(set(identities))==len(identities),'raw identity alias')
    return value

def validate_authorized_plan(ctx,plan,expected_sha,authorization_ref):
    authorization_trace(authorization_ref)
    path=ctx.cc.ordinary(plan,existing=True);p.pin(path,expected_sha);value=p.read(path);index=value['index']
    p.require(type(index) is int and 0<=index<67,'retirement chunk');p.exact(str(path),str(ctx.output/f'retirement-plan-{index:03d}.json'),'fixed verified plan path')
    report=p.read(ctx.output/f'chunk-{index:03d}.json')
    return validate_plan(ctx,path,expected_sha,index,report,raw_present=True)

def verify_retired(ctx,report,index):
    """Verify retained original plan, every preserved file and complete journal."""
    c=ctx.cc;target=ctx.output/'retirement'/f'chunk-{index:03d}.json';value=p.read(c.ordinary(target,existing=True))
    c.exact_keys(value,('schema','binding','passed','index','runtime_receipt_sha256','retired_files','verified_plan','authorization_ref','journal',*FLAGS),'retirement receipt')
    for k,v in {'schema':'rust-duty-windows-raw-retirement/v1','binding':ctx.runtime_binding,'passed':True,'index':index,'runtime_receipt_sha256':p.sha(ctx.output/f'chunk-{index:03d}.json'),'retired_files':report['raw_files'],**FLAGS}.items():p.exact(value[k],v,'retirement '+k)
    authorization_trace(value['authorization_ref'])
    plan=check_record(value['verified_plan'],c,ctx.output);validate_plan(ctx,plan,value['verified_plan']['sha256'],index,report,raw_present=False)
    journal=check_record(value['journal'],c,ctx.output);p.exact(str(journal),str(target.with_suffix('.plan.json')),'fixed retirement journal path')
    expected={'schema':'rust-duty-windows-raw-retirement-attempt/v1','binding':ctx.runtime_binding,'index':index,'runtime_receipt_sha256':value['runtime_receipt_sha256'],'verified_plan':value['verified_plan'],'authorization_ref':value['authorization_ref'],'retired_files':value['retired_files'],'passed':False}
    p.exact(p.read(journal),expected,'complete retained retirement journal')
    p.require(not target.with_suffix('.failed.json').exists(),'failed retirement cannot be admitted')
    return value

def execute(ctx,m,environment,plan,expected_sha,authorization_ref):
    import consumer
    ctx.require_production();capacity(ctx.output)
    value=validate_authorized_plan(ctx,plan,expected_sha,authorization_ref);index=value['index']
    # Full independent reconsumption is checked again before any deletion.
    regenerated=consumer.retirement_plan(ctx,m,environment,index)
    given={k:v for k,v in value.items() if k!='started_receipt'};p.exact(given,regenerated,'verified plan unchanged')
    target=ctx.output/'retirement'/f'chunk-{index:03d}.json';p.require(not target.exists(),'prior retirement preserved')
    lock=ctx.cc.ordinary(ctx.owner_lock);token=(uuid.uuid4().hex+'\n').encode()
    with lock.open('xb') as f:f.write(token);f.flush();os.fsync(f.fileno());owner=os.fstat(f.fileno())
    journal=None
    try:
        journal=consumer.write_new(ctx,target.with_suffix('.plan.json'),{'schema':'rust-duty-windows-raw-retirement-attempt/v1','binding':ctx.runtime_binding,'index':index,'runtime_receipt_sha256':value['runtime_receipt_sha256'],'verified_plan':record(plan),'authorization_ref':authorization_ref,'retired_files':value['retired_files'],'passed':False})
        for rec in value['retired_files']:
            capacity(ctx.output);f=check_record(rec,ctx.cc,ctx.candidate_root);f.unlink()
        p.require(all(not Path(r['path']).exists() for r in value['retired_files']),'partial raw retirement is failure')
        result={'schema':'rust-duty-windows-raw-retirement/v1','binding':ctx.runtime_binding,'passed':True,'index':index,'runtime_receipt_sha256':value['runtime_receipt_sha256'],'retired_files':value['retired_files'],'verified_plan':record(plan),'authorization_ref':authorization_ref,'journal':journal,'original_source_deleted':False,'fbx_deleted':False,'runtime_deleted':False,'failed_evidence_deleted':False}
        return consumer.write_new(ctx,target,result)
    except BaseException as exc:
        if journal is not None:consumer.write_new(ctx,target.with_suffix('.failed.json'),{'schema':'rust-duty-windows-raw-retirement-failure/v1','binding':ctx.runtime_binding,'passed':False,'journal':journal,'error':type(exc).__name__+': '+str(exc)[:1024],'partial_retirement_requires_inspection':True})
        raise
    finally:
        ctx.cc.ordinary(lock,existing=True);info=lock.stat();p.require((info.st_dev,info.st_ino)==(owner.st_dev,owner.st_ino) and lock.read_bytes()==token,'foreign owner replacement preserved');lock.unlink()

def main(argv=None):
    import argparse,json
    from runtime_context import RuntimeContext
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('context','context-sha256','context-package','environment','verified-plan','plan-sha256','authorization-ref'):parser.add_argument('--'+k,required=True)
    parser.add_argument('--execute-authorized',action='store_true',required=True)
    a=parser.parse_args(argv)
    try:
        ctx=RuntimeContext.read(a.context,a.context_sha256,a.context_package);ctx.require_production();m=p.load(ctx.root('audited_source'));env=ctx.cc.strict_json(a.environment)
        p.exact(p.digest(env),ctx.raw['dependencies']['runtime_environment_sha256'],'explicit runtime environment')
        result=execute(ctx,m,env,a.verified_plan,a.plan_sha256,a.authorization_ref);print(json.dumps(result));return 0
    except Exception as exc:print(json.dumps({'passed':False,'error':type(exc).__name__+': '+str(exc)[:2048]}));return 1
if __name__=='__main__':raise SystemExit(main())
