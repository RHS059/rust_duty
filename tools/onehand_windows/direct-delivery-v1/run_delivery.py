#!/usr/bin/env python3
"""Existing approved runtime files -> ordinary Cargo game build -> playable package."""
from __future__ import annotations
import argparse, os, shutil, sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).absolute().parent))
from common import *
from owned_commands import Commands, clean_environment
import runtime_binding

FEATURES=('audio','legacy-macroquad','wgpu-runtime')
TARGET='x86_64-pc-windows-msvc'
HERE=Path(__file__).absolute().parent

def cargo_command(cargo,target):
    return [str(cargo),'build','--locked','--release','--message-format=json','--target',TARGET,'--target-dir',str(target),'--no-default-features','--features',','.join(FEATURES),'--bin','vector-range']

def game_executable(stdout):
    events=[]
    for line in Path(stdout).read_text(encoding='utf-8').splitlines():
        if line.strip():events.append(json.loads(line))
    need(any(e.get('reason')=='build-finished' and e.get('success') is True for e in events),'Cargo did not report a successful build')
    paths=[e['executable'] for e in events if e.get('reason')=='compiler-artifact' and e.get('target',{}).get('name')=='vector-range' and e.get('executable')]
    need(len(paths)==1,'Cargo game executable missing/ambiguous')
    return ordinary(paths[0],True)

def build_and_stage(root,work,cargo,commands,environment):
    """Every compile/package failure propagates; nothing depends on proof/capture files."""
    root=ordinary(root,True);work=ordinary(work,True);target=work/'target'
    need(not target.exists(),'fresh build target required')
    try:
        result=commands.run('game-build',cargo_command(cargo,target),root,environment=environment,stdout_cap=64*1024**2,reserve=2*GIB)
    except Exception:
        # Keep ordinary compiler diagnostics, bounded separately from native export logs.
        messages=[]
        stdout=work/'process/game-build/stdout.bin'
        if stdout.is_file():
            with stdout.open('r',encoding='utf-8',errors='replace') as stream:
                for line in stream:
                    try: item=json.loads(line)
                    except ValueError: continue
                    if item.get('reason')=='compiler-message':
                        message=item.get('message',{}).get('rendered')
                        if isinstance(message,str):messages.append(message)
                    if sum(map(len,messages))>=65536:break
        stderr=work/'process/game-build/stderr.bin'
        if stderr.is_file():
            with stderr.open('rb') as stream:messages.append(stream.read(16384).decode('utf-8','replace'))
        if messages:(work/'build-errors.txt').write_text(''.join(messages)[:65536],encoding='utf-8')
        raise
    executable=game_executable(result['stdout']['path']);runtime_binding.replace_file(executable,root/'vector-range.exe')
    commands.run('updater-fetch',[str(cargo),'fetch','--locked','--manifest-path',str(root/'updater/Cargo.toml')],root,environment=environment,stdout_cap=16*1024**2)
    commands.run('updater-notices',[sys.executable,'-B',str(root/'tools/collect_updater_licenses.py'),'--manifest',str(root/'updater/Cargo.toml'),'--output',str(root/'updater/notices')],root,environment=environment,stdout_cap=16*1024**2)
    delivery=work/'delivery'
    commands.run('game-package',[sys.executable,'-B',str(root/'tools/package_game.py'),'stage','--root',str(root),'--binary','vector-range.exe','--output',str(delivery),'--require-generated'],root,environment=environment,stdout_cap=8*1024**2)
    need((delivery/'vector-range.exe').is_file(),'package did not contain game executable')
    pin(delivery/'vector-range.exe',sha(executable))
    return delivery,{'executable':record(executable),'build_process':result['terminal'],'features':list(FEATURES),'target':TARGET}

def run(args):
    args.delivery_phase='input-validation'
    need(re.fullmatch('[0-9a-f]{40}',args.source_commit),'immutable source commit required')
    root=ordinary(args.root,True);work=ordinary(args.work);need(not work.exists(),'fresh delivery work root required');work.mkdir(parents=True)
    environment=clean_environment();environment['RUSTC']=str(ordinary(args.rustc,True));environment['CARGO_TARGET_DIR']=str(work/'target')
    pathkey=next((k for k in environment if k.upper()=='PATH'),'PATH');environment[pathkey]=str(Path(args.cargo).parent)+os.pathsep+environment.get(pathkey,'')
    commands=Commands(root/'tools/onehand_windows/process-v2',work,environment)
    args.delivery_phase='prepare-base-assets'
    if args.generate_base:
        need(args.blender is not None,'explicit Blender path required for base export')
        plan=module('direct_game_asset_plan',root/'tools/direct_game_asset_plan.py')
        for step in plan.generator_plan(root,work/'base-production',sys.executable,args.blender):
            commands.run(step['label'],step['argv'],root,environment=environment,stdout_cap=16*1024**2,reserve=512*1024**2)
            if 'stage' in step:
                src=Path(step['stage']['source']);dst=Path(step['stage']['destination'])
                for p in src.rglob('*'):
                    if p.is_file():runtime_binding.replace_file(p,dst/p.relative_to(src))
    else:
        commands.run('materialize-existing',[sys.executable,'-B',str(root/'tools/package_game.py'),'materialize','--root',str(root),'--include-walk','--include-ads','--include-directional','--include-jump','--require-generated'],root,environment=environment,stdout_cap=8*1024**2)
    args.delivery_phase='bind-existing-runtime-files'
    integration=runtime_binding.bind_existing(root)
    args.delivery_phase='compile-and-package'
    delivery,build=build_and_stage(root,work,args.cargo,commands,environment)
    receipt={'schema':'rust-duty-direct-playable-delivery/v1','source_commit':args.source_commit,'changed_source_files':integration['changed_source_files'],'source_checkout_modified':bool(integration['changed_source_files']),'executable_sha256':build['executable']['sha256'],'runtime_manifest_sha256':sha(delivery/'assets/animations.cfg'),'features':list(FEATURES),'native_clock_unchanged':True,'numerical_parity_performed':False,'capture_performed':False}
    write(delivery/'GAME_CANDIDATE.json',receipt);write(work/'build-result.json',build)
    if args.github_output:
        with Path(args.github_output).open('a',encoding='utf-8') as f:f.write('delivery_root='+str(delivery)+'\ndelivery_ready=true\n')
    return delivery

def main():
    p=argparse.ArgumentParser()
    for name in ('root','work','cargo','rustc'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--source-commit',required=True);p.add_argument('--github-output',type=Path);p.add_argument('--generate-base',action='store_true');p.add_argument('--blender',type=Path)
    args=p.parse_args()
    try:run(args)
    except Exception as e:
        # Raw process logs remain local; no payload, credentials or unrelated paths in published summaries.
        failure={'schema':'rust-duty-direct-delivery-failure/v1','phase':getattr(args,'delivery_phase','argument-parsing'),'error_type':type(e).__name__,'message':str(e)[-2048:],'error_sha256':hashlib.sha256(str(e).encode()).hexdigest()}
        commands=args.work/'commands'
        if commands.is_dir():
            records=sorted(commands.glob('*.json'),key=lambda p:p.stat().st_mtime_ns)
            if records:
                command=read(records[-1]);failure['stage']=command['stage'];failure['command']=[str(x)[:512] for x in command['argv'][:64]]
        if args.work.exists():
            (args.work/'failure-summary.json').write_bytes(canonical(failure))
        print(json.dumps(failure));return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
