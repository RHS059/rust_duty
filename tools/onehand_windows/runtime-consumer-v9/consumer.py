#!/usr/bin/env python3
"""Actual Windows leaf-Rust runtime proof, fresh map, focus and all67 chunks.

This version's production dependency gates remain fail closed. Low-level math
and validators are independently testable; no CLI fixture/native bypass exists.
"""
from __future__ import annotations
import argparse,json,os,time,sys,uuid
from pathlib import Path
import pinned_math as p
from runtime_context import RuntimeContext,capacity,record,check_record
import evidence,transport

SCHEMA='rust-duty-windows-runtime-proof/v1'

def write_new(ctx,path,value,cap=8*1024**2):
    path=ctx.cc.ordinary(path);p.require(path.is_relative_to(ctx.output),'output outside runtime proof root')
    p.require(not path.exists(),'preserve previous runtime receipt')
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode();p.require(len(raw)<=cap,'receipt cap');capacity(path,len(raw))
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return record(path)

def expected_frames(ctx,kind,index=None):
    if kind=='loading':return [1.,96.]
    if kind=='initialize':return [1.]
    if kind=='focus':return list(p.FOCUS)
    p.require(kind=='chunk' and type(index) is int and 0<=index<67,'chunk 0..66 required');return ctx.grid()[index*64:(index+1)*64]

def validate_records(m,records,selected,index=None):
    p.require([r.get('source_frame') for r in records]==selected,'record grid missing/duplicate/reordered')
    p.require([r.get('time_seconds') for r in records]==[(f-1)/60 for f in selected],'exact source clock differs')
    if index is not None:p.require([r.get('global_sample_index') for r in records]==list(range(index*64,index*64+len(selected))),'global row order differs')
    return m.summarize(records)

def raw_records(root,witness):
    return [record(p.bounded(root,d[k+'_path'])) for d in witness['frames'].values() for k in ('row','skin')]

def process_recheck(ctx,value,selected,environment):
    terminal=value['terminal'];path=check_record(terminal,ctx.cc,ctx.candidate_root)
    actual=transport.verify(ctx,selected,path.parent,environment,terminal['sha256']);p.exact(actual,value['record'],'retained process record');return actual

def load_receipt(ctx,name,kind):
    path=ctx.output/name;v=p.read(path)
    for k,want in {'schema':SCHEMA,'kind':kind,'binding':ctx.runtime_binding,'passed':True,'activation_authorized':False}.items():p.exact(v.get(k),want,'runtime receipt '+k)
    return v

def loading(ctx,m,environment):
    pack,bones,counts,rigid=evidence.load_runtime(ctx,m);frames=expected_frames(ctx,'loading')
    def inspect(i,row):m.validate_loading_row(row,frames[i],bones,counts,rigid,pack);return {'source_frame':frames[i],'finite_full_geometry':True}
    rows,process=transport.run(ctx,frames,'loading',environment,inspect)
    return {'source_frames':frames,'samples':2,'canonical_bones':72,'skins':3,'skin_vertices':10234,'actors':3,'all_rigid_geometry':True,'rows':rows,'process':process,'full_grid_parity':False}

def verify_loading(ctx,m,environment):
    v=load_receipt(ctx,'loading.json','loading');p.exact(v['source_frames'],[1.,96.],'loading endpoints');p.exact(v['samples'],2,'loading coverage');process_recheck(ctx,v['process'],[1.,96.],environment)
    pack,bones,counts,rigid=evidence.load_runtime(ctx,m)
    stdout=Path(v['process']['terminal']['path']).parent/'stdout.bin'
    with stdout.open('rb') as f:transport.exact_rows((p.loads(line) for line in f),2,lambda i,row:m.validate_loading_row(row,[1.,96.][i],bones,counts,rigid,pack))
    return v

