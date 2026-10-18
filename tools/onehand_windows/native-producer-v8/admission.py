"""Host, immutable stage evidence, native gate and retained process admission."""
import dataclasses,json,os,struct,sys,time
from pathlib import Path,PurePosixPath
from pinned_code import HERE,CONTEXT_PINS_SHA,file_sha,isolated_module,load_context,require
from stage_context import StageContext,INPUTS,SOURCE_STAGES,capacity,MIB
from transport_binding import verify_transport
from planner import native_argv,output_cap,process_limits
from process_evidence import verify_completed_process,exact as process_exact
from host_identity import HOST_SCHEMA,require_native_host,verify_probe_binding
FOCUS_CHECKS=('bone_inventory','hierarchy','animated_camera_bound','animated_rig_bound','single_exact_take','bounded_window_admitted','bone_deformation_world_matrix','bone_head_world_m','actor_world_matrix','actor_camera_relative_matrix','camera_world_matrix','rig_world_matrix','skin_world_m','skin_camera_relative_m','finite_bones','finite_all_measured_transforms','skin_topology','camera_projection_rays','camera_type','single_native_clock','fps','source_unchanged','fbx_unchanged')


def verify_package(expected):
    require(file_sha(HERE/'PINS.json')==expected,'producer freeze differs')
    pins=json.loads((HERE/'PINS.json').read_text());allow=json.loads((HERE/'ALLOWLIST.json').read_text())
    require(set(pins)==set(allow['files'])-{'PINS.json'},'producer allowlist differs')
    for n,v in pins.items():require(Path(n).name==n and file_sha(HERE/n)==v,'producer pinned file differs: '+n)

def pe_x64(path):
    with Path(path).open('rb') as f:
        h=f.read(64);require(len(h)==64 and h[:2]==b'MZ','x64 PE tool required');off=struct.unpack_from('<I',h,60)[0]
        require(64<=off<=16*MIB,'PE offset cap');f.seek(off);h=f.read(24)
        require(len(h)==24 and h[:4]==b'PE\0\0' and struct.unpack_from('<H',h,4)[0]==0x8664,'x64 PE required')


def require_loaded_runtime(path):
    """Confirm the recorded DLL is actually loaded in this current Windows process."""
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetModuleHandleW.argtypes=[wintypes.LPCWSTR];kernel.GetModuleHandleW.restype=wintypes.HMODULE
    kernel.GetModuleFileNameW.argtypes=[wintypes.HMODULE,wintypes.LPWSTR,wintypes.DWORD];kernel.GetModuleFileNameW.restype=wintypes.DWORD
    module=kernel.GetModuleHandleW(Path(path).name);require(bool(module),'recorded Python runtime is not loaded')
    buffer=ctypes.create_unicode_buffer(32768);size=kernel.GetModuleFileNameW(module,buffer,len(buffer))
    require(0<size<len(buffer) and str(Path(buffer.value)).casefold()==str(Path(path)).casefold(),'actual loaded Python runtime differs')


