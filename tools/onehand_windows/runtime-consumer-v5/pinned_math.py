"""Compile unchanged audited definitions in explicit isolated namespaces.

No old common module is imported, no SOURCE_SHA/SAMPLER_SHA is defined/reassigned,
no prone clock/camera normalization function is selected. Every extracted node
is checked against both its exact original bytes and its original AST.
"""
from __future__ import annotations
import ast,builtins,hashlib,json,math,mmap,struct,sys,zlib
from itertools import product
from pathlib import Path
from types import ModuleType,SimpleNamespace
import numpy as np
HERE=Path(__file__).resolve().parent
CONTEXT_PINS_SHA='3162a4c5bbc50daa13ec1c84972b0e4b56c2221a909d1aa2c10617c912b0d801'
ACTION='aella_mantle_onehand_r6_camera_reconstructed_v6'
ACTION_SHA='c7ca6383364e055afe1d0246f443d33689ce86c56677570ba694a924c983ea01'
GRID_SHA='a521b1e779e45f85948d94b8b9aa9f9cad41d935783ba5fcbda34decb6aec08f'
CANONICAL_SHA='d02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab'
ACTORS=('hk416_weapon','hk416_magazine','hk416_magazine_outgoing')
COUNTS=(5710,3954,570);SKINS=tuple(f'Actual arms mesh {i}' for i in range(3))
LIMIT=1e-4;RAY_LIMIT=1e-5;FOCUS=[55.65625+i/512 for i in range(9)]
ERROR_KEYS=('skin_world_m','skin_camera_relative_m','bone_deformation_matrix','bone_head_world_m','bone_head_camera_relative_m','actor_world_matrix','actor_camera_relative_matrix','rigid_world_m','rigid_camera_relative_m')
FBX_KEYS=('bone_deformation_world_matrix','bone_head_world_m','actor_world_matrix','actor_camera_relative_matrix','camera_world_matrix','rig_world_matrix','skin_world_m','skin_camera_relative_m')
FBX_CHECKS=('bone_inventory','hierarchy','animated_camera_bound','animated_rig_bound','single_exact_take',*FBX_KEYS,'finite_bones','skin_topology','camera_projection_rays','camera_type','single_native_clock','fps','source_unchanged','fbx_unchanged')
THRESHOLDS={'position_m':LIMIT,'matrix_element':LIMIT,'source_fbx_projection_ray':RAY_LIMIT}
AUDITED_PATCHES={'blen_read_animations':'757bd21550d94e2190881ec6b0eb0ce80b275d2a230055cf7702044fe6dcc6e2','blen_store_keyframes_multi':'793a389ebde0e71ec3cec54e731c861753aa08015355904777a8c39b70da3a4e'}
class Error(ValueError):pass
def require(ok,message):
    if not ok:raise Error(message)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(65536),b''):h.update(b)
    return h.hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def exact(value,want,label):require(type(value) is type(want) and value==want,'mismatch: '+label)
def finite_number(v,label):require(type(v) in (int,float) and math.isfinite(v),'invalid '+label);return v
def pin(p,h):require(sha(p)==h,'file pin differs: '+str(p));return p
def loads(value):
    def pairs(items):
        out={}
        for k,v in items:require(k not in out,'duplicate JSON field');out[k]=v
        return out
    def bad(v):raise Error('nonfinite JSON')
    return json.loads(value,object_pairs_hook=pairs,parse_constant=bad)
def read(path):
    with Path(path).open('rb') as f:raw=f.read(64*1024**2+1)
    require(len(raw)<=64*1024**2,'JSON byte cap');return loads(raw)
def bounded(root,relative):
    require(isinstance(relative,str) and relative and not Path(relative).is_absolute() and '..' not in Path(relative).parts,'unsafe evidence path')
    p=Path(root)/relative
    for part in (p,*p.parents):
        if part.exists():require(not part.is_symlink() and not getattr(part.lstat(),'st_file_attributes',0)&0x400,'linked evidence path')
    require(p.resolve().is_relative_to(Path(root).resolve()),'outside evidence root');return p

def private_module(name,path,known):
    m=ModuleType('_windows_runtime_'+name);m.__file__=str(path)
    def importer(key,globals=None,locals=None,fromlist=(),level=0):
        if key in known:return known[key]
        return builtins.__import__(key,globals,locals,fromlist,level)
    m.__dict__['__builtins__']={**vars(builtins),'__import__':importer}
    sys.modules[m.__name__]=m
    try:exec(compile(path.read_bytes(),str(path),'exec',dont_inherit=True),m.__dict__)
    finally:del sys.modules[m.__name__]
    return m

def context_module(package):
    package=Path(package);pin(package/'PINS.json',CONTEXT_PINS_SHA)
    inventory=read(package/'PINS.json')
    for name,value in inventory.items():
        require(Path(name).name==name,'unsafe context pin name');pin(package/name,value)
    return private_module('context',package/'candidate_context.py',{})

def load(audited_source):
    root=Path(audited_source);pins=read(HERE/'ORIGINAL_PINS.json');fragments=read(HERE/'MATH_FRAGMENTS.json')
    for name,value in pins.items():pin(root/name,value)
    known={}
    for name in ('vrpack','vrskin','vrview'):
        known[name]=private_module(name,root/'onehand-runtime-20261016/importer-patch/tools'/(name+'.py'),known)
    def extract(group,namespace):
        item=fragments[group];text=(root/item['source_path']).read_text();nodes={n.name:n for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))};lines=text.splitlines(keepends=True)
        for name,value in item['definitions'].items():
            n=nodes[name];raw=''.join(lines[n.lineno-1:n.end_lineno])
            require(raw==value['source'] and hashlib.sha256(raw.encode()).hexdigest()==value['byte_sha256'],'math bytes differ: '+name)
            require(hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()==value['ast_sha256'],'math AST differs: '+name)
            exec(compile(ast.Module(body=[n],type_ignores=[]),item['source_path'],'exec',dont_inherit=True),namespace)
    shared={**globals(),'AdmissionError':Error,'VerificationError':Error,'POSITION_LIMIT':LIMIT,'TIME_LIMIT':1e-7,'RUNTIME_HZ':15360,'RUNTIME_KEYS':24321,'SUBDIVISIONS':256,'BASIS':np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]],dtype=float),**known}
    geo=dict(shared);extract('geometry',geo);G=SimpleNamespace(**geo);ns={**shared,'G':G}
    for group in ('common','scanner','window','parity'):extract(group,ns)
    for name,value in pins.items():pin(root/name,value)
    return SimpleNamespace(**ns)
