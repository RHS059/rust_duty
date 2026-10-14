"""Author isolated prone-entry r6 pair. Run only on the pinned Blender 4.3.2 r5.
No render, source overwrite, runtime activation, or source-asset publication.
"""
import bpy,sys,json,hashlib,math
import numpy as np
from pathlib import Path
from mathutils import Matrix,Vector
P=Path(__file__).resolve().parent
sys.path.insert(0,str(P))
from source_integrity import snapshot,action_fingerprint
from validate_source_structure import extra_snapshot
from motion_design import parameters,validate_config
c=json.loads((P/'correction_design.json').read_text());validate_config(c)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source=Path(bpy.data.filepath);out=P/'halcyon_prone_crawl_r6.blend'
assert bpy.app.version_string=='4.3.2'
assert sha(source)==c['source_sha256']
assert len(bpy.data.actions)==c['prior_action_count']
assert c['action'] not in bpy.data.actions and c['camera_action'] not in bpy.data.actions
assert not out.exists() and out!=source
before=snapshot(bpy);extra=extra_snapshot();s=bpy.context.scene;r=bpy.data.objects[c['armature_object']];cam=bpy.data.objects[c['camera_object']]
assert cam.animation_data is None and cam.parent is None
frame_state=(s.frame_current,s.frame_subframe)
scene_state={k:getattr(s,k) for k in ('frame_start','frame_end','frame_step')}
scene_state.update({'fps':s.render.fps,'fps_base':s.render.fps_base,'camera':s.camera.name})
object_defaults={o.name:{k:list(getattr(o,k)) for k in ('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')} for o in bpy.data.objects}
pose_defaults={b.name:{k:list(getattr(b,k)) for k in ('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')} for b in r.pose.bones}
adstate={o.name:(o.animation_data.action,o.animation_data.use_nla,[(t,t.mute,t.is_solo) for t in o.animation_data.nla_tracks]) for o in bpy.data.objects if o.animation_data}
for o in bpy.data.objects:
 if o.animation_data:
  o.animation_data.use_nla=False
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
base=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];old=bpy.data.actions[c['prior_action']]
r.animation_data.action=base;s.frame_set(1);bpy.context.view_layer.update()
R=r.matrix_world.copy();Ri=R.inverted();C=cam.matrix_world.copy();Ci=C.inverted()
root=r.pose.bones['righthand_prop'];new=old.copy();new.name=c['action'];new.use_fake_user=True
ca=bpy.data.actions.new(c['camera_action']);ca.use_fake_user=True
r.animation_data.action=old;s.frame_set(1);bpy.context.view_layer.update()
q=Vector((.08323424182818288,.005083007134545519,-.26023809868713904))
pivot_local=(R@root.matrix).inverted()@C@q
rows=[];early_old=[]
for i in range(545):
 f=1+i/8;s.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
 if f<=11:early_old.append(np.array([list(map(list,b.matrix)) for b in r.pose.bones]))
 p=parameters(c,f);W=R@root.matrix.copy();pivot=Ci@W@pivot_local
 # Camera follows real world-Z descent. Its lens/shift/projection never changes.
 CR=Matrix.Rotation(math.radians(p['camera_roll_deg']),4,'Z')@Matrix.Rotation(math.radians(-p['camera_pitch_down_deg']),4,'X')
 C6=Matrix.Translation((0,0,-p['camera_depth_m']))@C@CR
 D=C6@Ci;R6=D@R
 # Weapon changes are evaluated in the fixed original camera basis. Co-motion
 # later transports the already-corrected pose, leaving the environment fixed.
 rot=Matrix.Rotation(math.radians(p['weapon_additional_roll_deg']),4,'Z')@Matrix.Rotation(math.radians(-p['weapon_pitch_down_deg']),4,'X')
 z=pivot.z+p['weapon_depth_delta_m'];u=640+819.1626469882023*pivot.x/-pivot.z-p['weapon_left_pixels'];v=360-819.1626469882023*pivot.y/-pivot.z+p['weapon_down_pixels']
 target=Vector(((u-640)*-z/819.1626469882023,(360-v)*-z/819.1626469882023,z))
 T=C@Matrix.Translation(target)@rot@Matrix.Translation(-pivot)@Ci
 if f>11:root.matrix=Ri@T@W
 rows.append({'frame':f,'parameters':p,'location':list(root.location),'rotation_euler':list(root.rotation_euler),
              'camera_location':list(C6.translation),'camera_rotation_euler':list(C6.to_euler(cam.rotation_mode)),
              'rig_location':list(R6.translation),'rig_rotation_euler':list(R6.to_euler(r.rotation_mode)),
              'optic_target_pixels':[u,v], 'camera_world':list(map(list,C6)), 'rig_world':list(map(list,R6))})