def host_build(ctx, *, native=False, current=False):
    c=ctx.cc;v=c.strict_json(ctx.pin('host_binding').verify())
    c.exact_keys(v,('schema','candidate_id','session_id','runner_id','run_id','observed_host','native_observed_host','native_observation','tools','blender_version','blender_build_hash','blender_libraries','addon_relative','addon_pins_sha256','context_pins_sha256','producer_pins_sha256','gltf_source_files','native_environment_sha256','controller_environment_sha256','native_environment_keys'),'host')
    c.exact(v['schema'],HOST_SCHEMA,'host schema')
    for name,value in {'candidate_id':ctx.candidate_id,'session_id':ctx.session_id,'runner_id':ctx.host.runner_id,'run_id':ctx.host.run_id,
                       'observed_host':ctx.host.expected_host,'blender_version':[4,3,2],'context_pins_sha256':CONTEXT_PINS_SHA,
                       'producer_pins_sha256':ctx.raw['dependencies']['producer_pins_sha256']}.items():c.exact(v[name],value,'host '+name)
    c.sha(v['native_environment_sha256'])
    c.sha(v['controller_environment_sha256'])
    keys=v['native_environment_keys']
    require(type(keys) is list and len(keys)<=256 and all(type(k) is str and k and '=' not in k and '\0' not in k for k in keys),'native environment key inventory required')
    require(keys==sorted(set(keys)) and len({k.upper() for k in keys})==len(keys) and 'SYSTEMROOT' in {k.upper() for k in keys},'native environment keys ambiguous')
    require(not ({k.upper() for k in keys}&{'PYTHONPATH','PYTHONHOME','BLENDER_USER_SCRIPTS','BLENDER_SYSTEM_SCRIPTS','VRVIEW_TOOLS_PATH'}),'unreviewed native module lookup environment')
    require(type(v['blender_build_hash']) is str and 1<=len(v['blender_build_hash'])<=128,'actual Blender build hash required')
    c.exact_keys(v['tools'],('python','python_runtime','blender','blender_python_runtime'),'tool roles')
    seen=[]
    for role,rec in v['tools'].items():
        pin=c.FilePin.parse(role,rec);pin.verify();pe_x64(pin.path);seen.append(pin.path)
        if role.startswith('blender'):require(pin.path.is_relative_to(ctx.root('blender_bundle')),'tool outside explicit Blender bundle')
    require(len(set(seen))==4,'tool role alias')
    require(type(v['blender_libraries']) is list and 1<=len(v['blender_libraries'])<=128,'explicit relevant Blender library closure')
    for rec in v['blender_libraries']:
        pin=c.FilePin.parse('library',rec);require(pin.path.is_relative_to(ctx.root('blender_bundle')),'foreign bundle library');pin.verify()
    # The GLB static exporter depends on the inspected official glTF source tree.
    require(type(v['gltf_source_files']) is dict and 1<=len(v['gltf_source_files'])<=2048,'explicit glTF exporter source closure required')
    for rel,sha in v['gltf_source_files'].items():
        require(type(rel) is str and rel and not Path(rel).is_absolute() and '..' not in Path(rel).parts and 'io_scene_gltf2' in Path(rel).parts,'invalid glTF source path')
        require(file_sha(c.ordinary(ctx.root('blender_bundle')/rel,existing=True))==c.sha(sha),'glTF source pin differs')
    resolver=isolated_module('addon_resolver',ctx.root('context_package')/'addon_resolver.py',{'candidate_context':c})
    c.exact(v['addon_pins_sha256'],resolver.PIN_FILE_SHA,'official addon pins')
    files=resolver.resolve_addon(ctx.root('blender_bundle'),v['addon_relative'])
    verify_probe_binding(ctx,v,verify_transport(ctx,production=True),verify_completed_process)
    if current:
        if native:
            require_native_host(v['native_observed_host'],ctx.host.expected_host,ctx.context_sha256)
            import bpy
            require(tuple(bpy.app.version[:3])==(4,3,2) and bpy.app.background and not bpy.context.preferences.filepaths.use_scripts_auto_execute,'safe actual Blender host required')
            require(Path(bpy.app.binary_path)==Path(v['tools']['blender']['path']),'actual Blender binary differs')
            build=bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash,bytes) else str(bpy.app.build_hash)
            require(build==v['blender_build_hash'],'actual Blender build differs')
            import io_scene_fbx,io_scene_fbx.import_fbx
            modules={n:m for n,m in sys.modules.items() if n=='io_scene_fbx' or n.startswith('io_scene_fbx.')}
            resolver.verify_loaded_modules(files,modules)
            require(sys.flags.optimize==0,'assertions must not be disabled')
            require_loaded_runtime(v['tools']['blender_python_runtime']['path'])
        else:
            ctx.host.require_current_host()
            require(Path(sys.executable)==Path(v['tools']['python']['path']),'actual supervisor Python differs')
            require_loaded_runtime(v['tools']['python_runtime']['path'])
    return v

def receipt_ref(ctx):
    return {'context':{'path':str(ctx.path),'sha256':file_sha(ctx.path)},
            'native_receipt':{'path':str(ctx.output/'receipt.json'),'sha256':file_sha(ctx.output/'receipt.json')},
            'process_terminal':{'path':str(ctx.transport_output/'terminal.json'),'sha256':file_sha(ctx.transport_output/'terminal.json')}}

def verify_stage(stage_context_path,context_sha256,context_package,receipt_sha256,terminal_sha256,*,_active=None):
    """Default admission requires every native output file to remain present."""
    return _verify_stage(stage_context_path,context_sha256,context_package,receipt_sha256,terminal_sha256,_active=_active)


