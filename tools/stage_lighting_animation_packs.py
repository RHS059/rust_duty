"""Stage immutable existing animation packs, then run today's asset validators.

Lighting does not change animation authoring. Original pack generation/parity is
reused; this script does not claim fresh generation or source-oracle acceptance.
The download tool authenticates origin metadata and locks archive digests.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys
from revalidate_reused_companions import extract_archive, validate_lock, validate_metadata

root=Path(__file__).resolve().parents[1]
inputs=root/'evidence/original-inputs'
lock=json.loads((root/'tools/source_bound_companion_reuse_lock.json').read_text())
origin=json.loads((inputs/'origin.json').read_text())
validate_lock(lock)
validate_metadata(origin,lock)
from fetch_source_bound_companions import check_artifact
jump_record=json.loads((root/'tools/lighting_jump_pack.json').read_text())
jump_metadata=json.loads((inputs/'lighting-jump-r8-metadata.json').read_text())
check_artifact(jump_metadata,jump_record,jump_record)
for record in lock['artifacts']:
    kind=record['kind']
    destination=root/'assets'/kind
    guide=destination/'README.md'
    guide_bytes=guide.read_bytes() if guide.exists() else None
    staging=root/'evidence'/('lighting-pack-'+kind)
    archive=inputs/(str(record['artifact_id'])+'.zip')
    if kind == 'jump':
        record=jump_record
        archive=inputs/'lighting-jump-r8.zip'
    extract_archive(archive,record,staging,lock['limits'])
    if destination.exists():shutil.rmtree(destination)
    shutil.move(staging,destination)
    if guide_bytes and not guide.exists():guide.write_bytes(guide_bytes)
source=root/'assets/authoring/jump/halcyon_jump.blend'
source.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(inputs/'halcyon_jump.blend',source)
for kind in ('reload','walk','ads','directional','jump'):
    subprocess.run([sys.executable,'tools/check_generated_assets.py','--kind',kind,'--root',str(root),'--directory','assets/'+kind],cwd=root,check=True)
(root/'evidence/LIGHTING_BUILD_ANIMATION_ORIGIN.json').write_text(json.dumps({'generation_reused':True,'fresh_animation_generation':False,'fresh_source_oracle_parity':False,'origin':origin,'jump_override':{'artifact':jump_record,'github_metadata':jump_metadata},'current_asset_validators_passed':True},indent=2)+'\n')
