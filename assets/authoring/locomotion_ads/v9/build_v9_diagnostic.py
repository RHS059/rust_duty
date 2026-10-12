"""Save an isolated, editable, derived v9 arm-articulation preview scene.
Original source scene/rig/Actions remain preserved. No rendering occurs here.
"""
import bpy,json,math,hashlib,runpy,sys
from pathlib import Path
from mathutils import Matrix,Vector,Quaternion
import numpy as np

HERE=Path(__file__).resolve().parent
SRC=Path(__file__).resolve().parents[2]/'ads'
sys.dont_write_bytecode=True;sys.path.insert(0,str(SRC))
from source_integrity import snapshot
before=snapshot(bpy);native=bpy.context.scene
ctx=runpy.run_path(str(HERE/'probe_v9_articulation.py'))
A,W,C,CAM,select,base,baseRel,baseW,ready,p0,u0,blend=[ctx[k] for k in ('A','W','C','CAM','select','base','baseRel','baseW','ready','p0','u0','blend')]
camera_before=[list(r) for r in C]
select('ads_hold_r1');mag=bpy.data.objects['hk416_magazine'];baseMagRel=baseW.inverted()@mag.matrix_world
samples=[]
for i in range(501):
 f=i/4;select('hip_walk_forward_r5',1+((f+5.75)*.8)%38);walkW=W.matrix_world.copy();walk=ctx['globals_now']();walkRel={n:walkW.inverted()@m for n,m in walk.items()}
 delta=(C.inverted()@walkW)@ready.inverted();full=Quaternion().slerp(delta.to_quaternion(),.4).to_matrix().to_4x4();full.translation=delta.translation*.4;target=full@p0
 select('hip_walk_forward_r5',1+((f+5.75)*.8+19)%38)
 aux_delta=(C.inverted()@W.matrix_world)@ready.inverted();aux_full=Quaternion().slerp(aux_delta.to_quaternion(),.4).to_matrix().to_4x4();aux_full.translation=aux_delta.translation*.4;aux_target=aux_full@p0
 select('hip_walk_forward_r5',1+((f+5.75)*.8)%38)
 u=u0+(target.x/-target.z-u0)*.25;v=aux_target.y/-aux_target.z;theta=math.atan2(v,u)-math.atan2(p0.y,p0.x);theta=math.atan2(math.sin(theta),math.cos(theta));depth=-math.hypot(p0.x,p0.y)/math.hypot(u,v)-p0.z
 offset=Matrix.Rotation(theta,4,'Z');offset.translation=Vector((0,0,depth));anchor=(C@offset@C.inverted())@baseW
 samples.append({'frame':1+f,'globals':{n:anchor@blend(baseRel[n],walkRel[n],.15) for n in base},'weapon':anchor,'magazine':anchor@blend(baseMagRel,walkW.inverted()@mag.matrix_world,.15)})
select('ads_hold_r1');deps=bpy.context.evaluated_depsgraph_get();deps.update()
skin_names=['Actual arms mesh 0','Actual arms mesh 1','Actual arms mesh 2'];source_skin={}
for name in skin_names:
 o=bpy.data.objects[name].evaluated_get(deps);m=o.to_mesh();source_skin[name]=np.array([o.matrix_world@v.co for v in m.vertices]);o.to_mesh_clear()
actor_meshes={}
for name in ('hk416_weapon','hk416_magazine'):
 o=bpy.data.objects[name].evaluated_get(deps);actor_meshes[name]=(bpy.data.meshes.new_from_object(o,preserve_all_data_layers=True,depsgraph=deps),o.matrix_world.copy())

scene=bpy.data.scenes.new('ADS V9 Depth Phase Diagnostic');scene.world=native.world
scene.render.engine='BLENDER_EEVEE_NEXT';scene.render.resolution_x=960;scene.render.resolution_y=540;scene.render.resolution_percentage=100;scene.render.fps=60;scene.render.fps_base=1
scene.view_settings.view_transform=native.view_settings.view_transform;scene.view_settings.look=native.view_settings.look;scene.view_settings.exposure=native.view_settings.exposure;scene.view_settings.gamma=native.view_settings.gamma
scene.camera=CAM;scene.collection.objects.link(CAM)
for obj in native.objects:
 if obj.type=='LIGHT' or (obj.type=='MESH' and obj.name.startswith('RD_REFERENCE_ONLY | ')):scene.collection.objects.link(obj)
