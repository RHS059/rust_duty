"""Restore only production source inputs; no historical proof admission is read."""
from __future__ import annotations
import argparse, hashlib, subprocess, zlib
from pathlib import Path
from common import *

def decode_row(row,reader):
    size=row['canonical']['bytes'];need(type(size) is int and 0<=size<=128*1024**2,'input size limit')
    def blob(item):
        need(__import__('re').fullmatch('[0-9a-f]{40}',item['ref']),'immutable source commit required')
        logical(item['repository_path']);raw=reader(item)
        need(len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256'],'Git input identity differs')
        if item.get('blob_sha1'):need(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==item['blob_sha1'],'Git blob identity differs')
        return raw
    if row['encoding']=='identity':raw=blob(row['git'])
    else:
        need(row['encoding']=='gzip-single-member','unsupported input encoding')
        packed=b''.join(blob(p) for p in row['git']['parts'])
        need(len(packed)==row['transport']['bytes'] and hashlib.sha256(packed).hexdigest()==row['transport']['sha256'],'encoded input identity differs')
        decoder=zlib.decompressobj(31);raw=decoder.decompress(packed,size+1)
        need(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,'invalid or oversized compressed input')
    need(len(raw)==size and hashlib.sha256(raw).hexdigest()==row['canonical']['sha256'],'decoded source identity differs')
    return raw

def materialize(manifest,root,reader):
    need(manifest['schema']=='rust-duty-direct-source-inputs/v1','source input format')
    root=ordinary(root);need(not root.exists(),'fresh source workspace required');root.mkdir(parents=True)
    names=set();files={}
    for row in manifest['files']:
        relative=logical(row['destination']);need(str(relative).casefold() not in names,'duplicate source destination');names.add(str(relative).casefold())
        capacity(root,row['canonical']['bytes']*2);raw=decode_row(row,reader);path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as f:f.write(raw)
        files[relative.as_posix()]=sha(path)
    write(root/'SOURCE_INPUTS.json',{'source_commit':manifest['source_commit'],'files':files})
    return root

def main():
    p=argparse.ArgumentParser();p.add_argument('--repository',type=Path,required=True);p.add_argument('--git',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    def reader(item):
        return subprocess.run([a.git,'-C',str(a.repository),'cat-file','blob',item['ref']+':'+item['repository_path']],check=True,capture_output=True,timeout=90).stdout
    materialize(read(Path(__file__).with_name('source-inputs.json')),a.output,reader)
if __name__=='__main__':main()
