"""Read-only local source freeze verification; never admits a native candidate."""
from pathlib import Path
import json
from candidate_context import exact_keys, file_sha, require, sha, strict_json


def verify():
    root = Path(__file__).absolute().parent
    allow = strict_json(root / 'ALLOWLIST.json')
    exact_keys(allow, ('schema', 'files', 'publication_authorized'), 'allowlist')
    require(allow['schema'] == 'rust-duty-source-only-allowlist/v1' and allow['publication_authorized'] is False,
            'source-only allowlist required')
    names = allow['files']
    require(type(names) is list and len(set(names)) == len(names) and all(type(n) is str and Path(n).name == n for n in names),
            'unsafe or duplicate allowlist')
    pins = strict_json(root / 'PINS.json')
    require(set(pins) == set(names) - {'PINS.json'}, 'exact allowlist/pin coverage required')
    for name, expected in pins.items():
        require(file_sha(root / name) == sha(expected), 'frozen file changed: ' + name)
    return {'source_freeze_verified': True, 'allowlisted_files': len(names), 'pins_sha256': file_sha(root / 'PINS.json'),
            'windows_execution_proved': False, 'publication_performed': False}


if __name__ == '__main__': print(json.dumps(verify(), indent=2, sort_keys=True))
