"""Bounded v9 diagnostic: native articulation at 15%, unchanged v6 weapon map.
No rendering, source saving, camera/geometry/rest edits, or guard relaxation.
"""
import bpy, json, math, hashlib, os
from pathlib import Path
from mathutils import Matrix, Vector, Quaternion

HERE=Path(__file__).resolve().parent
ROOT=Path(__file__).resolve().parents[2]
ADS=ROOT/'ads/ads.blend'
HIP=Path(os.environ['ADS_V9_HIP_SOURCE'])
assert hashlib.sha256(ADS.read_bytes()).hexdigest()=='3acdf3e2d04757d719ba59ede08decdf8bad48e2e87d9448046fe8edcbba4f58'
assert hashlib.sha256(HIP.read_bytes()).hexdigest()=='36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d'
assert Path(bpy.data.filepath)==ADS
S=bpy.context.scene; A=bpy.data.objects['Arms']; W=bpy.data.objects['hk416_weapon']; CAM=bpy.data.objects['RD First Person Review']; C=CAM.matrix_world.copy()
BASE='RD_00_Supplied_Base_Guarded_Recovered'; READY='RD_Locomotion_Normal_Entry_4419_4434_WIP2'
A.animation_data.use_nla=False
for track in A.animation_data.nla_tracks:track.mute=True
A.animation_data.action=bpy.data.actions[BASE];S.frame_set(1);bpy.context.view_layer.update()
basis={p.name:p.matrix_basis.copy() for p in A.pose.bones}
def select(name,frame=1):
 A.animation_data.action=None
 for p in A.pose.bones:p.matrix_basis=basis[p.name].copy()
 A.animation_data.action=bpy.data.actions[BASE];S.frame_set(1);A.update_tag();bpy.context.view_layer.update()
 A.animation_data.action=bpy.data.actions[name];S.frame_set(math.floor(frame),subframe=frame%1);A.update_tag();bpy.context.view_layer.update()
def globals_now():return {p.name:A.matrix_world@p.matrix for p in A.pose.bones}
def blend(a,b,weight):
 at,aq,asc=a.decompose();bt,bq,bsc=b.decompose()
 return Matrix.LocRotScale(at.lerp(bt,weight),aq.slerp(bq,weight),asc.lerp(bsc,weight))
with bpy.data.libraries.load(str(HIP),link=False) as (_,data):data.actions=['hip_walk_forward_r5']
select(READY);ready=C.inverted()@W.matrix_world
select('ads_hold_r1');baseW=W.matrix_world.copy();base=globals_now();baseRel={n:baseW.inverted()@m for n,m in base.items()}
point=Vector((-6.210595893207937e-5,.11778369545936584,.07798250019550323));p0=C.inverted()@baseW@point;u0=p0.x/-p0.z;v0=p0.y/-p0.z
connected=[]
for side in ('l','r'):
 for parent,child in [('upperarm_'+side,'lowerarm_'+side),('lowerarm_'+side,'hand_'+side)]:
  offset=A.data.bones[parent].matrix_local.inverted()@A.data.bones[child].head_local
  connected.append((child,parent,offset))
def gaps(g):return {n:(g[n].translation-g[parent]@offset).length*1000 for n,parent,offset in connected}
baseGaps=gaps(base)
def guard(g,side):
 raw=[math.degrees(x) for x in (g['MCH_attach_forearm_'+side].inverted()@g['MCH_attach_goal_'+side]).to_euler('XYZ')]
 limits=json.loads(A['wrist_guard_'+side])['absolute_limits_deg']
 return min(min(v-lo,hi-v) for v,(lo,hi) in zip(raw,limits))
