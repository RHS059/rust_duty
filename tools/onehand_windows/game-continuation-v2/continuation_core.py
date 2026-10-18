"""Fail-closed same-job continuation primitives. No native work at import time."""
from __future__ import annotations
import hashlib,json,os,re,stat,types,sys
from pathlib import Path

ORCHESTRATION_SHA='2a39125dba25460e66d0f76ef6c871d2abb01e64073b7e419e1c1892345bdee5'
APPROVED_SOURCE='b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77'
ACTION='aella_mantle_onehand_r6_camera_reconstructed_v6'
ACTION_FINGERPRINT='c7ca6383364e055afe1d0246f443d33689ce86c56677570ba694a924c983ea01'
GRID='a521b1e779e45f85948d94b8b9aa9f9cad41d935783ba5fcbda34decb6aec08f'
PIN_LINE="const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = None;"
TARGET='x86_64-pc-windows-msvc'
FEATURES=['legacy-macroquad','wgpu-runtime']

def need(ok,message):
    if not ok:raise ValueError(message)

def sha_bytes(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
def digest(value):return sha_bytes(canonical(value))
def digest_value(value):
    need(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None,'exact SHA256 required');return value

def regular(path):
    p=Path(path)
    need(p.is_absolute() and '..' not in p.parts,'absolute ordinary path required')
    for part in (*reversed(p.parents),p):
        if part.exists() or part.is_symlink():
            s=part.lstat();need(not stat.S_ISLNK(s.st_mode) and not getattr(s,'st_file_attributes',0)&0x400,'redirected path forbidden')
    need(p.is_file(),'regular file missing');return p

def sha(path):
    p=regular(path)
    with p.open('rb') as f:
        a=os.fstat(f.fileno());h=hashlib.file_digest(f,'sha256').hexdigest();b=os.fstat(f.fileno())
    need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)==(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns),'file changed while hashing')
    return h

def pin(path,expected):need(sha(path)==digest_value(expected),'file identity differs: '+Path(path).name);return regular(path)
def record(path):return {'path':str(regular(path)),'sha256':sha(path),'bytes':Path(path).stat().st_size}
def read(path,cap=16*1024**2):
    p=regular(path);need(p.stat().st_size<=cap,'JSON bound exceeded');raw=p.read_bytes();need(len(raw)<=cap,'JSON bound exceeded')
    def pairs(items):
        out={}
        for k,v in items:need(k not in out,'duplicate JSON key');out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))

def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(canonical(value))
    return record(path)

def verify_package(root,expected):
    root=Path(root);pins=read(pin(root/'PINS.json',expected))
    need(type(pins) is dict and pins,'package freeze required')
    need({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}==set(pins)|{'PINS.json'},'unexpected/missing package file')
    for name,value in pins.items():
        need(type(name) is str and not Path(name).is_absolute() and '\\' not in name and all(x not in ('','.','..') for x in name.split('/')),'safe package path required');pin(root/name,value)
    return pins

def load_orchestration(root):
    root=Path(root);verify_package(root,ORCHESTRATION_SHA)
    module=types.ModuleType('_game_continuation_workflow_core');module.__file__=str(root/'workflow_core.py')
    exec(compile((root/'workflow_core.py').read_bytes(),module.__file__,'exec'),module.__dict__)
    loaded={'workflow_core':module}
    for name in ('owned_commands','source_selection','projection_binding','host_tools','build_rust','orchestrate'):
        loaded[name]=module.module(name,root/(name+'.py'),loaded)
    return types.SimpleNamespace(**loaded)

