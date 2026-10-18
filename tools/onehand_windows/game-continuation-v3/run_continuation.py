#!/usr/bin/env python3
"""Reviewed same-job continuation. Public null admission never executes anything."""
from __future__ import annotations
import argparse,os,sys,shutil,types,re
from pathlib import Path
sys.dont_write_bytecode=True
from continuation_core import *
import game_source,build_game,game_plan,verify_dx12

HERE=Path(__file__).resolve().parent

def admitted_file(admission_path,item):
    need(type(item) is dict and set(item)=={'path','sha256'},'exact admission file reference required')
    relative=game_source.logical(item['path'])
    return pin(Path(admission_path).parent/relative,item['sha256'])

def admit(path,expected,package_sha,revision):
    value=read(pin(path,expected))
    need(value.get('schema')=='rust-duty-onehand-game-continuation-admission/v1','admission schema')
    need(value.get('enabled') is True,'game continuation admission remains inactive')
    need(value.get('package_pins_sha256')==package_sha,'independently accepted source package required')
    need(value.get('orchestration_pins_sha256')==ORCHESTRATION_SHA,'original full proof must remain unchanged')
    need(value.get('game_source_revision')==revision and re.fullmatch('[0-9a-f]{40}',revision),'exact current game commit required')
    spec=read(admitted_file(path,value['game_source_spec']))
    review=read(admitted_file(path,value['independent_review']))
    for key,want in {'schema':'rust-duty-onehand-game-continuation-review/v1','accepted':True,
        'package_pins_sha256':package_sha,'orchestration_pins_sha256':ORCHESTRATION_SHA,
        'game_source_revision':revision,'game_source_spec_sha256':value['game_source_spec']['sha256'],
        'full4240_gates_preserved':True,'runner_local_patch_reviewed':True,'base_companion_producers_reviewed':True,
        'windows_capture_contract_reviewed':True,'public_defaults_inactive':True}.items():
        need(type(review.get(key)) is type(want) and review[key]==want,'independent review missing exact '+key)
    need(type(review.get('reviewer')) is str and review['reviewer'].strip(),'named independent reviewer required')
    need(type(value.get('reserve_bytes')) is int and value['reserve_bytes']>=3*1024**3,'reviewed build/generation disk reserve required')
    need(review.get('reserve_bytes')==value['reserve_bytes'],'resource reservation not independently reviewed')
    return value,spec

def load_original_verifier(source,wf):
    modules={}
    for name in ('verify_render_capture','verify_capture_frame_witness','verify_high_mantle_observer','verify_high_mantle_deterministic'):
        modules[name]=wf.module(name,source/'tools'/(name+'.py'),modules)
    return modules['verify_high_mantle_deterministic']

def stage_delivery(source,root,build,game_receipt,commands,env,proof):
    need(game_receipt['passed'] is True and game_receipt['both_rates_verified'] is True,'gameplay acceptance required before packaging')
    need(game_receipt['executable']==build['executable'],'captured executable differs')
    exe=source/'vector-range.exe';need(not exe.exists(),'no old staged executable permitted')
    shutil.copyfile(pin(build['executable']['path'],build['executable']['sha256']),exe)
    output=root/'delivery'
    commands.run('game-stage-delivery',[sys.executable,'-B',str(source/'tools/package_game.py'),'stage','--root',str(source),'--binary','vector-range.exe','--output',str(output),'--require-generated'],source,environment=env,stdout_cap=8*1024**2)
    for name in ('asset.vra','asset.vrs','asset.vrm','runtime-receipt.json'):
        src=source/'assets/onehand'/name;dst=output/'assets/onehand'/name;dst.parent.mkdir(parents=True,exist_ok=True)
        with src.open('rb') as inp,dst.open('xb') as out:shutil.copyfileobj(inp,out)
        need(sha(dst)==sha(src),'staged high payload changed')
    need(sha(output/'vector-range.exe')==build['executable']['sha256'],'staged executable changed')
    need(sha(output/'assets/animations.cfg')==build['runtime_manifest']['sha256'],'staged manifest changed')
    files=proof.orchestration.workflow_core.inventory(output)
    need(not any(Path(n).suffix.lower() in ('.blend','.fbx','.npz') for n in files),'raw intermediate entered game delivery')
    receipt={'schema':'rust-duty-onehand-captured-game-delivery/v1','files':files,
        'executable_sha256':build['executable']['sha256'],'game_source_revision':build['source_revision'],
        'build_receipt_sha256':game_receipt['game_build']['sha256'],'game_capture_sha256':digest(game_receipt),
        'candidate_receipt_sha256':proof.receipt['sha256'],'public_default_activated':False,
        'gameplay_capture_passed':True,'raw_intermediates_included':False}
    write_new(output/'GAME_CANDIDATE.json',receipt)
    return output,receipt