def initialize(ctx,m,environment,input_path,input_sha):
    verify_loading(ctx,m,environment);native=evidence.inputs(ctx,input_path,input_sha,'initialize')
    source_root=native['source'][1];witness,invariants=evidence.source_index(ctx,m,source_root/'source-samples.json',[1.,96.])
    first,skin=m.load_row(source_root,next(iter(witness['frames'].values())),invariants['source_rest_world'])
    rigid_path=native['rigid'][1]/'rigid-frame1.json';rigid,geometry=evidence.rigid_frame1(ctx,m,rigid_path,first)
    pack,bones,counts,mesh=evidence.load_runtime(ctx,m);checker=m.Checker(pack,bones,counts,mesh,invariants,first,geometry)
    rows,process=transport.run(ctx,[1.],'initialize',environment,lambda i,row:checker.check(row,first,skin,anchor=True));summary=validate_records(m,rows,[1.])
    correspondence={name:v.value for name,v in checker.maps.items()}
    return {'inputs':record(input_path),'loading':record(ctx.output/'loading.json'),'source_index':record(source_root/'source-samples.json'),'rigid_frame1':record(rigid_path),'initial_raw':raw_records(source_root,witness),'invariants':invariants,'invariants_sha256':p.digest(invariants),'initial_source':first,'correspondence':correspondence,'correspondence_sha256':p.digest(correspondence),'runtime_rest_head_error_m':checker.rest_error,'records':rows,'summary':summary,'process':process,'full_grid_parity':False}

def verify_session(ctx,m,environment):
    v=load_receipt(ctx,'session.json','initialize');check_record(v['loading'],ctx.cc,ctx.output);verify_loading(ctx,m,environment)
    process_recheck(ctx,v['process'],[1.],environment)
    for item in (v['inputs'],v['source_index'],v['rigid_frame1'],*v['initial_raw']):check_record(item,ctx.cc,ctx.candidate_root)
    evidence.inputs(ctx,v['inputs']['path'],v['inputs']['sha256'],'initialize')
    p.exact(p.digest(v['invariants']),v['invariants_sha256'],'invariant digest');p.exact(p.digest(v['correspondence']),v['correspondence_sha256'],'mapping digest')
    root=Path(v['source_index']['path']).parent;w,invariants=evidence.source_index(ctx,m,v['source_index']['path'],[1.,96.],v['invariants_sha256']);initial,skin=m.load_row(root,next(iter(w['frames'].values())),invariants['source_rest_world'])
    p.exact(initial,v['initial_source'],'initial source');baseline,geometry=evidence.rigid_frame1(ctx,m,v['rigid_frame1']['path'],initial)
    pack,bones,counts,rigid=evidence.load_runtime(ctx,m);checker=m.Checker(pack,bones,counts,rigid,invariants,initial,geometry)
    with (Path(v['process']['terminal']['path']).parent/'stdout.bin').open('rb') as f:
        rows=transport.exact_rows((p.loads(line) for line in f),1,lambda i,row:checker.check(row,initial,skin,anchor=True))
    p.exact({n:x.value for n,x in checker.maps.items()},v['correspondence'],'fresh retained frame1 frozen maps');p.exact(rows,v['records'],'frame1 measured records');p.exact(validate_records(m,rows,[1.]),v['summary'],'frame1 summary')
    return v

def measure(ctx,m,environment,kind,index,input_path,input_sha):
    session=verify_session(ctx,m,environment)
    if kind=='chunk':verify_focus(ctx,m,environment,session)
    selected=expected_frames(ctx,kind,index);native=evidence.inputs(ctx,input_path,input_sha,kind,index);root=native['source'][1]
    witness,invariants=evidence.source_index(ctx,m,root/'source-samples.json',selected,session['invariants_sha256'])
    baseline,geometry=evidence.rigid_frame1(ctx,m,session['rigid_frame1']['path'],session['initial_source']);evidence.rigid_samples(native['rigid'][0],selected,baseline)
    fbx=evidence.source_fbx(ctx,m,native['fbx'][0],selected);pack,bones,counts,rigid=evidence.load_runtime(ctx,m)
    checker=m.Checker(pack,bones,counts,rigid,invariants,session['initial_source'],geometry,session['correspondence']);descriptors=list(witness['frames'].values())
    def consume(i,pose):
        source,skin=m.load_row(root,descriptors[i],invariants['source_rest_world']);row=checker.check(pose,source,skin)
        if kind=='chunk':row['global_sample_index']=index*64+i
        return row
    rows,process=transport.run(ctx,selected,'focus' if kind=='focus' else f'chunk-{index:03d}',environment,consume);summary=validate_records(m,rows,selected,index)
    result={'index':index,'source_frames':selected,'samples':len(selected),'inputs':record(input_path),'input_envelopes':{k:v[0] for k,v in native.items()},'session':record(ctx.output/'session.json'),'correspondence_sha256':session['correspondence_sha256'],'records':rows,'summary':summary,'source_fbx':fbx,'source_index':record(root/'source-samples.json'),'raw_files':raw_records(root,witness),'process':process,'thresholds':p.THRESHOLDS,'full_grid_parity':False,'off_key_source_frames':[f for f in selected if f*256!=int(f*256)]}
    if kind=='focus':result.update(distinct_focus_only=True,focus_counts_toward_grid=False)
    else:result['focus']=record(ctx.output/'focus.json')
    return result

