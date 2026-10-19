#!/usr/bin/env python3
"""Byte-pinned isolated bootstrap; no package imports before exact pin checks."""
import argparse,hashlib,json,sys,stat
from pathlib import Path
sys.dont_write_bytecode=True
p=argparse.ArgumentParser(add_help=False);p.add_argument('--package-pins-sha256',required=True);a,remaining=p.parse_known_args()
root=Path(__file__).absolute().parent
for part in (*reversed(root.parents),root,root/'PINS.json'):
    info=part.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise SystemExit('redirected orchestration path')
raw=(root/'PINS.json').read_bytes()
if hashlib.sha256(raw).hexdigest()!=a.package_pins_sha256:raise SystemExit('orchestration source freeze differs')
pins=json.loads(raw)
if any(p.name not in set(pins)|{'PINS.json'} or not p.is_file() or p.is_symlink() for p in root.iterdir()):raise SystemExit('unexpected file/cache in immutable orchestration package')
for name,expected in pins.items():
    if Path(name).name!=name or hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:raise SystemExit('orchestration source file differs')
sys.path.insert(0,str(root))
import orchestrate
raise SystemExit(orchestrate.main(remaining))
