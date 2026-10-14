"""Bounded r7 -> r8 diagnostic. Headless authoring and checks only; never renders.

Changes two keys/handles on one root Euler curve. Derive a cubic screen-angle
landing ease on [4,7], matching the exact original boundary angle and tangent.
The target is an inference from review, not a measured COD rotation curve.
"""
import argparse, hashlib, json, math, sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector

PIN='a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b'
ROOT='righthand_prop'
LAND='jump_land_r7'
NEW='jump_land_r8_ease_candidate'
parser=argparse.ArgumentParser()
parser.add_argument('--inputs',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.output.mkdir(parents=True,exist_ok=True)
source=Path(bpy.data.filepath)
assert hashlib.sha256(source.read_bytes()).hexdigest()==PIN
assert NEW not in bpy.data.actions
scene=bpy.context.scene;arm=bpy.data.objects['Arms'];cam=scene.camera
orig_frame=scene.frame_current; orig_subframe=scene.frame_subframe
bindings={o.name:o.animation_data.action for o in bpy.data.objects if o.animation_data}
nlas={o.name:(o.animation_data.use_nla,[(t.mute,t.is_solo) for t in o.animation_data.nla_tracks]) for o in bpy.data.objects if o.animation_data}
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
arm.animation_data.use_nla=False

def set_frame(f):
 scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
def bind(a):
 arm.animation_data.action=a
 set_frame(1)

def curve_record(fc):
 return {'path':fc.data_path,'index':fc.array_index,'extrapolation':fc.extrapolation,'mute':fc.mute,
 'points':[{'co':list(k.co),'left':list(k.handle_left),'right':list(k.handle_right),'left_type':k.handle_left_type,'right_type':k.handle_right_type,'interpolation':k.interpolation,'easing':k.easing,'amplitude':k.amplitude,'back':k.back,'period':k.period} for k in fc.keyframe_points]}
def action_record(a):return [curve_record(f) for f in a.fcurves]
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
original_actions={a.name:digest(action_record(a)) for a in bpy.data.actions}
base=bpy.data.actions[LAND];base_record=action_record(base)
bind(bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'])
bind(bpy.data.actions['RD_Locomotion_Normal_Entry_4419_4434_WIP2'])
ready=arm.matrix_world@arm.pose.bones[ROOT].matrix
keys=json.loads((args.inputs/'authored_root_keys.json').read_text())
ready_error=float(np.max(np.abs(np.array(ready)-np.array(keys['ready_root_world']))))
assert ready_error<1e-5
geom=json.loads((args.inputs/'reference_geometry.json').read_text())
front=json.loads((args.inputs/'front_sight_geometry.json').read_text())
points={n:cam.matrix_world@Vector(v) for n,v in {'rear':geom['own_points_camera']['optic_guide'],'front':front['own_points_camera']['optic_guide'],'receiver':geom['own_points_camera']['receiver_guide']}.items()}
ready_inv=ready.inverted();camera_inv=cam.matrix_world.inverted()
curves=[base.fcurves.find(f'pose.bones["{ROOT}"].{kind}',index=i) for kind in ['location','rotation_euler'] for i in range(3)]
assert all(c is not None for c in curves)
rest=np.array(arm.matrix_world@arm.pose.bones[ROOT].bone.matrix_local,dtype=float)
cam_inv_np=np.array(camera_inv,dtype=float)
local_pts={n:np.array(ready_inv@p,dtype=float) for n,p in points.items()}

def params(t):return np.array([fc.evaluate(t) for fc in curves],dtype=float)
def slopes_at_key(t):
 out=[]
 for fc in curves:
  k=next(k for k in fc.keyframe_points if abs(k.co.x-t)<1e-6)
  out.append((k.handle_right.y-k.co.y)/(k.handle_right.x-k.co.x))
 return np.array(out)
def project_params(p):
 x,y,z=p[3:];cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z)
 rx=np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
 ry=np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
 rz=np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])
 basis=np.eye(4);basis[:3,:3]=rz@ry@rx;basis[:3,3]=p[:3]
 m=cam_inv_np@rest@basis
 out={}
 for n,pt in local_pts.items():
  c=m@np.r_[pt,1.0]
  out[n]=[geom['cx']+geom['fx']*c[0]/-c[2],geom['cy']-geom['fy']*c[1]/-c[2],-c[2]]
 r,f=out['rear'],out['front'];out['angle']=(math.degrees(math.atan2(f[1]-r[1],f[0]-r[0]))+90)%180-90
 return out
def gradient(p):
 out=[]
 for i in range(6):
  eps=1e-6;plus=p.copy();minus=p.copy();plus[i]+=eps;minus[i]-=eps
  out.append((project_params(plus)['angle']-project_params(minus)['angle'])/(2*eps))
 return np.array(out)

