import bpy,sys,json
from pathlib import Path
O=Path(sys.argv[sys.argv.index('--')+1]);O.mkdir(parents=True,exist_ok=True)
P='pose.bones["righthand_prop"].';report={}
def curve(fc):return {'path':fc.data_path,'idx':fc.array_index,'extrapolation':fc.extrapolation,'keys':[(list(k.co),list(k.handle_left),list(k.handle_right),k.interpolation,k.handle_left_type,k.handle_right_type) for k in fc.keyframe_points],'modifiers':[(m.type,m.show_expanded,m.active,m.mute) for m in fc.modifiers]}
for side in ['left','right']:
 a=bpy.data.actions['hip_strafe_'+side+'_r4'];b=bpy.data.actions['hip_strafe_'+side+'_r5'];old={(f.data_path,f.array_index):f for f in a.fcurves};new={(f.data_path,f.array_index):f for f in b.fcurves}
 assert set(old)==set(new)
 untouched=[key for key in old if key[0] not in [P+'location',P+'rotation_euler']];assert all(curve(old[k])==curve(new[k]) for k in untouched)
 rotmax=max(abs(old[(P+'rotation_euler',j)].evaluate(1+k/8)-new[(P+'rotation_euler',j)].evaluate(1+k/8)) for j in range(3) for k in range(49*8+1))
 endpoint_tangent_errors=[]
 for prop in ['location','rotation_euler']:
  for j in range(3):
   fc=new[(P+prop,j)];first,last=fc.keyframe_points[0],fc.keyframe_points[-1];assert first.co.y==last.co.y
   d0=(first.handle_right.y-first.co.y)/(first.handle_right.x-first.co.x);d1=(last.co.y-last.handle_left.y)/(last.co.x-last.handle_left.x);endpoint_tangent_errors.append(abs(d0-d1))
   assert any(m.type=='CYCLES' for m in fc.modifiers)
 report[side]={'nonroot_curves_preserved_exactly':len(untouched),'root_rotation_max_r4_r5_difference_radians_at480hz':rotmax,'max_loop_root_curve_tangent_numeric_error_per_frame':max(endpoint_tangent_errors),'root_curve_endpoints_exact':True,'root_curve_cycles_present':True}
 if side=='right':assert rotmax<1e-6
(O/'curve_contract.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
