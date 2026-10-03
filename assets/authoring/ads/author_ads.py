"""Blender 4.3.2: add independent sight-aligned ADS Actions to a preserved source copy.

Run from repo root:
  blender -b --factory-startup --disable-autoexec \
    assets/authoring/locomotion/locomotion.blend --python-exit-code 1 \
    --python assets/authoring/ads/author_ads.py

This only saves assets/authoring/ads/ads.blend; the locomotion source is read-only.
Sight dimensions are artistic mesh-local coordinates, not weapon specifications.
"""
import bpy, hashlib, json, math, sys
from pathlib import Path
import numpy as np
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view
P=Path(__file__).resolve().parent;sys.dont_write_bytecode=True;sys.path.insert(0,str(P))
from source_integrity import snapshot,action_fingerprint,digest
assert bpy.app.version_string=='4.3.2'
S=bpy.context.scene;A=bpy.data.objects['Arms'];R=A.pose.bones['righthand_prop'];W=bpy.data.objects['hk416_weapon'];CAM=bpy.data.objects['RD First Person Review'];C=CAM.matrix_world.copy()
INPUT=Path(bpy.data.filepath);CANONICAL=P.parent/'locomotion'/'locomotion.blend';assert INPUT.resolve()==CANONICAL.resolve()
source_sha=hashlib.sha256(INPUT.read_bytes()).hexdigest();before=snapshot(bpy)
assert len(before['actions'])==62
SKIN=['Actual arms mesh 0','Actual arms mesh 1','Actual arms mesh 2'];ACTORS=['hk416_weapon','hk416_magazine']
BASE='RD_00_Supplied_Base_Guarded_Recovered';READY='RD_Locomotion_Normal_Entry_4419_4434_WIP2'

def immutable_geometry():
 return {'meshes':{o.name:digest({'vertices':[list(v.co) for v in o.data.vertices],'polygons':[list(f.vertices) for f in o.data.polygons],'weights':[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices],'vertex_groups':[(g.name,g.index) for g in o.vertex_groups],'materials':[m.name if m else None for m in o.data.materials],'uv':{u.name:[list(x.uv) for x in u.data] for u in o.data.uv_layers},'parent':o.parent.name if o.parent else None,'parent_type':o.parent_type,'parent_bone':o.parent_bone,'matrix_parent_inverse':[list(r) for r in o.matrix_parent_inverse]}) for o in bpy.data.objects if o.type=='MESH'},'bones':digest([(b.name,b.parent.name if b.parent else None,b.use_deform,[list(r) for r in b.matrix_local]) for b in A.data.bones]),'armature_object_matrix':[list(r) for r in A.matrix_world],'camera':{'world':[list(r) for r in C],'lens':CAM.data.lens,'sensor_width':CAM.data.sensor_width,'sensor_height':CAM.data.sensor_height,'sensor_fit':CAM.data.sensor_fit,'shift_x':CAM.data.shift_x,'shift_y':CAM.data.shift_y,'clip_start':CAM.data.clip_start,'clip_end':CAM.data.clip_end}}
geometry_before=immutable_geometry()
original_tracks=before['nla']['Arms']['tracks']
for t in A.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions[BASE];S.frame_set(1);bpy.context.view_layer.update();base_basis={p.name:p.matrix_basis.copy() for p in A.pose.bones}
A.animation_data.action=bpy.data.actions[READY];S.frame_set(1);bpy.context.view_layer.update()
READY_M=C.inverted()@W.matrix_world;WR=(A.matrix_world@R.matrix).inverted()@W.matrix_world
# Centers traced from the unchanged source mesh: front circular aperture and rear
# sight's center bridge. The two share an authored sight-axis height and centerline.
REAR=Vector((-.000062134116888,.158475101,.0469331592))
FRONT=Vector((-.000062134116888,.158475116,-.313264295))
LANDMARKS=json.loads((P/'sight_landmarks.json').read_text())['landmarks']
for name,expected in [('rear',REAR),('front',FRONT)]:
 pts=[W.data.vertices[i].co for i in LANDMARKS[name]['vertex_indices']]
 measured=Vector([(min(v[k] for v in pts)+max(v[k] for v in pts))/2 for k in range(3)])
 assert (measured-expected).length<1e-7,('Source sight landmark changed',name)