bind(base)
# Verify that the analytical inverse uses the exact existing evaluated root.
model_errors=[]
for t in [3,4,4.5,5,6,7,8,12,29]:
 set_frame(t);actual=arm.matrix_world@arm.pose.bones[ROOT].matrix
 expected=rest.copy();p=params(t)
 # Compare guide output with real evaluated root, independent of fitted values.
 for n,pt in points.items():
  c=camera_inv@(actual@ready_inv@pt)
  pix=[geom['cx']+geom['fx']*c.x/-c.z,geom['cy']-geom['fy']*c.y/-c.z]
  model_errors.append(max(abs(pix[i]-project_params(p)[n][i]) for i in (0,1)))
assert max(model_errors)<.002,max(model_errors)
y0=project_params(params(4))['angle'];y1=project_params(params(7))['angle']
m0=float(gradient(params(4))@slopes_at_key(4));m1=float(gradient(params(7))@slopes_at_key(7))

def target(t):
 u=(t-4)/3
 value=(2*u**3-3*u*u+1)*y0+(u**3-2*u*u+u)*3*m0+(-2*u**3+3*u*u)*y1+(u**3-u*u)*3*m1
 derivative=((6*u*u-6*u)*y0+(3*u*u-4*u+1)*3*m0+(-6*u*u+6*u)*y1+(3*u*u-2*u)*3*m1)/3
 return value,derivative

candidate=base.copy();candidate.name=NEW;candidate.use_fake_user=True
fc=candidate.fcurves.find(f'pose.bones["{ROOT}"].rotation_euler',index=1)
changes=[]
for t in [5,6]:
 p=params(t);original=float(p[4]);desired,desired_slope=target(t)
 for _ in range(8):
  residual=project_params(p)['angle']-desired
  if abs(residual)<1e-9:break
  p[4]-=residual/gradient(p)[4]
 assert abs(project_params(p)['angle']-desired)<1e-6
 assert abs(p[4]-original)<math.radians(1.0)
 grad=gradient(p);base_slopes=slopes_at_key(t)
 new_slope=(desired_slope-float(grad@base_slopes)+grad[4]*base_slopes[4])/grad[4]
 k=next(k for k in fc.keyframe_points if abs(k.co.x-t)<1e-6)
 before={'co':list(k.co),'left':list(k.handle_left),'right':list(k.handle_right)}
 xl,xr=k.handle_left.x,k.handle_right.x
 k.co.y=float(p[4]);k.handle_left=(xl,p[4]+(xl-t)*new_slope);k.handle_right=(xr,p[4]+(xr-t)*new_slope)
 changes.append({'frame':t,'native_frame':4066+t,'target_angle':desired,'target_slope':desired_slope,'rotation_y_delta_degrees':math.degrees(p[4]-original),'before':before,'after':{'co':list(k.co),'left':list(k.handle_left),'right':list(k.handle_right)}})
fc.update()
# Only the two middle key records may differ, across every candidate curve.
after_record=action_record(candidate)
changed=[]
for before,after in zip(base_record,after_record):
 if before!=after:
  changed.append({'path':after['path'],'index':after['index'],'changed_frames':[a['co'][0] for a,b in zip(before['points'],after['points']) if a!=b]})
assert changed==[{'path':f'pose.bones["{ROOT}"].rotation_euler','index':1,'changed_frames':[5.0,6.0]}],changed

sample_times=sorted(set([1+i/4 for i in range(113)]+[3+i/16 for i in range(81)]))
hand_names=[b.name for b in arm.pose.bones if b.name in ['hand_l','hand_r','righthand_prop_lefthand','righthand_prop_righthand','OUT_hand_l','OUT_hand_r','OUT_magazine_guided'] or b.name.startswith(('index_','thumb_','middle_','ring_','pinky_')) and b.name.endswith(('_l','_r'))]

def evaluate(action):
 bind(action);rows=[]
 for t in sample_times:
  set_frame(t);root=arm.matrix_world@arm.pose.bones[ROOT].matrix;rinv=root.inverted();delta=root@ready_inv
  guides={}
  for n,pt in points.items():
   c=camera_inv@(delta@pt)
   guides[n]=[geom['cx']+geom['fx']*c.x/-c.z,geom['cy']-geom['fy']*c.y/-c.z,-c.z]
  r,f=guides['rear'],guides['front'];angle=(math.degrees(math.atan2(f[1]-r[1],f[0]-r[0]))+90)%180-90
  rows.append({'frame':t,'reference_native':4066+t,'angle':angle,'guides':guides,'root_world':np.array(root).tolist(),'root_location':list(arm.pose.bones[ROOT].location),'root_rotation':list(arm.pose.bones[ROOT].rotation_euler),'relative_bones':{n:np.array(rinv@arm.matrix_world@arm.pose.bones[n].matrix).tolist() for n in hand_names},'relative_props':{n:np.array(rinv@bpy.data.objects[n].matrix_world).tolist() for n in ['hk416_weapon','hk416_magazine']}})
 return rows