def replace_after_11(action,path,axis,values,group):
 fc=next((x for x in action.fcurves if x.data_path==path and x.array_index==axis),None)
 if fc is None:fc=action.fcurves.new(path,index=axis,action_group=group)
 early=[(list(k.co),list(k.handle_left),list(k.handle_right),k.interpolation,k.handle_left_type,k.handle_right_type) for k in fc.keyframe_points if k.co.x<=11]
 for k in range(len(fc.keyframe_points)-1,-1,-1):
  if fc.keyframe_points[k].co.x>11:fc.keyframe_points.remove(fc.keyframe_points[k],fast=True)
 for row,val in zip(rows,values):
  if row['frame']<=11 and early:continue
  k=fc.keyframe_points.insert(row['frame'],val,options={'FAST'});k.interpolation='LINEAR'
 fc.update()
 # Original left-side key coordinates and tangents survive exactly.
 for vals in early:
  k=next(x for x in fc.keyframe_points if x.co.x==vals[0][0]);k.handle_left_type='FREE';k.handle_right_type='FREE';k.co=vals[0];k.handle_left=vals[1];k.handle_right=vals[2];k.interpolation=vals[3]
 if early:
  k=next((x for x in fc.keyframe_points if x.co.x==11),None)
  if k is None:
   k=fc.keyframe_points.insert(11,values[80],options={'FAST'})
  k.interpolation='LINEAR'
 fc.update()
for prop in ('location','rotation_euler'):
 for axis in range(3):replace_after_11(new,f'pose.bones["righthand_prop"].{prop}',axis,[row[prop][axis] for row in rows],'righthand_prop')
# Restore source rig state while solving contact; pair co-motion is rigid and is
# applied only after bone-local correction, so it cannot hide reach error.
r.animation_data.action=new;shoulders={side:[] for side in ('l','r')}
for row in rows:
 f=row['frame'];s.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
 for side in ('l','r'):
  shoulder=r.pose.bones['clavicle_'+side];target=r.pose.bones['righthand_prop_'+('left' if side=='l' else 'right')+'hand'];hand=r.pose.bones['hand_'+side]
  for iteration in range(30):
   error=target.matrix.translation-hand.matrix.translation
   if f<=11 or error.length<.000003:break
   m=shoulder.matrix.copy();m.translation+=error;shoulder.matrix=m;bpy.context.view_layer.update()
  shoulders[side].append(list(shoulder.location))
for side,vals in shoulders.items():
 for axis in range(3):replace_after_11(new,f'pose.bones["clavicle_{side}"].location',axis,[v[axis] for v in vals],'clavicle_'+side)
for action,prefix,group in ((new,'rig_','r6_world_comotion'),(ca,'camera_','r6_camera_motion')):
 for prop in ('location','rotation_euler'):
  for axis in range(3):
   fc=action.fcurves.new(prop,index=axis,action_group=group)
   for row in rows:
    k=fc.keyframe_points.insert(row['frame'],row[prefix+prop][axis],options={'FAST'});k.interpolation='LINEAR'
   fc.update()