def verify_retained_stage(stage_context_path,context_sha256,context_package,receipt_sha256,terminal_sha256,*,retired_files):
    """Read-only source-chunk admission after independent retirement validation.

    The caller must first validate the immutable original chunk, retirement plan
    and journal. Only its exact full row+skin {POSIX name:{sha256,bytes}} inventory
    may be missing. Every input, index, envelope, process and dependency still
    passes the same verification as verify_stage. This API authorizes no deletion.
    """
    require(type(retired_files) is dict and retired_files,'exact retired file inventory required')
    return _verify_stage(stage_context_path,context_sha256,context_package,receipt_sha256,terminal_sha256,retired_files=retired_files)


def _verify_stage(stage_context_path,context_sha256,context_package,receipt_sha256,terminal_sha256,*,_active=None,retired_files=None):
    ctx=StageContext.read(stage_context_path,context_sha256,context_package);c=ctx.cc
    verify_package(ctx.raw['dependencies']['producer_pins_sha256']);ctx.verify_files();host=host_build(ctx)
    adapter=verify_transport(ctx,production=True)
    require(file_sha(ctx.output/'receipt.json')==c.sha(receipt_sha256),'native envelope pin differs')
    require(file_sha(ctx.transport_output/'terminal.json')==c.sha(terminal_sha256),'transport terminal pin differs')
    expected_host={'runner_id':ctx.host.runner_id,'run_id':ctx.host.run_id,'build_sha256':ctx.host.build_sha256,
        'context_sha256':ctx.context_sha256,'observed_host':ctx.host.expected_host,'owner_lock':str(ctx.owner_lock),
        'environment_sha256':host['native_environment_sha256'],'environment_keys':host['native_environment_keys']}
    tool=lambda role:{**host['tools'][role],'bytes':Path(host['tools'][role]['path']).stat().st_size}
    process=verify_completed_process(adapter,ctx.transport_output,{'command':native_argv(ctx),'cwd':str(ctx.candidate_root),
        'host_binding':expected_host,'limits':dataclasses.asdict(process_limits(adapter)),
        'supervisor_python':tool('python'),'executable':tool('blender'),'rows':0})
    env=c.strict_json(ctx.output/'receipt.json',32*MIB)
    c.exact_keys(env,('schema','stage','index','context_sha256','context_file_sha256','binding','output_files','payload','passed','source_saved','rendered','cross_platform_float64_equality_proved','runtime_equivalence_proved','artistic_approval','activation_authorized'),'native envelope')
    for name,expected in {'schema':'rust-duty-windows-native-stage/v1','stage':ctx.stage,'index':ctx.index,'context_sha256':ctx.context_sha256,'context_file_sha256':file_sha(ctx.path),'binding':ctx.binding,'passed':True,
                          'source_saved':False,'rendered':False,'cross_platform_float64_equality_proved':False,'runtime_equivalence_proved':False,'artistic_approval':False,'activation_authorized':False}.items():c.exact(env[name],expected,'native '+name)
    verify_output_inventory(ctx,env,retired_files=retired_files)
    validate_payload(ctx,env['payload'])
    validate_output_links(ctx,env)
    validate_dependencies(ctx,_active=_active)
    # This recomputed read-only field is not part of the stored receipt bytes.
    return {**env,'retained_process_validation':process['resources']}

def verify_reference(ctx,ref,active):
    c=ctx.cc;c.exact_keys(ref,('context','native_receipt','process_terminal'),'stage reference')
    pins={n:c.FilePin.parse(n,r) for n,r in ref.items()}
    for pin in pins.values():require(pin.path.is_relative_to(ctx.candidate_root),'foreign stage reference');pin.verify()
    key=pins['context'].sha256
    require(key not in active and len(active)<32,'cyclic/deep native stage evidence')
    active.add(key)
    try:return verify_stage(pins['context'].path,key,ctx.root('context_package'),pins['native_receipt'].sha256,pins['process_terminal'].sha256,_active=active)
    finally:active.remove(key)

