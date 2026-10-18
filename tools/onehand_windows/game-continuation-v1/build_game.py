"""Build/generate inside this candidate's job under the existing Windows owner."""
from pathlib import Path
import shutil,sys,os,types
from continuation_core import *
from game_plan import generator_plan,cargo_command,KINDS

MATH_FILES=('Cargo.toml','Cargo.lock','build.rs','build_number.rs','src/viewmodel_animation.rs','src/skinned_asset.rs','src/asset.rs','examples/sample_viewmodel_clip.rs')

def require_math(source,proof):
    refs=proof.packages.consumer.pinned_math.read(proof.packages.consumer.pinned_math.HERE/'RUST_REFERENCE_PINS.json')
    for name in MATH_FILES:pin(source/name,refs[name])

def staging_changes_allowed(before,after):
    for name in set(before)|set(after):
        if before.get(name)==after.get(name):continue
        need(name=='assets/locomotion/asset.vrs' or name.startswith(tuple('assets/'+k+'/' for k in KINDS)), 'base generator changed source outside its explicit runtime destinations: '+name)

def make_env(proof,target,cargo_home,environment):
    env=dict(proof.cfg['native_environment'])
    for key in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT'):
        need(environment.get(key,'').isdigit(),'actual CI build identity missing');env[key]=environment[key]
    env['GITHUB_ACTIONS']='true'
    path_key=next((k for k in env if k.upper()=='PATH'),'PATH');env[path_key]=str(Path(proof.cfg['rust']['cargo']).parent)+os.pathsep+env.get(path_key,'')
    env.update(RUSTC=proof.cfg['rust']['rustc'],CARGO_HOME=str(cargo_home),CARGO_TARGET_DIR=str(target),CARGO_INCREMENTAL='0',CARGO_BUILD_JOBS='1')
    return env

