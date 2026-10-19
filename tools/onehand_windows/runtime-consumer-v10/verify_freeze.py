#!/usr/bin/env python3
"""Read-only exact allowlist/byte verification."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main():
    allow=json.loads((HERE/'ALLOWLIST.json').read_text());pins=json.loads((HERE/'PINS.json').read_text())
    actual={f.name for f in HERE.iterdir() if f.is_file()}
    if actual!=set(allow['files']):raise ValueError('unexpected/missing package file')
    if set(pins)!=set(allow['files'])-{'PINS.json'}:raise ValueError('allowlist/pins differ')
    for name,want in pins.items():
        if Path(name).name!=name or hashlib.sha256((HERE/name).read_bytes()).hexdigest()!=want:raise ValueError('frozen source differs: '+name)
    print(json.dumps({'verified':True,'files':len(pins),'pins_sha256':hashlib.sha256((HERE/'PINS.json').read_bytes()).hexdigest()}))
if __name__=='__main__':main()