def _verify_context_gate(ctx,gate_role,*,_active=None):
    """Recheck full control/focus/12-block evidence; a passed boolean never suffices."""
    c=ctx.cc;gate=c.strict_json(ctx.pin(gate_role).verify(),4*MIB);c.exact_keys(gate,('schema','kind','binding','stages'),'native gate')
    require(gate['schema']=='rust-duty-windows-native-gate/v1','native gate schema differs')
    kind={'control_gate':'control','focus_gate':'focus','conversion_gate':'conversion'}[gate_role];require(gate['kind']==kind,'wrong gate kind')
    binding=dict(ctx.binding)
    if kind=='control':binding.pop('actual_fbx_sha256',None)
    require(gate['binding']==binding,'mixed candidate native gate')
    refs=gate['stages'];require(type(refs) is list and len(refs)=={'control':3,'focus':3,'conversion':13}[kind],'gate complete stage inventory required')
    active=set() if _active is None else _active
    results=[verify_reference(ctx,ref,active) for ref in refs]
    for result in results:
        b=dict(result['binding'])
        if kind=='control':b.pop('actual_fbx_sha256',None)
        elif result['stage']=='export':b['actual_fbx_sha256']=result['output_files']['animation.fbx']['sha256']
        require(b==binding,'stage/gate candidate binding differs')
    if kind=='control':
        require([r['stage'] for r in results]==['control-export','control-full','control-bounded'],'fresh target export/full/bounded trio required')
        exported,full,bounded=results;payload=bounded['payload']
        require(exported['output_files']['animation.fbx']['sha256']==full['payload']['fbx_sha256'],'full oracle uses a different control export')
        full_file=full['output_files']['full-control.json']['sha256']
        require(payload['full_import_control_sha256']==full_file and payload['fbx_sha256']==full['payload']['fbx_sha256'],'bounded compared different full oracle or FBX')
    elif kind=='focus':
        require([r['stage'] for r in results]==['export','source-focus','focus-import'],'export/source/import focus required')
        export,source,imported=results
        # Export predates actual_fbx; output file creates that exact role.
        require(export['output_files']['animation.fbx']['sha256']==ctx.pin('actual_fbx').sha256,'focus uses different exported FBX')
        require(imported['payload']['source_oracle_sha256']==source['output_files']['source-samples.json']['sha256'],'focus source oracle differs')
    else:
        require(results[0]['stage']=='geometry' and [(r['stage'],r['index']) for r in results[1:]]==[('block',i) for i in range(12)],'exact ordered 12 block production required')
        geometry=results[0]['output_files']['runtime/geometry-metadata.json']['sha256']
        require(all(r['payload']['geometry_metadata_sha256']==geometry for r in results[1:]),'block geometry identity differs')
    return {'schema':gate['schema'],'kind':kind,'binding':binding,'stages':results}

def validate_dependencies(ctx,*,_active=None):
    for role in ('control_gate','focus_gate'):
        if role in ctx.raw['files']:_verify_context_gate(ctx,role,_active=_active)