def build(source,root,proof,commands,environment,source_export):
    wf=proof.orchestration.workflow_core;source=Path(source);root=Path(root)
    target=root/'target';vendor=root/'vendor';home=root/'cargo-home'
    need(not any(x.exists() for x in (target,vendor,home)),'fresh game Cargo roots required')
    target.mkdir();home.mkdir();env=make_env(proof,target,home,environment)
    require_math(source,proof);public=wf.inventory(source)
    cargo=pin(proof.cfg['rust']['cargo'],read(proof.cfg['rust']['toolchain_receipt'])['cargo']['sha256'])
    rustc=pin(proof.cfg['rust']['rustc'],read(proof.cfg['rust']['toolchain_receipt'])['rustc']['sha256'])
    compiler_executables=[record(cargo),record(rustc)]
    version=commands.run('game-rustc-version',[str(rustc),'-vV'],source,environment=env)
    proof.orchestration.source_selection.verify_compiler(Path(version['stdout']['path']).read_text())
    vendored=commands.run('game-cargo-vendor',[str(cargo),'vendor','--locked','--versioned-dirs','--sync',str(source/'updater/Cargo.toml'),str(vendor)],source,environment=env,stdout_cap=16*1024**2)
    raw=Path(vendored['stdout']['path']).read_bytes();need(raw and len(raw)<=1024**2,'Cargo vendor config bound')
    (home/'config.toml').write_bytes(raw)
    compiler_provenance=[record(proof.cfg['rust']['rustup_manifest']),record(home/'config.toml'),record(proof.cfg['rust']['toolchain_receipt']),*[record(x) for x in proof.cfg['rust']['compiler_tool_files']]]
    installed=read(proof.cfg['rust']['toolchain_receipt'])
    need(installed['compiler_tools']==[record(x) for x in proof.cfg['rust']['compiler_tool_files']],'installed compiler/linker/SDK inventory changed')
    need(wf.inventory(source)==public,'source changed during dependency preparation')
    vendor_files=wf.inventory(vendor)
    notices=commands.run('game-license-notices',[sys.executable,'-B',str(source/'tools/collect_updater_licenses.py'),'--manifest',str(source/'updater/Cargo.toml'),'--output',str(source/'updater/notices')],source,environment=env,stdout_cap=4*1024**2)
    licensed=wf.inventory(source)
    for name in set(public)|set(licensed):
        need(public.get(name)==licensed.get(name) or name in ('updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt','updater/notices/UPDATER_DEPENDENCIES.json'),'unexpected license generator source change')
    public_before_notices=public;public=licensed
    meta=commands.run('game-cargo-metadata',[str(cargo),'metadata','--locked','--offline','--format-version','1','--no-default-features','--features',','.join(FEATURES)],source,environment=env,stdout_cap=32*1024**2)
    dependency={'cargo_lock_sha256':public['Cargo.lock'],'metadata':meta['stdout'],'roots':[{'path':str(vendor),'files':vendor_files,'sha256':wf.digest(vendor_files)}]}
    sampler_target=root/'sampler-target';sampler_target.mkdir()
    sampler_env={**env,'CARGO_TARGET_DIR':str(sampler_target)}
    sampler_command=cargo_command(cargo,sampler_target,'sampler')
    sampled=commands.run('game-base-sampler-build',sampler_command,source,environment=sampler_env,stdout_cap=64*1024**2,reserve=2*1024**3)
    sampler_events=proof.orchestration.build_rust.cargo_events(sampled['stdout']['path'])
    samplers=[r['executable'] for r in sampler_events if r.get('reason')=='compiler-artifact' and r.get('target',{}).get('name')=='sample_viewmodel_clip' and r.get('executable')]
    need(len(samplers)==1,'one actual current-game sampler required');sampler=Path(samplers[0]);proof.packages.consumer.runtime_context.pe_x64(sampler)
    need(wf.inventory(source)==public and wf.inventory(vendor)==vendor_files,'source/dependency changed during current sampler build')
    sampler_root=root/'sampler-proof';sampler_root.mkdir()
    sampler_process=write_new(sampler_root/'build-process.json',{'stdout':sampled['stdout'],'stderr':sampled['stderr'],'owned_process_terminal':sampled['terminal'],'command':sampler_command,'source_tree_sha256':wf.digest(public),'target_empty_before_build':True})
    sampler_build={'schema':'rust-duty-current-base-sampler-build/v1','command':sampler_command,'source_tree_sha256':wf.digest(public),'source_files':public,'dependency_closure':dependency,'build_process':sampler_process,'sampler':record(sampler)}
    sampler_report=proof.orchestration.build_rust.compiler_report(sampler_build,sampler_process,sampler_events,sampler_target,source,proof.packages.consumer.build_closure.dep_info_paths,sampler_root)
    sampler_build['compiler_inputs']=write_new(sampler_root/'compiler-inputs.json',sampler_report)
    sampler_context=types.SimpleNamespace(cc=proof.ctx.cc,candidate_root=root,root=lambda role: source if role=='rust_source' else (_ for _ in ()).throw(ValueError('unsupported sampler closure root')))
    proof.packages.consumer.build_closure.verify(sampler_context,sampler_build,[(source,public),(vendor,vendor_files)],read(meta['stdout']['path'],cap=32*1024**2),sampler_target)
    sampler_pin=write_new(sampler_root/'sampler-build.json',sampler_build)
    base_work=root/'base-production';base_work.mkdir();base_processes=[]
    for step in generator_plan(source,base_work,sys.executable,Path(proof.cfg['roots']['blender_bundle'])/'blender.exe',sampler):
        proof.orchestration.host_tools.verify_embedded(proof.cfg)
        before=wf.inventory(source)
        result=commands.run(step['label'],step['argv'],source,environment=env,stdout_cap=16*1024**2,reserve=512*1024**2)
        base_processes.append({'label':step['label'],'process':result['terminal']})
        if 'stage' in step:
            src=Path(step['stage']['source']);dst=Path(step['stage']['destination'])
            produced=wf.inventory(src);need(all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in produced),'unsafe base generated inventory')
            for n in produced:
                q=dst/n;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src/n,q)
            base_processes[-1]['produced_files']=produced
        staging_changes_allowed(before,wf.inventory(source));require_math(source,proof)
    after_base=wf.inventory(source);staging_changes_allowed(public,after_base)
    receipt=high_receipt(proof);receipt_pin=write_new(source/'assets/onehand/runtime-receipt.json',receipt)
    for role in ('vra','vrs','vrm'):
        source_pin=proof.value['runtime_assets'][role];path=pin(source_pin['path'],source_pin['sha256']);dest=source/'assets/onehand'/('asset.'+role)
        with path.open('rb') as inp,dest.open('xb') as out:shutil.copyfileobj(inp,out)
        pin(dest,source_pin['sha256'])
    original=(source/'src/authored_high_mantle.rs').read_text(encoding='utf-8')
    patched=patch_runtime_pins(original,receipt);(source/'src/authored_high_mantle.rs').write_bytes(patched.encode())
    import difflib
    delta=''.join(difflib.unified_diff(original.splitlines(True),patched.splitlines(True),fromfile='a/src/authored_high_mantle.rs',tofile='b/src/authored_high_mantle.rs'))
    patch_file=root/'runtime-pin.patch';patch_file.write_bytes(delta.encode())
    manifest=source/'assets/animations.cfg';original_manifest=manifest.read_text(encoding='utf-8')
    manifest.write_bytes(candidate_manifest(original_manifest,receipt_pin['sha256']).encode())
    source_files=wf.inventory(source);need(wf.inventory(vendor)==vendor_files,'dependency source changed')
    need(not any(target.iterdir()),'game target must be empty before actual build')
    argv=cargo_command(cargo,target,'game')
    actual=commands.run('game-cargo-build',argv,source,environment=env,stdout_cap=64*1024**2,reserve=2*1024**3)
    need(wf.inventory(source)==source_files and wf.inventory(vendor)==vendor_files,'source/dependency changed during game build')
    events=proof.orchestration.build_rust.cargo_events(actual['stdout']['path'])
    executables=[r['executable'] for r in events if r.get('reason')=='compiler-artifact' and r.get('target',{}).get('name')=='vector-range' and r.get('executable')]
    need(len(executables)==1,'one actual game executable required');exe=Path(executables[0]);proof.packages.consumer.runtime_context.pe_x64(exe)
    build={'schema':'rust-duty-onehand-current-game-build/v1','source_revision':source_export['source_revision'],
        'source_export':source_export,'public_source_files':public_before_notices,'public_source_tree_sha256':wf.digest(public_before_notices),'license_notice_process':notices['terminal'],
        'source_files':source_files,'source_tree_sha256':wf.digest(source_files),'source_root':str(source),
        'runtime_pin_patch':record(patch_file),'candidate_receipt':proof.receipt,'runtime_receipt':receipt_pin,
        'runtime_manifest':record(manifest),'source_equivalent_to_unpatched_public_commit':False,
        'dependency_closure':dependency,'command':argv,'features':FEATURES,'target':TARGET,
        'build_process':actual['terminal'],'executable':record(exe),'sampler':record(sampler),'sampler_process':sampled['terminal'],'base_sampler_build':sampler_pin,
        'base_companion_processes':base_processes,'cargo':record(cargo),'rustc':record(rustc),
        'rustc_verbose':Path(version['stdout']['path']).read_text(),'environment_sha256':wf.digest(env),
        'toolchain_receipt':record(proof.cfg['rust']['toolchain_receipt']),'compiler_provenance':compiler_provenance, 'game_capture_performed':False}
    # Reuse the existing dep-info/OUT_DIR reconstruction, with fresh game-specific identity.
    process_record=write_new(root/'game-build-process.json',{'stdout':actual['stdout'],'stderr':actual['stderr'],'owned_process_terminal':actual['terminal'],'command':argv,'source_tree_sha256':wf.digest(source_files),'target_empty_before_build':True})
    build['owned_process_terminal']=build['build_process'];build['build_process']=process_record
    compiler=proof.orchestration.build_rust.compiler_report(build,process_record,events,target,source,proof.packages.consumer.build_closure.dep_info_paths,root)
    build['compiler_inputs']=write_new(root/'compiler-inputs.json',compiler)
    for item in [*compiler_executables,*compiler_provenance]:pin(item['path'],item['sha256'])
    # Reuse EVERY strict dependency, target and OUT_DIR membership check. The
    # generic verifier's historical 'sampler' key denotes its executable output;
    # adapt that key in a read-only view to this independently selected game EXE.
    context=types.SimpleNamespace(cc=proof.ctx.cc,candidate_root=root,root=lambda role: source if role=='rust_source' else (_ for _ in ()).throw(ValueError('unsupported game closure root')))
    view={**build,'sampler':build['executable']}
    proof.packages.consumer.build_closure.verify(context,view,[(source,source_files),(vendor,vendor_files)],read(meta['stdout']['path'],cap=32*1024**2),target)
    build['compiler_input_membership_verified']=True
    build_pin=write_new(root/'game-build.json',build)
    return build,build_pin,env
