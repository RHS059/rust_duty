"""Resolve exact local source-only publication bytes, without Git/network writes."""
import argparse,hashlib,json,stat
from pathlib import Path

def inventory(root,expected):
    root=Path(root).absolute();pins_path=root/'PINS.json';raw=pins_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('independently expected source freeze differs')
    pins=json.loads(raw)
    for name,h in pins.items():
        if Path(name).name!=name or hashlib.sha256((root/name).read_bytes()).hexdigest()!=h:raise ValueError('source freeze differs')
    layout=json.loads((root/'PUBLICATION_LAYOUT.json').read_bytes());out=[]
    for item in layout['files']:
        source=root/item['source'] if item['origin']=='orchestration' else root.parent.parent/item['source']
        info=source.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('ordinary exact source file required')
        raw=source.read_bytes();actual=hashlib.sha256(raw).hexdigest()
        want=(expected if item['source']=='PINS.json' else pins[item['source']]) if item['origin']=='orchestration' else item['sha256']
        if actual!=want:raise ValueError('publication source bytes differ')
        out.append({'source_path':str(source),'repository_path':item['repository_path'],'materialized_path':item['materialized_path'],'sha256':actual,'bytes':len(raw),'kind':item['kind']})
    if len({r['repository_path'].casefold() for r in out})!=len(out):raise ValueError('duplicate publication destination')
    return {'schema':'rust-duty-onehand-source-publication-inventory/v1','orchestration_pins_sha256':expected,'source_only':True,'publication_performed':False,'private_or_held_payloads_included':False,'files':out}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--package-pins-sha256',required=True);a=p.parse_args()
    print(json.dumps(inventory(Path(__file__).parent,a.package_pins_sha256),sort_keys=True,indent=2))
