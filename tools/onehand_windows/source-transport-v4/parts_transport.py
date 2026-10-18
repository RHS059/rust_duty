"""Ordered <=64 KiB Git parts; reconstruct the exact existing gzip stream only."""
import hashlib,re,shutil,stat
from pathlib import Path
PART_SIZE=65536
DISK_FLOOR=1288490189
PREFIX='tools/onehand_windows/source-transport-v4/'
CATALOG_PATH=PREFIX+'TRANSPORT_PARTS.json'
SCHEMA='rust-duty-onehand-encoded-gzip-parts/v1'

def require(ok,message):
    if not ok:raise ValueError(message)

def validate_catalog(value,transport_rows,manifest_sha):
    require(type(value) is dict and set(value)=={'schema','transport_manifest_sha256','part_size','files'},'parts catalog fields')
    require(value['schema']==SCHEMA and value['transport_manifest_sha256']==manifest_sha and type(value['part_size']) is int and value['part_size']==PART_SIZE,'parts catalog identity')
    require(type(value['files']) is list and len(value['files'])==len(transport_rows)==38,'complete fixed38 parts catalog')
    for row,expected in zip(value['files'],transport_rows):
        require(type(row) is dict and set(row)=={'name','kind','canonical','reconstructed','parts'},'parts row fields')
        require(all(row[k]==expected[k] for k in ('name','kind','canonical')) and row['reconstructed']==expected['transport'],'unchanged canonical and gzip identities required')
        parts=row['parts'];size=row['reconstructed']['bytes'];count=(size+PART_SIZE-1)//PART_SIZE
        require(type(parts) is list and len(parts)==count and count>0,'exact ordered part count')
        for i,part in enumerate(parts):
            require(type(part) is dict and set(part)=={'path','bytes','sha256','blob_sha1'},'part identity fields')
            require(part['path']=='parts/'+row['name']+f'/{i:03d}.gzpart','ordered deterministic part path')
            require(type(part['bytes']) is int and part['bytes']==min(PART_SIZE,size-i*PART_SIZE),'exact bounded part length')
            require(type(part['sha256']) is str and re.fullmatch('[0-9a-f]{64}',part['sha256']),'part SHA256')
            require(type(part['blob_sha1']) is str and re.fullmatch('[0-9a-f]{40}',part['blob_sha1']),'part Git blob SHA1')
    return value['files']

def validate_git_parts(parts,expected):
    require(type(parts) is list and len(parts)==len(expected['parts']),'complete ordered Git parts required')
    refs=set()
    for supplied,pinned in zip(parts,expected['parts']):
        require(type(supplied) is dict and set(supplied)=={'ref','repository_path','sha256','bytes','blob_sha1'},'Git part fields')
        require(type(supplied['ref']) is str and re.fullmatch('[0-9a-f]{40}',supplied['ref']),'actual immutable part commit required')
        refs.add(supplied['ref'])
        require(supplied['repository_path']==PREFIX+pinned['path'] and all(supplied[k]==pinned[k] for k in ('sha256','bytes','blob_sha1')),'exact ordered Git part identity differs')
    require(len(refs)==1,'one immutable publication commit per encoded input required')

def reconstruct(parts,expected,target,read_blob):
    validate_git_parts(parts,expected);target=Path(target)
    require(target.is_absolute() and not target.exists() and '..' not in target.parts,'fresh absolute reconstructed path required')
    for path in (*reversed(target.parents),target):
        if path.exists() or path.is_symlink():
            info=path.lstat();require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,'redirected reconstructed path')
    parent=target.parent
    while not parent.exists():parent=parent.parent
    require(shutil.disk_usage(parent).free>=DISK_FLOOR+expected['reconstructed']['bytes'],'encoded reconstruction plus disk floor required')
    target.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256();size=0
    with target.open('xb') as output:
        for part in parts:
            raw=read_blob(part['ref'],part['repository_path'],part['bytes'])
            require(type(raw) is bytes and len(raw)==part['bytes']<=PART_SIZE,'bounded exact Git part bytes required')
            require(hashlib.sha256(raw).hexdigest()==part['sha256'] and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==part['blob_sha1'],'Git part hash differs')
            # Hash, count and write the identical returned bounded byte string.
            h.update(raw);size+=len(raw);require(size<=expected['reconstructed']['bytes'],'encoded reconstruction overflow');output.write(raw)
    result={'sha256':h.hexdigest(),'bytes':size}
    require(result=={k:expected['reconstructed'][k] for k in ('sha256','bytes')},'reconstructed gzip hash/size differs')
    return result
