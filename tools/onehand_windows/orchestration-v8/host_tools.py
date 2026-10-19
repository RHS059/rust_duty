"""Bind observed official archive/bundle, live DLLs and exact native environment."""
import ctypes,platform,sys
from pathlib import Path
from workflow_core import *
from owned_commands import Commands,transport_environment_binding

BLENDER_SHA='933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6'
BLENDER_BYTES=405138423
VENDOR='https://download.blender.org/release/Blender4.3/'

def python_runtime():
    require(sys.platform=='win32' and hasattr(sys,'dllhandle'),'actual Windows Python required')
    get_name=ctypes.WinDLL('kernel32',use_last_error=True).GetModuleFileNameW
    get_name.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint];get_name.restype=ctypes.c_uint
    buffer=ctypes.create_unicode_buffer(32768);n=get_name(sys.dllhandle,buffer,len(buffer));require(0<n<len(buffer),'actual Python DLL observation failed');return ordinary(buffer.value,True)

def verify_install(path,bundle):
    receipt=strict_json(path)
    exact={'schema':'rust-duty-onehand-official-blender-install/v1','version':'4.3.2','vendor_checksum_url':VENDOR+'blender-4.3.2.sha256','archive_url':VENDOR+'blender-4.3.2-windows-x64.zip','vendor_sha256':BLENDER_SHA,'archive_sha256':BLENDER_SHA,'archive_bytes':BLENDER_BYTES,'bundle_root':str(bundle)}
    for k,v in exact.items():require(type(receipt.get(k)) is type(v) and receipt[k]==v,'official Blender installer receipt differs: '+k)
    archive=pin(receipt['archive_path'],BLENDER_SHA);require(archive.stat().st_size==BLENDER_BYTES,'Blender archive bytes differ')
    require(sha(bundle/'blender.exe')==receipt['executable_sha256'],'actual official Blender executable differs')
    require(receipt['vendor_checksum_verified'] is True,'actual vendor checksum required')
    # This is a second read of retained vendor data, not just a passed flag.
    checksum_path=pin(receipt['vendor_checksum_file']['path'],receipt['vendor_checksum_file']['sha256'])
    lines=checksum_path.read_text().splitlines();name='blender-4.3.2-windows-x64.zip'
    matches=[m.group(1).lower() for line in lines if (m:=re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?'+re.escape(name),line))]
    require(matches==[BLENDER_SHA],'retained official vendor checksum differs')
    return receipt

def collect(config,adapter,cc,candidate,process_validator):
    require(sys.platform=='win32' and platform.system()=='Windows','actual Windows controller required')
    bundle=ordinary(config['roots']['blender_bundle'],True);install=verify_install(config['blender_install_receipt'],bundle)
    host={'runner_id':config['runner_id'],'run_id':config['run_id'],**{k:getattr(platform,k)() for k in ('system','release','version','machine')},'build_sha256':digest({'install_receipt':file_pin(config['blender_install_receipt']),'python':file_pin(sys.executable),'python_runtime':file_pin(python_runtime())})}
    commands=Commands(adapter,host,candidate,config['native_environment'],process_validator,diagnostic_roots=config['roots'])
    candidate.mkdir(parents=True,exist_ok=True)
    embedded=bundle/'4.3'/'python'/'bin'/'python.exe';require(embedded.is_file(),'official embedded Python missing')
    commands.run('blender-ensurepip',[str(embedded),'-I','-m','ensurepip'],candidate,reserve=128*1024**2)
    commands.run('blender-pillow-install',[str(embedded),'-I','-m','pip','--isolated','install','--index-url','https://pypi.org/simple','--disable-pip-version-check','--no-cache-dir','--no-deps','--only-binary=:all:','Pillow==11.3.0'],candidate,reserve=128*1024**2)
    site=bundle/'4.3'/'python'/'lib'/'site-packages'
    supplemental={'schema':'rust-duty-onehand-embedded-python-closure/v1','root':str(site),'files':inventory(site),'installed_requirement':'Pillow==11.3.0','installation_processes':[file_pin(candidate/'process'/(label)/'terminal.json') for label in ('blender-ensurepip','blender-pillow-install')]}
    config['embedded_python_closure']=write_new(candidate/'embedded-python-closure.json',supplemental)
    probe=candidate/'blender-observed.json';exe=bundle/'blender.exe'
    command=[str(exe),'--background','--factory-startup','--disable-autoexec','--threads','1','--python-exit-code','1','--python',str(HERE/'probe_blender.py'),'--',str(probe)]
    result=commands.run('blender-host-observation',command,candidate,reserve=1024**2)
    value=strict_json(probe);require(value['blender_version']==[4,3,2] and value['blender_binary_sha256']==sha(exe),'observed Blender binary/version differs')
    require(value['blender_binary']==str(exe) and value['source_saved'] is False and value['rendered'] is False,'unexpected host probe action')
    addon=ordinary(value['fbx_addon_file'],True).parent;require(addon.is_relative_to(bundle),'foreign FBX addon')
    resolver=module('addon_resolver',Path(config['roots']['context_package'])/'addon_resolver.py',{'candidate_context':cc});resolver.resolve_addon(bundle,addon.relative_to(bundle).as_posix())
    gltf=addon.parent/'io_scene_gltf2';require(gltf.is_dir(),'official glTF addon missing')
    gltf_files={p.relative_to(bundle).as_posix():sha(p) for p in sorted(gltf.rglob('*.py'))}
    dlls=sorted(bundle.glob('*.dll'));require(dlls,'official Blender shared libraries missing')
    transport_env=transport_environment_binding(adapter,config['native_environment'])
    result={'schema':'rust-duty-windows-native-host/v2','candidate_id':config['candidate_id'],'session_id':config['session_id'],'runner_id':config['runner_id'],'run_id':config['run_id'],'observed_host':{k:host[k] for k in ('system','release','version','machine')},'tools':{'python':file_pin(sys.executable),'python_runtime':file_pin(python_runtime()),'blender':file_pin(exe),'blender_python_runtime':file_pin(value['python_runtime'])},'blender_version':[4,3,2],'blender_build_hash':value['blender_build_hash'],'blender_libraries':[file_pin(p) for p in dlls],'addon_relative':addon.relative_to(bundle).as_posix(),'addon_pins_sha256':resolver.PIN_FILE_SHA,'context_pins_sha256':config['pins']['context'],'producer_pins_sha256':config['pins']['producer'],'gltf_source_files':gltf_files,'native_environment_sha256':transport_env['environment_sha256'],'native_environment_keys':transport_env['environment_keys']}
    path=candidate/'host-binding.json';write_new(path,result);host['build_sha256']=sha(path)
    return host,file_pin(path),Commands(adapter,host,candidate,config['native_environment'],process_validator,diagnostic_roots=config['roots'])


def verify_embedded(config):
    closure=config['embedded_python_closure'];value=strict_json(pin(closure['path'],closure['sha256']))
    require(inventory(value['root'])==value['files'],'embedded Python code changed after exact dependency install')
    return closure