# The source has a <=15nm height discrepancy between mesh landmark centers. A
# tiny proper X rotation makes the actual sight landmarks exactly coaxial.
a=math.atan((FRONT.y-REAR.y)/(FRONT.z-REAR.z))
AIM=Matrix.Rotation(a,4,'X');AIM.translation=Vector((0.,0.,-.280+REAR.z))-AIM.to_3x3()@REAR
assert abs((AIM@FRONT).x)<1e-9 and abs((AIM@FRONT).y)<1e-7
ready_root_location=R.location.copy();ready_root_rotation=R.rotation_euler.copy()
A.animation_data.action=None

def motion(t):
 t=max(0,min(1,t));s=t*t*t*(10+t*(-15+6*t))
 rot=READY_M.to_quaternion().slerp(AIM.to_quaternion(),s)
 out=rot.to_matrix().to_4x4();out.translation=READY_M.translation.lerp(AIM.translation,s)
 # A slight authored lift through the center draw; zero endpoint velocity.
 out.translation.y+=.0035*math.sin(math.pi*s)
 return out

def root_channels(t,compat):
 R.matrix=A.matrix_world.inverted()@C@motion(t)@WR.inverted();e=R.rotation_euler.copy();e.make_compatible(compat)
 return R.location.copy(),e
keys=[];previous=ready_root_rotation.copy()
for i in range(16):
 t=i/15;loc,e=root_channels(t,previous);lo,eo=root_channels(t-1e-4,e);hi,eh=root_channels(t+1e-4,e)
 dl=(hi-lo)/.0002/15;de=Vector([(eh[k]-eo[k])/.0002/15 for k in range(3)])
 if i==0:loc=ready_root_location.copy();e=ready_root_rotation.copy()
 if i in (0,15):dl=Vector((0,0,0));de=Vector((0,0,0))
 keys.append({'frame':1+i,'location':list(loc),'rotation_euler':list(e),'location_derivative':list(dl),'rotation_derivative':list(de)});previous=e


def make_action(name,end,rows):
 act=bpy.data.actions[READY].copy();act.name=name;act.use_fake_user=True
 for fc in act.fcurves:
  v=fc.evaluate(1);fc.keyframe_points.clear()
  for m in list(fc.modifiers):fc.modifiers.remove(m)
  for f in (1,end):k=fc.keyframe_points.insert(f,v);k.interpolation='LINEAR'
 for fc in list(act.fcurves):
  if fc.data_path in ['pose.bones["righthand_prop"].location','pose.bones["righthand_prop"].rotation_euler']:act.fcurves.remove(fc)
 for prop,der in [('location','location_derivative'),('rotation_euler','rotation_derivative')]:
  for axis in range(3):
   fc=act.fcurves.new('pose.bones["righthand_prop"].'+prop,index=axis,action_group=name+' | weapon-root');fc.lock=False;fc.group.lock=False
   for row in rows:
    f=row['frame'];v=row[prop][axis];dv=row[der][axis];k=fc.keyframe_points.insert(f,v,options={'FAST'});k.interpolation='BEZIER';k.handle_left_type='FREE';k.handle_right_type='FREE';k.handle_left=(f-1/3,v-dv/3);k.handle_right=(f+1/3,v+dv/3)
   fc.update()
 act['authored_revision']=1;act['source_fps']=60;act['animation_owner']='Blender weapon-root control, evaluated arm IK and weapon-follow constraints';act['camera_unchanged']=True;act['sight_alignment']='Existing mesh rear and front aperture centers at optical center';act['contact_limit']='Attachment transforms and wrist guards verified; hidden finger surface contact is inherited, not certified'
 return act
