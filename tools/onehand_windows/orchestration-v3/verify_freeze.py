"""Read-only exact package byte verifier; never imports runtime/native code."""
import hashlib,json,stat
from pathlib import Path

def verify(root=None):
    root=Path(root) if root else Path(__file__).absolute().parent
    pins=json.loads((root/'PINS.json').read_bytes());allow=json.loads((root/'ALLOWLIST.json').read_bytes())
    if set(pins)!=set(allow['files'])-{'PINS.json'}:raise ValueError('manifest coverage differs')
    if set(p.name for p in root.iterdir())!=set(allow['files']):raise ValueError('unexpected source/cache file')
    for name,h in pins.items():
        p=root/name;info=p.lstat()
        if Path(name).name!=name or not stat.S_ISREG(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400 or hashlib.sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('source bytes differ: '+name)
    return {'files':len(pins)+1,'pins_sha256':hashlib.sha256((root/'PINS.json').read_bytes()).hexdigest(),'verified':True}
if __name__=='__main__':print(json.dumps(verify(),sort_keys=True))
