"""Fresh saved-BLEND evaluation. Does not save, export or render any scene."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion,Vector
from bpy_extras.object_utils import world_to_camera_view

P=Path(__file__).resolve().parent
sys.path.insert(0,str(P));sys.dont_write_bytecode=True
from correction_contract import evaluation_times,protected,weapon_protected,validate_report
parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--authoring-dir',type=Path,required=True)
parser.add_argument('--integrity-dir',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
sys.path.insert(0,str(args.integrity_dir))
from source_integrity import snapshot,action_fingerprint
from validate_directional_source import extra_snapshot
D=json.loads((P/'design.json').read_text())
authoring=json.loads((args.authoring_dir/'authoring_report.json').read_text())
preserved=json.loads((args.authoring_dir/'preservation_before.json').read_text())
source=Path(bpy.data.filepath);sha=hashlib.sha256(source.read_bytes()).hexdigest()
assert sha==authoring['source_sha256']
assert bpy.app.version_string=='4.3.2'
fresh=snapshot(bpy);structure=extra_snapshot()
prior_actions=all(fresh['actions'].get(n)==v for n,v in preserved['snapshot']['actions'].items())
structure_ok=all(structure[k]==preserved['structure'][k] for k in ['meshes','armatures','objects_and_bindings','materials','cameras'])
structure_ok=structure_ok and all(fresh[k]==preserved['snapshot'][k] for k in ['drivers','packed_images','nla'])
for field in ['actions_metadata','actions_extended']:
    structure_ok=structure_ok and all(structure[field].get(n)==v for n,v in preserved['structure'][field].items())
A=bpy.data.objects['Arms'];W=bpy.data.objects['hk416_weapon'];C=bpy.data.objects['RD First Person Review']
S=next(s for s in bpy.data.scenes if C.name in s.objects);bpy.context.window.scene=S
for obj in bpy.data.objects:
    if obj.animation_data:
        for track in obj.animation_data.nla_tracks:track.mute=True
A.animation_data.use_nla=False
A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered']
S.frame_set(1);bpy.context.view_layer.update()
basis={b.name:b.matrix_basis.copy() for b in A.pose.bones}
props={b.name:{k:v for k,v in b.items() if isinstance(v,(int,float,str))} for b in A.pose.bones}
guard=json.loads(A['wrist_guard_l']);base=guard['base_euler_deg'];limits=guard['absolute_limits_deg']
skin=[o for o in bpy.data.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==A for m in o.modifiers)]
receiver=Vector(authoring['landmarks']['receiver_local']);muzzle=Vector(authoring['landmarks']['muzzle_local'])

def select(name,frame):
    A.animation_data.action=None
    for b in A.pose.bones:
        b.matrix_basis=basis[b.name]
        for k,v in props[b.name].items():b[k]=v
    A.animation_data.action=bpy.data.actions[name]
    integer=math.floor(frame);S.frame_set(integer,subframe=frame-integer)
    A.update_tag();bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update()
    return dg

def difference(a,b):return max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))
def projection(point):
    p=world_to_camera_view(S,C,point)
    return [1280*p.x,720*(1-p.y),p.z]

rows=[];pose_delta=0.;weapon_delta=0.;skin_finite=True;bone_finite=True;drivers_valid=True;skin_count=0
for index,frame in enumerate(evaluation_times(switches=(44,48,58,65,85,88,89))):
    compare_pose=protected(frame);compare_weapon=weapon_protected(frame)
    if compare_pose or compare_weapon:
        select(D['prior_action'],frame)
        old_weapon=W.matrix_world.copy()
        old_pose={b.name:b.matrix.copy() for b in A.pose.bones} if compare_pose else None
    dg=select(D['action'],frame)
    if compare_weapon:weapon_delta=max(weapon_delta,difference(old_weapon,W.matrix_world))
    if compare_pose:pose_delta=max(pose_delta,max(difference(b.matrix,old_pose[b.name]) for b in A.pose.bones))
    bones=A.pose.bones;L=bones['righthand_prop_lefthand'];follow=float(L['weapon_follow'])
    hand=A.matrix_world@bones['hand_l'].matrix;target=A.matrix_world@bones['OUT_hand_target_l'].matrix
    free_angles=[base[i]+float(L[k]) for i,k in enumerate(['wrist_flex','wrist_twist','wrist_deviation'])]
    guard_delta=math.degrees(bones['MCH_hand_guarded_l'].matrix.to_quaternion().rotation_difference(bones['MCH_attach_goal_l'].matrix.to_quaternion()).angle)
    right_delta=None
    if 'MCH_hand_guarded_r' in bones and 'MCH_attach_goal_r' in bones:
        right_delta=math.degrees(bones['MCH_hand_guarded_r'].matrix.to_quaternion().rotation_difference(bones['MCH_attach_goal_r'].matrix.to_quaternion()).angle)
    row={'frame':frame,'native':7786+frame,'follow':follow,
         'hand_position':list(hand.translation),'hand_quaternion':list(hand.to_quaternion()),
         'wrist_target_mm':(hand.translation-target.translation).length*1000,
         'attached_guard_delta_deg':guard_delta if follow>.999 else None,
         'right_guard_delta_deg':right_delta,
         'free_guard_margin_deg':min(min(v-lo,hi-v) for v,(lo,hi) in zip(free_angles,limits)) if follow<.001 else None,
         'receiver_px':projection(W.matrix_world@receiver),'muzzle_px':projection(W.matrix_world@muzzle),
         'hand_px':projection(hand.translation)}
    rows.append(row)
    bone_finite=bone_finite and all(math.isfinite(x) for b in bones for r in b.matrix for x in r)
    drivers_valid=drivers_valid and all(f.driver.is_valid for o in bpy.data.objects if o.animation_data for f in o.animation_data.drivers)
    if abs(frame*4-round(frame*4))<1e-8:
        for obj in skin:
            evaluated=obj.evaluated_get(dg);mesh=evaluated.to_mesh()
            skin_count+=len(mesh.vertices)
            skin_finite=skin_finite and all(math.isfinite(x) for v in mesh.vertices for x in v.co)
            evaluated.to_mesh_clear()
    if index%256==0:print('VERIFY_PROGRESS',frame,flush=True)
switches={}
for frame in [44,48,58,65,85,88,89]:
    left=next(r for r in rows if abs(r['frame']-(frame-.0001))<1e-8)
    right=next(r for r in rows if abs(r['frame']-(frame+.0001))<1e-8)
    switches[str(frame)]={'position_mm':(Vector(left['hand_position'])-Vector(right['hand_position'])).length*1000,
                         'rotation_deg':math.degrees(Quaternion(left['hand_quaternion']).rotation_difference(Quaternion(right['hand_quaternion'])).angle)}
finite_free=[r['free_guard_margin_deg'] for r in rows if r['free_guard_margin_deg'] is not None]
report={'status':'diagnostic','input_sha256':D['input_sha256'],'source_sha256':sha,
        'action':D['action'],'source_window':[7787,7883],'fps':[60,1],'frames':96,
        'prior_actions_preserved':prior_actions,'structure_preserved':structure_ok,
        'protected_pose_max_delta':pose_delta,'protected_weapon_max_delta':weapon_delta,
        'all_skin_finite':skin_finite,'all_bones_finite':bone_finite,'all_drivers_valid':drivers_valid,
        'skin_vertex_samples':skin_count,'samples':len(rows),
        'support_follow_at_65':next(r['follow'] for r in rows if r['frame']==65),
        'max_wrist_target_mm':max(r['wrist_target_mm'] for r in rows),
        'max_attached_guard_delta_deg':max(r['attached_guard_delta_deg'] or 0 for r in rows),
        'max_right_guard_delta_deg':max([r['right_guard_delta_deg'] or 0 for r in rows]),
        'min_free_guard_margin_deg':min(finite_free) if finite_free else None,
        'max_switch_position_mm':max(v['position_mm'] for v in switches.values()),
        'max_switch_rotation_deg':max(v['rotation_deg'] for v in switches.values()),
        'switches':switches,'reopened':True,'rendered':False,'visual_acceptance':None,'runtime_verified':False}
failures=validate_report(report)
report['technical_failures']=failures;report['technical_passed']=not failures
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps({'summary':report,'samples':rows},indent=2)+'\n')
print('VERIFY_RESULT',json.dumps(report),flush=True)
assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
if failures:raise SystemExit(2)