entry=make_action('ads_entry_r1',16,keys)
exit_keys=[]
for k in reversed(keys):
 q={p:(list(v) if isinstance(v,list) else v) for p,v in k.items()};q['frame']=17-k['frame'];q['location_derivative']=[-x for x in q['location_derivative']];q['rotation_derivative']=[-x for x in q['rotation_derivative']];exit_keys.append(q)
exit_action=make_action('ads_exit_r1',16,exit_keys)
hold_keys=[dict(keys[-1],frame=f) for f in (1,61)];hold=make_action('ads_hold_r1',61,hold_keys)
entry['clip_role']='Ready to aimed, nonlooping, 0.25 seconds';exit_action['clip_role']='Exact authored reverse to ready, nonlooping, 0.25 seconds';hold['clip_role']='Stable fully aimed hold, looping 1 second';hold['static_hold']=True;hold['loop_period_seconds']=1.
S.render.fps=60;S.render.fps_base=1

def select(act,frame=1):
 A.animation_data.action=None
 for p in A.pose.bones:p.matrix_basis=base_basis[p.name].copy()
 A.animation_data.action=bpy.data.actions[BASE];S.frame_set(1);bpy.context.view_layer.update();A.animation_data.action=act
 i=math.floor(frame);S.frame_set(i,subframe=frame-i);bpy.context.view_layer.update()

def pose_arrays():
 dg=bpy.context.evaluated_depsgraph_get();dg.update();ar=A.evaluated_get(dg)
 out={'bones':np.asarray([ar.matrix_world@p.matrix for p in ar.pose.bones if p.bone.use_deform],dtype=np.float32),'actors':np.asarray([bpy.data.objects[n].evaluated_get(dg).matrix_world for n in ACTORS],dtype=np.float32)}
 for n in SKIN:
  o=bpy.data.objects[n].evaluated_get(dg);m=o.to_mesh();v=np.asarray([o.matrix_world@x.co for x in m.vertices],dtype=np.float32);out[n]=v;o.to_mesh_clear()
 return out
