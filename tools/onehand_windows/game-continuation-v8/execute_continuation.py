#!/usr/bin/env python3
"""Isolated bootstrap: verify all frozen bytes before importing local code."""
import argparse,hashlib,json,stat,sys
from pathlib import Path
sys.dont_write_bytecode=True
p=argparse.ArgumentParser(add_help=False);p.add_argument('--package-pins-sha256',required=True);a,rest=p.parse_known_args()
root=Path(__file__).absolute().parent
for q in (*reversed(root.parents),root,root/'PINS.json'):
 s=q.lstat()
 if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:raise SystemExit('redirected package path')
raw=(root/'PINS.json').read_bytes()
if hashlib.sha256(raw).hexdigest()!=a.package_pins_sha256:raise SystemExit('continuation source freeze differs')
def pairs(items):
 out={}
 for k,v in items:
  if k in out:raise ValueError('duplicate package pin')
  out[k]=v
 return out
pins=json.loads(raw,object_pairs_hook=pairs)
if not isinstance(pins,dict) or not pins:raise SystemExit('empty package')
actual=set()
for q in root.rglob('*'):
 s=q.lstat()
 if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:raise SystemExit('redirected package member')
 if q.is_file():actual.add(q.relative_to(root).as_posix())
if actual!=set(pins)|{'PINS.json'}:raise SystemExit('unexpected package file/cache')
for name,expected in pins.items():
 if not isinstance(name,str) or '\\' in name or Path(name).is_absolute() or any(x in ('','.','..') for x in name.split('/')):raise SystemExit('unsafe package member')
 if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:raise SystemExit('continuation file differs')
sys.path.insert(0,str(root))
if rest==['--source-tests']:
 import unittest
 suite=unittest.defaultTestLoader.discover(str(root),pattern='test_continuation.py')
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 raise SystemExit(0 if result.wasSuccessful() else 1)
import run_continuation
sys.argv=[sys.argv[0],'--package-pins-sha256',a.package_pins_sha256,*rest]
raise SystemExit(run_continuation.main())
