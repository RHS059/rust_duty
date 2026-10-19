#!/usr/bin/env python3
"""Exact event-commit export and fail-closed admission, before native work.

This standalone bootstrap's own SHA is pinned by the reviewed workflow. No
unverified local module is imported and no mutable branch or artifact is used.
"""
import argparse,hashlib,json,re,stat,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
PREFIX='tools/onehand_windows/game-continuation-v9/'
ADMISSION='tools/onehand_windows/game-admission-v1/'
def need(ok,message):
 if not ok:raise ValueError(message)
def valid(name):
 need(type(name) is str and name and '\\' not in name and not name.startswith('/') and all(x not in ('','.','..') and ':' not in x and x==x.rstrip(' .') for x in name.split('/')),'safe exact Git name required');return name
def raw(git,repo,ref,name,cap=16*1024**2):
 need(re.fullmatch('[0-9a-f]{40}',ref),'immutable event commit required');valid(name)
 argv=[git,'-C',repo,'cat-file']
 size=int(subprocess.check_output([*argv,'-s',ref+':'+name],timeout=60,stderr=subprocess.PIPE));need(0<=size<=cap,'Git blob bound exceeded')
 data=subprocess.check_output([*argv,'blob',ref+':'+name],timeout=60,stderr=subprocess.PIPE);need(len(data)==size,'Git blob changed');return data
def store(path,data):
 for q in (*reversed(path.parents),path):
  if q.exists() or q.is_symlink():
   st=q.lstat();need(not stat.S_ISLNK(st.st_mode) and not getattr(st,'st_file_attributes',0)&0x400,'redirected export')
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('xb') as f:f.write(data)
def main():
 p=argparse.ArgumentParser()
 for x in ('git','repository','event-commit','package-pins-sha256','output','summary'):p.add_argument('--'+x,required=True)
 p.add_argument('--github-output');a=p.parse_args();root=Path(a.output);need(root.is_absolute() and not root.exists(),'fresh absolute export required')
 pins_raw=raw(a.git,a.repository,a.event_commit,PREFIX+'PINS.json');need(hashlib.sha256(pins_raw).hexdigest()==a.package_pins_sha256,'exact package freeze differs')
 pins=json.loads(pins_raw);need(type(pins) is dict and 1<=len(pins)<=64,'bounded package required')
 package=root/'package';store(package/'PINS.json',pins_raw)
 for name,want in pins.items():
  valid(name);need('/' not in name,'flat runtime package required');data=raw(a.git,a.repository,a.event_commit,PREFIX+name)
  need(hashlib.sha256(data).hexdigest()==want,'package byte identity differs');store(package/name,data)
 sys.path.insert(0,str(package))
 import continuation_core as c,game_source,run_continuation
 c.verify_package(package,a.package_pins_sha256)
 admission_path=root/'admission/admission.json';store(admission_path,raw(a.git,a.repository,a.event_commit,ADMISSION+'admission.json'))
 value=c.read(admission_path);need(value.get('schema')=='rust-duty-onehand-game-continuation-admission/v1','admission schema')
 if value.get('enabled') is False:
  need(value.get('game_source_revision') is None and value.get('game_source_spec') is None and value.get('independent_review') is None,'inactive admission cannot claim accepted inputs')
  result={'schema':'rust-duty-onehand-game-preflight/v1','native_game_ready':False,'source_only':True,'event_commit':a.event_commit,'package_pins_sha256':a.package_pins_sha256}
 else:
  need(value.get('enabled') is True,'explicit enabled boolean required')
  for key in ('game_source_spec','independent_review'):
   item=value[key];name=valid(item['path']);data=raw(a.git,a.repository,a.event_commit,ADMISSION+name)
   need(hashlib.sha256(data).hexdigest()==item['sha256'],'admission dependency identity differs');store(admission_path.parent/name,data)
  accepted,spec=run_continuation.admit(admission_path,c.sha(admission_path),a.package_pins_sha256,value['game_source_revision'])
  entries=game_source.current_closure(a.git,a.repository,value['game_source_revision'],a.event_commit)
  game_source.validate_spec(spec,entries,value['game_source_revision'])
  bindings={'package_root':str(package),'package_pins_sha256':a.package_pins_sha256,'admission':c.record(admission_path),'game_revision':value['game_source_revision'],'event_commit':a.event_commit}
  c.write_new(root/'accepted-bindings.json',bindings)
  result={'schema':'rust-duty-onehand-game-preflight/v1','native_game_ready':True,'source_only':False,'event_commit':a.event_commit,'game_source_revision':value['game_source_revision'],'package_pins_sha256':a.package_pins_sha256,'admission_sha256':c.sha(admission_path),'game_capture_performed':False}
 c.write_new(Path(a.summary),result)
 if a.github_output:
  with Path(a.github_output).open('a',encoding='utf-8') as f:f.write('game_ready='+str(result['native_game_ready']).lower()+'\npackage_root='+str(package)+'\n')
 print(json.dumps(result,sort_keys=True))
if __name__=='__main__':
 try:main()
 except Exception as error:
  summary={'schema':'rust-duty-onehand-game-preflight/v1','native_game_ready':False,'passed':False,'error_type':type(error).__name__,'error_sha256':hashlib.sha256(str(error).encode()).hexdigest(),'game_capture_performed':False}
  print(json.dumps(summary,sort_keys=True))
  if '--summary' in sys.argv:
   path=Path(sys.argv[sys.argv.index('--summary')+1])
   if path.is_absolute() and not path.exists():store(path,(json.dumps(summary,sort_keys=True,separators=(',',':'))+'\n').encode())
  raise SystemExit(1)
