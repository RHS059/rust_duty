"""Actual Blender4.3.2 safe-read host probe; no scene, save, export or render."""
import ctypes,hashlib,json,os,platform,re,sys
from pathlib import Path

def observe_host():
    if sys.platform!='win32' or ctypes.sizeof(ctypes.c_void_p)!=8:
        raise ValueError('actual native 64-bit Windows Blender required')
    value={k:getattr(platform,k)() for k in ('system','release','version','machine')}
    if any(type(v) is not str or not 1<=len(v)<=128 or '\0' in v or not v.strip() or v.strip().casefold()=='unknown' for v in value.values()):
        raise ValueError('complete native host observation required')
    if value['system']!='Windows' or value['machine']!='AMD64':
        raise ValueError('actual native AMD64 Windows Blender required')
    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',value['release']) is None:
        raise ValueError('native host release invalid')
    if re.fullmatch(r'[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,10}',value['version']) is None:
        raise ValueError('native host version invalid')
    return value

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()

def main():
    import bpy,io_scene_fbx
    observed_host=observe_host()
    assert sys.platform=='win32' and tuple(bpy.app.version[:3])==(4,3,2)
    assert bpy.app.background and not bpy.context.preferences.filepaths.use_scripts_auto_execute
    assert sys.flags.optimize==0 and hasattr(sys,'dllhandle')
    get_name=ctypes.WinDLL('kernel32',use_last_error=True).GetModuleFileNameW
    get_name.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint];get_name.restype=ctypes.c_uint
    buffer=ctypes.create_unicode_buffer(32768);n=get_name(sys.dllhandle,buffer,len(buffer));assert 0<n<len(buffer)
    args=sys.argv[sys.argv.index('--')+1:];assert len(args)==1
    output=Path(args[0]);assert output.is_absolute() and not output.exists()
    value={'schema':'rust-duty-official-blender-host-observation/v2','observed_host':observed_host,'sys_platform':sys.platform,'pointer_bits':ctypes.sizeof(ctypes.c_void_p)*8,'blender_version':list(bpy.app.version[:3]),'blender_build_hash':bpy.app.build_hash.decode(),'blender_binary':str(Path(bpy.app.binary_path)),'blender_binary_sha256':sha(bpy.app.binary_path),'python_runtime':str(Path(buffer.value)),'python_runtime_sha256':sha(buffer.value),'fbx_addon_file':str(Path(io_scene_fbx.__file__)),'background':True,'autoexec_disabled':True,'source_saved':False,'rendered':False}
    with output.open('xb') as f:f.write((json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode());f.flush();os.fsync(f.fileno())
if __name__=='__main__':main()
