"""Create independent editable mantle/climb Actions from frozen public r5 source.
Headless authoring only. This script performs no rendering and no runtime edits.
"""
import bpy,json,hashlib,math,argparse,sys
from pathlib import Path
from mathutils import Matrix,Vector,Euler
P=Path(__file__).resolve().parent;ROOT=P.parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(P.parent/'locomotion_directional'/'r5'))
from source_integrity import snapshot,action_fingerprint
from validate_directional_source import extra_snapshot
from bpy_extras.object_utils import world_to_camera_view
parser=argparse.ArgumentParser();parser.add_argument('--kind',choices=['mantle','climb'],required=True)
a=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);D=P.parent/a.kind;D.mkdir(exist_ok=True)
design=json.loads((P/'design_r1.json').read_text());source=Path(bpy.data.filepath)
assert hashlib.sha256(source.read_bytes()).hexdigest()==design['rig_sha256']
assert bpy.app.version_string=='4.3.2'
S=bpy.context.scene;A=bpy.data.objects['Arms'];W=bpy.data.objects['hk416_weapon'];C=bpy.data.objects['RD First Person Review'];R=A.pose.bones['righthand_prop']
before=snapshot(bpy);structural=extra_snapshot();base_name='RD_00_Supplied_Base_Guarded_Recovered';ready_name='RD_Locomotion_Normal_Entry_4419_4434_WIP2'
original_active=A.animation_data.action;original_nla=A.animation_data.use_nla
original_basis={p.name:p.matrix_basis.copy() for p in A.pose.bones}
for t in A.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions[base_name];S.frame_set(1);bpy.context.view_layer.update()
base_basis={p.name:p.matrix_basis.copy() for p in A.pose.bones}
A.animation_data.action=bpy.data.actions[ready_name];S.frame_set(1);bpy.context.view_layer.update()
M0=C.matrix_world.inverted()@W.matrix_world;WR=(A.matrix_world@R.matrix).inverted()@W.matrix_world;ready_loc=R.location.copy();ready_rot=R.rotation_euler.copy()
pivot=Vector(design['pivot_weapon_local']);pivot0=M0@pivot
A.animation_data.action=None

def interpolate(rows,f):
 if f<=rows[0][0]:return rows[0][1:]
 if f>=rows[-1][0]:return rows[-1][1:]
 for i in range(len(rows)-1):
  x,y=rows[i:i+2]
  if x[0]<=f<=y[0]:
   t=(f-x[0])/(y[0]-x[0]);dt=y[0]-x[0];out=[]
   for c in range(1,7):
    # Piecewise cubic Hermite; finite slopes, no periodic extrapolation.
    m0=0 if i==0 else (y[c]-rows[i-1][c])/(y[0]-rows[i-1][0])
    m1=0 if i+2==len(rows) else (rows[i+2][c]-x[c])/(rows[i+2][0]-x[0])
    if y[c]==x[c]:m0=m1=0
    out.append((2*t**3-3*t*t+1)*x[c]+(t**3-2*t*t+t)*dt*m0+(-2*t**3+3*t*t)*y[c]+(t**3-t*t)*dt*m1)
   return out

def root_pose(values,compat):
 xyz=Vector(values[:3]);rot=Euler([math.radians(v) for v in values[3:]],'XYZ').to_matrix()
 M=(rot@M0.to_3x3()).to_4x4();M.translation=pivot0+xyz-M.to_3x3()@pivot
 R.matrix=A.matrix_world.inverted()@C.matrix_world@M@WR.inverted()
 e=R.rotation_euler.copy();e.make_compatible(compat)
 return R.location.copy(),e

