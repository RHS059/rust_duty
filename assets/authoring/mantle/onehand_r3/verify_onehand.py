"""Evaluate saved source, full skin, subframe switches, and protected weapon track. No render."""
import bpy,json,hashlib,math,sys,argparse
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
A=bpy.data.objects['Arms'];W=bpy.data.objects['hk416_weapon'];S=bpy.context.scene;D=json.loads((P/'design.json').read_text());start,end=D['source_window'];last=end-start
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update()
basis={p.name:p.matrix_basis.copy() for p in A.pose.bones};props={p.name:{k:v for k,v in p.items() if isinstance(v,(int,float,str))} for p in A.pose.bones}
guard=json.loads(A['wrist_guard_l']);base=guard['base_euler_deg']; limits=guard['absolute_limits_deg'];skin=[o for o in bpy.data.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==A for m in o.modifiers)]
def select(name,n):
 A.animation_data.action=None
 for p in A.pose.bones:
  p.matrix_basis=basis[p.name]
  for k,v in props[p.name].items():p[k]=v
 A.animation_data.action=bpy.data.actions[name];f=n-start+1;i=math.floor(f);S.frame_set(i,subframe=f-i);A.update_tag();bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();return dg
samples=sorted(set([start+i/16 for i in range((last-1)*16+1)]+[s+d for s in [D['detach_native'],D['reattach_native']] for d in [-.01,-.001,-.0001,0,.0001,.001,.01]]))
rows=[];weapon_delta=0;finite=True;all_valid=True;meshcount=0
for n in samples:
 select(D['prior_action'],n);oldw=np.asarray(W.matrix_world).copy()
 dg=select(D['action'],n);p=A.pose.bones;L=p['righthand_prop_lefthand'];w=np.asarray(W.matrix_world);weapon_delta=max(weapon_delta,float(np.max(abs(w-oldw))))
 hand=A.matrix_world@p['hand_l'].matrix;target=A.matrix_world@p['OUT_hand_target_l'].matrix;free_angles=[base[i]+float(L[k]) for i,k in enumerate(['wrist_flex','wrist_twist','wrist_deviation'])]
 raw=(p['MCH_attach_forearm_l'].matrix.inverted()@p['MCH_attach_goal_l'].matrix).to_euler('XYZ');f=float(L['weapon_follow']);delta=math.degrees(p['MCH_hand_guarded_l'].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_l'].matrix.to_quaternion()).angle)
 row={'native':n,'follow':f,'hand_position':list(hand.translation),'hand_quaternion':list(hand.to_quaternion()),'wrist_target_mm':(hand.translation-target.translation).length*1000,'attached_guard_delta_deg':delta if f>.999 else None,'free_guard_margin_deg':min(min(v-lo,hi-v) for v,(lo,hi) in zip(free_angles,limits)),'forearm_roll_deg':float(L['forearm_roll']),'raw_attached_deg':[math.degrees(v) for v in raw]};rows.append(row)
 finite=finite and all(math.isfinite(v) for b in p for r in b.matrix for v in r)
 all_valid=all_valid and all(c.driver.is_valid for o in bpy.data.objects if o.animation_data for c in o.animation_data.drivers)
 if abs(n*4-round(n*4))<1e-7:
  for obj in skin:
   ev=obj.evaluated_get(dg);m=ev.to_mesh();meshcount+=len(m.vertices);finite=finite and all(math.isfinite(v) for x in m.vertices for v in x.co);ev.to_mesh_clear()
max_step=max((np.linalg.norm(np.array(b['hand_position'])-a['hand_position'])*1000,a['native'],b['native']) for a,b in zip(rows,rows[1:]))
switches={}
for n in [D['detach_native'],D['reattach_native']]:
 a=next(r for r in rows if abs(r['native']-(n-.0001))<1e-7);b=next(r for r in rows if abs(r['native']-(n+.0001))<1e-7)
 from mathutils import Quaternion
 switches[str(n)]={'position_mm':float(np.linalg.norm(np.array(a['hand_position'])-b['hand_position'])*1000),'rotation_deg':math.degrees(Quaternion(a['hand_quaternion']).rotation_difference(Quaternion(b['hand_quaternion'])).angle)}
summary={'status':'diagnostic','source_sha256':hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),'samples':len(rows),'finite_skin_vertex_samples':meshcount,'all_finite':finite,'all_drivers_valid':all_valid,'weapon_matrix_max_component_delta':weapon_delta,'max_wrist_target_mm':max(r['wrist_target_mm'] for r in rows),'max_attached_guard_delta_deg':max(r['attached_guard_delta_deg'] or 0 for r in rows),'min_free_guard_margin_deg':min(r['free_guard_margin_deg'] for r in rows if r['follow']<.001),'max_hand_step_mm_and_interval':max_step,'switches':switches,'rendered':False,'visual_acceptance':None}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({'summary':summary,'samples':rows},indent=2)+'\n');print('ONEHAND_VERIFY',json.dumps(summary))
sys.path.insert(0,str(P))
from report_contract import validate
failures=validate(summary)
print('TECHNICAL_GATE_FAILURES',json.dumps(failures))
if failures:raise SystemExit(2)
from report_contract import validate_authoring
authoring=json.loads((P/'candidate/authoring_report.json').read_text())
authoring_failures=validate_authoring(authoring,summary['source_sha256'])
print('AUTHORING_GATE_FAILURES',json.dumps(authoring_failures))
if authoring_failures:raise SystemExit(2)
