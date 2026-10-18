"""Source-only immutable Git inventory measurement, never native admission."""
from __future__ import annotations
import argparse,hashlib,json,os,platform,stat,subprocess,sys
from pathlib import Path
import continuation_core as c
import game_source as source
import prepare_game_spec as helper
from game_plan import JUMP_REF,JUMP_PATH

REPOSITORY='RHS059/rust_duty'
JOB='source-and-guarded-proof'
SPEC='game-source-spec.json'
RECEIPT='game-source-spec-receipt.json'
MAX_SPEC_BYTES=2*1024**2
MAX_FILES=2048

def ordinary_directory(path):
    p=Path(path);c.need(p.is_absolute() and '..' not in p.parts and p.is_dir(),'ordinary absolute directory required')
    for q in (*reversed(p.parents),p):
        st=q.lstat();c.need(not stat.S_ISLNK(st.st_mode) and not getattr(st,'st_file_attributes',0)&0x400,'redirected directory forbidden')
    return p

def github_identity(environment,event_commit):
    c.need(type(event_commit) is str and source.re.fullmatch('[0-9a-f]{40}',event_commit) and event_commit!=JUMP_REF,'distinct immutable event source required')
    c.need(environment.get('GITHUB_ACTIONS')=='true','actual Actions execution required')
    c.need(environment.get('GITHUB_REPOSITORY')==REPOSITORY and environment.get('GITHUB_EVENT_NAME')=='pull_request','exact repository pull-request context required')
    c.need(environment.get('PROOF_COMMIT')==event_commit and environment.get('GITHUB_JOB')==JOB,'event/source/job mismatch')
    for key in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT'):
        c.need(type(environment.get(key)) is str and environment[key].isdigit() and int(environment[key])>0,'actual positive run and attempt required')
    for key in ('GITHUB_SHA','GITHUB_WORKFLOW_SHA'):
        c.need(type(environment.get(key)) is str and source.re.fullmatch('[0-9a-f]{40}',environment[key]),'immutable Actions SHA required')
    ref=environment.get('GITHUB_WORKFLOW_REF','')
    c.need(ref.startswith(REPOSITORY+'/.github/workflows/onehand-windows-proof.yml@refs/') and len(ref)<=512 and not any(ch.isspace() for ch in ref),'exact public workflow reference required')
    runner=environment.get('RUNNER_NAME','')
    c.need(type(runner) is str and 0<len(runner)<=256,'actual runner identity required')
    c.need(environment.get('RUNNER_OS')=='Windows' and environment.get('RUNNER_ARCH')=='X64','Windows x64 runner required')
    event_path=c.regular(environment['GITHUB_EVENT_PATH']);event=c.read(event_path,cap=8*1024**2)
    pr=event['pull_request']
    c.need(pr['head']['sha']==event_commit and pr['head']['repo']['full_name']==REPOSITORY and pr['base']['repo']['full_name']==REPOSITORY,'actual event payload source/repository mismatch')
    return {'repository':REPOSITORY,'event_name':'pull_request','event_head_commit':event_commit,
        'actions_sha':environment['GITHUB_SHA'],'workflow_sha':environment['GITHUB_WORKFLOW_SHA'],'workflow_ref':ref,
        'run_id':environment['GITHUB_RUN_ID'],'run_attempt':environment['GITHUB_RUN_ATTEMPT'],'job':JOB,
        'runner_name_sha256':c.sha_bytes(runner.encode()),'runner_os':'Windows','runner_arch':'X64',
        'event_payload_sha256':c.sha(event_path)}

def git_identity(git,repository,event_commit,jump_repository):
    c.need(source.git_run(git,repository,'rev-parse','HEAD').decode().strip()==event_commit,'checkout HEAD/event mismatch')
    c.need(source.git_run(git,jump_repository,'rev-parse','HEAD').decode().strip()==JUMP_REF,'immutable Jump checkout HEAD mismatch')
    c.need(source.git_run(git,jump_repository,'cat-file','-t',JUMP_REF).strip()==b'commit','real immutable Jump commit required')
    trees={}
    for role,repo,ref in [('game',repository,event_commit),('jump',jump_repository,JUMP_REF)]:
        tree=source.git_run(git,repo,'rev-parse',ref+'^{tree}').decode().strip()
        c.need(source.re.fullmatch('[0-9a-f]{40}',tree),'exact Git tree required');trees[role]=tree
    return {'game_source_commit':event_commit,'game_tree_sha1':trees['game'],'jump_source_commit':JUMP_REF,'jump_tree_sha1':trees['jump']}

def audit_spec(spec,git,repository,event_commit,jump_repository):
    c.need(type(spec) is dict and set(spec)=={'schema','revision','files'},'exact measured spec fields required')
    rows=source.validate_spec(spec,source.tree(git,repository,event_commit),event_commit)
    c.need(len(rows)<=MAX_FILES,'bounded source inventory required')
    total=0;jump=None
    for row in rows:
        repo=jump_repository if row['ref']==JUMP_REF else repository
        raw=source.blob(git,repo,row['ref'],row['repository_path'],row['bytes'])
        c.need(c.sha_bytes(raw)==row['sha256'],'measured payload SHA256 differs')
        c.need(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==row['git_blob_sha1'],'measured Git blob identity differs')
        total+=len(raw)
        if row['ref']==JUMP_REF:jump={k:row[k] for k in ('ref','repository_path','git_blob_sha1','sha256','bytes')}
    c.need(jump is not None,'actual immutable Jump row required')
    return {'files':len(rows),'input_bytes':total,'unique_git_blobs':len({r['git_blob_sha1'] for r in rows}),'jump':jump}

