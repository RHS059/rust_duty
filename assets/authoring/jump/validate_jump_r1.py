"""Non-rendering validation of on-disk authored jump Actions and attached grips.
Run on the candidate .blend, with -- OUTPUT.json. No source is saved.
"""
import bpy,sys,json,hashlib,math
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
args=sys.argv[sys.argv.index('--')+1:];out=Path(args[0]);path=Path(bpy.data.filepath)
sha=hashlib.sha256(path.read_bytes()).hexdigest()
s=bpy.context.scene;r=bpy.data.objects['Arms'];camera=s.camera
assert bpy.app.version_string=='4.3.2'
assert s.render.fps/s.render.fps_base==60
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
r.animation_data.use_nla=False
base=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];ready=bpy.data.actions['RD_Locomotion_Normal_Entry_4419_4434_WIP2']
def diff(a,b):return max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))
def frame(f):
 s.frame_set(math.floor(f),subframe=f-math.floor(f));bpy.context.view_layer.update();d=bpy.context.evaluated_depsgraph_get();d.update();return d
def evaluate(f):
 d=frame(f);er=r.evaluated_get(d)
 mats={b.name:b.matrix.copy() for b in er.pose.bones}
 root=er.matrix_world@mats['righthand_prop'];inv=root.inverted()
 return {'bones':mats,'root':root,'player_root':er.matrix_world@mats['root'],'camera':camera.matrix_world.copy(),'armature':er.matrix_world.copy(),
  'hands':{side:inv@er.matrix_world@mats['hand_'+side] for side in ['l','r']},
  'actors':{name: bpy.data.objects[name].evaluated_get(d).matrix_world.copy() for name in ['hk416_weapon','hk416_magazine']},
  'wrist_error':[ (mats['hand_'+side].translation-mats['righthand_prop_'+suffix].translation).length for side,suffix in [('l','lefthand'),('r','righthand')] ],
  'guard_error_degrees':[math.degrees(mats['MCH_hand_guarded_'+side].to_quaternion().rotation_difference(mats['MCH_attach_goal_'+side].to_quaternion()).angle) for side in ['l','r']]}