def verify_raw(ctx,v,index):
    root=Path(v['source_index']['path']).parent;descriptor=p.read(check_record(v['source_index'],ctx.cc,ctx.candidate_root));selected=expected_frames(ctx,'chunk',index)
    p.require(list(descriptor['frames'])==[str(f) for f in selected],'retained raw descriptor ordering')
    expected=[]
    for i,(frame,row) in enumerate(zip(selected,descriptor['frames'].values())):
        p.exact(row['source_frame'],frame,'raw descriptor frame')
        for kind,folder,ext in [('row','sample-rows','json'),('skin','skin-rows','npz')]:
            rel=f'{folder}/{i:04d}.{ext}';p.exact(row[kind+'_path'],rel,'retirement exact row path');expected.append((str(p.bounded(root,rel)),row[kind+'_sha256']))
    p.require([(r['path'],r['sha256']) for r in v['raw_files']]==expected,'raw exact measured file set')
    exists=[Path(r['path']).exists() for r in v['raw_files']]
    if all(exists):
        for rec in v['raw_files']:check_record(rec,ctx.cc,root)
    else:
        p.require(not any(exists),'partial retirement retained as failure; never accepted')
        import retirement
        retirement.verify_retired(ctx,v,index)
    return all(exists)

def verify_native_retained(ctx,v):
    # Shared producer verification relaxes ONLY the exact independently retired
    # raw row inventory. All envelope/process/dependency checks stay identical.
    index=v['index'];p.require(type(index) is int and 0<=index<67,'retained chunk index')
    path=check_record(v['inputs'],ctx.cc,ctx.candidate_root)
    bundle=evidence.input_bundle(ctx,path,v['inputs']['sha256'],'chunk',index)
    ctx.cc.exact_keys(v['input_envelopes'],evidence.INPUT_ROLES['chunk'],'retained envelope roles')
    raw_present=verify_raw(ctx,v,index)
    retired=None
    if not raw_present:
        root=Path(v['source_index']['path']).parent
        retired={Path(r['path']).relative_to(root).as_posix():{k:r[k] for k in ('sha256','bytes')} for r in v['raw_files']}
    found={}
    for role,stage_name in evidence.INPUT_ROLES['chunk'].items():
        value,folder=evidence.stage(ctx,bundle['stages'][role],stage_name,index,retired_files=retired if role=='source' else None)
        p.exact(value,v['input_envelopes'][role],'retained native envelope unchanged');found[role]=value
        if role=='source':p.exact(str(folder/'source-samples.json'),v['source_index']['path'],'retained source index path')
    p.exact(found['fbx']['payload']['source_oracle_sha256'],found['source']['output_files']['source-samples.json']['sha256'],'retained FBX oracle linkage')
    p.exact(v['source_fbx'],found['fbx']['payload'],'retained measured source FBX report')
    return bundle

def validate_chunk(ctx,m,v,index,session,focus_sha):
    selected=expected_frames(ctx,'chunk',index)
    for k,want in {'schema':SCHEMA,'kind':'chunk','binding':ctx.runtime_binding,'passed':True,'activation_authorized':False,'index':index,'source_frames':selected,'samples':len(selected),'correspondence_sha256':session['correspondence_sha256'],'thresholds':p.THRESHOLDS,'full_grid_parity':False}.items():p.exact(v.get(k),want,'chunk '+k)
    p.exact(v['session']['sha256'],p.sha(ctx.output/'session.json'),'chunk session');p.exact(v['focus']['sha256'],focus_sha,'same-candidate independent focus')
    p.exact(v['summary'],validate_records(m,v['records'],selected,index),'chunk exact maxima');return v['records']

