"""Ordinary file identities and isolated imports for direct game delivery."""
from __future__ import annotations
import builtins, hashlib, json, os, re, shutil, stat, sys, types, uuid
from pathlib import Path
GIB=1024**3

def need(value, message):
    if not value: raise ValueError(message)

def ordinary(path, exists=False):
    path=Path(path).absolute()
    need('..' not in path.parts, 'parent path not permitted')
    for part in (*reversed(path.parents),path):
        if part.exists() or part.is_symlink():
            info=part.lstat()
            need(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,'redirected path not permitted')
    if exists: need(path.exists(),'required input missing: '+path.name)
    return path

def logical(value):
    need(isinstance(value,str) and value and '\\' not in value and '\0' not in value,'invalid relative path')
    p=Path(value);need(not p.is_absolute() and all(x not in ('','.','..') and ':' not in x for x in value.split('/')),'unsafe relative path')
    return p

def sha(path):
    with ordinary(path,True).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def record(path):return {'path':str(ordinary(path,True)),'sha256':sha(path),'bytes':Path(path).stat().st_size}
def pin(path,expected):
    need(isinstance(expected,str) and re.fullmatch('[0-9a-f]{64}',expected),'invalid file digest')
    need(sha(path)==expected,'input hash differs: '+Path(path).name);return ordinary(path,True)

def read(path,limit=16*1024**2):
    with ordinary(path,True).open('rb') as f: data=f.read(limit+1)
    need(len(data)<=limit,'JSON file exceeds limit')
    def pairs(rows):
        out={}
        for key,val in rows:need(key not in out,'duplicate JSON key');out[key]=val
        return out
    return json.loads(data,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))

def write(path,value):
    path=ordinary(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(canonical(value))
    return record(path)

def capacity(path,reserve=0):
    path=ordinary(path)
    while not path.exists():path=path.parent
    need(shutil.disk_usage(path).free>=GIB+reserve,'1 GiB disk floor plus operation reserve required')

def module(name,path,loaded=None):
    loaded={} if loaded is None else loaded;private='_direct_'+uuid.uuid4().hex+'_'+name
    m=types.ModuleType(private);m.__file__=str(path)
    def importer(key,globals=None,locals=None,fromlist=(),level=0):
        return loaded[key] if key in loaded and level==0 else builtins.__import__(key,globals,locals,fromlist,level)
    m.__dict__['__builtins__']={**vars(builtins),'__import__':importer};sys.modules[private]=m
    try:exec(compile(Path(path).read_bytes(),str(path),'exec'),m.__dict__)
    finally:sys.modules.pop(private,None)
    loaded[name]=m;return m