r.animation_data.action=base;frame(1);r.animation_data.action=ready;reference=evaluate(1)
results={};checks={};max_total=0
for name,N,loop in [('jump_takeoff_r1',10,False),('jump_air_r1',1,True),('jump_land_r1',16,False)]:
 a=bpy.data.actions[name]
 r.animation_data.action=base;frame(1);r.animation_data.action=a
 samples=[];max_wrist=[0.,0.];max_guard=[0.,0.];max_hand=[0.,0.];max_actor=[0.,0.];max_root=0.;max_camera=0.;max_armature=0.;endpoint={};max_bone=0.
 for k in range(N*2+1):
  f=1+k/2;e=evaluate(f);inv=e['root'].inverted()
  for i,side in enumerate(['l','r']):
   max_wrist[i]=max(max_wrist[i],e['wrist_error'][i]);max_guard[i]=max(max_guard[i],e['guard_error_degrees'][i]);max_hand[i]=max(max_hand[i],diff(e['hands'][side],reference['hands'][side]))
  for i,actor in enumerate(['hk416_weapon','hk416_magazine']):max_actor[i]=max(max_actor[i],diff(inv@e['actors'][actor],reference['root'].inverted()@reference['actors'][actor]))
  max_root=max(max_root,diff(e['player_root'],reference['player_root']));max_camera=max(max_camera,diff(e['camera'],reference['camera']));max_armature=max(max_armature,diff(e['armature'],reference['armature']))
  for b in ['righthand_prop_lefthand','righthand_prop_righthand','lefthand_prop']:assert abs(float(r.pose.bones[b]['weapon_follow'])-1)<1e-7
  if k in (0,N*2):
   endpoint[str(f)]={'max_all_pose_bone_matrix_error_to_ready':max(diff(e['bones'][b],m) for b,m in reference['bones'].items()),'weapon_matrix_error_to_ready':diff(e['actors']['hk416_weapon'],reference['actors']['hk416_weapon']),'magazine_matrix_error_to_ready':diff(e['actors']['hk416_magazine'],reference['actors']['hk416_magazine'])}
  points={'muzzle':e['actors']['hk416_weapon']@Vector((-.000062,.090545,-.411509)),'receiver':e['actors']['hk416_weapon']@Vector((.020,.075,.020)),'support_wrist':r.matrix_world@e['bones']['hand_l'].translation,'firing_wrist':r.matrix_world@e['bones']['hand_r'].translation}
  screen={}
  for label,p in points.items():q=world_to_camera_view(s,camera,p);screen[label]={'x_norm':q.x,'y_norm':q.y,'depth':q.z,'in_frame':0<=q.x<=1 and 0<=q.y<=1 and q.z>0}
  samples.append({'frame':f,'screen_landmarks':screen})
 varying=[(fc.data_path,fc.array_index) for fc in a.fcurves if len({float(k.co.y) for k in fc.keyframe_points})>1]
 nonroot=[p for p,i in varying if p not in ['pose.bones["righthand_prop"].location','pose.bones["righthand_prop"].rotation_euler']]
 zero_end_tangents=all(abs(k.handle_left.y-k.co.y)<1e-8 and abs(k.handle_right.y-k.co.y)<1e-8 for fc in a.fcurves if fc.data_path in ['pose.bones["righthand_prop"].location','pose.bones["righthand_prop"].rotation_euler'] for k in [fc.keyframe_points[0],fc.keyframe_points[-1]])
 checks.update({name+'_range':list(a.frame_range)==[1,N+1],name+'_only_viewmodel_control_varies':not nonroot,name+'_grip_contacts':max(max_wrist)<1e-5 and max(max_hand)<1e-5 and max(max_actor)<1e-5,name+'_no_world_root_or_camera_motion':max_root==0 and max_camera==0 and max_armature==0,name+'_exact_ready_endpoints':all(max(row.values())<1e-6 for row in endpoint.values()),name+'_zero_endpoint_velocity':zero_end_tangents,name+'_baseline_visible_landmarks_retained':all(row['screen_landmarks'][k]['in_frame'] for row in samples for k in ['muzzle','receiver','support_wrist'])})
 if loop:checks[name+'_static_extendable_air']=not varying
 results[name]={'range':[1,N+1],'duration_seconds':N/60,'loop':loop,'sample_rate_hz':120,'sample_count':len(samples),'varying_curves':varying,'max_wrist_error_m':max_wrist,'max_guard_error_degrees':max_guard,'max_hand_to_root_matrix_drift':max_hand,'max_weapon_and_magazine_relative_root_matrix_drift':max_actor,'max_player_root_matrix_drift':max_root,'max_camera_matrix_drift':max_camera,'max_armature_world_matrix_drift':max_armature,'endpoints':endpoint,'samples':samples}
invalid=[o.name+':'+f.data_path for o in bpy.data.objects if o.animation_data for f in o.animation_data.drivers if not f.driver.is_valid]
checks['drivers_valid']=not invalid;checks['source_bytes_unchanged']=hashlib.sha256(path.read_bytes()).hexdigest()==sha
report={'schema':'rust-duty-jump-technical-validation/v1','source_sha256':sha,'blender':bpy.app.version_string,'fps':60,'camera':camera.name,'ready_baseline':{'action':ready.name,'frame':1},'actions':results,'invalid_drivers':invalid,'checks':checks,'passed':all(checks.values()),'limitations':['Technical checks only; no artistic rating or Elara acceptance','The firing-wrist anatomical origin is already below/right of the baseline camera frame; it is reported but not treated as a newly lost visible landmark','Absolute HIP source; ADS composition belongs to runtime integration','No render, game export, runtime controller edit, or game playback performed by this validator']}
out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':report['passed'],'checks':checks,'contact_summary':{name:{k:v for k,v in row.items() if k.startswith('max_') or k=='endpoints'} for name,row in results.items()}},indent=2))
assert report['passed'],'Technical jump validation failed'