def tool_record(path):
    p=c.regular(path);return {'filename':p.name,'sha256':c.sha(p),'bytes':p.stat().st_size}

def python_runtime():
    c.need(sys.platform=='win32' and platform.system()=='Windows' and hasattr(sys,'dllhandle'),'actual Windows Python required')
    import ctypes
    get=ctypes.WinDLL('kernel32',use_last_error=True).GetModuleFileNameW
    get.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint];get.restype=ctypes.c_uint
    buffer=ctypes.create_unicode_buffer(32768);n=get(sys.dllhandle,buffer,len(buffer))
    c.need(0<n<len(buffer),'actual loaded Python DLL observation required');return c.regular(buffer.value)

def observe_tools(git):
    runtime=python_runtime()
    result=subprocess.run([str(git),'--version'],capture_output=True,check=True,timeout=30)
    c.need(not result.stderr and len(result.stdout)<=1024,'bounded Git version required')
    version=result.stdout.decode('ascii').strip();c.need(source.re.fullmatch(r'git version [A-Za-z0-9.+-]+',version),'actual Git version format')
    return {'git':{**tool_record(git),'version':version},'python':{**tool_record(sys.executable),'version':list(sys.version_info[:3])},'python_runtime':tool_record(runtime)}

def run(args,package,expected_package,environment):
    package=Path(package);c.verify_package(package,expected_package)
    c.need(sys.platform=='win32' and platform.system()=='Windows','actual Windows measurement required')
    identity=github_identity(environment,args.event_commit)
    git=c.regular(args.git);ordinary_directory(args.repository);ordinary_directory(args.jump_repository);identities=git_identity(git,args.repository,args.event_commit,args.jump_repository)
    tools=observe_tools(git)
    output=ordinary_directory(args.output_directory)
    for name in (SPEC,RECEIPT,'game-source-spec-failure.json'):c.need(not (output/name).exists(),'fresh measurement outputs required')
    # Unchanged pinned helper is called only after the isolated package check.
    # stdout is not redirected to a public asset dump: helper prints only counts.
    argv=['prepare_game_spec.py','--git',str(git),'--repository',str(args.repository),'--revision',args.event_commit,
        '--jump-repository',str(args.jump_repository),'--output',str(output/SPEC)]
    saved=sys.argv
    try:sys.argv=argv;helper.main()
    finally:sys.argv=saved
    spec_path=c.regular(output/SPEC);c.need(spec_path.stat().st_size<=MAX_SPEC_BYTES,'bounded measured inventory required')
    spec=c.read(spec_path,cap=MAX_SPEC_BYTES);spec_sha=c.sha_bytes(c.canonical(spec))
    c.need(c.sha(spec_path)==spec_sha,'exact helper-canonical inventory bytes required')
    stats=audit_spec(spec,git,args.repository,args.event_commit,args.jump_repository)
    c.need(git_identity(git,args.repository,args.event_commit,args.jump_repository)==identities,'Git identity changed during measurement')
    c.need(github_identity(environment,args.event_commit)==identity,'event identity changed during measurement')
    c.need(observe_tools(git)==tools,'measured tool identity changed')
    c.verify_package(package,expected_package)
    c.need(c.sha(spec_path)==spec_sha,'inventory changed during validation')
    receipt={'schema':'rust-duty-game-source-spec-measurement/v1','measured':True,'source_only':True,'independently_accepted':False,
        'native_admission_enabled_by_measurement':False,'blender_or_cargo_launched':False,'candidate_generated':False,'game_capture_performed':False,'raw_source_uploaded':False,
        'actions':identity,'source':identities,'package_pins_sha256':expected_package,'package_pins_bytes':(package/'PINS.json').stat().st_size,
        'implementation':{name:c.sha(package/name) for name in ('export_source_inventory.py','execute_continuation.py','measure_source_spec.py','prepare_game_spec.py','game_source.py','continuation_core.py','game_plan.py')},
        'tools':tools,'spec':{'path':SPEC,'sha256':spec_sha,'bytes':spec_path.stat().st_size,**stats}}
    c.need(len(c.canonical(receipt))<=32*1024,'bounded provenance receipt required')
    c.write_new(output/RECEIPT,receipt)
    if args.github_output:
        with c.regular(args.github_output).open('a',encoding='utf-8') as f:f.write('source_inventory_measured=true\n')
    summary={'source_inventory_measured':True,'source_only':True,'independently_accepted':False,'source_spec_sha256':c.sha(spec_path),'measurement_receipt_sha256':c.sha(output/RECEIPT),'files':stats['files'],'input_bytes':stats['input_bytes'],'raw_source_uploaded':False}
    print(json.dumps(summary,sort_keys=True));return receipt

class Parser(argparse.ArgumentParser):
    def error(self,message):raise ValueError('invalid measurement arguments')
def main(argv,package,expected_package):
    parser=Parser()
    for name in ('git','repository','event-commit','jump-repository','output-directory'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--github-output');args=parser.parse_args(argv)
    return run(args,package,expected_package,os.environ)
