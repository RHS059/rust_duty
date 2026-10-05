import bpy,sys,json,hashlib,math
from pathlib import Path
from mathutils import Matrix,Vector
sys.path.insert(0,str(Path(__file__).parent))
from source_integrity import snapshot
from validate_source_structure import extra_snapshot
P=Path(__file__).parent; source=Path(bpy.data.filepath); sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(source)=='be9161fcba0f8550e1aa894e3d6df0dec5f98b0364e11cd0265556a07ca1da00'
before=snapshot(bpy); extra=extra_snapshot(); scene=bpy.context.scene;rig=bpy.data.objects['Arms'];root=rig.pose.bones['righthand_prop']
state=(scene.frame_current,scene.frame_subframe)
pose={p.name:{k:list(getattr(p,k)) for k in ('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')} for p in rig.pose.bones}
adstate={o.name:(o.animation_data.action,o.animation_data.use_nla,[(t,t.mute,t.is_solo) for t in o.animation_data.nla_tracks]) for o in bpy.data.objects if o.animation_data}
for o in bpy.data.objects:
 if o.animation_data:
  o.animation_data.use_nla=False
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
rig.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];scene.frame_set(1);bpy.context.view_layer.update()
old=bpy.data.actions['prone_crawl_enter_r3'];new=old.copy();new.name='prone_crawl_enter_r4';new.use_fake_user=True
C=scene.camera.matrix_world.copy();Ci=C.inverted();Ri=rig.matrix_world.inverted()
# A fixed point in the old weapon root space near the rear sight defines the
# rotation pivot. This preserves its original visible path without fitting scale.
rig.animation_data.action=old;scene.frame_set(1);bpy.context.view_layer.update()
q=Vector((0.08323424182818288,0.005083007134545519,-0.26023809868713904))
pivot_local=(rig.matrix_world@root.matrix).inverted()@C@q
rows=[]
for i in range(41*8,69*8+1):
 f=i/8
 scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
 W=rig.matrix_world@root.matrix.copy(); pivot=Ci@W@pivot_local
 u=max(0,min(1,(f-41)/14));w=u*u*u*(10+u*(-15+6*u))
 R=Matrix.Rotation(math.radians(8*w),4,'Z')@Matrix.Rotation(math.radians(2*w),4,'Y')
 T=C@Matrix.Translation(pivot)@R@Matrix.Translation(-pivot)@Ci
 root.matrix=Ri@T@W
 rows.append({'frame':f,'roll_delta_degrees':8*w,'yaw_delta_degrees':2*w,'location':list(root.location),'rotation_euler':list(root.rotation_euler)})
for prop in ['location','rotation_euler']:
 for axis in range(3):
  fc=next(f for f in new.fcurves if f.data_path==f'pose.bones["righthand_prop"].{prop}' and f.array_index==axis)
  for ki in range(len(fc.keyframe_points)-1,-1,-1):
   if fc.keyframe_points[ki].co.x>41:fc.keyframe_points.remove(fc.keyframe_points[ki],fast=True)
  fc.update()
  for row in rows:
   if row['frame']==41:continue
   k=fc.keyframe_points.insert(row['frame'],row[prop][axis],options={'FAST'});k.interpolation='LINEAR'
  k=next(k for k in fc.keyframe_points if k.co.x==41);k.interpolation='LINEAR';fc.update()
new['acceptance_status']='WIP r4; independent fixed-view review pending';new['revision_reason']='Late rail near-vertical residual in independently inspected r3 native frames 46-55; preserve pitch correction and cuff fix';new['runtime_id']='prone_crawl_enter'
# New Action-only left shoulder compensation keeps the support hand on its
# existing target where revised orientation would exceed the finite IK reach.
rig.animation_data.action=new
shoulder=rig.pose.bones['clavicle_l'];shoulder_rows=[]
for i in range(545):
 f=1+i/8;scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
 for iteration in range(20):
  error=rig.pose.bones['righthand_prop_lefthand'].matrix.translation-rig.pose.bones['hand_l'].matrix.translation
  if f<=41 or error.length<.000004:break
  m=shoulder.matrix.copy();m.translation+=error;shoulder.matrix=m;bpy.context.view_layer.update()
 shoulder_rows.append({'frame':f,'location':list(shoulder.location)})
for axis in range(3):
 path='pose.bones["clavicle_l"].location';fc=next((c for c in new.fcurves if c.data_path==path and c.array_index==axis),None)
 if fc is None:fc=new.fcurves.new(path,index=axis,action_group='clavicle_l')
 fc.keyframe_points.clear()
 for row in shoulder_rows:
  k=fc.keyframe_points.insert(row['frame'],row['location'][axis],options={'FAST'});k.interpolation='LINEAR'
 fc.update()
# Evaluate attachment residual at both native and subframe instants. No render.
rig.animation_data.action=new;contacts=[]
for i in range(545):
 f=1+i/8;scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
 err={s:(rig.pose.bones['hand_'+s].matrix.translation-rig.pose.bones['righthand_prop_'+('left' if s=='l' else 'right')+'hand'].matrix.translation).length for s in ['l','r']}
 contacts.append({'frame':f,'error_m':err})
maxima={s:max(r['error_m'][s] for r in contacts) for s in ['l','r']}
(P/'contact_precheck.json').write_text(json.dumps({'maxima_m':maxima,'rows':contacts},indent=2))
assert max(maxima.values())<.0001,maxima
for p in rig.pose.bones:
 for k,v in pose[p.name].items():setattr(p,k,v)
for name,(action,nla,tracks) in adstate.items():
 ad=bpy.data.objects[name].animation_data;ad.action=action;ad.use_nla=nla
 for t,m,s in tracks:t.mute=m;t.is_solo=s
scene.frame_set(state[0],subframe=state[1]);bpy.context.view_layer.update()
(P/'baseline_preservation.json').write_text(json.dumps({'snapshot':before,'extra':extra},sort_keys=True))
after=snapshot(bpy);eafter=extra_snapshot();checks={k:after[k]==before[k] for k in before if k!='actions'}
checks['all_110_prior_actions']=all(after['actions'][n]==v for n,v in before['actions'].items())
for k,v in extra.items():checks[k]=all(eafter[k].get(n)==x for n,x in v.items()) if k in ('actions_metadata','actions_extended') else eafter[k]==v
assert all(checks.values()),checks
out=P/'halcyon_prone_crawl_r4.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out),compress=True)
(P/'revision_report.json').write_text(json.dumps({'source_sha256':sha(source),'candidate_sha256':sha(out),'action':new.name,'checks':checks,'contact_maxima_480hz_m':maxima,'contact_maxima_240hz_m':{s:max(r['error_m'][s] for r in contacts[::2]) for s in ['l','r']},'correction':'Camera-space +8 degree roll/+2 degree yaw around tracked rear-sight pivot, quintic blend f41–55, held through69; preserves r3 early motion/cuff fix, r2 pitch correction and original timing. Bounded artistic inference from independently inspected stock/receiver witnesses, not an acceptance score.','root_samples':rows},indent=2))
print('SAVED',sha(out),maxima)
