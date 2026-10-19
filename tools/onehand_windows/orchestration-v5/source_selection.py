"""Exact immutable repository input selection, never Windows compiler evidence."""
import hashlib,json
from pathlib import Path
REVISION='c61dbd67039a4961d0c56f0a3c7e478c431d1ced'
TOOLCHAIN='1.99.0-x86_64-pc-windows-msvc'
SELECTION_SHA='14c52fc3a46f8cca2ae17a2a4db43c4a6f4d184a560e0d5c37f22a88238f0d22'

def require(ok,message):
    if not ok:raise ValueError(message)

def selection():
    with (Path(__file__).absolute().parent/'SOURCE_CLOSURE.json').open('rb') as stream:raw=stream.read(256*1024+1)
    require(len(raw)<=256*1024 and hashlib.sha256(raw).hexdigest()==SELECTION_SHA,'exact immutable Rust source selection required')
    value=json.loads(raw);require(value['commit']==REVISION and len(value['files'])==213,'complete selected c61 compiler source closure required')
    return value

def verify(files,revision,features):
    value=selection();require(revision==REVISION,'actual selected immutable Rust commit required')
    require(features==value['features']==[],'unchanged reviewed default-feature sampler build required')
    require(files=={r['path']:r['sha256'] for r in value['files']},'complete selected Rust source inventory differs')

def verify_compiler(version):
    require(type(version) is str and '\nrelease: 1.99.0\n' in version and '\nhost: x86_64-pc-windows-msvc\n' in version,'actual exact Rust 1.99.0 Windows compiler provenance required')