scene.eevee.taa_samples=8;scene.eevee.taa_render_samples=8
rig=A.copy();rig.data=A.data.copy();rig.name='DIAG_V9_Arms';rig.animation_data_clear();rig.parent=None;rig.matrix_world=A.matrix_world.copy();scene.collection.objects.link(rig)
for p in rig.pose.bones:
 for constraint in list(p.constraints):p.constraints.remove(constraint)
 p.rotation_mode='QUATERNION'
skin={}
for name in skin_names:
 original=bpy.data.objects[name];obj=original.copy();obj.name='DIAG_V9_'+name;obj.parent=None;obj.matrix_world=original.matrix_world.copy();obj.animation_data_clear();scene.collection.objects.link(obj)
 for modifier in obj.modifiers:
  if modifier.type=='ARMATURE':modifier.object=rig
 skin[name]=obj
actors={}
for name,(mesh,world) in actor_meshes.items():
 obj=bpy.data.objects.new('DIAG_V9_'+name,mesh);scene.collection.objects.link(obj);obj.matrix_world=world;obj.rotation_mode='QUATERNION';actors[name]=obj
arm_inverse=rig.matrix_world.inverted()
def bases(globals_):
 pose={n:arm_inverse@m for n,m in globals_.items()};result={}
 for p in rig.pose.bones:
  kw={'parent_matrix':pose[p.parent.name],'parent_matrix_local':p.parent.bone.matrix_local} if p.parent else {}
  result[p.name]=p.bone.convert_local_to_pose(pose[p.name],p.bone.matrix_local,invert=True,**kw)
 return result
for name,m in bases(base).items():rig.pose.bones[name].matrix_basis=m
if bpy.context.window:bpy.context.window.scene=scene
bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();deps.update();skin_errors={}
for name,obj in skin.items():
 evaluated=obj.evaluated_get(deps);mesh=evaluated.to_mesh();actual=np.array([evaluated.matrix_world@v.co for v in mesh.vertices]);evaluated.to_mesh_clear();skin_errors[name]=float(np.max(np.abs(actual-source_skin[name])))
(HERE/'v9_clone_baseline.json').write_text(json.dumps({'held_skin_max_component_errors_m':skin_errors,'clone_method':'Same original skin mesh data and modifier settings, copied rest armature, constraints removed only from diagnostic copy; exact evaluated globals assigned.'},indent=2)+'\n')
assert max(skin_errors.values())<1e-5,skin_errors
frames=[s['frame'] for s in samples];channels={p.name:[[] for _ in range(10)] for p in rig.pose.bones};last_q={}
for sample in samples:
 for name,m in bases(sample['globals']).items():
  loc,q,scale=m.decompose()
  if name in last_q and q.dot(last_q[name])<0:q.negate()
  last_q[name]=q.copy()
  for dst,value in zip(channels[name],[*loc,*q,*scale]):dst.append(float(value))
