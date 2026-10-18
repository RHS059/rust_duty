"""Read-only Git inspection emits a reviewable source spec; never approves it."""
import argparse,hashlib,json
from pathlib import Path
import game_source as s
from continuation_core import write_new,sha_bytes,need
from game_plan import JUMP_REF,JUMP_PATH

def main():
 p=argparse.ArgumentParser();p.add_argument('--git',required=True);p.add_argument('--repository',required=True);p.add_argument('--revision',required=True);p.add_argument('--output',required=True);p.add_argument('--jump-repository');a=p.parse_args()
 rows=[]
 for ref,path,dest,oid in [(a.revision,n,n,oid) for n,oid in s.tree(a.git,a.repository,a.revision).items()]+[(JUMP_REF,JUMP_PATH,'.jump-source/'+JUMP_PATH,None)]:
  repo=a.jump_repository if ref==JUMP_REF and a.jump_repository else a.repository
  size=int(s.git_run(a.git,repo,'cat-file','-s',ref+':'+path).strip());raw=s.blob(a.git,repo,ref,path,size)
  actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest();need(oid is None or oid==actual,'Git object identity mismatch')
  rows.append({'ref':ref,'repository_path':path,'destination':dest,'bytes':size,'sha256':sha_bytes(raw),'git_blob_sha1':actual})
 spec={'schema':'rust-duty-current-game-source-inputs/v1','revision':a.revision,'files':rows}
 s.validate_spec(spec,s.tree(a.git,a.repository,a.revision),a.revision);write_new(Path(a.output).absolute(),spec)
 print(json.dumps({'source_spec_prepared':True,'independently_accepted':False,'files':len(rows)}))
if __name__=='__main__':main()
