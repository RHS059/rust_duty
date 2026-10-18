"""Explicit immutable current-game/source-input export. No network or Git writes."""
from pathlib import Path,PurePosixPath
import re,subprocess,hashlib,shutil
from continuation_core import need,sha_bytes,pin,read,write_new,record
from game_plan import JUMP_REF,JUMP_PATH

MAX_SOURCE_BYTES=1024**3
SOURCE_PREFIXES=('src/','updater/','examples/','tests/','ui/','profiles/')
ASSET_PREFIXES=('assets/locomotion/','assets/source/reload/','assets/authoring/locomotion/',
    'assets/authoring/ads/','assets/authoring/locomotion_directional/','assets/authoring/jump/',
    'assets/walk/','assets/ads/','assets/jump/','assets/levels/','assets/weapons/')
ROOT_FILES={'Cargo.toml','Cargo.lock','build.rs','build_number.rs','settings.cfg','LICENSE','THIRD_PARTY_LICENSES.txt','README.md','assets/animations.cfg','assets/README.md'}

def selected(path):
    return path in ROOT_FILES or path.startswith(SOURCE_PREFIXES+ASSET_PREFIXES) or (path.startswith('tools/') and not path.startswith('tools/onehand_windows/')) or path.startswith('docs/')

def logical(name):
    need(type(name) is str and name and '\\' not in name and '\0' not in name,'invalid logical name')
    parts=name.split('/');need(not name.startswith('/') and all(p not in ('','.','..') and ':' not in p and p==p.rstrip(' .') and not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',p) for p in parts),'unsafe Windows logical name')
    return Path(*parts)

def git_run(git,repository,*args,limit=16*1024**2):
    result=subprocess.run([str(git),'-C',str(repository),*args],capture_output=True,check=True,timeout=120)
    need(len(result.stdout)<=limit and len(result.stderr)<=1024**2,'bounded Git result required')
    return result.stdout

def tree(git,repository,revision):
    need(re.fullmatch('[0-9a-f]{40}',revision) is not None,'immutable Git commit required')
    need(git_run(git,repository,'cat-file','-t',revision).strip()==b'commit','real Git commit required')
    entries={}
    for raw in git_run(git,repository,'ls-tree','-r','-z','--full-tree',revision).split(b'\0'):
        if not raw:continue
        head,name=raw.split(b'\t',1);mode,kind,oid=head.decode().split();name=name.decode('utf-8');logical(name)
        if selected(name):
            need(mode in ('100644','100755') and kind=='blob','source symlink/submodule forbidden')
            need(name.casefold() not in {x.casefold() for x in entries},'Windows source aliases')
            entries[name]=oid
    need(entries and ROOT_FILES<=set(entries),'complete root source files required')
    return entries

def blob(git,repository,revision,path,size):
    need(type(size) is int and 0<=size<=128*1024**2,'source file bound')
    need(git_run(git,repository,'cat-file','-s',revision+':'+path).strip()==str(size).encode(),'Git blob size mismatch')
    return git_run(git,repository,'cat-file','blob',revision+':'+path,limit=size)

def validate_spec(spec,entries,revision):
    need(spec['schema']=='rust-duty-current-game-source-inputs/v1' and spec['revision']==revision,'game source specification differs')
    rows=spec['files'];need(type(rows) is list and rows,'full explicit source inventory required')
    regular={r['repository_path']:r for r in rows if r['ref']==revision}
    need(set(regular)==set(entries) and len(regular)==len(entries),'partial/extra current source closure')
    seen=set();total=0;jumps=[]
    for row in rows:
        need(set(row)=={'ref','repository_path','destination','sha256','bytes','git_blob_sha1'},'source row fields differ')
        logical(row['repository_path']);logical(row['destination'])
        need(row['destination'].casefold() not in seen,'source destination alias');seen.add(row['destination'].casefold())
        need(type(row['bytes']) is int and 0<=row['bytes']<=128*1024**2,'source byte count invalid');total+=row['bytes']
        need(re.fullmatch('[0-9a-f]{64}',row['sha256']) and re.fullmatch('[0-9a-f]{40}',row['git_blob_sha1']),'source digest invalid')
        if row['ref']==revision:
            need(row['destination']==row['repository_path'] and row['git_blob_sha1']==entries[row['repository_path']],'current source identity changed')
        else:
            need(row['ref']==JUMP_REF and row['repository_path']==JUMP_PATH and row['destination']=='.jump-source/'+JUMP_PATH,'only established immutable Jump input permitted')
            jumps.append(row)
    need(len(jumps)==1 and total<=MAX_SOURCE_BYTES,'one Jump source and bounded closure required')
    return rows

def current_closure(git,repository,revision,event_commit):
    admitted=tree(git,repository,revision)
    need(tree(git,repository,event_commit)==admitted,'event head game source/input closure differs from admitted commit')
    return admitted

def materialize(spec,git,repository,revision,output,jump_repository=None):
    rows=validate_spec(spec,tree(git,repository,revision),revision);output=Path(output)
    need(output.is_absolute() and not output.exists(),'fresh source output required')
    need(shutil.disk_usage(output.parent).free>=1024**3+sum(r['bytes'] for r in rows),'source reserve plus 1GiB floor required')
    output.mkdir()
    for row in rows:
        raw=blob(git,jump_repository if row['ref']==JUMP_REF and jump_repository else repository,row['ref'],row['repository_path'],row['bytes'])
        need(sha_bytes(raw)==row['sha256'] and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==row['git_blob_sha1'],'actual Git bytes differ')
        dest=output/logical(row['destination']);dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as f:f.write(raw)
    return {'schema':'rust-duty-current-game-source-export/v1','source_revision':revision,'files':rows,'exact_git_blob_export':True,'filter_or_checkout_bytes_used':False}
