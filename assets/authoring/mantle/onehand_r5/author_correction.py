"""Author one isolated correction Action from the pinned local source, without render.

The unchanged camera, actual mesh muzzle slice and a bounded two-ray solve
define the weapon hypothesis. Source assets are required locally and never
embedded in this script or copied to a publication packet.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

P=Path(__file__).resolve().parent
sys.path.insert(0,str(P))
sys.dont_write_bytecode=True
from correction_contract import interpolate,smooth5
from curve_splice import splice_curve

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--integrity-dir',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
sys.path.insert(0,str(args.integrity_dir))
from source_integrity import snapshot,action_fingerprint
from validate_directional_source import extra_snapshot

D=json.loads((P/'design.json').read_text())
source=Path(bpy.data.filepath)
assert hashlib.sha256(source.read_bytes()).hexdigest()==D['input_sha256']
assert bpy.app.version_string=='4.3.2'
assert not args.output.exists(), 'Refuse to overwrite a previous candidate'
A=bpy.data.objects['Arms'];C=bpy.data.objects['RD First Person Review']
W=bpy.data.objects['hk416_weapon'];R=A.pose.bones['righthand_prop']
L=A.pose.bones['righthand_prop_lefthand']
S=next(s for s in bpy.data.scenes if C.name in s.objects)
bpy.context.window.scene=S
before=snapshot(bpy);structure=extra_snapshot()
old=bpy.data.actions[D['prior_action']]
assert D['action'] not in bpy.data.actions
original_action=A.animation_data.action;original_nla=A.animation_data.use_nla
original_frame=S.frame_current;original_subframe=S.frame_subframe
original_basis={b.name:b.matrix_basis.copy() for b in A.pose.bones}
original_props={b.name:{k:v for k,v in b.items() if isinstance(v,(int,float,str))} for b in A.pose.bones}
for obj in bpy.data.objects:
    if obj.animation_data:
        for track in obj.animation_data.nla_tracks:track.mute=True
A.animation_data.use_nla=False
A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered']
S.frame_set(1);bpy.context.view_layer.update()
base_basis={b.name:b.matrix_basis.copy() for b in A.pose.bones}

def update():
    A.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()

def select(frame):
    A.animation_data.action=None
    for b in A.pose.bones:
        b.matrix_basis=base_basis[b.name]
        for k,v in original_props[b.name].items():b[k]=v
    A.animation_data.action=old
    integer=math.floor(frame);S.frame_set(integer,subframe=frame-integer);update()

select(1)
attached_basis=L.matrix_basis.copy()
weapon_from_root=(A.matrix_world@R.matrix).inverted()@W.matrix_world
cam_inverse=C.matrix_world.inverted()
focal=1280*C.data.lens/C.data.sensor_width
min_z=min(v.co.z for v in W.data.vertices)
slice_points=[v.co for v in W.data.vertices if v.co.z<=min_z+D['muzzle_slice_m']]
center=sum(slice_points,Vector())/len(slice_points)
muzzle=Vector((center.x,center.y,min_z))
receiver=Vector((center.x,center.y,D['receiver_local_z']))
barrel_length=(muzzle-receiver).length
guard=json.loads(A['wrist_guard_l']);guard_base=guard['base_euler_deg']

def ray(x,y):return Vector(((x-640)/focal,(360-y)/focal,-1))
def projection(world):
    p=world_to_camera_view(S,C,world)
    return [1280*p.x,720*(1-p.y),p.z]

def desired_weapon(old_camera,frame):
    rx,ry,mx,my,roll=interpolate(D['target_keys'],frame)
    receiver_depth=-(old_camera@receiver).z
    g=ray(rx,ry)*receiver_depth;q=ray(mx,my)
    qa=q.dot(q);qb=-2*q.dot(g);qc=g.dot(g)-barrel_length**2
    disc=qb*qb-4*qa*qc
    if disc<=0:raise ValueError(f'No physical two-ray depth branch at {frame}')
    roots=[(-qb-sign*math.sqrt(disc))/(2*qa) for sign in [-1,1]]
    depth=max(roots)
    if depth<=receiver_depth:raise ValueError(f'Muzzle depth branch reversed at {frame}')
    tip=q*depth;z=(g-tip).normalized()
    x=Vector((0,1,0)).cross(z).normalized();y=z.cross(x).normalized()
    rotation=Matrix((x,y,z)).transposed()@Matrix.Rotation(math.radians(roll),3,'Z')
    target=rotation.to_4x4();target.translation=g-rotation@receiver
    weight=smooth5((frame-D['weapon_blend_in'][0])/(D['weapon_blend_in'][1]-D['weapon_blend_in'][0]))
    weight*=1-smooth5((frame-D['weapon_blend_out'][0])/(D['weapon_blend_out'][1]-D['weapon_blend_out'][0]))
    mixed=old_camera.to_quaternion().slerp(target.to_quaternion(),weight).to_matrix().to_4x4()
    mixed.translation=old_camera.translation.lerp(target.translation,weight)
    return mixed,weight

def attached_properties():
    p=A.pose.bones
    raw=(p['MCH_attach_forearm_l'].matrix.inverted()@p['MCH_attach_goal_l'].matrix).to_euler('XYZ')
    return {'forearm_roll':math.degrees(p['MCH_attach_forearm_l'].rotation_euler.y),
            'wrist_flex':math.degrees(raw.x)-guard_base[0],
            'wrist_twist':math.degrees(raw.y)-guard_base[1],
            'wrist_deviation':math.degrees(raw.z)-guard_base[2]}

rows=[];previous_root=None;previous_left=None;max_root_error=0.;max_target_error=0.
for index in range((96-1)*D['divisions']+1):
    frame=1+index/D['divisions'];select(frame)
    old_world=W.matrix_world.copy();old_camera=cam_inverse@old_world
    if 8<frame<85:
        camera_goal,weight=desired_weapon(old_camera,frame)
        A.animation_data.action=None
        R.matrix=A.matrix_world.inverted()@C.matrix_world@camera_goal@weapon_from_root.inverted()
        update()
        max_root_error=max(max_root_error,max(abs(W.matrix_world[i][j]-(C.matrix_world@camera_goal)[i][j]) for i in range(4) for j in range(4)))
    else:
        weight=0.;A.animation_data.action=None
    root_euler=R.rotation_euler.copy()
    if previous_root is not None:root_euler.make_compatible(previous_root)
    previous_root=root_euler
    if 8<frame<89:
        L.matrix_basis=attached_basis.copy();L['weapon_follow']=1.;L['magazine_follow']=0.;update()
        goal=L.matrix.copy();raw=attached_properties()
        a,b,c,d=D['support_free_envelope']
        free=smooth5((frame-a)/(b-a))*(1-smooth5((frame-c)/(d-c)))
        if free:
            px,py=interpolate(D['free_hand_pixel_keys'],frame)
            camera_hand=cam_inverse@A.matrix_world@goal.translation
            free_position=C.matrix_world@(ray(px,py)*(-camera_hand.z))
            desired_local=A.matrix_world.inverted()@free_position
            goal.translation=goal.translation.lerp(desired_local,free)
        target={'forearm_roll':D['free_forearm_roll_deg'],
                'wrist_flex':D['free_wrist_delta_deg'][0],
                'wrist_twist':D['free_wrist_delta_deg'][1],
                'wrist_deviation':D['free_wrist_delta_deg'][2]}
        L['weapon_follow']=1-free
        for k in target:L[k]=(1-free)*raw[k]+free*target[k]
        for digit in ['thumb','index','middle','ring','pinky']:L[digit+'_curl']=D['free_curl_rad']*free
        update()
        for _ in range(10):
            L.matrix_basis=L.matrix_basis@L.matrix.inverted()@goal;update()
            if (L.matrix.translation-goal.translation).length<1e-7 and L.matrix.to_quaternion().rotation_difference(goal.to_quaternion()).angle<1e-6:break
        max_target_error=max(max_target_error,(L.matrix.translation-goal.translation).length)
    left_euler=L.rotation_euler.copy()
    if previous_left is not None:left_euler.make_compatible(previous_left)
    previous_left=left_euler
    rows.append({'frame':frame,'native':7786+frame,
                 'root_location':list(R.location),'root_rotation_euler':list(root_euler),
                 'left_location':list(L.location),'left_rotation_euler':list(left_euler),
                 'left_properties':{k:float(L[k]) for k in ['weapon_follow','magazine_follow','forearm_roll','wrist_flex','wrist_twist','wrist_deviation','thumb_curl','index_curl','middle_curl','ring_curl','pinky_curl']},
                 'receiver_px':projection(W.matrix_world@receiver),
                 'muzzle_px':projection(W.matrix_world@muzzle),
                 'left_wrist_px':projection(A.matrix_world@A.pose.bones['hand_l'].matrix.translation),
                 'weapon_blend':weight})
    if index%128==0:print('AUTHOR_PROGRESS',frame,flush=True)

new=old.copy();new.name=D['action'];new.use_fake_user=True
for prefix,name,end in [('righthand_prop','root',85),('righthand_prop_lefthand','left',89)]:
    for channel in ['location','rotation_euler']:
        for axis in range(3):
            splice_curve(new,f'pose.bones["{prefix}"].{channel}',axis,
                         [(r['frame'],r[name+'_'+channel][axis]) for r in rows],end=end)
for prop in rows[0]['left_properties']:
    splice_curve(new,f'pose.bones["righthand_prop_lefthand"]["{prop}"]',0,
                 [(r['frame'],r['left_properties'][prop]) for r in rows],end=89)
new['status']='diagnostic';new['render_status']='not rendered'
new['source_frame_start']=7787;new['source_frame_end_exclusive']=7883
new['source_fps']=60;new['camera_unchanged']=True
new['acceptance']='Visual, surface contact, export and runtime unverified'
A.animation_data.action=original_action;A.animation_data.use_nla=original_nla
for b in A.pose.bones:
    b.matrix_basis=original_basis[b.name]
    for k,v in original_props[b.name].items():b[k]=v
for obj in bpy.data.objects:
    if obj.animation_data and obj.name in before['nla']:
        for track,record in zip(obj.animation_data.nla_tracks,before['nla'][obj.name]['tracks']):
            track.mute=record['mute'];track.is_solo=record['is_solo']
S.frame_set(original_frame,subframe=original_subframe);update()
after=snapshot(bpy);after_structure=extra_snapshot()
assert all(action_fingerprint(bpy.data.actions[n])==h for n,h in before['actions'].items())
for key in ['meshes','armatures','objects_and_bindings','materials','cameras']:
    assert structure[key]==after_structure[key],key
for key in ['drivers','packed_images','nla']:assert before[key]==after[key],key
args.output.parent.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output),compress=True)
report={'status':'diagnostic','input_sha256':D['input_sha256'],
        'source_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
        'action':new.name,'prior_action_count':len(before['actions']),'action_count':len(after['actions']),
        'prior_actions_preserved':True,'structure_preserved':True,
        'source_window':[7787,7883],'fps':[60,1],'frames':96,
        'authored_samples':len(rows),'max_root_matrix_error':max_root_error,
        'max_support_controller_target_error_m':max_target_error,
        'landmarks':{'receiver_local':list(receiver),'muzzle_local':list(muzzle),
                     'muzzle_slice_vertices':len(slice_points)},
        'reopened':False,'rendered':False,'visual_acceptance':None,'runtime_verified':False}
(args.output.parent/'authoring_report.json').write_text(json.dumps(report,indent=2)+'\n')
(args.output.parent/'controls.json').write_text(json.dumps(rows,indent=2)+'\n')
(args.output.parent/'preservation_before.json').write_text(json.dumps({'snapshot':before,'structure':structure},indent=2)+'\n')
assert hashlib.sha256(source.read_bytes()).hexdigest()==D['input_sha256']
print('AUTHOR_RESULT',json.dumps(report),flush=True)
