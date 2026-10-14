"""One bounded barrel-axis roll family after the shoulder family was rejected.

Preserve the measured receiver/muzzle axis and screen projections. Inspect
guard/anatomy effects only. No save, no rendering, no broadened search.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix,Vector
from bpy_extras.object_utils import world_to_camera_view

P=Path(__file__).resolve().parent;sys.dont_write_bytecode=True
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
assert bpy.app.version_string=='4.3.2'
source=Path(bpy.data.filepath);sha=hashlib.sha256(source.read_bytes()).hexdigest()
assert sha=='f6d8cf85c065f703cfd7d480303568fad3ebba5246fc3068600f4804f3d703bb'
A=bpy.data.objects['Arms'];W=bpy.data.objects['hk416_weapon'];C=bpy.data.objects['RD First Person Review']
S=next(s for s in bpy.data.scenes if C.name in s.objects);bpy.context.window.scene=S
for obj in bpy.data.objects:
    if obj.animation_data:
        for track in obj.animation_data.nla_tracks:track.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered']
S.frame_set(1);bpy.context.view_layer.update()
basis={b.name:b.matrix_basis.copy() for b in A.pose.bones}
props={b.name:{k:v for k,v in b.items() if isinstance(v,(int,float,str))} for b in A.pose.bones}
report=json.loads((P/'candidate/authoring_report.json').read_text())
receiver=Vector(report['landmarks']['receiver_local']);muzzle=Vector(report['landmarks']['muzzle_local'])
guard=json.loads(A['wrist_guard_l']);limits=guard['absolute_limits_deg']

def update():
    A.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()

def select(frame):
    A.animation_data.action=None
    for b in A.pose.bones:
        b.matrix_basis=basis[b.name]
        for k,v in props[b.name].items():b[k]=v
    A.animation_data.action=bpy.data.actions['aella_mantle_onehand_r4']
    floor=math.floor(frame);S.frame_set(floor,subframe=frame-floor);update()

def pixel(point):
    p=world_to_camera_view(S,C,point);return Vector((p.x*1280,(1-p.y)*720))

rows=[]
for frame in [20,26,35.375,44]:
    for degrees in [-30,-15,0,15,30]:
        select(frame);root=A.pose.bones['righthand_prop']
        old_weapon=W.matrix_world.copy()
        binding=(A.matrix_world@root.matrix).inverted()@old_weapon
        goal=old_weapon@Matrix.Translation(receiver)@Matrix.Rotation(math.radians(degrees),4,'Z')@Matrix.Translation(-receiver)
        before=[pixel(old_weapon@p) for p in [receiver,muzzle]]
        A.animation_data.action=None
        root.matrix=A.matrix_world.inverted()@goal@binding.inverted();update()
        p=A.pose.bones
        raw=(p['MCH_attach_forearm_l'].matrix.inverted()@p['MCH_attach_goal_l'].matrix).to_euler('XYZ')
        raw_deg=[math.degrees(v) for v in raw]
        clipped=math.degrees(p['MCH_hand_guarded_l'].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_l'].matrix.to_quaternion()).angle)
        after=[pixel(W.matrix_world@p) for p in [receiver,muzzle]]
        rows.append({'frame':frame,'barrel_roll_delta_deg':degrees,
                     'raw_wrist_xyz_deg':raw_deg,'guard_delta_deg':clipped,
                     'guard_axis_margin_deg':[min(v-lo,hi-v) for v,(lo,hi) in zip(raw_deg,limits)],
                     'landmark_max_shift_px':max((a-b).length for a,b in zip(before,after)),
                     'bones':{b.name:{'head_world':list(A.matrix_world@b.head),'tail_world':list(A.matrix_world@b.tail)}
                              for b in A.pose.bones if b.name in ['clavicle_l','MCH_upperarm_l','lowerarm_l','hand_l']}})
summary=[]
for degrees in [-30,-15,0,15,30]:
    subset=[r for r in rows if r['barrel_roll_delta_deg']==degrees]
    summary.append({'barrel_roll_delta_deg':degrees,'max_guard_delta_deg':max(r['guard_delta_deg'] for r in subset),
                    'min_axis_margin_deg':min(min(r['guard_axis_margin_deg']) for r in subset),
                    'max_landmark_shift_px':max(r['landmark_max_shift_px'] for r in subset)})
result={'status':'diagnostic','candidate_sha256':sha,'samples':len(rows),
        'families':summary,'rows':rows,'saved':False,'rendered':False,
        'scope':'One roll family around fixed weapon barrel-axis landmarks; no source/guard/rest edits. Contours and anatomy remain unverified.'}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
print('ROLL_PROBE',json.dumps(summary),flush=True)
