import bpy,sys,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));from source_integrity import snapshot
from validate_directional_source import extra_snapshot
args=sys.argv[sys.argv.index('--')+1:];baseline=Path(args[0]);out=Path(args[1]);candidate=Path(bpy.data.filepath);chash=hashlib.sha256(candidate.read_bytes()).hexdigest();after=snapshot(bpy);after_extra=extra_snapshot()
bpy.ops.wm.open_mainfile(filepath=str(baseline),load_ui=False,use_scripts=False);before=snapshot(bpy);before_extra=extra_snapshot()
assert len(before['actions'])==82;new=set(after['actions'])-set(before['actions']);assert len(new)==4 and all(n.endswith('_colab_visual_v1') for n in new)
assert {n:after['actions'][n] for n in before['actions']}==before['actions']
for k in ['nla','drivers','packed_images']:assert after[k]==before[k],k
for k in ['meshes','armatures','objects_and_bindings','materials','cameras','pose_channel_defaults']:assert after_extra[k]==before_extra[k],k
for k in ['actions_metadata','actions_extended']:assert {n:after_extra[k][n] for n in before_extra[k]}==before_extra[k],k
out.write_text(json.dumps({'reopened_candidate_sha256':chash,'original82actions_unchanged':True,'new_actions':sorted(new),'protected_scene_data_unchanged':True,'blender_runtime':bpy.app.version_string,'source_authoring_version':'4.3.2','passed':True},indent=2)+'\n');print(out.read_text())