def validate_candidate(value,ctx,config,environment):
    need(value['schema']=='rust-duty-onehand-private-capture-candidate/v1','candidate schema')
    need(value['binding']==ctx.runtime_binding,'candidate/context binding differs')
    need(value['capture_ready_private_candidate'] is True and value['target_source_to_rust_proved'] is True,'target full proof required')
    for key in ('activation_authorized','game_capture_performed','game_capture_binding_reviewed','cross_platform_float64_equality_proved'):
        need(value[key] is False,'candidate must remain proof-only; no claim laundering')
    need(value['raw_private_evidence_runner_local'] is True,'private same-runner candidate required')
    run=environment.get('GITHUB_RUN_ID','');attempt=environment.get('GITHUB_RUN_ATTEMPT','')
    need(run.isdigit() and attempt.isdigit(),'actual Actions run and attempt required')
    session='run-'+run+'-attempt-'+attempt
    need(config['session_id']==config['run_id']==session,'runner attempt changed; regenerate and reprove')
    need(config['runner_id']=='runner-'+__import__('hashlib').sha256(json.dumps(environment.get('RUNNER_NAME','unknown'),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()[:24],'runner identity changed')
    need(ctx.host.runner_id==config['runner_id'] and ctx.host.run_id==config['run_id'],'foreign runtime-context runner/run')
    need(ctx.raw['candidate_id']==config['candidate_id'] and ctx.raw['session_id']==session,'foreign candidate/session')
    need(Path(ctx.raw['private_root'])==Path(config['private_root']),'foreign controller private root')
    need(ctx.candidate_root==Path(config['private_root'])/session/'candidates'/config['candidate_id'],'foreign controller candidate root')
    for key in ('vra','vrs','vrm','manifest'):
        actual=ctx.pin(key);need(value['runtime_assets'][key]=={'path':str(actual.path),'sha256':actual.sha256},'candidate asset identity differs')
        pin(actual.path,actual.sha256)
    for name in ('runtime_context','runtime_aggregate','rust_build','approved_lineage_authored_admission'):
        p=value[name];pin(p['path'],p['sha256'])
    need(value['runtime_context']['sha256']==ctx.context_sha256,'context receipt differs')
    need(Path(value['runtime_aggregate']['path'])==ctx.output/'aggregate.json','foreign aggregate')
    for name,role in [('rust_build','rust_build'),('approved_lineage_authored_admission','authored_admission')]:
        actual=ctx.pin(role);need(value[name]=={'path':str(actual.path),'sha256':actual.sha256},'exact candidate evidence differs: '+name)

def reconsume(config,config_sha,orchestration_root,environment):
    config_path=pin(config,config_sha);cfg=read(config_path);o=load_orchestration(orchestration_root)
    p=o.orchestrate.load_packages(cfg,o.orchestrate.reviewed_dependencies())
    candidate=Path(cfg['private_root'])/cfg['session_id']/'candidates'/cfg['candidate_id']
    candidate_file=candidate/'capture-candidate.json';value=read(candidate_file)
    ctx=p.consumer.runtime_context.RuntimeContext.read(value['runtime_context']['path'],value['runtime_context']['sha256'],cfg['roots']['context_package'])
    ctx.require_production();validate_candidate(value,ctx,cfg,environment)
    maths=p.consumer.pinned_math.load(ctx.root('audited_source'))
    actual=p.consumer.consumer.aggregate(ctx,maths,cfg['runtime_environment'])
    old=p.consumer.consumer.load_receipt(ctx,'aggregate.json','aggregate')
    for k,v in actual.items():need(old.get(k)==v,'aggregate differs from full independent reconsumption')
    need(actual['full_grid_parity'] is True and actual['samples']==4240 and actual['chunks']==67,'complete 4240/67 proof required')
    cfg['embedded_python_closure']=value['embedded_python_closure'];o.host_tools.verify_embedded(cfg)
    return types.SimpleNamespace(cfg=cfg,orchestration=o,packages=p,ctx=ctx,candidate=candidate,value=value,receipt=record(candidate_file),full=actual)

def high_receipt(proof):
    b=proof.value['binding'];assets=proof.value['runtime_assets']
    # The v1 candidate_sha256 field retains its established approved-lineage meaning.
    # The actual target serialization is separately mandatory and never mislabeled.
    return {'schema':'rust-duty-high-onto-onehand/v1','presentation_policy':'high_onto_onehand_v6_native',
        'clip_name':ACTION,'source_action':ACTION,'export_take':ACTION,'candidate_sha256':APPROVED_SOURCE,
        'approved_source_sha256':APPROVED_SOURCE,'generated_source_sha256':b['generated_source_sha256'],
        'source_action_fingerprint':ACTION_FINGERPRINT,'source_fbx_sha256':b['actual_fbx_sha256'],
        **{'asset_'+k+'_sha256':assets[k]['sha256'] for k in ('vra','vrs','vrm')},
        'runtime_source_proof_sha256':proof.value['runtime_aggregate']['sha256'],
        'runtime_manifest_sha256':assets['manifest']['sha256'],'runtime_context_sha256':b['runtime_context_sha256'],
        'candidate_receipt_sha256':proof.receipt['sha256'],'candidate_id':b['candidate_id'],'session_id':b['session_id'],
        'verification_grid_sha256':GRID,'verification_sample_count':4240,'skin_vertex_observations':43392160,
        'native_processes_complete':True,'candidate_frame_range':[1,96],'reference_frame_range_half_open':[7787,7883],
        'native_fps':[60,1],'native_crop':[0,95],'imported_frame_offset':1,'subdivisions':256,
        'camera_and_rig_basis':'static','camera_motion_removal':'none','actor_basis':'reload_mesh_local',
        'anchor_actor':'hk416_weapon','return_seconds':0.2}

def patch_runtime_pins(source,receipt):
    need(source.count(PIN_LINE)==1,'public inactive pin declaration changed')
    pins={'receipt':digest(receipt),'fbx':receipt['source_fbx_sha256'],
        **{k:receipt['asset_'+k+'_sha256'] for k in ('vra','vrs','vrm')},'proof':receipt['runtime_source_proof_sha256']}
    for value in pins.values():digest_value(value)
    replacement="const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = Some(RuntimePins {\n"+''.join(f'    {k}: "{v}",\n' for k,v in pins.items())+'});'
    return source.replace(PIN_LINE,replacement)

def candidate_manifest(original,receipt_sha):
    digest_value(receipt_sha)
    need(not any(line.split('=',1)[0].strip().startswith(('high_mantle.','low_vault.','prone_entry.')) for line in original.splitlines() if '=' in line),'public baseline must remain inactive; no override of optional slots')
    suffix='\n# Private same-candidate diagnostic binding; public defaults are unchanged.\n'
    for k,v in {'high_mantle.policy':'high_onto_onehand_v6_native','high_mantle.asset':'onehand/asset.vra','high_mantle.clip':ACTION,'high_mantle.receipt':'onehand/runtime-receipt.json','high_mantle.receipt_sha256':receipt_sha}.items():suffix+=k+'='+v+'\n'
    return original+suffix
