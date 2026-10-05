"""Correct only this new Action's stale preview-status text; retain the prior bytes."""
import bpy,hashlib,json,shutil,sys
from pathlib import Path
P=Path(__file__).resolve().parent;source=Path(bpy.data.filepath)
expected='18d7d0a6a1dfcf25b6e07db28434d35aeeafcf47f8ae5603ca6bfa6b357647cb'
assert hashlib.sha256(source.read_bytes()).hexdigest()==expected
sys.dont_write_bytecode=True;sys.path.insert(0,str(P.parent.parent/'locomotion_directional'/'r5'))
from source_integrity import snapshot
from validate_directional_source import extra_snapshot
before=snapshot(bpy);struct=extra_snapshot()
backup=P/'pre_metadata_bytes';backup.mkdir(exist_ok=True);shutil.copyfile(source,backup/source.name)
bpy.data.actions['aella_vault_low_r3']['render_status']='not attempted; genuine Eevee viewport witness pending'
after=snapshot(bpy);newstruct=extra_snapshot()
assert before==after
for k in ['meshes','armatures','objects_and_bindings','materials','cameras','actions_extended','pose_channel_defaults']:assert struct[k]==newstruct[k],k
bpy.ops.wm.save_as_mainfile(filepath=str(source),compress=True)
sha=hashlib.sha256(source.read_bytes()).hexdigest();report=json.loads((P/'candidate/authoring_report.json').read_text());report['source_sha256']=sha;report['metadata_only_update']={'previous_sha256':expected,'field':'aella_vault_low_r3.render_status','all_action_curves_and_source_structure_unchanged':True};(P/'candidate/authoring_report.json').write_text(json.dumps(report,indent=2)+'\n');print('LABEL_ONLY',sha)
