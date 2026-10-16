"""Author four isolated reference-guided crawl segment Actions into a separate frozen source copy.
Usage: blender --background --factory-startup --disable-autoexec BASE.blend --python author_jump_r7.py -- jump_design_r7.json OUTPUT.blend
Never saves the input, overwrites a revision, edits existing Actions or renders.
"""
import bpy,sys,json,hashlib,math
from pathlib import Path
from mathutils import Matrix,Vector,Euler
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from source_integrity import snapshot
from validate_source_structure import extra_snapshot
args=sys.argv[sys.argv.index('--')+1:]
design_path,output=map(Path,args);design=json.loads(design_path.read_text())
source=Path(bpy.data.filepath);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert bpy.app.version_string=='4.3.2'
assert sha(source)==design['source_sha256']
assert source.resolve()!=output.resolve() and not output.exists(),'Refuse overwrite'
assert len(bpy.data.actions)==design['source_action_count']
assert not(set(design['actions']) & set(bpy.data.actions.keys()))
output.parent.mkdir(parents=True,exist_ok=True)
before=snapshot(bpy);extra_before=extra_snapshot()
scene=bpy.context.scene;rig=bpy.data.objects['Arms'];root=rig.pose.bones[design['animated_control']]
assert root.parent is None and root.rotation_mode=='XYZ'
assert scene.render.fps/scene.render.fps_base==60 and scene.camera.name==design['camera']
frame_state=(scene.frame_current,scene.frame_subframe)
def native(v):
 if hasattr(v,'to_list'):return v.to_list()
 if hasattr(v,'to_dict'):return v.to_dict()
 return v
raw_pose={p.name:{'rotation_mode':p.rotation_mode,**{k:list(getattr(p,k)) for k in ('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')},'properties':{k:native(p[k]) for k in p.keys()}} for p in rig.pose.bones}
ad_state={o.name:(o.animation_data.action,o.animation_data.use_nla,[(t,t.mute,t.is_solo) for t in o.animation_data.nla_tracks]) for o in bpy.data.objects if o.animation_data}
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
rig.animation_data.use_nla=False
rig.animation_data.action=bpy.data.actions[design['guarded_initialization']];scene.frame_set(1);bpy.context.view_layer.update()
ready=bpy.data.actions[design['baseline_action']]
rig.animation_data.action=ready;scene.frame_set(design['baseline_frame']);bpy.context.view_layer.update()
C=scene.camera.matrix_world.copy();Ci=C.inverted();Ri=rig.matrix_world.inverted()
ready_world=rig.matrix_world@root.matrix.copy();ready_local={'location':list(root.location),'rotation_euler':list(root.rotation_euler)}
pivot=Ci@rig.matrix_world@rig.pose.bones['hand_l'].matrix.translation
ready_curves={(f.data_path,f.array_index):f.evaluate(design['baseline_frame']) for f in ready.fcurves}
root_paths={f'pose.bones["{root.name}"].'+p for p in ('location','rotation_euler')}
def params_at(entry,frame):
 samples=design['native_parameters'];xs=[b['source_frame'] for b in samples]
 source_frame=entry['source_frame_range_inclusive'][0]+frame-1
 if source_frame<=xs[0]:return samples[0]['params'][:]
 if source_frame>=xs[-1]:return samples[-1]['params'][:]
 seg=next(i for i in range(len(xs)-1) if xs[i]<=source_frame<=xs[i+1])
 hs=[b-a for a,b in zip(xs,xs[1:])];values=[]
 for axis in range(6):
  ys=[b['params'][axis] for b in samples];ds=[(b-a)/h for a,b,h in zip(ys,ys[1:],hs)];slopes=[0.]*len(xs)
  for i in range(1,len(xs)-1):
   if ds[i-1]*ds[i]>0:
    w1=2*hs[i]+hs[i-1];w2=hs[i]+2*hs[i-1];slopes[i]=(w1+w2)/(w1/ds[i-1]+w2/ds[i])
  h=hs[seg];t=(source_frame-xs[seg])/h
  values.append((2*t**3-3*t**2+1)*ys[seg]+(t**3-2*t**2+t)*h*slopes[seg]+(-2*t**3+3*t**2)*ys[seg+1]+(t**3-t**2)*h*slopes[seg+1])
 return values
def local_at(params):
 if all(v==0 for v in params):return {k:v[:] for k,v in ready_local.items()}
 x,y,z,pitch,yaw,roll=params
 R=Matrix.Rotation(math.radians(pitch),4,'X')@Matrix.Rotation(math.radians(yaw),4,'Y')@Matrix.Rotation(math.radians(roll),4,'Z')
 T=C@Matrix.Translation(pivot+Vector((x,y,z)))@R@Matrix.Translation(-pivot)@Ci
 root.matrix=Ri@T@ready_world
 return {'location':list(root.location),'rotation_euler':list(root.rotation_euler)}
