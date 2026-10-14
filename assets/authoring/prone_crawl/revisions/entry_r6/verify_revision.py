"""Fresh-reopen numerical audit of r6 pair; no rendering or source writes."""
import bpy,sys,json,math,hashlib
from pathlib import Path
import numpy as np
from mathutils import Matrix,Vector
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P))
from source_integrity import snapshot,action_fingerprint
from validate_source_structure import extra_snapshot
from motion_design import parameters,validate_config
c=json.loads((P/'correction_design.json').read_text());validate_config(c)
baseline=json.loads((P/'baseline_preservation.json').read_text());actual=json.loads(json.dumps({'snapshot':snapshot(bpy),'extra':extra_snapshot()},sort_keys=True));preservation={}
for section in ('snapshot','extra'):
 for key,value in baseline[section].items():
  preservation[section+'.'+key]=all(actual[section][key].get(n)==v for n,v in value.items()) if key in ('actions','actions_metadata','actions_extended') else actual[section][key]==value
assert all(preservation.values()),preservation
assert len(bpy.data.actions)==114
assert set(actual['snapshot']['actions'])-set(baseline['snapshot']['actions'])=={c['action'],c['camera_action']}
s=bpy.context.scene;r=bpy.data.objects[c['armature_object']];cam=bpy.data.objects[c['camera_object']];weapon=bpy.data.objects['hk416_weapon'];ground=bpy.data.objects['RD_REFERENCE_ONLY | Ground']
assert cam.animation_data is None
preservation['object_defaults']=all(all(list(getattr(bpy.data.objects[n],k))==v for k,v in vals.items()) for n,vals in baseline['object_defaults'].items())
assert preservation['object_defaults']
for o in bpy.data.objects:
 if o.animation_data:
  o.animation_data.use_nla=False
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
R=r.matrix_world.copy();C=cam.matrix_world.copy();Ci=C.inverted();ground0=ground.matrix_world.copy();weaponbase=weapon.matrix_world.copy()
r.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];s.frame_set(1);bpy.context.view_layer.update()
baseprops={b.name:{k:v for k,v in b.items() if isinstance(v,(int,float,str))} for b in r.pose.bones}
basis={b.name:b.matrix_basis.copy() for b in r.pose.bones}
r.animation_data.action=bpy.data.actions[c['prior_action']];s.frame_set(1);bpy.context.view_layer.update()
local={n:list((R@r.pose.bones['righthand_prop'].matrix).inverted()@C@Vector(v)) for n,v in {'optic':(.08323424182818288,.005083007134545519,-.26023809868713904),'receiver':(.09500017721109932,-.042628284646006105,-.24942498919420647),'support':(.00935299787670374,-.10889146476984024,-.465015172958374)}.items()}
report=json.loads((P/'revision_report.json').read_text());expected=report['rows']
fm=json.loads((P/'frame_map.json').read_text());assert fm['blend_sha256']==hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()
assert all(action_fingerprint(bpy.data.actions[n])==v for n,v in fm['actions'].items())
contacts=[];oldposes=[];newposes=[];oldguard=[];newguard=[];rows=[];finite_skin=0;onscreen_below_ground=[]
def reset(action, camera_action):
 r.animation_data.action=None;r.matrix_world=R
 for b in r.pose.bones:
  b.matrix_basis=basis[b.name]
  for k,v in baseprops[b.name].items():b[k]=v
 if cam.animation_data:cam.animation_data_clear()
 cam.matrix_world=C
 r.animation_data.action=bpy.data.actions[action]
 if camera_action:
  cam.animation_data_create();cam.animation_data.action=bpy.data.actions[camera_action]

def guard():
 angles={side:math.degrees(r.pose.bones['MCH_hand_guarded_'+side].matrix.to_quaternion().rotation_difference(r.pose.bones['MCH_attach_goal_'+side].matrix.to_quaternion()).angle) for side in ('l','r')}
 return {side:min(angle,360-angle) for side,angle in angles.items()}
