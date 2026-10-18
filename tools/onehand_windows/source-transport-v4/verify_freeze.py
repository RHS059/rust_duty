import hashlib,json,stat
from pathlib import Path
HERE=Path(__file__).absolute().parent

def verify():
    pins=json.loads((HERE/'PINS.json').read_bytes());allow=json.loads((HERE/'ALLOWLIST.json').read_bytes())
    actual={p.relative_to(HERE).as_posix() for p in HERE.rglob('*') if p.is_file()}
    assert actual==set(allow['files']) and set(pins)==actual-{'PINS.json'}
    for name,sha in pins.items():
        p=HERE/name;assert '..' not in Path(name).parts and not Path(name).is_absolute()
        assert stat.S_ISREG(p.lstat().st_mode) and not p.is_symlink()
        assert hashlib.sha256(p.read_bytes()).hexdigest()==sha,name
    return {'verified':True,'files':len(actual),'pins_sha256':hashlib.sha256((HERE/'PINS.json').read_bytes()).hexdigest()}
if __name__=='__main__':print(json.dumps(verify(),sort_keys=True))