def run(args):
    verify_package(HERE,args.package_pins_sha256)
    accepted,spec=admit(args.admission,args.admission_sha256,args.package_pins_sha256,args.game_revision)
    need(sys.platform=='win32','actual Windows execution required; no Linux capture substitution')
    need(os.environ.get('PROOF_COMMIT')==args.event_commit,'immutable event head differs from Actions event')
    game_source.current_closure(args.git,args.repository,args.game_revision,args.event_commit)
    proof=reconsume(args.config,args.config_sha256,args.orchestration,os.environ)
    wf=proof.orchestration.workflow_core
    wf.capacity(proof.candidate,accepted['reserve_bytes'])
    root=proof.candidate/'game-continuation';need(not root.exists(),'fresh continuation required; failed evidence is retained');root.mkdir()
    source=root/'source'
    exported=game_source.materialize(spec,args.git,args.repository,args.game_revision,source,args.jump_repository)
    exported['event_commit']=args.event_commit;exported['current_event_game_closure_identical']=True
    exported['git']=record(Path(args.git));write_new(root/'source-export.json',exported)
    # These observer additions must be present in the selected, reviewed public
    # commit. We never apply an unreviewed source overlay while running.
    need('pub fn high_candidate_observation' in (source/'src/authored_viewmodel.rs').read_text(),'current source lacks actual-clip observer')
    need('row["candidate_visual"]' in (source/'src/high_mantle_capture.rs').read_text(),'current source lacks candidate frame binding')
    command_module=wf.module('game_commands',HERE/'game_commands.py',{'workflow_core':wf})
    commands=command_module.Commands(proof.packages.adapter,proof.ctx.raw['host'],proof.candidate,proof.cfg['native_environment'],proof.packages.native.process_evidence.verify_completed_process)
    build,build_pin,env=build_game.build(source,root,proof,commands,os.environ,exported)
    # A new source build is not accepted merely because the previous sampler ran.
    reconsume(args.config,args.config_sha256,args.orchestration,os.environ)
    original=load_original_verifier(source,wf)
    binding={'receipt_sha256':build['runtime_receipt']['sha256'],'asset_sha256':proof.value['runtime_assets']['vra']['sha256'],'return_seconds':0.2}
    rates=[];capture_root=root/'capture';capture_root.mkdir()
    settings=root/'capture-settings.cfg';shutil.copyfile(source/'settings.cfg',settings);settings_pin=record(settings)
    for hz in (30,60):
        need(wf.inventory(source)==build['source_files'],'built source/assets changed before capture')
        folder=capture_root/str(hz);folder.mkdir();output=folder/'game'
        context={'candidate':proof.receipt,'game_build':build_pin,'manifest':build['runtime_manifest'],'settings':settings_pin,'hz':hz,'run_id':os.environ['GITHUB_RUN_ID'],'run_attempt':os.environ['GITHUB_RUN_ATTEMPT'],'backend':'Dx12'}
        identity=digest(context);write_new(folder/'capture-context.json',context)
        argv=game_plan.capture_command(build['executable']['path'],build['runtime_manifest']['path'],settings,output,identity,hz)
        process=commands.run('game-dx12-capture-'+str(hz),argv,source,environment=env,stdout_cap=4*1024**2,reserve=128*1024**2,deadline_seconds=600)
        rate=verify_dx12.verify(output,binding,hz,identity,[process['stdout']['path'],process['stderr']['path']],original)
        rate['process']=process['terminal'];rate['context_sha256']=digest(context);rates.append(rate)
        pin(settings,settings_pin['sha256']);pin(build['executable']['path'],build['executable']['sha256'])
        need(wf.inventory(source)==build['source_files'],'built source/assets changed during capture')
        write_new(folder/'verification.json',rate)
    reconsume(args.config,args.config_sha256,args.orchestration,os.environ)
    receipt={'schema':'rust-duty-onehand-game-continuation/v1','passed':True,'both_rates_verified':{r['sampling_hz'] for r in rates}=={30,60},
        'game_build':build_pin,'executable':build['executable'],'candidate_receipt':proof.receipt,'binding':binding,'rates':rates,
        'same_runner_same_candidate':True,'full4240_proof_reconsumed':True,'public_defaults_inactive':True,
        'platform_hotkeys_verified':False,'combined_gameplay_verified':False,'artistic_approval':False}
    receipt_pin=write_new(root/'game-capture.json',receipt)
    output,delivery=stage_delivery(source,root,build,receipt,commands,env,proof)
    summary={'schema':'rust-duty-onehand-game-public-summary/v1','passed':True,'game_capture_sha256':receipt_pin['sha256'],
        'candidate_receipt_sha256':proof.receipt['sha256'],'game_build_sha256':build_pin['sha256'],
        'game_executable_sha256':build['executable']['sha256'],'game_source_revision':args.game_revision,
        'runtime_manifest_sha256':build['runtime_manifest']['sha256'],'candidate_assets':{k:v['sha256'] for k,v in proof.value['runtime_assets'].items()},
        'samples':4240,'chunks':67,'capture_rates':[30,60],'private_raw_evidence_uploaded':False,'platform_hotkeys_verified':False,'artistic_approval':False}
    write_new(root/'public-summary.json',summary)
    if args.github_output:
        with Path(args.github_output).open('a',encoding='utf-8') as f:f.write('game_capture_passed=true\ndelivery_root='+str(output)+'\n')
    if args.public_summary:write_new(Path(args.public_summary),summary)
    print(json.dumps(summary,sort_keys=True));return summary

def main():
 p=argparse.ArgumentParser()
 for name in ('package-pins-sha256','admission','admission-sha256','game-revision','event-commit','config','config-sha256','orchestration','git','repository'):p.add_argument('--'+name,required=True)
 p.add_argument('--github-output');p.add_argument('--jump-repository');p.add_argument('--public-summary');args=p.parse_args()
 try:run(args);return 0
 except Exception as e:
    # Public failure line cannot leak paths, source, env, geometry or logs.
    failure={'passed':False,'error_type':type(e).__name__,'error_sha256':sha_bytes(str(e).encode()),'game_capture_claimed':False,'raw_private_evidence_runner_local':True,'runner_teardown_destroys_raw_forensics':True}
    if args.public_summary and not Path(args.public_summary).exists():write_new(Path(args.public_summary),failure)
    print(json.dumps(failure));return 1
if __name__=='__main__':raise SystemExit(main())