def verify_focus(ctx,m,environment,session):
    v=load_receipt(ctx,'focus.json','focus');p.exact(v['source_frames'],p.FOCUS,'nine focus');p.exact(v['off_key_source_frames'],p.FOCUS[1::2],'four offkeys');p.exact(v['distinct_focus_only'],True,'distinct focus');p.exact(v['focus_counts_toward_grid'],False,'focus grid separation')
    p.exact(v['correspondence_sha256'],session['correspondence_sha256'],'focus frozen map');check_record(v['session'],ctx.cc,ctx.output);p.exact(v['session']['sha256'],p.sha(ctx.output/'session.json'),'focus actual session')
    p.exact(v['summary'],validate_records(m,v['records'],p.FOCUS),'focus measured maxima');p.require(v['summary']['skin_vertex_observations']==92106 and v['summary']['canonical_bone_observations']==648,'focus complete counts')
    process_recheck(ctx,v['process'],p.FOCUS,environment)
    for r in v['raw_files']:check_record(r,ctx.cc,ctx.candidate_root)
    evidence.inputs(ctx,v['inputs']['path'],v['inputs']['sha256'],'focus');return v

def aggregate_records(ctx,m,reports,session,focus_sha):
    p.require(len(reports)==67,'all67 chunks required');rows=[]
    for index,value in enumerate(reports):rows.extend(validate_chunk(ctx,m,value,index,session,focus_sha))
    p.require([r['source_frame'] for r in rows]==ctx.grid() and [r['global_sample_index'] for r in rows]==list(range(4240)),'complete ordered4240 grid required')
    summary=m.summarize(rows);p.require(summary['skin_vertex_observations']==43392160 and summary['canonical_bone_observations']==4240*72 and summary['actor_visibility_checks']==4240*3,'complete full geometry counts')
    for value in reports:
        p.require(set(value['source_fbx']['maxima'])==set(p.FBX_KEYS),'FBX maxima coverage')
        for k,error in value['source_fbx']['maxima'].items():p.require(0<=p.finite_number(error,k)<1e-4,'FBX threshold')
        p.require(0<=p.finite_number(value['source_fbx']['camera_projection_ray_error'],'ray')<1e-5,'ray threshold')
    return {'samples':4240,'chunks':67,'source_frames':ctx.grid(),'source_fbx_bone_observations':4240*148,'summary':summary,'source_fbx_maxima':{k:max(v['source_fbx']['maxima'][k] for v in reports) for k in p.FBX_KEYS},'source_fbx_projection_ray_max':max(v['source_fbx']['camera_projection_ray_error'] for v in reports),'full_grid_parity':True,'scope':'CPU geometry on actual bound Windows Rust leaf sampler; no raster, gameplay, GL/DX12, art or activation claim'}

def aggregate(ctx,m,environment):
    session=verify_session(ctx,m,environment);verify_focus(ctx,m,environment,session);reports=[]
    for i in range(67):
        v=load_receipt(ctx,f'chunk-{i:03d}.json','chunk');check_record(v['session'],ctx.cc,ctx.output);check_record(v['focus'],ctx.cc,ctx.output)
        process_recheck(ctx,v['process'],expected_frames(ctx,'chunk',i),environment);raw_present=verify_raw(ctx,v,i);verify_native_retained(ctx,v)
        if raw_present:evidence.inputs(ctx,v['inputs']['path'],v['inputs']['sha256'],'chunk',i)
        evidence.source_fbx(ctx,m,v['input_envelopes']['fbx'],expected_frames(ctx,'chunk',i))
        reports.append(v)
    result=aggregate_records(ctx,m,reports,session,p.sha(ctx.output/'focus.json'));result['chunk_receipts']=[record(ctx.output/f'chunk-{i:03d}.json') for i in range(67)];result['focus']=record(ctx.output/'focus.json');return result