def curve(action,path,index,values,group):
 fc=action.fcurves.new(path,index=index,action_group=group)
 if max(values)-min(values)<1e-12:co=[frames[0],values[0]]
 else:co=[v for f,x in zip(frames,values) for v in (f,x)]
 fc.keyframe_points.add(len(co)//2);fc.keyframe_points.foreach_set('co',co)
 for key in fc.keyframe_points:key.interpolation='LINEAR'
 fc.update()
action=bpy.data.actions.new('DIAG_v9_forward_native15_output');action.use_fake_user=True;rig.animation_data_create();rig.animation_data.action=action
for name,values in channels.items():
 p=rig.pose.bones[name]
 for j,data in enumerate(values):
  channel,index=('location',j) if j<3 else (('rotation_quaternion',j-3) if j<7 else ('scale',j-7))
  curve(action,p.path_from_id(channel),index,data,name)
for name,obj in actors.items():
 a=bpy.data.actions.new('DIAG_v9_'+name+'_output');a.use_fake_user=True;obj.animation_data_create();obj.animation_data.action=a;values=[[] for _ in range(10)];last=None
 for sample in samples:
  loc,q,scale=sample['weapon' if name=='hk416_weapon' else 'magazine'].decompose()
  if last is not None and q.dot(last)<0:q.negate()
  last=q.copy()
  for dst,value in zip(values,[*loc,*q,*scale]):dst.append(float(value))
 for j,data in enumerate(values):
  channel,index=('location',j) if j<3 else (('rotation_quaternion',j-3) if j<7 else ('scale',j-7));curve(a,channel,index,data,name)
print('BAKE_KEYS_READY',flush=True)
worst_matrix=0.;worst_actor=0.;worst_deform=0.;worst_hand=0.;worst_bone=None;worst_frame=None
for sample in samples:
 f=sample['frame'];scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
 for n,m in sample['globals'].items():
  error=max(abs(a-b) for ra,rb in zip(rig.matrix_world@rig.pose.bones[n].matrix,m) for a,b in zip(ra,rb))
  if error>worst_matrix:worst_matrix=error;worst_bone=n;worst_frame=f
  if rig.data.bones[n].use_deform:worst_deform=max(worst_deform,error)
 for name,obj in actors.items():worst_actor=max(worst_actor,max(abs(a-b) for ra,rb in zip(obj.matrix_world,sample['weapon' if name=='hk416_weapon' else 'magazine']) for a,b in zip(ra,rb)))
 for side in ('l','r'):
  actual=actors['hk416_weapon'].matrix_world.inverted()@rig.matrix_world@rig.pose.bones['hand_'+side].matrix
  worst_hand=max(worst_hand,(actual.translation-baseRel['hand_'+side].translation).length*1000)
print('BAKE_VALIDATION',json.dumps({'all_bone_component_error':worst_matrix,'deform_bone_component_error':worst_deform,'actor_component_error':worst_actor,'actual_baked_hand_translation_mm':worst_hand,'worst_bone':worst_bone,'worst_frame':worst_frame}),flush=True)
# Restore the original source scene's selection/mutes and retain every original Action.
state=before['nla']['Arms'];A.animation_data.action=bpy.data.actions[state['action']] if state['action'] else None;A.animation_data.use_nla=state['use_nla']
for track,old in zip(A.animation_data.nla_tracks,state['tracks']):track.mute=old['mute'];track.is_solo=old['is_solo']
after=snapshot(bpy);assert all(after['actions'][k]==v for k,v in before['actions'].items());assert after['packed_images']==before['packed_images'];assert all(after['drivers'][k]==v for k,v in before['drivers'].items());assert after['nla']['Arms']==before['nla']['Arms'];assert [list(r) for r in CAM.matrix_world]==camera_before
scene.frame_start=1;scene.frame_end=126;scene.frame_set(1);scene['status']='Derived v9 diagnostic, structural caveat: joint-anchor residual increases; not accepted animation.';scene['candidate_id']='ads-v9-depthphase-forward-public47-r5';scene['render_policy']='Eevee rendered viewport only'
out=HERE/'ads_v9_depthphase_public47_hipr5_diagnostic.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out),compress=True)
summary=json.loads((HERE/'v9_articulation_probe.json').read_text())['summary']
manifest={'status':'saved WIP derived diagnostic, unreviewed','candidate_id':scene['candidate_id'],'blend':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'bytes':out.stat().st_size,'scene':scene.name,'camera':CAM.name,'source_ads_sha256':ctx['contract']['source_ads_sha256'],'source_hip_sha256':ctx['contract']['source_hip_sha256'],'original_actions_preserved':len(before['actions']),'original_drivers_images_nla_preserved':True,'camera_unchanged':True,'held_clone_skin_errors_m':skin_errors,'quarter_frame_matrix_max_error':worst_matrix,'quarter_frame_deform_matrix_max_error':worst_deform,'quarter_frame_actor_max_error':worst_actor,'actual_baked_hand_translation_mm':worst_hand,'worst_matrix_bone':worst_bone,'worst_matrix_frame':worst_frame,'deform_actor_matrix_tolerance_1e5_pass':worst_deform<1e-5 and worst_actor<1e-5,'bake_sample_hz':240,'render_frames':[1,126],'render_fps':60,'reference_frames':[2298,2423],'comparison_phase_offset_rational':'23/240','phase_rate':'4/5','articulation_weight':.15,'weapon_policy':'primary X; vertical target from native half-period; no gain change','vertical_channel_native_offset_frames':19,'structural_probe':summary,'claim_limit':'Native-input-derived global-pose interpolation with preserved rest/skin. Increased joint-anchor residual and any helper-bone TRS approximation are disclosed. Not a new accepted locomotion clip, not runtime validation, and no reference-match score.'}
(HERE/'v9_scene_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest),flush=True)
