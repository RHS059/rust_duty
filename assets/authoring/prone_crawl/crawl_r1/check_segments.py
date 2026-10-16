import bpy,json,math
from pathlib import Path
from mathutils import Vector
P=Path(__file__).resolve().parent;d=json.loads((P/'crawl_design.json').read_text());s=bpy.context.scene;r=bpy.data.objects['Arms'];w=bpy.data.objects['hk416_weapon'];data={}
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
r.animation_data.use_nla=False;r.animation_data.action=bpy.data.actions[d['guarded_initialization']];s.frame_set(1);bpy.context.view_layer.update();r.animation_data.action=bpy.data.actions[d['baseline_action']];s.frame_set(1);bpy.context.view_layer.update()
def grip(b):return w.matrix_world.inverted()@r.matrix_world@r.pose.bones[b].matrix.translation
base={b:grip(b).copy() for b in ['hand_l','hand_r']}
for name,e in d['actions'].items():
 r.animation_data.action=bpy.data.actions[name];errors={b:[] for b in base};finite=True
 for n in range(1,e['frame_range'][1]+1):
  s.frame_set(n);bpy.context.view_layer.update()
  finite &= all(math.isfinite(x) for bone in r.pose.bones for row in bone.matrix for x in row)
  for b in base:errors[b].append((grip(b)-base[b]).length)
 data[name]={'frame_count':e['frame_range'][1],'range':list(r.animation_data.action.frame_range),'loop':False,'all_evaluated_bone_matrices_finite':finite,'max_grip_origin_drift_weapon_local_m':{b:max(v) for b,v in errors.items()},'first_last_poses_forced_equal':False}
passed=all(v['all_evaluated_bone_matrices_finite'] and max(v['max_grip_origin_drift_weapon_local_m'].values()) < .0001 for v in data.values())
(P/'segment_technical_checks.json').write_text(json.dumps({'checks':data,'grip_drift_threshold_m':.0001,'passed':passed,'meaning':'Finite matrices and bone-origin attachment diagnostics only. Not a render, visual deformation/grip assessment, or artistic score. Source never saved.','source_saved':False},indent=2)+'\n');print(json.dumps(data,indent=2))

assert passed, "Finite pose or grip attachment threshold failed"