def validate_payload(ctx,p):
    require(type(p) is dict,'native payload required');stage=ctx.stage
    if stage in SOURCE_STAGES:
        for flag in ('source_bytes_unchanged','in_memory_source_state_restored'):require(p.get(flag) is True,'source restoration evidence required')
        require(p.get('source_saved') is False and p.get('rendered') is False,'source was saved/rendered')
    if stage in ('export','control-export'):
        n=64 if stage=='control-export' else 256
        g=p['raw_key_grid'];require(g['passed'] is True and g['key_count']==95*n+1 and g['subdivisions']==n and g['curve_count']==1379 and g['logical_stack']==ctx.cc.ACTION,'exact full raw export required')
    if stage=='control-full':require(p['bones']==148 and p['samples']==9 and p['full_key_count']==6081 and p['subdivisions']==64 and p['all_curves_full_instantiated'] is True,'fresh full control coverage differs')
    if stage=='control-bounded':
        require(p['passed'] is True and p['bones']==148 and p['matrix_components_checked']==21312 and p['matrix_component_bit_mismatch_count']==0 and p['focus_channel_bit_mismatch_count']==0 and p['maximum_component_difference']==0 and p['mismatches']==[],'same-target bounded/full control failed')
    if stage in ('focus-import','chunk-import'):
        from native_stages import MAXIMA
        require(p['sample_frames']==ctx.frames() and p['samples']==len(ctx.frames()) and p['skin_vertex_samples']==len(ctx.frames())*10234 and p['source_total_bones_including_helpers']==148,'source/skin/time coverage differs')
        require(type(p['checks']) is dict and set(p['checks'])==set(FOCUS_CHECKS) and all(v is True for v in p['checks'].values()),'full native checks required')
        require(set(p['maxima'])==set(MAXIMA) and all(type(v) in (float,int) and 0<=v<1e-4 for v in p['maxima'].values()),'strict matrix/position bounds differ')
        require(type(p['camera_projection_ray_error']) in (float,int) and 0<=p['camera_projection_ray_error']<1e-5,'strict projection bound differs')
        require(p['off_key_source_frames']==[f for f in ctx.frames() if f*256!=int(f*256)],'offkey coverage differs')
    if 'window_admission' in p:
        w=p['window_admission'];require(w['passed'] is True and w['retained_key_count']<=2051 and w['requested_source_frames']==ctx.frames(),'window coverage/cap differs')
        require(w['full_transformed_admission']['full_transform_sequence_preserved_before_selection'] is True and w['full_transformed_admission']['all_full_input_times_values_checked'] is True,'full official transform history required')
        require(w['full_raw_admission']['curve_count']==1379 and w['full_raw_admission']['all_times_values_finite_checked'] is True,'all raw curves required')
        require(ctx.cc.digest(w['full_raw_admission'])==w['full_raw_admission_sha256'] and ctx.cc.digest(w['full_transformed_admission'])==w['full_transformed_admission_sha256'],'raw/transform evidence hashes differ')


def verify_gate(path,expected_sha,context_package):
    """Public caller-pinned target control/focus/conversion gate verifier."""
    c=load_context(context_package);pin=c.FilePin.parse('gate',{'path':str(path),'sha256':expected_sha})
    gate=c.strict_json(pin.verify(),4*MIB);c.exact_keys(gate,('schema','kind','binding','stages'),'native gate')
    require(type(gate['stages']) is list and gate['stages'],'complete native gate references required')
    first=gate['stages'][0]['context'];ctx=StageContext.read(first['path'],first['sha256'],context_package)
    require(pin.path.is_relative_to(ctx.candidate_root),'foreign native gate')
    # Use a tiny immutable role view; no frozen/global source constants change.
    class GateView:
        def __getattr__(self,name):return getattr(ctx,name)
        def pin(self,role):return pin if role=='conversion_gate' or role=='focus_gate' or role=='control_gate' else ctx.pin(role)
    roles={'control':'control_gate','focus':'focus_gate','conversion':'conversion_gate'}
    require(gate['kind'] in roles,'unknown gate kind')
    view=GateView()
    if gate['kind']=='focus':
        # Export context predates the actual FBX role; bind its declared output.
        export_receipt=c.strict_json(gate['stages'][0]['native_receipt']['path'],32*MIB)
        class FocusGateView(GateView):
            @property
            def binding(self):return {**ctx.binding,'actual_fbx_sha256':export_receipt['output_files']['animation.fbx']['sha256']}
            def pin(self,role):
                if role=='actual_fbx':return c.FilePin.parse(role,{'path':str(ctx.output/'animation.fbx'),'sha256':self.binding['actual_fbx_sha256']})
                return super().pin(role)
        view=FocusGateView()
    return _verify_context_gate(view,roles[gate['kind']])