created=[];keys_out={}
rig.animation_data.action=None
for name,entry in design['actions'].items():
 a=ready.copy();a.name=name;a.use_fake_user=True
 # A new Action gets its own honest metadata, never inherited reference/approval labels.
 for key in list(a.keys()):del a[key]
 for marker in list(a.pose_markers):a.pose_markers.remove(marker)
 a.use_frame_range=True;a.frame_start=entry['frame_range'][0];a.frame_end=entry['frame_range'][1]
 for f in a.fcurves:
  f.lock=False;f.mute=False;f.extrapolation='CONSTANT'
  if f.group:f.group.lock=False
  for modifier in list(f.modifiers):f.modifiers.remove(modifier)
  f.keyframe_points.clear()
  if f.data_path not in root_paths:
   value=ready_curves[(f.data_path,f.array_index)]
   for frame in entry['frame_range']:
    k=f.keyframe_points.insert(frame,value);k.interpolation='CONSTANT'
 rows=[]
 for frame in range(entry['frame_range'][0],entry['frame_range'][1]+1):
  params=params_at(entry,frame);values=local_at(params)
  # Numerical derivatives use a broad enough central interval to avoid float32 cancellation.
  # Zero endpoint tangents make connection to a static hold exact.
  if entry['source_frame_range_inclusive'][0]+frame-1 in tuple(entry['source_frame_range_inclusive']):slope={p:[0.,0.,0.] for p in ready_local}
  else:
   h=.05;left=local_at(params_at(entry,frame-h));right=local_at(params_at(entry,frame+h))
   slope={p:[(r-l)/(2*h) for l,r in zip(left[p],right[p])] for p in ready_local}
  rows.append({'frame':frame,'time_seconds':(frame-1)/60,'params':params,**values,'slope_per_frame':slope})
 for prop in ready_local:
  for i in range(3):
   f=next(f for f in a.fcurves if f.data_path==f'pose.bones["{root.name}"].{prop}' and f.array_index==i)
   for row in rows:
    t=row['frame'];v=row[prop][i];d=row['slope_per_frame'][prop][i]
    k=f.keyframe_points.insert(t,v);k.interpolation='BEZIER';k.handle_left_type='FREE';k.handle_right_type='FREE';k.handle_left=(t-1/3,v-d/3);k.handle_right=(t+1/3,v+d/3)
 if 'preserve_curve_action' in entry:
  previous=bpy.data.actions[entry['preserve_curve_action']]
  for fc in a.fcurves:
   prior=next(c for c in previous.fcurves if c.data_path==fc.data_path and c.array_index==fc.array_index)
   fc.keyframe_points.clear()
   for old_key in prior.keyframe_points:
    k=fc.keyframe_points.insert(old_key.co.x,old_key.co.y);k.interpolation=old_key.interpolation;k.handle_left_type=old_key.handle_left_type;k.handle_right_type=old_key.handle_right_type;k.handle_left=old_key.handle_left;k.handle_right=old_key.handle_right
  for row in rows:
   for prop in ready_local:
    for i in range(3):
     fc=next(c for c in a.fcurves if c.data_path==f'pose.bones["{root.name}"].{prop}' and c.array_index==i)
     k=next(k for k in fc.keyframe_points if k.co.x==row['frame'])
     row[prop][i]=float(k.co.y);row['slope_per_frame'][prop][i]=float((k.handle_right.y-k.co.y)/(k.handle_right.x-k.co.x))
 if 'match_start_tangent_action' in entry:
  previous=bpy.data.actions[entry['match_start_tangent_action']]
  for fc in a.fcurves:
   if fc.data_path not in root_paths:continue
   prior=next(c for c in previous.fcurves if c.data_path==fc.data_path and c.array_index==fc.array_index)
   old_key=prior.keyframe_points[-1];k=fc.keyframe_points[0]
   k.handle_left=k.co+(old_key.handle_left-old_key.co);k.handle_right=k.co+(old_key.handle_right-old_key.co)
   prop=fc.data_path.rsplit('.',1)[1];rows[0]['slope_per_frame'][prop][fc.array_index]=float((k.handle_right.y-k.co.y)/(k.handle_right.x-k.co.x))
 for b in entry['beats']:m=a.pose_markers.new(b['label']);m.frame=round(b['frame'])
 a['runtime_id']=entry['runtime_id'];a['authoring_fps']=60;a['duration_seconds']=entry['duration_seconds'];a['loop']=entry['loop'];a['pose_space']='absolute';a['base_action']=ready.name;a['base_frame']=1;a['motion_origin']=design['motion_origin'];a['reference_id']=design['reference']['youtube_id'];a['source_frame_start']=entry['source_frame_range_inclusive'][0];a['source_frame_end_inclusive']=entry['source_frame_range_inclusive'][1];a['hold_after_end']=entry['hold_after_end'];a['acceptance_status']='WIP; Elara review pending';a['animated_control']='righthand_prop only';a['camera_motion']='none';a['root_motion']=False;a['purpose']=entry['purpose']
 assert list(a.frame_range)==entry['frame_range']
 created.append(name);keys_out[name]=rows
