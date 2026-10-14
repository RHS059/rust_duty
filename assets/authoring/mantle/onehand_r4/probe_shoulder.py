"""Bounded read-only shoulder family for the retained r4 wrist failure.

One finite hypothesis family, no optimization or repeated search. No save or
render. The weapon matrices and guard definitions stay unchanged throughout.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

P=Path(__file__).resolve().parent;sys.path.insert(0,str(P));sys.dont_write_bytecode=True
from correction_contract import interpolate
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
old_offsets=[[7799,0,0],[7804,0,.03],[7806,.004,.06],[7808,.02,.06],[7810,.06,.04],[7818,.06,.06],[7834,.06,.06],[7844,0,0],[7882,0,0]]
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
    p=world_to_camera_view(S,C,point);return [p.x*1280,(1-p.y)*720,p.z]

families=[('keep',False,0,0),('remove_r3',True,0,0)]
families += [(f'removed_plus_y{dy:+.2f}_z{dz:+.2f}',True,dy,dz)
             for dy,dz in [(-.06,-.06),(-.06,0),(-.06,.06),(0,-.06),(0,.06),(.06,-.06),(.06,0),(.06,.06)]]
rows=[]
for frame in [20,26,35.375,44]:
    inherited=interpolate(old_offsets,7786+frame)
    for name,remove,dy,dz in families:
        select(frame);weapon=W.matrix_world.copy()
        A.animation_data.action=None
        shoulder=A.pose.bones['clavicle_l'];m=shoulder.matrix.copy()
        y=dy-inherited[0] if remove else dy;z=dz-inherited[1] if remove else dz
        m.translation.y+=y;m.translation.z+=z;shoulder.matrix=m;update()
        p=A.pose.bones
        raw=(p['MCH_attach_forearm_l'].matrix.inverted()@p['MCH_attach_goal_l'].matrix).to_euler('XYZ')
        raw_deg=[math.degrees(v) for v in raw]
        clipped=math.degrees(p['MCH_hand_guarded_l'].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_l'].matrix.to_quaternion()).angle)
        drift=max(abs(weapon[i][j]-W.matrix_world[i][j]) for i in range(4) for j in range(4))
        rows.append({'frame':frame,'family':name,'delta_pose_yz_m':[y,z],
                     'total_hypothesis_yz_m':[dy,dz] if remove else list(inherited),
                     'raw_wrist_xyz_deg':raw_deg,'guard_delta_deg':clipped,
                     'guard_axis_margin_deg':[min(v-lo,hi-v) for v,(lo,hi) in zip(raw_deg,limits)],
                     'weapon_matrix_delta':drift,
                     'shoulder_location':list(shoulder.location),
                     'bones':{b.name:{'head_px':pixel(A.matrix_world@b.head),'tail_px':pixel(A.matrix_world@b.tail),
                                      'head_world':list(A.matrix_world@b.head),'tail_world':list(A.matrix_world@b.tail)}
                              for b in A.pose.bones if b.name in ['clavicle_l','upperarm_l','forearm_l','hand_l']}})
summary=[]
for name,_,_,_ in families:
    subset=[r for r in rows if r['family']==name]
    summary.append({'family':name,'max_guard_delta_deg':max(r['guard_delta_deg'] for r in subset),
                    'min_axis_margin_deg':min(min(r['guard_axis_margin_deg']) for r in subset),
                    'max_weapon_matrix_delta':max(r['weapon_matrix_delta'] for r in subset)})
result={'status':'diagnostic','candidate_sha256':sha,'samples':len(rows),
        'families':summary,'rows':rows,'saved':False,'rendered':False,
        'scope':'Shoulder pose-only finite probe; no guard/mesh/rest changes. Anatomy remains visually unverified.'}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
print('SHOULDER_PROBE',json.dumps(summary),flush=True)