for old in (True,False):
 reset(c['prior_action'] if old else c['action'],None if old else c['camera_action'])
 for i in range(545):
  f=1+i/8;s.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update()
  pose=np.array([list(map(list,b.matrix)) for b in r.pose.bones]);assert np.isfinite(pose).all()
  (oldposes if old else newposes).append(pose);(oldguard if old else newguard).append(guard())
  if old:continue
  pts={n:cam.matrix_world.inverted()@r.matrix_world@r.pose.bones['righthand_prop'].matrix@Vector(v) for n,v in local.items()}
  xy={n:[640+819.1626469882023*q.x/-q.z,360-819.1626469882023*q.y/-q.z] for n,q in pts.items()}
  errors={side:(r.pose.bones['hand_'+side].matrix.translation-r.pose.bones['righthand_prop_'+('left' if side=='l' else 'right')+'hand'].matrix.translation).length for side in ('l','r')};contacts.append(errors)
  cmerr=float(np.max(abs(np.array(cam.matrix_world)-np.array(expected[i]['camera_world']))));rmerr=float(np.max(abs(np.array(r.matrix_world)-np.array(expected[i]['rig_world']))))
  assert cmerr<1e-6 and rmerr<1e-6,(f,cmerr,rmerr)
  assert np.array_equal(np.array(ground.matrix_world),np.array(ground0)),f
  assert all(d.driver.is_valid for o in bpy.data.objects if o.animation_data for d in o.animation_data.drivers)
  projection_error=max(abs(x-y) for x,y in zip(xy['optic'],expected[i]['optic_target_pixels']))
  assert projection_error<.002,(f,projection_error)
  row={'frame':f,'camera_z':cam.matrix_world.translation.z,'camera_height_above_ground':cam.matrix_world.translation.z-ground.matrix_world.translation.z,'projected_guides':xy,'optic_target_error_px':projection_error,'wrist_guard_degrees':guard(),'camera_world':[list(v) for v in cam.matrix_world],'common_world_delta':[list(v) for v in cam.matrix_world@Ci]}
  if f.is_integer() and int(f) in (1,12,20,21,28,32,35,41,45,55,69):
   row['onscreen_vertices_below_ground']={}
   for obj in [o for o in bpy.data.objects if o.type=='MESH' and (o.name.startswith('Actual arms mesh') or o.name in ('hk416_weapon','hk416_magazine'))]:
    ev=obj.evaluated_get(dg);mesh=ev.to_mesh();coords=np.array([list(ev.matrix_world@v.co) for v in mesh.vertices]);assert np.isfinite(coords).all();finite_skin+=len(mesh.vertices)
    count=0
    for v in mesh.vertices:
     w=ev.matrix_world@v.co;q=cam.matrix_world.inverted()@w
     if q.z<-.01:
      u=640+819.1626469882023*q.x/-q.z;vv=360-819.1626469882023*q.y/-q.z
      if 0<=u<1280 and 0<=vv<720 and w.z<ground.matrix_world.translation.z-.001:count+=1
    row['onscreen_vertices_below_ground'][obj.name]=count;ev.to_mesh_clear()
   onscreen_below_ground.append({'frame':f,'counts':row['onscreen_vertices_below_ground']})
  rows.append(row)
early=float(np.max(abs(np.array(oldposes[:81])-np.array(newposes[:81]))));assert early==0.,early
maxcontact={side:max(v[side] for v in contacts) for side in ('l','r')};assert max(maxcontact.values())<.0001,maxcontact
maxguard={side:max(v[side] for v in newguard) for side in ('l','r')};oldmaxguard={side:max(v[side] for v in oldguard) for side in ('l','r')}
summary={'candidate_sha256':hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),'actions':fm['actions'],'action_count':len(bpy.data.actions),'sample_count':len(rows),'fresh_reopen_preservation':preservation,'protected_f1_to_11_all_bone_max_difference':early,'all_bone_matrices_finite':True,'all_drivers_valid':True,'contact_480hz_max_m':maxcontact,'old_wrist_guard_max_deg':oldmaxguard,'new_wrist_guard_max_deg':maxguard,'strict_wrist_guard_threshold_deg':0.08,'strict_wrist_guard_pass':max(maxguard.values())<=.08,'wrist_guard_non_regression_pass':all(n[side]<=o[side]+.05 for n,o in zip(newguard,oldguard) for side in ('l','r')), 'max_wrist_guard_increase_deg':{side:max(n[side]-o[side] for n,o in zip(newguard,oldguard)) for side in ('l','r')},'min_camera_height_above_ground_m':min(r['camera_height_above_ground'] for r in rows),'max_optic_projection_error_px':max(r['optic_target_error_px'] for r in rows),'finite_evaluated_vertex_samples':finite_skin,'ground_intersection_probes':onscreen_below_ground,'no_render':True,'visual_pass':None}
(P/'fresh_reopen_checks.json').write_text(json.dumps({'summary':summary,'rows':rows},indent=2));print(json.dumps(summary,indent=2))
sidecar={'schema':'prone-entry-r6-camera-motion/v1','candidate_sha256':summary['candidate_sha256'],'action_fingerprints':fm['actions'],'units':'metres and radians; Blender world +Z up','camera_local_axes':'+X right, +Y up, -Z forward','initial_camera_world':[list(v) for v in C],'initial_camera_height_above_ground_m':1.600000023841858,'sample_hz':480,'fps':60,'time_seconds':'(candidate_frame-1)/60; no retiming','duration_key_span_seconds':68/60,'encoded_native_69_frame_duration_seconds':69/60,'runtime_binding':'NOT IMPLEMENTED. Height is a replacement track during the clip, never additive to generic stance easing. For continuous runtime endpoints use height = entry_eye_height + normalized_depth_fraction * (prone_eye_height-entry_eye_height). The source preview itself keeps its exact authored matrices. Strip common object co-motion from camera-relative weapon export.', 'height_contract':{'mode':'replace_stance_height_during_clip','source_endpoint_descent_m':1.26,'normalized_depth_fraction':'(initial_camera_world_Z - current_camera_world_Z)/1.26','runtime_formula':'entry_eye_height + normalized_depth_fraction * (target_prone_eye_height - entry_eye_height)','allow_impact_overshoot':True,'runtime_target_prone_eye_height_m':0.2794,'end_behavior':'hold final Action sample while this clip owns the view; release height ownership continuously to the same prone-height target','integration_status':'contract only; no runtime implementation'},'rows':[{'candidate_frame':x['frame'],'time_seconds':(x['frame']-1)/60,'camera_world':x['camera_world'],'common_world_delta':x['common_world_delta'],'height_above_source_ground_m':x['camera_height_above_ground'],'normalized_depth_fraction':(C.translation.z-x['camera_z'])/1.26} for x in rows]}
(P/'camera_motion_samples.json').write_text(json.dumps(sidecar,indent=2))
from report_contract import validate
failures=validate(summary);assert not failures,failures