before_rows=evaluate(base);after_rows=evaluate(candidate)
max_location=max(np.max(np.abs(np.array(a['root_location'])-np.array(b['root_location']))) for a,b in zip(before_rows,after_rows))
max_outside=max(np.max(np.abs(np.array(a['root_world'])-np.array(b['root_world']))) for a,b in zip(before_rows,after_rows) if not 4<a['frame']<7)
max_root_world_translation=max(np.max(np.abs(np.array(a['root_world'])[:3,3]-np.array(b['root_world'])[:3,3])) for a,b in zip(before_rows,after_rows))
contact_deltas={n:max(float(np.max(np.abs(np.array(a['relative_bones'][n])-np.array(b['relative_bones'][n])))) for a,b in zip(before_rows,after_rows)) for n in hand_names}
prop_deltas={n:max(float(np.max(np.abs(np.array(a['relative_props'][n])-np.array(b['relative_props'][n])))) for a,b in zip(before_rows,after_rows)) for n in ['hk416_weapon','hk416_magazine']}
assert max_location==0 and max_outside==0 and max_root_world_translation==0
assert max(contact_deltas.values())<1e-4,contact_deltas
assert max(prop_deltas.values())<1e-5,prop_deltas
for name,h in original_actions.items():assert digest(action_record(bpy.data.actions[name]))==h,name

integer_before={int(x['frame']):x for x in before_rows if x['frame']%1==0}
integer_after={int(x['frame']):x for x in after_rows if x['frame']%1==0}
integer_comparison=[]
for f in range(3,10):
 a,b=integer_before[f],integer_after[f]
 integer_comparison.append({'land_frame':f,'reference_frame':4066+f,'r7_angle':a['angle'],'candidate_angle':b['angle'],'r7_velocity_previous':a['angle']-integer_before[f-1]['angle'],'candidate_velocity_previous':b['angle']-integer_after[f-1]['angle'],'r7_rear_y':a['guides']['rear'][1],'candidate_rear_y':b['guides']['rear'][1]})
report={'status':'diagnostic; unrendered; final artistic review pending','source_path':str(source),'source_sha256':PIN,'source_action':LAND,'candidate_action':NEW,'changed_curves':changed,'changes':changes,'target_description':'One cubic Hermite projected guide-angle ease from land f4 to f7, matching the original endpoint values and tangents. Fixed translation and all other Euler channels. This is inferred authoring, not COD measurement.','target_boundary':{'angle4':y0,'angle7':y1,'slope4':m0,'slope7':m1},'analytical_model_max_error_px':max(model_errors),'sample_count':len(sample_times),'sample_rate':'whole landing 240Hz plus f3-f8 960Hz','preservation':{'all_original_actions_same_complete_curve_hash':True,'original_action_count':len(original_actions),'other_774_candidate_curves_identical':True,'root_translation_curves_identical':True,'max_local_translation_delta':float(max_location),'max_world_root_translation_delta':float(max_root_world_translation),'max_world_root_delta_outside_open_4_7':float(max_outside),'relative_contact_bone_max_matrix_delta':contact_deltas,'relative_prop_max_matrix_delta':prop_deltas,'trough_f12_and_closure_f29_world_matrices_unchanged':True,'takeoff_air_actions_untouched':True},'integer_comparison':integer_comparison,'source_bytes_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==PIN,'no_render_operator':True,'no_external_upload':True}
# Restore source session choices; a separate Action is added, existing state retained.
for name,action in bindings.items():bpy.data.objects[name].animation_data.action=action
for name,(use_nla,tracks) in nlas.items():
 ad=bpy.data.objects[name].animation_data;ad.use_nla=use_nla
 for tr,(mute,solo) in zip(ad.nla_tracks,tracks):tr.mute=mute;tr.is_solo=solo
scene.frame_set(orig_frame,subframe=orig_subframe)
bpy.context.view_layer.update()
out=args.output/'halcyon_jump_r8_ease_candidate.blend'
assert out.resolve()!=source.resolve()
assert not out.exists(),'Refuse to overwrite an existing candidate'
bpy.ops.wm.save_as_mainfile(filepath=str(out),check_existing=True)
report['candidate_path']=str(out);report['candidate_sha256']=hashlib.sha256(out.read_bytes()).hexdigest()
(args.output/'landing_ease_validation.json').write_text(json.dumps(report,indent=2)+'\n')
(args.output/'dense_evaluation.json').write_text(json.dumps({'baseline':before_rows,'candidate':after_rows},indent=2)+'\n')
(args.output/'candidate_action_curves.json').write_text(json.dumps(after_record,indent=2)+'\n')
(args.output/'original_action_hashes.json').write_text(json.dumps(original_actions,indent=2)+'\n')
print(json.dumps(report,indent=2))