contract={'version':'v9_depth_phase_trial1','vertical_channel_native_offset_frames':19,'native_action':'hip_walk_forward_r5','hip_source_commit':'493c202477604892ee6d332fc24ef01e8703f1ae','status':'diagnostic, unreviewed','source_ads_sha256':hashlib.sha256(ADS.read_bytes()).hexdigest(),'source_hip_sha256':hashlib.sha256(HIP.read_bytes()).hexdigest(),'articulation_weight':.15,'weapon_policy':'v6 mapping with primary X and half-period native Y; no amplitude gain; primary phase4/5','hypothesis':'Use the same native forward curve at half-period offset only for the vertical optical target, to test the observed reversal of strong/weak cuff pulses. Primary clock, horizontal target and articulation remain unchanged.','protected':'Original source files, camera, geometry, skin weights, rest, authored Actions, wrist limits and native phase ordering.','stop_condition':'Report contact, wrist-limit or connected-joint defects without widening limits. Preserve this failed or successful source checkpoint. No fidelity claim from numerical checks.'}
(HERE/'v9_contract.json').write_text(json.dumps(contract,indent=2)+'\n')
rows=[];worst=None
for i in range(501):
 f=i/4;native=1+((f+5.75)*.8)%38;select('hip_walk_forward_r5',native);walkW=W.matrix_world.copy();walk=globals_now();walkRel={n:walkW.inverted()@m for n,m in walk.items()}
 delta=(C.inverted()@walkW)@ready.inverted();full=Quaternion().slerp(delta.to_quaternion(),.4).to_matrix().to_4x4();full.translation=delta.translation*.4;target=full@p0
 select('hip_walk_forward_r5',1+((f+5.75)*.8+19)%38)
 aux_delta=(C.inverted()@W.matrix_world)@ready.inverted();aux_full=Quaternion().slerp(aux_delta.to_quaternion(),.4).to_matrix().to_4x4();aux_full.translation=aux_delta.translation*.4;aux_target=aux_full@p0
 select('hip_walk_forward_r5',1+((f+5.75)*.8)%38)
 u=u0+(target.x/-target.z-u0)*.25;v=aux_target.y/-aux_target.z;theta=math.atan2(v,u)-math.atan2(p0.y,p0.x);theta=math.atan2(math.sin(theta),math.cos(theta));depth=-math.hypot(p0.x,p0.y)/math.hypot(u,v)-p0.z
 offset=Matrix.Rotation(theta,4,'Z');offset.translation=Vector((0,0,depth));anchor=(C@offset@C.inverted())@baseW
 candidate={n:anchor@blend(baseRel[n],walkRel[n],.15) for n in base}
 cg=gaps(candidate);wg=gaps(walk);contact={}
 for side in ('l','r'):
  actual=anchor.inverted()@candidate['hand_'+side];expected=baseRel['hand_'+side]
  contact[side]={'translation_mm':(actual.translation-expected.translation).length*1000,'angle_degrees':math.degrees(actual.to_quaternion().rotation_difference(expected.to_quaternion()).angle),'raw_guard_margin_degrees':guard(candidate,side)}
 row={'output_frame':f,'native_frame':native,'hands':contact,'max_connected_gap_mm':max(cg.values(),default=0),'max_input_connected_gap_mm':max([*baseGaps.values(),*wg.values()],default=0),'worst_connected_bone':max(cg,key=cg.get) if cg else None}
 rows.append(row)
 if worst is None or row['max_connected_gap_mm']>worst['max_connected_gap_mm']:worst={**row,'candidate_globals':{n:[list(r) for r in m] for n,m in candidate.items()},'weapon_world':[list(r) for r in anchor]}
summary={'sample_count':len(rows),'max_hand_translation_mm':max(h['translation_mm'] for r in rows for h in r['hands'].values()),'max_hand_angle_degrees':max(h['angle_degrees'] for r in rows for h in r['hands'].values()),'min_raw_guard_margin_degrees':min(h['raw_guard_margin_degrees'] for r in rows for h in r['hands'].values()),'max_connected_gap_mm':max(r['max_connected_gap_mm'] for r in rows),'max_input_connected_gap_mm':max(r['max_input_connected_gap_mm'] for r in rows),'connected_deform_pairs':len(connected),'rendered':False,'source_files_unchanged':hashlib.sha256(ADS.read_bytes()).hexdigest()==contract['source_ads_sha256'] and hashlib.sha256(HIP.read_bytes()).hexdigest()==contract['source_hip_sha256'],'camera_unchanged':[list(r) for r in CAM.matrix_world]==[list(r) for r in C]}
(HERE/'v9_articulation_probe.json').write_text(json.dumps({'summary':summary,'samples':rows,'worst':worst},indent=2)+'\n');print(json.dumps(summary),flush=True)
