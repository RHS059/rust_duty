"""Blender 4.3.2 source-first directional loop authoring from measured frame keys.
Loads a frozen canonical source and saves a separate lane file. Never edits source bytes.
The six righthand_prop channels are the only varying channels in each new Action.
"""
import bpy,json,sys,math,hashlib
import numpy as np
from pathlib import Path
from mathutils import Matrix,Vector,Euler
args=sys.argv[sys.argv.index('--')+1:];design_path=Path(args[0]);OUT=Path(args[1]);OUT.parent.mkdir(parents=True,exist_ok=True)
design=json.loads(design_path.read_text());assert bpy.app.version_string=='4.3.2';assert not OUT.exists(), "Refuse overwrite existing revision";source=Path(bpy.data.filepath);source_hash=hashlib.sha256(source.read_bytes()).hexdigest();assert source_hash==design['source_sha256'];assert source.resolve()!=OUT.resolve()
sys.path.insert(0,str(Path(__file__).resolve().parent))
from source_integrity import snapshot
before=snapshot(bpy);s=bpy.context.scene;r=bpy.data.objects['Arms'];orig_frame=s.frame_current;orig_sub=s.frame_subframe
def idcopy(value):
 if hasattr(value,'to_list'):return value.to_list()
 if hasattr(value,'to_dict'):return value.to_dict()
 return value
raw_pose={p.name:{'rotation_mode':p.rotation_mode,'location':list(p.location),'rotation_euler':list(p.rotation_euler),'rotation_quaternion':list(p.rotation_quaternion),'rotation_axis_angle':list(p.rotation_axis_angle),'scale':list(p.scale),'properties':{k:idcopy(p[k]) for k in p.keys()}} for p in r.pose.bones}
ad_state={o.name:(o.animation_data.action,o.animation_data.use_nla,[(t,t.mute,t.is_solo) for t in o.animation_data.nla_tracks]) for o in bpy.data.objects if o.animation_data}
base=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];ready=bpy.data.actions['RD_Locomotion_Normal_Entry_4419_4434_WIP2'];root=r.pose.bones['righthand_prop'];cam=s.camera
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
r.animation_data.use_nla=False;r.animation_data.action=base;s.frame_set(1);bpy.context.view_layer.update();basis={p.name:p.matrix_basis.copy() for p in r.pose.bones}
r.animation_data.action=ready;s.frame_set(1);bpy.context.view_layer.update();root_world=r.matrix_world@root.matrix.copy();pivot=Vector(design['geometry']['points_camera']['support_wrist']);C=cam.matrix_world.copy();Ci=C.inverted();Ri=r.matrix_world.inverted()
rootprefix='pose.bones["righthand_prop"].';created=[];allkeys={}
for name,entry in design['actions'].items():
 assert name not in bpy.data.actions, 'Refuse overwrite Action'
 N=entry['period_frames'];a=ready.copy();a.name=name;a.use_fake_user=True
 for fc in a.fcurves:
  v=fc.evaluate(1)
  fc.keyframe_points.clear()
  for m in list(fc.modifiers):fc.modifiers.remove(m)
  if not fc.data_path.startswith(rootprefix):
   for frame in (1,N+1):
    k=fc.keyframe_points.insert(frame,v);k.interpolation='LINEAR'
  fc.lock=False
  if fc.group:fc.group.lock=False
 r.animation_data.action=None
 keys=[]
 for row in entry['keyframes']:
  p=row['params'];rot=Euler((p[2],p[3],0),'YXZ').to_matrix().to_4x4()
  # scipy intrinsic XY equals Rx(pitch) @ Ry(yaw); explicit product removes convention ambiguity.
  rot=Matrix.Rotation(p[2],4,'X')@Matrix.Rotation(p[3],4,'Y')@Matrix.Rotation(p[4] if len(p)>4 else 0,4,'Z')
  T=C@Matrix.Translation(pivot+Vector((p[0],p[1],p[5] if len(p)>5 else 0)))@rot@Matrix.Translation(-pivot)@Ci
  root.matrix=Ri@T@root_world
  keys.append({'frame':row['frame'],'location':list(root.location),'rotation_euler':list(root.rotation_euler)})
 assert len(keys)==N+1
 keys[-1]={'frame':N+1,'location':keys[0]['location'][:],'rotation_euler':keys[0]['rotation_euler'][:]}
 for prop in ('location','rotation_euler'):
  for idx in range(3):
   path=rootprefix+prop;fc=next((f for f in a.fcurves if f.data_path==path and f.array_index==idx),None)
   if fc is None:fc=a.fcurves.new(path,index=idx,action_group='Directional root pose')
   vals=[k[prop][idx] for k in keys];tangents=[(vals[(i+1)%N]-vals[(i-1)%N])/2 for i in range(N)];tangents.append(tangents[0])
   for i,k in enumerate(keys):
    frame=k['frame'];v=vals[i];point=fc.keyframe_points.insert(frame,v);point.interpolation='BEZIER';point.handle_left_type='FREE';point.handle_right_type='FREE';point.handle_left=(frame-1/3,v-tangents[i]/3);point.handle_right=(frame+1/3,v+tangents[i]/3)
   fc.modifiers.new('CYCLES')
 a['reference_id']=entry['reference_id'];a['reference_frame_start']=entry['source_range_half_open'][0];a['reference_frame_end_exclusive']=entry['source_range_half_open'][1];a['authoring_fps']=60;a['loop_period_frames']=N;a['presentation']='absolute native rig pose';a['acceptance_status']='WIP; independent visual and runtime review required';a['motion_reference']='R5 longitudinal motion-only feedback revision; native HK416 ready carry preserved';a['revision_notes']=entry['revision_notes'];a['revision_of']=entry['revision_of']
 created.append(name);allkeys[name]=keys
