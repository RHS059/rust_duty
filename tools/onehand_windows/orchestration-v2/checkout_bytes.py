#!/usr/bin/env python3
"""Fresh explicit Git-blob materialization: no checkout filters/CRLF conversion.

The controller receives a reviewed manifest from the exact Git commit before any
proof-package import. Only allowlisted original source and named existing public
baseline/canonical data may materialize. No network or Git writes occur here.
"""
from __future__ import annotations
import argparse,hashlib,json,re,shutil,stat,subprocess
from pathlib import Path

def require(v,m):
    if not v:raise ValueError(m)

def relative(value):
    require(type(value) is str and value and '\\' not in value and '\0' not in value,'invalid logical path')
    p=Path(value);require(not p.is_absolute() and all(x not in ('','.','..') and ':' not in x and x==x.rstrip(' .') and not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',x) for x in value.split('/')),'unsafe logical path');return p

def validate_manifest(value):
    require(type(value) is dict and set(value)=={'schema','files'},'materialization fields')
    require(value['schema']=='rust-duty-onehand-byte-materialization/v1' and type(value['files']) is list and value['files'],'materialization schema/files')
    seen=set()
    for row in value['files']:
        require(type(row) is dict and set(row)=={'ref','repository_path','destination','sha256','bytes','kind'},'materialization record')
        require(type(row['ref']) is str and re.fullmatch('[0-9a-f]{40}',row['ref']),'immutable full Git commit required')
        relative(row['repository_path']);destination=relative(row['destination']);require(str(destination).casefold() not in seen,'duplicate materialized destination');seen.add(str(destination).casefold())
        require(type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}',row['sha256']),'expected source bytes missing')
        require(type(row['bytes']) is int and 0<=row['bytes']<=128*1024**2,'bounded file size')
        require(row['kind'] in ('original-source','hash-only-reference','original-action-delta','existing-public-baseline','existing-public-canonical'),'unreviewed input kind')
        if row['kind']=='existing-public-baseline':require(row['ref']=='1daee9ff0d250b6ad926dedaab4977663f560406' and row['repository_path']=='assets/authoring/mantle/r3/candidate/aella_mantle_r3.blend' and row['sha256']=='6b95bdcdfa78e8127ef4b4fa5ac88e4cf9a0654bd0a1271c9916b903f6ee4e79','only exact existing public baseline permitted')
        elif row['kind']=='existing-public-canonical':require(row['repository_path']=='assets/locomotion/asset.vra' and row['sha256']=='d02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab','only exact existing public canonical permitted')
        elif row['kind']=='original-action-delta':require(row['sha256']=='7be513e2c9fa5d0ff1c00684c542a73354d49fd561fd406a08dad8e05c219a9d','original delta differs')
        else:require(destination.suffix.lower() not in ('.blend','.fbx','.vra','.vrs','.vrm','.glb','.npz','.bin','.png','.mp4'),'raw/private media excluded from source materialization')
    return value

def materialize(value,root,read_blob):
    validate_manifest(value);root=Path(root);require(root.is_absolute() and not root.exists() and '..' not in root.parts,'fresh absolute destination required')
    for part in (*reversed(root.parents),root):
        if part.exists() or part.is_symlink():
            info=part.lstat();require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,'redirected materialization root')
    root.mkdir(parents=True)
    records=[]
    for row in value['files']:
        require(shutil.disk_usage(root).free>=1024**3+row['bytes'],'1 GiB floor plus exact source file required')
        raw=read_blob(row['ref'],row['repository_path'],row['bytes']);require(type(raw) is bytes and len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'],'exact Git source bytes differ')
        target=root/relative(row['destination']);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as f:f.write(raw)
        require(hashlib.sha256(target.read_bytes()).hexdigest()==row['sha256'],'written source differs');records.append(row)
    return {'schema':'rust-duty-onehand-byte-checkout/v1','files':records,'byte_preserving_git_blobs':True,'checkout_filters_used':False}

def git_blob_reader(git,repository):
    verified=set()
    def read(ref,path,expected_size):
        require(type(ref) is str and re.fullmatch('[0-9a-f]{40}',ref),'immutable full Git commit required')
        if ref not in verified:
            kind=subprocess.run([git,'-C',str(repository),'cat-file','-t',ref],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=True)
            require(kind.stdout.strip()==b'commit','actual Git commit object required; tree/blob/tag rejected');verified.add(ref)
        size=subprocess.run([git,'-C',str(repository),'cat-file','-s',ref+':'+path],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=True)
        require(size.stdout.strip()==str(expected_size).encode(),'Git blob size differs before materialization')
        value=subprocess.run([git,'-C',str(repository),'cat-file','blob',ref+':'+path],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=True);return value.stdout
    return read

def main():
    p=argparse.ArgumentParser();p.add_argument('--git',required=True);p.add_argument('--repository',required=True);p.add_argument('--manifest',required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--output',required=True);p.add_argument('--receipt',required=True);a=p.parse_args()
    raw=Path(a.manifest).read_bytes();require(hashlib.sha256(raw).hexdigest()==a.manifest_sha256,'reviewed materialization manifest differs')
    result=materialize(json.loads(raw),Path(a.output),git_blob_reader(a.git,a.repository))
    with Path(a.receipt).open('xb') as f:f.write((json.dumps(result,sort_keys=True,separators=(',',':'))+'\n').encode())
if __name__=='__main__':main()
