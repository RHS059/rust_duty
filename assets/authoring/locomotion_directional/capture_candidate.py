import bpy,sys,json,math,csv,hashlib
import numpy as np
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
args=sys.argv[sys.argv.index('--')+1:];OUT=Path(args[0]);OUT.mkdir(parents=True,exist_ok=True)
render='--render' in args;video='--video' in args
s=bpy.context.scene;r=bpy.data.objects['Arms'];cam=s.camera;s.render.resolution_x=1280;s.render.resolution_y=720;s.render.resolution_percentage=100;s.render.fps=60;s.render.fps_base=1
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
r.animation_data.use_nla=False;base=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];r.animation_data.action=base;s.frame_set(1);bpy.context.view_layer.update();basis={p.name:p.matrix_basis.copy() for p in r.pose.bones}
names=sorted(a.name for a in bpy.data.actions if a.name.startswith('hip_') and a.name.endswith('_r1'))
summary={'schema':'rust-duty-directional-native-capture/v1','candidate_sha256':hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),'blender':bpy.app.version_string,'fps':60,'sweep_hz':480,'resolution':[1280,720],'camera':cam.name,'horizontal_fov_degrees':math.degrees(cam.data.angle_x),'camera_animated':False,'landmark_definition':{'muzzle_tip':{'object':'hk416_weapon','local_point':[-.000062,.090545,-.411509]},'receiver_center':{'object':'hk416_weapon','local_point':[.020,.075,.020]},'support_wrist':{'bone':'hand_l','point':'head'},'firing_wrist':{'bone':'hand_r','point':'head'}},'actions':{}}
cuff_binding={'object':'Actual arms mesh 0','vertex_indices':[5681,5679,5666],'barycentric_weights':[0.38801232981670086,0.5282059672418871,0.08378170294141207],'baseline_pixel':[663,491]}
summary['landmark_definition']['support_cuff_surface']=cuff_binding
rows=[]
for name in names:
 a=bpy.data.actions[name];N=int(a['loop_period_frames']);r.animation_data.action=None
 for p in r.pose.bones:p.matrix_basis=basis[p.name].copy()
 r.animation_data.action=base;s.frame_set(1);bpy.context.view_layer.update();r.animation_data.action=a
 wrist_errors=[];guard_errors=[];drifts=[];invalid=[];root_mats=[];actor_mats=[];hand_mats=[]
 first_rel=None
 for k in range(N*8+1):
  frame=1+k/8;i=math.floor(frame);s.frame_set(i,subframe=frame-i);bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();deps.update();er=r.evaluated_get(deps);ew=bpy.data.objects['hk416_weapon'].evaluated_get(deps);root=er.matrix_world@er.pose.bones['righthand_prop'].matrix
  rel=[root.inverted()@er.matrix_world@er.pose.bones['hand_'+side].matrix for side in ['l','r']]
  if first_rel is None:first_rel=[x.copy() for x in rel]
  drifts.append([max(abs(rel[z][i][j]-first_rel[z][i][j]) for i in range(4) for j in range(4)) for z in range(2)])
  wrist_errors.append([(er.pose.bones['hand_'+side].matrix.translation-er.pose.bones['righthand_prop_'+('left' if side=='l' else 'right')+'hand'].matrix.translation).length for side in ['l','r']])
  guard_errors.append([math.degrees(er.pose.bones['MCH_hand_guarded_'+side].matrix.to_quaternion().rotation_difference(er.pose.bones['MCH_attach_goal_'+side].matrix.to_quaternion()).angle) for side in ['l','r']])
  if k in (0,N*8):
   root_mats.append(np.array(root));actor_mats.append(np.array(ew.matrix_world));hand_mats.append(np.array([er.pose.bones['hand_'+side].matrix for side in ['l','r']]))
  if k%8==0:
   pts={'muzzle_tip':ew.matrix_world@Vector((-.000062,.090545,-.411509)),'receiver_center':ew.matrix_world@Vector((.020,.075,.020)),'support_wrist':er.matrix_world@er.pose.bones['hand_l'].matrix.translation,'firing_wrist':er.matrix_world@er.pose.bones['hand_r'].matrix.translation}
   eo=bpy.data.objects[cuff_binding['object']].evaluated_get(deps);me=eo.to_mesh();cuff_local=sum((me.vertices[idx].co*w for idx,w in zip(cuff_binding['vertex_indices'],cuff_binding['barycentric_weights'])),Vector((0,0,0)));pts['support_cuff_surface']=eo.matrix_world@cuff_local;eo.to_mesh_clear()
   row={'action':name,'frame':int(frame),'time_s':(frame-1)/60}
   for pn,p in pts.items():
    q=world_to_camera_view(s,cam,p);row[pn+'_x']=q.x*1280;row[pn+'_y']=(1-q.y)*720;row[pn+'_depth']=q.z;row[pn+'_in_frame']=bool(0<=q.x<=1 and 0<=q.y<=1 and q.z>0)
   rows.append(row)
  assert all(abs(float(r.pose.bones[b]['weapon_follow'])-1)<1e-7 for b in ['righthand_prop_lefthand','righthand_prop_righthand','lefthand_prop'])
 invalid=[o.name+':'+fc.data_path for o in bpy.data.objects if o.animation_data for fc in o.animation_data.drivers if not fc.driver.is_valid]
 summary['actions'][name]={'frame_range':[1,N+1],'period_seconds':N/60,'unique_native_frames':N,'samples_480hz':N*8+1,'max_wrist_error_m':np.max(wrist_errors,axis=0).tolist(),'max_guard_error_degrees':np.max(guard_errors,axis=0).tolist(),'max_hand_relative_root_matrix_drift':np.max(drifts,axis=0).tolist(),'loop_endpoint_root_matrix_error':float(abs(root_mats[-1]-root_mats[0]).max()),'loop_endpoint_actor_matrix_error':float(abs(actor_mats[-1]-actor_mats[0]).max()),'loop_endpoint_hand_matrix_error':float(abs(hand_mats[-1]-hand_mats[0]).max()),'invalid_drivers':invalid}
 print(name,json.dumps(summary['actions'][name]),flush=True)
 if render:
  d=OUT/name;d.mkdir(exist_ok=True);frames=list(range(1,N+2)) if video else sorted(set(list(range(1,N+1,3))+[N+1]))
  s.render.engine='CYCLES';s.cycles.samples=8 if not video else 4;s.cycles.use_denoising=False;s.render.image_settings.file_format='PNG'
  for frame in frames:
   s.frame_set(frame);bpy.context.view_layer.update();s.render.filepath=str(d/f'f{frame:03d}.png');bpy.ops.render.render(write_still=True)
with open(OUT/'candidate_tracks_60fps.csv','w') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
(OUT/'native_validation.json').write_text(json.dumps(summary,indent=2)+'\n')
print('CAPTURED',OUT,flush=True)