select(bpy.data.actions[READY]);ready_pose=pose_arrays()
measurements=[];all_hands=[];max_hold_error_px=0.;max_attachment_mm=0.;attachment_ref={};max_guard_deg=0.;endpoints={}
for act,end in [(entry,16),(hold,61),(exit_action,16)]:
 rows=[];last=None;max_step=0.
 for i in range(int((end-1)*8)+1):
  f=1+i/8;select(act,f);wm=W.matrix_world.copy();row={'frame':f,'time':(f-1)/60,'hands':{},'sight_px':{}}
  for side in ['l','r']:
   p=A.pose.bones;hand=A.matrix_world@p['hand_'+side].matrix;ctrl=A.matrix_world@p['righthand_prop_'+('left' if side=='l' else 'right')+'hand'].matrix;raw=[math.degrees(x) for x in (p['MCH_attach_forearm_'+side].matrix.inverted()@p['MCH_attach_goal_'+side].matrix).to_euler('XYZ')];limits=json.loads(A['wrist_guard_'+side])['absolute_limits_deg'];margin=min(min(v-lo,hi-v) for v,(lo,hi) in zip(raw,limits));attachment=wm.inverted()@hand
   attachment_ref.setdefault(side,attachment.copy());drift=(attachment.translation-attachment_ref[side].translation).length*1000;max_attachment_mm=max(max_attachment_mm,drift)
   h={'wrist_solve_error_mm':(hand.translation-ctrl.translation).length*1000,'guard_error_degrees':math.degrees(p['MCH_hand_guarded_'+side].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_'+side].matrix.to_quaternion()).angle),'raw_guard_margin_degrees':margin,'reach_margin_mm':(p['MCH_upperarm_'+side].bone.length+p['MCH_lowerarm_'+side].bone.length-(ctrl.translation-A.matrix_world@p['MCH_upperarm_'+side].head).length)*1000,'weapon_follow':float(p['righthand_prop_'+('left' if side=='l' else 'right')+'hand']['weapon_follow']),'hand_in_weapon_translation':list(attachment.translation),'hand_in_weapon_quaternion':list(attachment.to_quaternion())};row['hands'][side]=h;all_hands.append(h)
  for n,v in [('rear',REAR),('front',FRONT)]:
   q=world_to_camera_view(S,CAM,wm@v);row['sight_px'][n]=[q.x*1280,(1-q.y)*720]
   if act==hold:max_hold_error_px=max(max_hold_error_px,math.hypot(q.x*1280-640,(1-q.y)*720-360))
  if last:max_step=max(max_step,(wm.translation-last.translation).length*1000)
  last=wm;rows.append(row)
 measurements.append({'action':act.name,'max_weapon_step_mm_480hz':max_step,'samples':rows})
 select(act,1);endpoints[act.name+'__start']=pose_arrays();select(act,end);endpoints[act.name+'__end']=pose_arrays()

def delta(a,b):
 return {n:float(np.max(np.abs(a[n]-b[n]))) for n in a}
continuity={'ready_entry':delta(ready_pose,endpoints['ads_entry_r1__start']),'entry_hold':delta(endpoints['ads_entry_r1__end'],endpoints['ads_hold_r1__start']),'hold_loop':delta(endpoints['ads_hold_r1__start'],endpoints['ads_hold_r1__end']),'hold_exit':delta(endpoints['ads_hold_r1__start'],endpoints['ads_exit_r1__start']),'exit_ready':delta(endpoints['ads_exit_r1__end'],ready_pose)}
summary={'sample_hz':480,'sample_count':sum(len(r['samples']) for r in measurements),'max_wrist_solve_error_mm':max(h['wrist_solve_error_mm'] for h in all_hands),'max_guard_error_degrees':max(h['guard_error_degrees'] for h in all_hands),'min_raw_guard_margin_degrees':min(h['raw_guard_margin_degrees'] for h in all_hands),'min_reach_margin_mm':min(h['reach_margin_mm'] for h in all_hands),'max_hand_in_weapon_translation_drift_mm':max_attachment_mm,'all_weapon_follow_one':all(h['weapon_follow']==1 for h in all_hands),'max_hold_sight_optical_center_error_px_1280x720':max_hold_error_px,'endpoint_max_component_errors':continuity,'hold_is_exactly_static':all(v==0 for v in continuity['hold_loop'].values()),'claims':'Native source rig/deformed-pose and attachment verification. Hidden finger contact and runtime visuals require independent review.'}
assert summary['max_wrist_solve_error_mm']<.05 and summary['max_guard_error_degrees']<.08 and summary['min_raw_guard_margin_degrees']>0 and summary['min_reach_margin_mm']>0
assert max(v for d in continuity.values() for v in d.values())<1e-6
assert max_hold_error_px<.001 and summary['hold_is_exactly_static'] and summary['all_weapon_follow_one']
assert all(action_fingerprint(bpy.data.actions[n])==h for n,h in before['actions'].items())
assert snapshot(bpy)['nla']['Arms']['tracks']==original_tracks
assert immutable_geometry()==geometry_before
for act,end in [(entry,16),(hold,61),(exit_action,16)]:
 t=A.animation_data.nla_tracks.new();t.name=act.name;st=t.strips.new(act.name,1,act);st.name=act.name;st.action_frame_start=1;st.action_frame_end=end;st.frame_start=1;st.frame_end=end;st.blend_type='REPLACE';st.extrapolation='NOTHING';st.use_auto_blend=False;t.mute=True
select(hold,1);S.frame_start=1;S.frame_end=61;S.camera=CAM
assert snapshot(bpy)['drivers']==before['drivers'];assert snapshot(bpy)['packed_images']==before['packed_images'];assert S.camera.matrix_world==C
assert all(fc.driver.is_valid for o in bpy.data.objects if o.animation_data for fc in o.animation_data.drivers)
# Packed texture bytes already live in the source. No source script is embedded or executed.
bpy.ops.wm.save_as_mainfile(filepath=str(P/'ads.blend'))
after=snapshot(bpy);outsha=hashlib.sha256((P/'ads.blend').read_bytes()).hexdigest()
(P/'source_integrity.json').write_text(json.dumps({'portable_source_sha256':outsha,'preserved':after},indent=2)+'\n')
(P/'preservation.json').write_text(json.dumps({'baseline_file':'../locomotion/locomotion.blend','baseline_sha256':source_sha,'ads_source_sha256':outsha,'prior_action_count':62,'prior_actions_unchanged':True,'prior_nla_tracks_unchanged':True,'prior_nla_track_count':len(original_tracks),'drivers_unchanged':True,'packed_images_unchanged':True,'geometry_weights_rest_bones_object_bindings_camera_unchanged':True,'immutable_geometry':geometry_before,'prior_snapshot':before,'new_actions':['ads_entry_r1','ads_hold_r1','ads_exit_r1'],'final_action_count':len(after['actions'])},indent=2)+'\n')
(P/'validation.json').write_text(json.dumps({'summary':summary,'sweeps':measurements},indent=2)+'\n')
(P/'sight_alignment.json').write_text(json.dumps({'coordinate_system':'Unmodified hk416_weapon mesh-local artistic coordinates; camera local right/up/back','rear_landmark_local':list(REAR),'front_landmark_local':list(FRONT),'near_post_tip_local':list(REAR),'far_aperture_center_local':list(FRONT),'legacy_landmark_aliases':{'rear_landmark_local':'near_post_tip_local','front_landmark_local':'far_aperture_center_local'},'landmark_method':'The top-edge midpoint of the existing near central post and the center of the existing far circular aperture, each verified against original source mesh vertex indices. The supplied mesh has no far central post. Legacy front/rear keys are depth aliases only.','camera_world':[list(r) for r in C],'horizontal_fov_degrees':math.degrees(CAM.data.angle_x),'camera_unchanged':True,'runtime_viewmodel_fov_default_degrees':76,'runtime_mapping':'Blender (x,y,z) -> FBX (x,z,-y) -> game (-x,z,y), with camera at origin and game -Z forward','ready_weapon_camera':[list(r) for r in READY_M],'aimed_weapon_camera':[list(r) for r in AIM],'max_hold_optical_center_error_pixels_1280x720':max_hold_error_px,'source_geometry_sha256':geometry_before['meshes']['hk416_weapon']},indent=2)+'\n')
(P/'design.json').write_text(json.dumps({'entry_keys':keys,'exit_keys':exit_keys,'hold_keys':hold_keys,'entry_seconds':.25,'hold_seconds':1,'exit_seconds':.25,'hold_motion':'Exactly static to preserve stable sight line and arbitrary-release continuity; no procedural breath','gameplay_timing':'Simulation settings remain authoritative for readiness and accuracy. Runtime owner determines presentation phase mapping; no settings edited. Default .220/.160 s; M4 candidate .250/.250 s.'},indent=2)+'\n')
config={'schema':'rust-duty-ads-authoring-export/v1','blender_version':'4.3.2','source_file':'ads.blend','source_fps':60,'bake_hz':480,'armature':'Arms','skin_objects':SKIN,'rigid_actors':ACTORS,'excluded_rigid_actor':'hk416_magazine_outgoing','deform_bone_count':72,'source_take_count':3,'authored_gameplay_take_count':3,'runtime_gameplay_clip_count':3,'normal_ready':{'name':'normal_ready','action':READY,'frame_start':1,'frame_end':2,'freeze_at_source_frame':1},'source_takes':[{'name':a.name,'action':a.name,'frame_start':1,'frame_end':e,'loop':loop,'role':'gameplay'} for a,e,loop in [(entry,16,False),(hold,61,True),(exit_action,16,False)]],'conversion_groups':[['ads_entry_r1','ads_hold_r1','ads_exit_r1']],'runtime_derivation':{'none':True}}
(P/'export_config.json').write_text(json.dumps(config,indent=2)+'\n')
print('ADS_VALIDATION',json.dumps(summary),flush=True)
assert hashlib.sha256(CANONICAL.read_bytes()).hexdigest()==source_sha
