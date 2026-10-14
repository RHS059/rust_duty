"""Fetch the immutable approved r8 Jump pack required by current validators."""
import json
import os
from pathlib import Path
from fetch_source_bound_companions import api_json, check_artifact, download

root = Path(__file__).resolve().parents[1]
record = json.loads((root / 'tools/lighting_jump_pack.json').read_text())
folder = root / 'evidence/original-inputs'
token = os.environ['GITHUB_TOKEN']
api = '/repos/RHS059/rust_duty/actions/artifacts/' + str(record['artifact_id'])
metadata = api_json(api, token)
check_artifact(metadata, record, record)
download(api + '/zip', token, folder / 'lighting-jump-r8.zip', record['size_bytes'], record['zip_sha256'])
(folder / 'lighting-jump-r8-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
