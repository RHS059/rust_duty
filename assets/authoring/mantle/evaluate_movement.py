"""Reopen-only native quarter-frame motion and contact diagnostics; no render."""
import bpy,json,hashlib,math,argparse,sys
import numpy as np
from pathlib import Path
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);a=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);P=a.output;P.mkdir(exist_ok=True,parents=True)
source=Path(bpy.data.filepath);D=source.parent;manifest=json.loads((D/'manifest.json').read_text());assert hashlib.sha256(source.read_bytes()).hexdigest()==manifest['source_blend_sha256']
A=bpy.data.objects['Arms'];W=bpy.data.objects['hk416_weapon'];C=bpy.data.objects['RD First Person Review'];S=next(s for s in bpy.data.scenes if C.name in s.objects)
bpy.context.window.scene=S;S.camera=C;S.render.resolution_x=1280;S.render.resolution_y=720;S.render.resolution_percentage=100
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();basis={p.name:p.matrix_basis.copy() for p in A.pose.bones}
np.savez_compressed(P/'weapon_geometry.npz',vertices=np.array([list(v.co) for v in W.data.vertices]),triangles=np.array([list(t.vertices) for t in W.data.loop_triangles]))
rows=[];worst={};mats={}
for clip in manifest['clips']:
 start,end=clip['source_window'];last=end-start;act=bpy.data.actions[clip['name']];srows=[];quarter=[];wm=[]
 A.animation_data.action=None
 for b in A.pose.bones:b.matrix_basis=basis[b.name]
 A.animation_data.action=act
 for i in range((last-1)*4+1):
  f=1+i/4;fi=math.floor(f);S.frame_set(fi,subframe=f-fi);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();rig=A.evaluated_get(dg);weapon=W.evaluated_get(dg).matrix_world
  hands={}
  for side,word in [('l','left'),('r','right')]:
   p=rig.pose.bones;hand=rig.matrix_world@p['hand_'+side].matrix;goal=rig.matrix_world@p['righthand_prop_'+word+'hand'].matrix
   hands[side]={'wrist_solve_error_mm':(hand.translation-goal.translation).length*1000,'guard_error_degrees':math.degrees(p['MCH_hand_guarded_'+side].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_'+side].matrix.to_quaternion()).angle),'reach_margin_mm':(p['MCH_upperarm_'+side].bone.length+p['MCH_lowerarm_'+side].bone.length-(goal.translation-rig.matrix_world@p['MCH_upperarm_'+side].head).length)*1000,'follow':float(A.pose.bones['righthand_prop_'+word+'hand']['weapon_follow'])}
  row={'blender_frame':f,'source_frame':start+f-1,'hands':hands};quarter.append(row)
  if i%4==0:
   points={}
   for name,local in [('near_post_tip',[-.000062134116888,.158475101,.0469331592]),('far_aperture_center',[-.000062134116888,.158475116,-.313264295])]:
    q=world_to_camera_view(S,C,weapon@Vector(local));points[name]={'xy':[q.x*1280,(1-q.y)*720],'depth':q.z,'state':'out_of_frame' if q.z<=0 or not(0<=q.x<=1 and 0<=q.y<=1) else 'uncertain','method':'Evaluated mesh-local geometric projection; visual visibility not yet reviewed.'}
   srows.append({'frame':int(start+f-1),'source_pts':int(start+f-1)*256,'candidate_time':[int(f-1),60],'candidate':points,'weapon_world':[list(r) for r in weapon]});wm.append(np.array(weapon))
 report={'action':act.name,'quarter_frame_samples':len(quarter),'max_wrist_solve_error_mm':max(h['wrist_solve_error_mm'] for r in quarter for h in r['hands'].values()),'max_guard_error_degrees':max(h['guard_error_degrees'] for r in quarter for h in r['hands'].values()),'min_reach_margin_mm':min(h['reach_margin_mm'] for r in quarter for h in r['hands'].values()),'claims':'Native diagnostics only. Attached-hand baseline is not the observed release motion; no reference score or full-contact approval.'}
 (P/(act.name+'_native.json')).write_text(json.dumps({'summary':report,'camera':{'name':C.name,'world':[list(r) for r in C.matrix_world],'horizontal_fov_rad':C.data.angle_x,'resolution':[1280,720]},'samples':srows,'quarter_frames':quarter},indent=2));rows.append(report);mats[act.name]=np.asarray(wm)
np.savez_compressed(P/'weapon_matrices.npz',**mats)
(P/'validation_summary.json').write_text(json.dumps({'source_sha256':manifest['source_blend_sha256'],'status':'diagnostic','clips':rows,'scene':S.name,'scene_objects':[o.name for o in S.objects]},indent=2));print(json.dumps(rows));assert hashlib.sha256(source.read_bytes()).hexdigest()==manifest['source_blend_sha256']