def validate_output_links(ctx,env):
    """Bind numerical payload fields to exact retained output bytes."""
    p=env['payload'];files=env['output_files'];stage=ctx.stage
    def linked(name,wanted):
        require(name in files and files[name]['sha256']==wanted,'native payload/output hash mismatch: '+name)
    if stage in ('export','control-export','source-focus','source-chunk'):
        require(p['samples']==len(ctx.frames()) and p['sample_frames']==ctx.frames(),'source witness coverage differs')
        linked('source-samples.json',p['source_samples_sha256'])
        sample=ctx.cc.strict_json(ctx.output/'source-samples.json',32*MIB)
        require(sample['generated_source_sha256']==ctx.pin('generated_source').sha256 and sample['approved_source_sha256']==ctx.cc.APPROVED_SHA,'source index provenance differs')
        require(list(sample['frames'])==[str(f) for f in ctx.frames()] and len(sample['source_rest_world'])==148 and set(sample['source_rest_world'])==set(sample['hierarchy']),'ordered all148 source witness required')
        for i,f in enumerate(ctx.frames()):
            row=sample['frames'][str(f)]
            require(row['source_frame']==f,'source row time differs')
            require(row['row_path']==f'sample-rows/{i:04d}.json' and row['skin_path']==f'skin-rows/{i:04d}.npz','source descriptor exact POSIX path differs')
            linked(row['row_path'],row['row_sha256']);linked(row['skin_path'],row['skin_sha256'])
        if stage in ('export','control-export'):linked('animation.fbx',p['actual_fbx_sha256'])
    elif stage=='control-full':linked('full-control.json',p['full_control_sha256'])
    elif stage in ('control-bounded','focus-import','chunk-import'):
        require(ctx.cc.strict_json(ctx.output/'report.json',32*MIB)==p,'native measured report/payload differs')
    elif stage=='geometry':linked('runtime/geometry-metadata.json',p['geometry_metadata_sha256'])
    elif stage=='block':
        lo=ctx.index*2048;hi=min(lo+2048,24320)
        for key,expected in {'block_index':ctx.index,'start_tick':lo,'end_tick':hi,'frames':hi-lo+1,'frame_bytes':3007,'final_full_key_count':24321,'full_clip_instantiated':False}.items():ctx.cc.exact(p.get(key),expected,'block '+key)
        linked('block/frames.bin',p['frame_file_sha256'])
        require(files['block/frames.bin']['bytes']==p['frame_file_bytes']==(hi-lo+1)*3007,'exact packed frame byte count differs')
        require(ctx.cc.strict_json(ctx.output/'block/receipt.json',32*MIB)==p,'block numerical receipt differs')
    elif stage in ('rigid-frame1','rigid-focus','rigid-chunk'):
        require(p['source_frames']==ctx.frames() and [r['source_frame'] for r in p['samples']]==ctx.frames() and p['actor_count']==3 and p['full_float64_and_topology_bytes_compared'] is True,'complete rigid geometry coverage required')


def verify_output_inventory(ctx,env,*,retired_files=None):
    """Same exact present inventory, except independently retired source rows."""
    c=ctx.cc;files=env['output_files']
    require(type(files) is dict and 1<=len(files)<=150,'bounded output inventory')
    retired={} if retired_files is None else retired_files
    if retired_files is not None:
        require(ctx.stage=='source-chunk','only source-chunk rows may be retired')
        sample=c.strict_json(ctx.output/'source-samples.json',32*MIB)
        require(list(sample['frames'])==[str(f) for f in ctx.frames()],'retired source frame inventory differs')
        allowed={}
        for i,f in enumerate(ctx.frames()):
            row=sample['frames'][str(f)];require(row['source_frame']==f,'retired source row time differs')
            for kind,folder,ext in (('row','sample-rows','json'),('skin','skin-rows','npz')):
                name=f'{folder}/{i:04d}.{ext}'
                require(row[kind+'_path']==name and name in files and files[name]['sha256']==row[kind+'_sha256'],'retired descriptor/hash differs')
                allowed[name]=files[name]
        process_exact(retired,allowed,'exact full retired row/skin inventory')
        require(len(retired)==2*len(ctx.frames()),'exact full retired row/skin inventory required')
    total=0
    for name,rec in files.items():
        require(type(name) is str and name and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts and '\\' not in name and PurePosixPath(name).as_posix()==name,'unsafe native output path')
        c.exact_keys(rec,('sha256','bytes'),'native output');c.sha(rec['sha256'])
        require(type(rec['bytes']) is int and rec['bytes']>=0,'native output byte count invalid');total+=rec['bytes']
        path=c.ordinary(ctx.output/name,existing=name not in retired)
        if name in retired:
            require(not path.exists(),'retired output unexpectedly exists')
        else:require(path.is_file() and path.stat().st_size==rec['bytes'] and file_sha(path)==rec['sha256'],'native output differs')
    actual=set()
    for path in ctx.output.rglob('*'):
        c.ordinary(path,existing=True)
        if path.is_file():actual.add(path.relative_to(ctx.output).as_posix())
    require(actual-{'receipt.json'}==set(files)-set(retired) and total<=output_cap(ctx),'native output inventory/cap differs')
