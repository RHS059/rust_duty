#!/usr/bin/env python3
"""Standalone exact-event export for source-only inventory; no admission reader."""
import argparse,hashlib,json,re,stat,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
PREFIX='tools/onehand_windows/game-continuation-v2/'

def need(ok,message):
 if not ok:raise ValueError(message)
def ordinary(path):
 p=Path(path);need(p.is_absolute() and '..' not in p.parts,'absolute ordinary path required')
 for q in (*reversed(p.parents),p):
  if q.exists() or q.is_symlink():
   st=q.lstat();need(not stat.S_ISLNK(st.st_mode) and not getattr(st,'st_file_attributes',0)&0x400,'redirected source-only export')
 return p
def pairs(items):
 out={}
 for key,value in items:need(key not in out,'duplicate source pin');out[key]=value
 return out
def git_raw(git,repository,*args):return subprocess.check_output([str(git),'-C',str(repository),*args],stderr=subprocess.PIPE,timeout=60)
def blob(git,repository,revision,name):
 need(re.fullmatch(r'[A-Za-z0-9_]+\.(py|json)',name),'flat source filename required')
 obj=revision+':'+PREFIX+name
 size=int(git_raw(git,repository,'cat-file','-s',obj));need(0<size<=1024**2,'bounded source-only blob required')
 data=git_raw(git,repository,'cat-file','blob',obj);need(len(data)==size,'source blob changed');return data

def export(args):
 need(re.fullmatch('[0-9a-f]{40}',args.event_commit) and re.fullmatch('[0-9a-f]{64}',args.package_pins_sha256),'immutable source/package identities required')
 git=ordinary(args.git);repository=ordinary(args.repository);need(git.is_file() and repository.is_dir(),'existing Git and source repository required')
 need(git_raw(git,repository,'rev-parse','HEAD').decode().strip()==args.event_commit,'event checkout identity differs')
 need(git_raw(git,repository,'cat-file','-t',args.event_commit).strip()==b'commit','actual source commit required')
 root=ordinary(args.output);need(not root.exists(),'fresh source-only export required')
 raw=blob(git,repository,args.event_commit,'PINS.json');need(hashlib.sha256(raw).hexdigest()==args.package_pins_sha256,'exact source-only package freeze differs')
 pins=json.loads(raw,object_pairs_hook=pairs);need(type(pins) is dict and 1<=len(pins)<=64,'bounded original-source package required')
 need('export_source_inventory.py' in pins and 'execute_continuation.py' in pins and 'measure_source_spec.py' in pins,'complete source inventory bootstrap required')
 # Check the external initial bootstrap itself before exporting/importing modules.
 own=ordinary(Path(__file__).absolute());need(hashlib.sha256(own.read_bytes()).hexdigest()==pins['export_source_inventory.py'],'initial bootstrap bytes differ')
 payload={}
 for name,want in pins.items():
  need(type(want) is str and re.fullmatch('[0-9a-f]{64}',want),'exact source pin required')
  data=blob(git,repository,args.event_commit,name);need(hashlib.sha256(data).hexdigest()==want,'source-only package member differs');payload[name]=data
 need(git_raw(git,repository,'rev-parse','HEAD').decode().strip()==args.event_commit,'event checkout changed')
 root.mkdir(parents=True)
 for name,data in {'PINS.json':raw,**payload}.items():
  with ordinary(root/name).open('xb') as stream:stream.write(data)
 print(json.dumps({'source_inventory_package_exported':True,'source_only':True,'event_commit':args.event_commit,'package_pins_sha256':args.package_pins_sha256,'files':len(payload),'native_admission_enabled_by_measurement':False},sort_keys=True))
 return 0
class Parser(argparse.ArgumentParser):
 def error(self,message):raise ValueError('invalid source-only export arguments')
def main(argv):
 p=Parser()
 for name in ('git','repository','event-commit','package-pins-sha256','output'):p.add_argument('--'+name,required=True)
 return export(p.parse_args(argv))
if __name__=='__main__':
 try:raise SystemExit(main(sys.argv[1:]))
 except Exception as error:
  print(json.dumps({'source_inventory_package_exported':False,'passed':False,'source_only':True,'error_type':type(error).__name__,'error_sha256':hashlib.sha256(str(error).encode()).hexdigest(),'native_admission_enabled_by_measurement':False},sort_keys=True));raise SystemExit(1)
