"""Add one diagnostic Action; no rendering, constraints, drivers, or runtime edits."""
import bpy,json,hashlib,math,sys
from pathlib import Path
from mathutils import Vector
P=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(P.parent.parent/'locomotion_directional'/'r5'))
from source_integrity import snapshot,action_fingerprint
from validate_directional_source import extra_snapshot
D=json.loads((P/'design.json').read_text()); INPUT=Path(bpy.data.filepath)
assert hashlib.sha256(INPUT.read_bytes()).hexdigest()==D['input_sha256']
assert bpy.app.version_string=='4.3.2'
A=bpy.data.objects['Arms']; C=bpy.data.objects['RD First Person Review']; W=bpy.data.objects['hk416_weapon']; L=A.pose.bones['righthand_prop_lefthand']; S=next(s for s in bpy.data.scenes if C.name in s.objects)
bpy.context.window.scene=S
before=snapshot(bpy); structural=extra_snapshot(); original_action=A.animation_data.action; original_use_nla=A.animation_data.use_nla
original_basis={p.name:p.matrix_basis.copy() for p in A.pose.bones};original_frame=S.frame_current;original_subframe=S.frame_subframe
original_props={p.name:{k:v for k,v in p.items() if isinstance(v,(int,float,str))} for p in A.pose.bones}
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False
A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered']; S.frame_set(1);bpy.context.view_layer.update()
base_basis={p.name:p.matrix_basis.copy() for p in A.pose.bones}
old=bpy.data.actions[D['prior_action']];assert D['action'] not in bpy.data.actions
new=old.copy();new.name=D['action'];new.use_fake_user=True
start,end=D['source_window'];last=end-start;division=D['sample_divisions_per_frame'];detach=D['detach_native'];reattach=D['reattach_native']
limits=json.loads(A['wrist_guard_l']);base=limits['base_euler_deg']

def update():
 A.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()
def select(act,n):
 A.animation_data.action=None
 for p in A.pose.bones:p.matrix_basis=base_basis[p.name]
 for name,props in original_props.items():
  for k,v in props.items():A.pose.bones[name][k]=v
 A.animation_data.action=act;f=n-start+1;i=math.floor(f);S.frame_set(i,subframe=f-i);update()
def smooth(t):
 t=max(0,min(1,t));return t*t*t*(10+t*(-15+6*t))
def keyed(rows,n):
 if n<=rows[0][0]:return rows[0][1:]
 if n>=rows[-1][0]:return rows[-1][1:]
 for a,b in zip(rows,rows[1:]):
  if a[0]<=n<=b[0]:
   t=smooth((n-a[0])/(b[0]-a[0]));return [(1-t)*x+t*y for x,y in zip(a[1:],b[1:])]
def properties():
 p=A.pose.bones
 raw=(p['MCH_attach_forearm_l'].matrix.inverted()@p['MCH_attach_goal_l'].matrix).to_euler('XYZ')
 return {'forearm_roll':math.degrees(p['MCH_attach_forearm_l'].rotation_euler.y),'wrist_flex':math.degrees(raw.x)-base[0],'wrist_twist':math.degrees(raw.y)-base[1],'wrist_deviation':math.degrees(raw.z)-base[2]}
ends={}
for n in [detach,reattach]:select(old,n);ends[n]=properties()
rows=[];max_target_error=0.;qcompat=None
for i in range((last-1)*division+1):
 n=start+i/division;select(old,n)
 weapon=W.matrix_world.copy()
 pole=A.pose.bones['clavicle_l'];polemat=pole.matrix.copy();shoulder=keyed(D['shoulder_pose_keys_native_yz_m'],n);polemat.translation.y+=shoulder[0];polemat.translation.z+=shoulder[1];pole.matrix=polemat;update()
 poleloc=list(pole.location);goal=L.matrix.copy();raw=properties()
 free=detach<=n<reattach
 env=smooth((n-detach)/6)*(1-smooth((n-7870)/(reattach-7870))) if free else 0.
 follow=1-smooth((n-detach)/6)*(1-smooth((n-7872)/(reattach-7872)))
 if free:
  # Both sides of each discrete ownership switch have the same evaluated target.
  goal.translation+=A.matrix_world.inverted().to_3x3()@C.matrix_world.to_3x3()@Vector(keyed(D['free_offset_keys_camera_m'],n))
  t=smooth((n-detach)/(reattach-detach))
  target={'forearm_roll':D['free_forearm_roll_deg'],'wrist_flex':D['free_wrist_delta_deg'][0],'wrist_twist':D['free_wrist_delta_deg'][1],'wrist_deviation':D['free_wrist_delta_deg'][2]}
  props={k:(1-env)*raw[k]+env*target[k] for k in target}
 else:props=raw
 A.animation_data.action=None
 L['weapon_follow']=follow;L['magazine_follow']=0.
 for k,v in props.items():L[k]=float(v)
 for digit in ['thumb','index','middle','ring','pinky']:L[digit+'_curl']=D['open_curl_rad']*smooth((n-7829)/2)*(1-smooth((n-7871)/3))
 update()
 # Solve unparented raw controller against unchanged Child Of inverse.
 for _ in range(3):
  L.matrix_basis=L.matrix_basis@L.matrix.inverted()@goal;update()
 max_target_error=max(max_target_error,(L.matrix.translation-goal.translation).length)
 e=L.rotation_euler.copy()
 if qcompat is not None:e.make_compatible(qcompat)
 qcompat=e
 rows.append({'frame':1+i/division,'native':n,'location':list(L.location),'rotation_euler':list(e),'weapon_follow':float(L['weapon_follow']),'magazine_follow':0.,**props,**{digit+'_curl':float(L[digit+'_curl']) for digit in ['thumb','index','middle','ring','pinky']},'weapon_world':[list(r) for r in weapon],'pole_location':poleloc})