# Reach compensation in new Actions only: keep the firing hand attached without
# changing constraints, arm lengths, original Actions, skeleton root or camera.
weapon=bpy.data.objects['hk416_weapon'];shoulder=rig.pose.bones['clavicle_r']
rig.animation_data.action=ready;scene.frame_set(design['baseline_frame']);bpy.context.view_layer.update()
base_shoulder_location=shoulder.location.copy()
grip_local=weapon.matrix_world.inverted()@rig.matrix_world@rig.pose.bones['hand_r'].matrix.translation
reach={}
for name in created:
 action=bpy.data.actions[name];rig.animation_data.action=action;rows=[]
 for sample_index in range((int(action.frame_end)-int(action.frame_start))*8+1):
  frame=int(action.frame_start)+sample_index/8
  shoulder.location=base_shoulder_location.copy();scene.frame_set(math.floor(frame),subframe=frame-math.floor(frame));bpy.context.view_layer.update()
  for iteration in range(16):
   expected=weapon.matrix_world@grip_local
   actual=rig.matrix_world@rig.pose.bones['hand_r'].matrix.translation
   error=expected-actual
   if error.length<0.000005:break
   m=shoulder.matrix.copy();m.translation+=rig.matrix_world.inverted().to_3x3()@error
   shoulder.matrix=m;bpy.context.view_layer.update()
  rows.append({'frame':frame,'location':list(shoulder.location),'grip_error_m':error.length})
 for axis in range(3):
  path='pose.bones["clavicle_r"].location';fc=next((f for f in action.fcurves if f.data_path==path and f.array_index==axis),None)
  if fc is None:fc=action.fcurves.new(path,index=axis,action_group='clavicle_r')
  fc.keyframe_points.clear()
  for row in rows:
   key=fc.keyframe_points.insert(row['frame'],row['location'][axis]);key.interpolation='LINEAR'
 action['animated_control']='righthand_prop, plus clavicle_r location for finite-chain grip reach'
 reach[name]=rows
(output.parent/'reach_compensation.json').write_text(json.dumps({'scope':'New segment Actions only. Minimal shoulder translation at 480 Hz closes the measured right-hand IK reach residual, including native interframes. Weapon curves and native shoulder poses are retained. No constraints, arm length, skeleton root, camera or unrelated data changed.','actions':reach},indent=2)+'\n')

# Restore all original source state, including animated and unkeyed pose defaults.
for p in rig.pose.bones:
 saved=raw_pose[p.name];p.rotation_mode=saved['rotation_mode']
 for field in ('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale'):setattr(p,field,saved[field])
 for key,value in saved['properties'].items():
  current=p[key]
  if hasattr(current,'to_list'):
   for i,v in enumerate(value):current[i]=v
  elif isinstance(value,(str,int,float,bool)):p[key]=value
  else:assert native(current)==value
for name,(action,use_nla,tracks) in ad_state.items():
 ad=bpy.data.objects[name].animation_data;ad.action=action;ad.use_nla=use_nla
 for track,mute,solo in tracks:track.mute=mute;track.is_solo=solo
scene.frame_set(frame_state[0],subframe=frame_state[1]);bpy.context.view_layer.update()
after=snapshot(bpy);extra_after=extra_snapshot()
checks={
 'all_prior_action_fingerprints':all(after['actions'][n]==v for n,v in before['actions'].items()),
 'only_expected_new_actions':set(after['actions'])-set(before['actions'])==set(created),
 'nla_and_active_actions':after['nla']==before['nla'],
 'drivers':after['drivers']==before['drivers'],
 'packed_images':after['packed_images']==before['packed_images']}
for key in extra_before:
 checks[key]=(all(extra_after[key].get(n)==v for n,v in extra_before[key].items()) if key in ('actions_metadata','actions_extended') else extra_after[key]==extra_before[key])
assert all(checks.values()),checks
bpy.ops.wm.save_as_mainfile(filepath=str(output),compress=True)
assert sha(source)==design['source_sha256']
(output.parent/'authored_root_keys.json').write_text(json.dumps({'schema':'rust-duty-prone-crawl-authored-root-keys/v1','candidate_sha256':sha(output),'ready_root_local':ready_local,'pivot_camera':list(pivot),'camera_matrix_world':[list(x) for x in C],'ready_root_world':[list(x) for x in ready_world],'parameter_order':design['parameter_order'],'actions':keys_out},indent=2)+'\n')
(output.parent/'authoring_preservation.json').write_text(json.dumps({'schema':'rust-duty-prone-crawl-source-preservation/v1','source_sha256':sha(source),'candidate_sha256':sha(output),'source_actions':design['source_action_count'],'candidate_actions':len(bpy.data.actions),'created_actions':created,'checks':checks,'passed':all(checks.values()),'source_saved':False,'candidate_saved':True,'design_sha256':sha(design_path)},indent=2)+'\n')
(output.parent/'baseline_fingerprint.json').write_text(json.dumps({'source_sha256':sha(source),'preserved':before,'structural':extra_before},indent=2)+'\n')
print(json.dumps({'output':str(output),'sha256':sha(output),'created':created,'preservation_checks':checks},indent=2))