created=[];controls={}
for clip in design['clips']:
 if clip['directory']!=a.kind:continue
 name=clip['name'];assert name not in bpy.data.actions
 start,end=clip['source_window'];last=end-start
 act=bpy.data.actions[ready_name].copy();act.name=name;act.use_fake_user=True
 for fc in act.fcurves:
  value=fc.evaluate(1);fc.keyframe_points.clear()
  for m in list(fc.modifiers):fc.modifiers.remove(m)
  for frame in [1,last]:k=fc.keyframe_points.insert(frame,value);k.interpolation='LINEAR'
 for fc in list(act.fcurves):
  if fc.data_path in ['pose.bones["righthand_prop"].location','pose.bones["righthand_prop"].rotation_euler']:act.fcurves.remove(fc)
 rows=[];prev=ready_rot.copy()
 for f in range(start,end):
  v=interpolate(clip['keys'],f);loc,e=root_pose(v,prev)
  if all(abs(x)<1e-14 for x in v):loc=ready_loc.copy();e=ready_rot.copy()
  rows.append({'blender_frame':f-start+1,'source_frame':f,'location':list(loc),'rotation_euler':list(e),'camera_hypothesis':v});prev=e
 for prop in ['location','rotation_euler']:
  for axis in range(3):
   fc=act.fcurves.new('pose.bones["righthand_prop"].'+prop,index=axis,action_group=name+' | source-time weapon');fc.lock=False;fc.group.lock=False
   for row in rows:
    k=fc.keyframe_points.insert(row['blender_frame'],row[prop][axis],options={'FAST'});k.interpolation='BEZIER';k.handle_left_type='AUTO_CLAMPED';k.handle_right_type='AUTO_CLAMPED'
   fc.update()
 act['status']='diagnostic';act['reference_supported_scope']='Event order and approximate native timing; spatial poses need independent source-anchor comparison.'
 act['source_frame_start']=start;act['source_frame_end_exclusive']=end;act['source_fps']=60;act['source_sha256']=design['source_sha256'];act['camera_unchanged']=True;act['hand_contact_status']='Inherited attached hands only; free-hand release not yet authored. Not contact-approved.'
 act['hidden_motion_inferred']=bool(clip.get('inferred_hidden_source_frames'))
 created.append(act);controls[name]=rows
# Restore inherited active pose and raw defaults before saving; original scene/camera unchanged.
A.animation_data.action=original_active;A.animation_data.use_nla=original_nla
for p in A.pose.bones:p.matrix_basis=original_basis[p.name]
for o in bpy.data.objects:
 if o.animation_data and o.name in before['nla']:
  for tr,old in zip(o.animation_data.nla_tracks,before['nla'][o.name]['tracks']):tr.mute=old['mute'];tr.is_solo=old['is_solo']
assert all(action_fingerprint(bpy.data.actions[n])==v for n,v in before['actions'].items())
after=snapshot(bpy);afterstruct=extra_snapshot()
for key in ['meshes','armatures','objects_and_bindings','materials','cameras']:assert afterstruct[key]==structural[key],key
assert after['drivers']==before['drivers'] and after['packed_images']==before['packed_images'] and after['nla']==before['nla']
# New Actions are retained by fake users. No inherited NLA track is edited.
out=D/('aella_'+a.kind+'_r1.blend');assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out),compress=True)
manifest={'schema':'rust-duty-movement-authoring/v1','status':'diagnostic','source_blend_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'baseline_sha256':design['rig_sha256'],'baseline_commit':'61c3ccd26e8cf9f288e5e56c536c92b7d30409ef','source_reference_sha256':design['source_sha256'],'source_rate':[60,1],'new_actions':[a.name for a in created],'prior_action_count':len(before['actions']),'prior_actions_preserved':True,'preserved_geometry_rig_bindings_drivers_camera':True,'root_track_locked':False,'independent_score':None,'runtime_status':'not exported or integrated','hand_status':'release/contact work pending','render_status':'Eevee foreground witness pending','clips':[c for c in design['clips'] if c['directory']==a.kind]}
(D/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(D/'authored_controls.json').write_text(json.dumps(controls,indent=2)+'\n');(D/'source_integrity.json').write_text(json.dumps({'portable_source_sha256':manifest['source_blend_sha256'],'preserved':after},indent=2)+'\n')
print('SOURCE_CHECKPOINT',json.dumps(manifest));assert hashlib.sha256(source.read_bytes()).hexdigest()==design['rig_sha256']
