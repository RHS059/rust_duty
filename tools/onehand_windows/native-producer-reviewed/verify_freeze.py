"""Read-only source freeze verification, no native admission or execution."""
import json
from pathlib import Path
from pinned_code import HERE,file_sha,require

def verify():
    pins=json.loads((HERE/'PINS.json').read_text());allow=json.loads((HERE/'ALLOWLIST.json').read_text())
    require(allow['publication_authorized'] is False and set(pins)==set(allow['files'])-{'PINS.json'},'source-only allowlist mismatch')
    for name,expected in pins.items():require(Path(name).name==name and file_sha(HERE/name)==expected,'source freeze differs: '+name)
    return {'source_freeze_verified':True,'pins_sha256':file_sha(HERE/'PINS.json'),'allowlisted_files':len(allow['files']),'windows_execution_proved':False,'publication_performed':False}
if __name__=='__main__':print(json.dumps(verify(),indent=2))
