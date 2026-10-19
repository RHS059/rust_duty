#!/usr/bin/env python3
"""Verify every frozen byte before source tests, inventory, or native continuation."""
import argparse,hashlib,json,stat,sys
from pathlib import Path
sys.dont_write_bytecode=True

def ordinary(path):
 p=Path(path)
 if not p.is_absolute() or '..' in p.parts:raise ValueError('absolute ordinary path required')
 for q in (*reversed(p.parents),p):
  if q.exists() or q.is_symlink():
   st=q.lstat()
   if stat.S_ISLNK(st.st_mode) or getattr(st,'st_file_attributes',0)&0x400:raise ValueError('redirected package or output path')
 return p

def failure(error,argv):
 value={'source_inventory_measured':False,'passed':False,'source_only':True,'error_type':type(error).__name__,'error_sha256':hashlib.sha256(str(error).encode()).hexdigest(),'native_admission_enabled_by_measurement':False,'game_capture_performed':False,'raw_source_uploaded':False}
 # Only the one fixed bounded JSON filename may be written on measurement failure.
 if '--measure-source' in argv and argv.count('--output-directory')==1:
  try:
   root=ordinary(argv[argv.index('--output-directory')+1]);out=ordinary(root/'game-source-spec-failure.json')
   if root.is_dir() and not out.exists():
    with out.open('xb') as f:f.write((json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode())
  except Exception:pass
 print(json.dumps(value,sort_keys=True));return 1

class Parser(argparse.ArgumentParser):
 def error(self,message):raise ValueError('invalid isolated bootstrap arguments')

def main(argv):
 parser=Parser(add_help=False);parser.add_argument('--package-pins-sha256',required=True);a,rest=parser.parse_known_args(argv)
 root=ordinary(Path(__file__).absolute().parent);pin_file=ordinary(root/'PINS.json');raw=pin_file.read_bytes()
 if len(raw)>1024**2 or hashlib.sha256(raw).hexdigest()!=a.package_pins_sha256:raise ValueError('continuation source freeze differs')
 def pairs(items):
  out={}
  for k,v in items:
   if k in out:raise ValueError('duplicate package pin')
   out[k]=v
  return out
 pins=json.loads(raw,object_pairs_hook=pairs)
 if not isinstance(pins,dict) or not pins:raise ValueError('empty package')
 actual=set()
 for q in root.rglob('*'):
  ordinary(q)
  if q.is_file():actual.add(q.relative_to(root).as_posix())
 if actual!=set(pins)|{'PINS.json'}:raise ValueError('unexpected package file/cache')
 for name,expected in pins.items():
  if not isinstance(name,str) or '\\' in name or Path(name).is_absolute() or any(x in ('','.','..') for x in name.split('/')):raise ValueError('unsafe package member')
  if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:raise ValueError('continuation file differs')
 sys.path.insert(0,str(root))
 if rest==['--source-tests']:
  import unittest
  suite=unittest.defaultTestLoader.discover(str(root),pattern='test_*.py')
  result=unittest.TextTestRunner(verbosity=2).run(suite)
  return 0 if result.wasSuccessful() else 1
 if rest and rest[0]=='--measure-source':
  import measure_source_spec
  measure_source_spec.main(rest[1:],root,a.package_pins_sha256);return 0
 if not rest or any(x in ('--source-tests','--measure-source') for x in rest) or '--admission' not in rest:raise ValueError('unknown or partial isolated entry mode')
 import run_continuation
 sys.argv=[sys.argv[0],'--package-pins-sha256',a.package_pins_sha256,*rest]
 return run_continuation.main()

if __name__=='__main__':
 try:raise SystemExit(main(sys.argv[1:]))
 except Exception as error:raise SystemExit(failure(error,sys.argv[1:]))