# Replace only the support-hand channels in the copied Action.
prefix='pose.bones["righthand_prop_lefthand"]'
props=['weapon_follow','magazine_follow','forearm_roll','wrist_flex','wrist_twist','wrist_deviation','thumb_curl','index_curl','middle_curl','ring_curl','pinky_curl']
paths=[prefix+'.location',prefix+'.rotation_euler']+[prefix+'["'+k+'"]' for k in props]
for fc in list(new.fcurves):
 if fc.data_path in paths:new.fcurves.remove(fc)
for prop in ['location','rotation_euler']+props:
 path=prefix+'.'+prop if prop in ['location','rotation_euler'] else prefix+'["'+prop+'"]'
 for axis in range(3 if prop in ['location','rotation_euler'] else 1):
  fc=new.fcurves.new(path,index=axis,action_group='One-hand mantle matched support-hand hypothesis')
  for row in rows:
   v=row[prop][axis] if isinstance(row[prop],list) else row[prop]
   key=fc.keyframe_points.insert(row['frame'],v,options={'FAST'});key.interpolation='LINEAR'
  fc.update()
polepath='pose.bones["clavicle_l"].location'
for fc in list(new.fcurves):
 if fc.data_path==polepath:new.fcurves.remove(fc)
for axis in range(3):
 fc=new.fcurves.new(polepath,index=axis,action_group='Bounded support shoulder-plane hypothesis')
 for row in rows:
  key=fc.keyframe_points.insert(row['frame'],row['pole_location'][axis],options={'FAST'});key.interpolation='LINEAR'
 fc.update()
new['status']='diagnostic';new['render_status']='not attempted; authorization hold';new['hand_status']='Matched ownership switches and bounded free reach; no visible contact approval';new['baseline_action_count']=len(before['actions']);new['source_frame_start']=start;new['source_frame_end_exclusive']=end
# Restore all original editable state, including custom-property defaults.
A.animation_data.action=original_action;A.animation_data.use_nla=original_use_nla
for p in A.pose.bones:
 p.matrix_basis=original_basis[p.name]
 for k,v in original_props[p.name].items():p[k]=v
for o in bpy.data.objects:
 if o.animation_data and o.name in before['nla']:
  for t,d in zip(o.animation_data.nla_tracks,before['nla'][o.name]['tracks']):t.mute=d['mute'];t.is_solo=d['is_solo']
assert all(action_fingerprint(bpy.data.actions[n])==h for n,h in before['actions'].items())
after=snapshot(bpy); after_structure=extra_snapshot()
for k in ['meshes','armatures','objects_and_bindings','materials','cameras']:assert structural[k]==after_structure[k],k
for k in ['drivers','packed_images','nla']:assert before[k]==after[k],k
S.frame_set(original_frame,subframe=original_subframe)
OUT=P/'candidate';OUT.mkdir(exist_ok=True)
out=OUT/'aella_mantle_onehand_r2.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out),compress=True)
(OUT/'controls.json').write_text(json.dumps(rows,indent=2)+'\n')
report={'status':'diagnostic','source_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'input_sha256':D['input_sha256'],'input_action_count':len(before['actions']),'output_action_count':len(after['actions']),'prior_actions_preserved':True,'structure_drivers_nla_preserved':True,'max_target_error_m':max_target_error,'render_performed':False,'baseline':'Preserves85 Actions: recovered r5 82 plus2r1 mantle Actions plus frozen low-vault r2; no canonical Jump/Prone replacement'}
(OUT/'authoring_report.json').write_text(json.dumps(report,indent=2)+'\n');print('R2_AUTHORING',json.dumps(report))
assert hashlib.sha256(INPUT.read_bytes()).hexdigest()==D['input_sha256']