new['acceptance_status']='WIP r6; genuine paired Eevee capture and Elara review pending'
new['revision_reason']='Reviewed r5 64/Fail: deepen existing drop beats, inward trough roll, low-center weapon, grounded recovery'
new['camera_motion']=ca.name;new['root_motion']=True
new['animated_control']='righthand_prop, clavicle_l/r location; armature-object rigid camera co-motion'
new['motion_origin']='R5 camera-relative foreground correction plus new isolated paired world camera Action; not recovered COD 3D motion'
new['runtime_id']='prone_crawl_enter';new['runtime_integration_status']='not integrated; camera pair requires explicit consumer binding'
new['paired_camera_object']=cam.name;new['protected_frames']='1-11'
ca['paired_rig_action']=new.name;ca['camera_object']=cam.name;ca['runtime_integration_status']='authoring-only, not integrated'
# Fresh evaluation verifies the COMPLETE pair and the protected early interval.
cam.animation_data_create();cam.animation_data.action=ca
contacts=[];early_new=[];matrices=[]
for row in rows:
 f=row['frame'];s.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
 if f<=11:early_new.append(np.array([list(map(list,b.matrix)) for b in r.pose.bones]))
 matrices.append(np.array([list(map(list,b.matrix)) for b in r.pose.bones]))
 errors={side:(r.pose.bones['hand_'+side].matrix.translation-r.pose.bones['righthand_prop_'+('left' if side=='l' else 'right')+'hand'].matrix.translation).length for side in ('l','r')}
 contacts.append({'frame':f,'error_m':errors})
maxima={side:max(x['error_m'][side] for x in contacts) for side in ('l','r')}
assert np.array_equal(np.array(early_old),np.array(early_new)),float(np.max(np.abs(np.array(early_old)-np.array(early_new))))
assert all(np.isfinite(x).all() for x in matrices)
(P/'contact_precheck.json').write_text(json.dumps({'maxima_m':maxima,'rows':contacts},indent=2))
assert max(maxima.values())<.0001,maxima
# Remove temporary binding and restore every original active/default state.
cam.animation_data_clear()
for b in r.pose.bones:
 for k,v in pose_defaults[b.name].items():setattr(b,k,v)
for name,(action,nla,tracks) in adstate.items():
 ad=bpy.data.objects[name].animation_data;ad.action=action;ad.use_nla=nla
 for t,m,solo in tracks:t.mute=m;t.is_solo=solo
for name,values in object_defaults.items():
 for k,v in values.items():setattr(bpy.data.objects[name],k,v)
s.frame_set(frame_state[0],subframe=frame_state[1]);bpy.context.view_layer.update()
baseline={'snapshot':before,'extra':extra,'object_defaults':object_defaults,'scene':scene_state}
(P/'baseline_preservation.json').write_text(json.dumps(baseline,sort_keys=True))
after=snapshot(bpy);eafter=extra_snapshot();checks={k:after[k]==before[k] for k in before if k!='actions'}
checks['all_112_prior_actions']=all(after['actions'][n]==v for n,v in before['actions'].items())
for k,v in extra.items():checks[k]=all(eafter[k].get(n)==x for n,x in v.items()) if k in ('actions_metadata','actions_extended') else eafter[k]==v
checks['camera_animation_unbound']=cam.animation_data is None
checks['object_defaults']=all(all(list(getattr(bpy.data.objects[n],k))==v for k,v in vals.items()) for n,vals in object_defaults.items())
checks['scene_fields']=all(getattr(s,k)==v for k,v in scene_state.items() if k in ('frame_start','frame_end','frame_step'))
assert all(checks.values()),checks
bpy.ops.wm.save_as_mainfile(filepath=str(out),compress=True)
report={'source_sha256':sha(source),'candidate_sha256':sha(out),'actions':[new.name,ca.name],'checks':checks,'contact_maxima_480hz_m':maxima,'protected_f1_to_11_all_bone_difference':0,'rendered':False,'visual_pass':None,'rows':rows}
(P/'revision_report.json').write_text(json.dumps(report,indent=2))
assert sha(source)==c['source_sha256']
fm={'source_commit':c['source_commit'],'blend_sha256':sha(out),'actions':{a.name:action_fingerprint(a) for a in (new,ca)},'required_bindings':{r.name:new.name,cam.name:ca.name},'fps':60,'capture_status':'Not captured','reference_sha256':c['reference_sha256'],'rows':[{'output_index':i,'candidate_frame':i+1,'reference_native_frame':2241+i} for i in range(69)]}
(P/'frame_map.json').write_text(json.dumps(fm,indent=2))
print('SAVED',sha(out),maxima)