# Restore source state exactly. Source Actions/NLA are not rewritten or rearranged.
for p in r.pose.bones:
 saved=raw_pose[p.name];p.rotation_mode=saved['rotation_mode']
 for field in ['location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale']:setattr(p,field,saved[field])
 for key,value in saved['properties'].items():
  current=p[key]
  if hasattr(current,'to_list'):
   for i,v in enumerate(value):current[i]=v
  elif isinstance(value,(str,int,float,bool)):p[key]=value
  else:assert idcopy(current)==value, 'Unexpected changed complex custom property'

for oname,(action,use_nla,tracks) in ad_state.items():
 ad=bpy.data.objects[oname].animation_data;ad.action=action;ad.use_nla=use_nla
 for track,mute,solo in tracks:track.mute=mute;track.is_solo=solo
s.frame_set(orig_frame,subframe=orig_sub);bpy.context.view_layer.update();after=snapshot(bpy)
assert {n:after['actions'][n] for n in before['actions']}==before['actions']
assert after['nla']==before['nla'];assert after['drivers']==before['drivers'];assert after['packed_images']==before['packed_images']
assert set(after['actions'])-set(before['actions'])==set(created)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT),compress=True)
assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
(OUT.parent/(('' if OUT.stem=='halcyon_hip_directional_r1' else OUT.stem+'_')+'authored_root_keys.json')).write_text(json.dumps({'schema':'rust-duty-directional-authored-root-keys/v1','blender':'4.3.2','design_sha256':hashlib.sha256(design_path.read_bytes()).hexdigest(),'actions':allkeys},indent=2)+'\n')
(OUT.parent/(('' if OUT.stem=='halcyon_hip_directional_r1' else OUT.stem+'_')+'authoring_preservation.json')).write_text(json.dumps({'source_sha256':source_hash,'candidate_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'preserved_actions':len(before['actions']),'preserved_nla_tracks':sum(len(x['tracks']) for x in before['nla'].values()),'preserved_drivers':sum(len(x) for x in before['drivers'].values()),'created_actions':created,'original_nla_active_driver_texture_snapshots_equal':True},indent=2)+'\n')
print('AUTHORED',str(OUT),created)
