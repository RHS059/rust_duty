"""Small immutable orchestration primitives. No native imports at import time."""
from __future__ import annotations
import builtins, contextlib, hashlib, json, os, re, shutil, stat, sys, types, uuid
from pathlib import Path
from types import SimpleNamespace

GIB=1024**3
HERE=Path(__file__).absolute().parent

def require(value,message):
    if not value: raise ValueError(message)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def sha_value(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None,'missing or invalid reviewed SHA256')
    return value

def ordinary(value,existing=False):
    require(isinstance(value,(str,Path)) and '\0' not in str(value),'invalid path')
    p=Path(value);require(p.is_absolute() and '..' not in p.parts,'absolute ordinary path required')
    for component in p.parts[1:]:
        require(':' not in component and component==component.rstrip(' .') and not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',component),'ambiguous Windows path')
    for part in (*reversed(p.parents),p):
        try: info=part.lstat()
        except FileNotFoundError: continue
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,'symlink/reparse forbidden')
    if existing:require(p.exists(),'required path absent')
    return p

def sha(path):
    p=ordinary(path,True);h=hashlib.sha256()
    with p.open('rb') as f:
        before=os.fstat(f.fileno());require(stat.S_ISREG(before.st_mode),'regular file required')
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
        after=os.fstat(f.fileno())
    require((before.st_size,before.st_mtime_ns,before.st_ino)==(after.st_size,after.st_mtime_ns,after.st_ino),'file changed during hash')
    return h.hexdigest()

def pin(path,expected):
    require(sha(path)==sha_value(expected),'file pin differs: '+Path(path).name);return ordinary(path,True)

def file_pin(path):return {'path':str(ordinary(path,True)),'sha256':sha(path)}
def record(path):return {**file_pin(path),'bytes':Path(path).stat().st_size}

def strict_json(path,cap=16*1024**2):
    def pairs(values):
        out={}
        for k,v in values:require(k not in out,'duplicate JSON key');out[k]=v
        return out
    def bad(v):raise ValueError('nonfinite JSON')
    with ordinary(path,True).open('rb') as f:raw=f.read(cap+1)
    require(len(raw)<=cap,'JSON cap exceeded')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=bad)

def capacity(path,reserve=0):
    p=ordinary(path)
    while not p.exists():p=p.parent
    require(shutil.disk_usage(p).free>=GIB+reserve,'1 GiB floor plus bounded reserve required')

def write_new(path,value,cap=16*1024**2):
    p=ordinary(path);raw=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    require(len(raw)<=cap,'output JSON cap');capacity(p,len(raw));p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return file_pin(p)

def package(root,expected,kind='flat'):
    root=ordinary(root,True);pin(root/'PINS.json',expected);value=strict_json(root/'PINS.json')
    files=value['files'] if kind=='transport' else value
    require(type(files) is dict and files,'source package inventory required')
    for n,h in files.items():
        require(Path(n).name==n and n not in ('.','..'),'unsafe package filename')
        pin(root/n,h['sha256'] if kind=='transport' else h)
    return value

def module(name,path,loaded):
    # Exact source is checked by package()/input inventory before this function.
    private='_onehand_workflow_'+uuid.uuid4().hex+'_'+name
    m=types.ModuleType(private);m.__file__=str(path)
    def importer(key,globals=None,locals=None,fromlist=(),level=0):
        if key in loaded:require(level==0,'relative package import forbidden');return loaded[key]
        return builtins.__import__(key,globals,locals,fromlist,level)
    m.__dict__['__builtins__']={**vars(builtins),'__import__':importer};sys.modules[private]=m
    try:exec(compile(Path(path).read_bytes(),str(path),'exec',dont_inherit=True),m.__dict__)
    finally:sys.modules.pop(private,None)
    loaded[name]=m;return m

def modules(root,names):
    loaded={}
    for n in names:module(n,Path(root)/(n+'.py'),loaded)
    return SimpleNamespace(**loaded)

def inventory(root):
    root=ordinary(root,True);out={}
    for base,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=sorted(dirs)
        for d in dirs:ordinary(Path(base)/d,True)
        for n in sorted(names):out[(Path(base)/n).relative_to(root).as_posix()]=sha(Path(base)/n)
    require(out,'empty source inventory');return out

def unique_roles(files):
    paths=[ordinary(r['path'],True) for r in files.values()]
    require(len({str(p).casefold() for p in paths})==len(paths),'role path aliases')
    ids=[(p.stat().st_dev,p.stat().st_ino) for p in paths]
    require(len(set(ids))==len(ids),'hardlinked input aliases')

def materialize_companion(source,target):
    """Only already-generated same-candidate runtime bytes; never source assets."""
    source=ordinary(source,True);target=ordinary(target)
    require(source.name==target.name and source.name in ('asset.vrs','asset.vrm'),'only generated runtime companion layout')
    require(not target.exists(),'fresh runtime companion required');expected=record(source);capacity(target,expected['bytes'])
    with source.open('rb') as src,target.open('xb') as dst:
        for b in iter(lambda:src.read(1024**2),b''):dst.write(b)
        dst.flush();os.fsync(dst.fileno())
    pin(source,expected['sha256']);pin(target,expected['sha256']);return file_pin(target)

def sequence():
    result=[('control-export',None),('control-full',None),('control-bounded',None),('export',None),('source-focus',None),('focus-import',None),('rigid-frame1',None),('rigid-focus',None),('geometry',None)]
    result.extend(('block',i) for i in range(12))
    for i in range(67):result.extend((stage,i) for stage in ('source-chunk','chunk-import','rigid-chunk'))
    return tuple(result)


def private_call(root,call):
    """Keep imported CLI diagnostics runner-local, including failed raw errors."""
    root=ordinary(root);require(not root.exists(),'fresh private CLI logs required');capacity(root,2*1024**2);root.mkdir(parents=True)
    class BoundedLog:
        def __init__(self,file):self.file=file;self.bytes=0
        def write(self,value):
            raw=value.encode('utf-8');self.bytes+=len(raw);require(self.bytes<=1024**2,'private CLI log cap');self.file.write(raw);return len(value)
        def flush(self):self.file.flush()
    with (root/'stdout.log').open('xb') as out,(root/'stderr.log').open('xb') as err:
        with contextlib.redirect_stdout(BoundedLog(out)),contextlib.redirect_stderr(BoundedLog(err)):
            result=call()
    write_new(root/'logs.json',{'stdout':record(root/'stdout.log'),'stderr':record(root/'stderr.log')})
    return result