def retirement_plan(ctx,m,environment,index):
    session=verify_session(ctx,m,environment);verify_focus(ctx,m,environment,session);v=load_receipt(ctx,f'chunk-{index:03d}.json','chunk')
    validate_chunk(ctx,m,v,index,session,p.sha(ctx.output/'focus.json'));p.require(verify_raw(ctx,v,index),'chunk already retired');process_recheck(ctx,v['process'],expected_frames(ctx,'chunk',index),environment);verify_native_retained(ctx,v)
    # Independent second read/consume of the exact retained Rust byte stream.
    native=evidence.inputs(ctx,v['inputs']['path'],v['inputs']['sha256'],'chunk',index);root=native['source'][1]
    witness,invariants=evidence.source_index(ctx,m,root/'source-samples.json',expected_frames(ctx,'chunk',index),session['invariants_sha256'])
    baseline,geometry=evidence.rigid_frame1(ctx,m,session['rigid_frame1']['path'],session['initial_source']);evidence.rigid_samples(native['rigid'][0],expected_frames(ctx,'chunk',index),baseline)
    fbx=evidence.source_fbx(ctx,m,native['fbx'][0],expected_frames(ctx,'chunk',index));p.exact(fbx,v['source_fbx'],'reconsumed source FBX')
    checker=m.Checker(*evidence.load_runtime(ctx,m),invariants,session['initial_source'],geometry,session['correspondence']);descriptors=list(witness['frames'].values())
    def replay(i,pose):
        source,skin=m.load_row(root,descriptors[i],invariants['source_rest_world']);row=checker.check(pose,source,skin);row['global_sample_index']=index*64+i;return row
    with (Path(v['process']['terminal']['path']).parent/'stdout.bin').open('rb') as f:rows=transport.exact_rows((p.loads(line) for line in f),len(descriptors),replay)
    p.exact(rows,v['records'],'independent successful raw consumption');p.exact(m.summarize(rows),v['summary'],'independent maxima')
    files=v['raw_files'];p.require(len(files)==2*len(descriptors) and len({r['path'] for r in files})==len(files),'retirement exact files')
    for r in files:
        path=check_record(r,ctx.cc,root);p.require(path.parent in (root/'sample-rows',root/'skin-rows') and path.suffix in ('.json','.npz'),'raw-only retirement')
    return {'schema':'rust-duty-windows-raw-retirement-plan/v1','binding':ctx.runtime_binding,'index':index,'passed':False,'plan_only':True,'independently_reconsumed':True,'runtime_receipt_sha256':p.sha(ctx.output/f'chunk-{index:03d}.json'),'retired_files':files,'preserved_files':__import__('retirement').preserved_records(ctx,v,index),'original_source_deleted':False,'fbx_deleted':False,'runtime_deleted':False,'failed_evidence_deleted':False}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('context','context-sha256','context-package','environment'):parser.add_argument('--'+k,required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('loading','initialize','focus','chunk','aggregate','retirement-plan'):
        cmd=sub.add_parser(name)
        if name in ('initialize','focus','chunk'):
            cmd.add_argument('--inputs',required=True);cmd.add_argument('--inputs-sha256',required=True)
        if name in ('chunk','retirement-plan'):cmd.add_argument('--index',type=int,required=True)
    args=parser.parse_args(argv);ctx=None;started=None
    try:
        ctx=RuntimeContext.read(args.context,args.context_sha256,args.context_package);ctx.require_production();m=p.load(ctx.root('audited_source'));environment=ctx.cc.strict_json(args.environment)
        p.exact(p.digest(environment),ctx.raw['dependencies']['runtime_environment_sha256'],'runtime explicit environment')
        label={'initialize':'session','retirement-plan':f'retirement-plan-{getattr(args,"index",0):03d}'}.get(args.command,args.command)
        if args.command=='chunk':label=f'chunk-{args.index:03d}'
        target=ctx.output/(label+'.json');p.require(not target.exists() and not target.with_suffix('.failed.json').exists(),'preserve previous proof attempt');started=write_new(ctx,target.with_suffix('.started.json'),{'schema':SCHEMA,'kind':args.command,'binding':ctx.runtime_binding,'passed':False,'started_unix':time.time()})
        if args.command=='loading':result=loading(ctx,m,environment)
        elif args.command=='initialize':result=initialize(ctx,m,environment,args.inputs,args.inputs_sha256)
        elif args.command in ('focus','chunk'):result=measure(ctx,m,environment,args.command,getattr(args,'index',None),args.inputs,args.inputs_sha256)
        elif args.command=='aggregate':result=aggregate(ctx,m,environment)
        else:result=retirement_plan(ctx,m,environment,args.index)
        if args.command!='retirement-plan':result={'schema':SCHEMA,'kind':args.command,'binding':ctx.runtime_binding,'passed':True,'activation_authorized':False,**result}
        result['started_receipt']=started;ctx.verify_files();out=write_new(ctx,target,result);print(json.dumps(out,sort_keys=True));return 0
    except Exception as exc:
        if ctx is not None and started is not None:
            write_new(ctx,Path(started['path']).with_name(Path(started['path']).name.replace('.started.json','.failed.json')),{'schema':SCHEMA,'kind':args.command,'binding':ctx.runtime_binding,'passed':False,'error_type':type(exc).__name__,'error':str(exc)[:2048],'argv':sys.argv if argv is None else argv,'raw_private_evidence_runner_local':True,'raw_evidence_may_be_lost_on_runner_teardown':True,'started_receipt':started})
        print(json.dumps({'passed':False,'error':str(exc)[:2048]}));return 1

if __name__=='__main__':
    import sys
    raise SystemExit(main())
