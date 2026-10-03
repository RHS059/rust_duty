"""Read-only new Action structure and cyclic key checks."""
import bpy,json,sys,math
from pathlib import Path
out=Path(sys.argv[sys.argv.index('--')+1]);r={};prefix='pose.bones["righthand_prop"].'
for name,N in [('hip_walk_forward_r5',38),('hip_walk_backward_r5',45)]:
 a=bpy.data.actions[name];vary=[];curves=[]
 for fc in a.fcurves:
  values=[k.co.y for k in fc.keyframe_points]
  assert all(math.isfinite(x) for x in values)
  if values and max(values)-min(values)>1e-8:vary.append([fc.data_path,fc.array_index])
  if fc.data_path.startswith(prefix) and fc.data_path[len(prefix):] in ['location','rotation_euler']:
   keys=fc.keyframe_points;assert len(keys)==N+1 and keys[0].co.x==1 and keys[-1].co.x==N+1 and keys[0].co.y==keys[-1].co.y
   assert any(m.type=='CYCLES' for m in fc.modifiers)
   s0=(keys[0].handle_right.y-keys[0].co.y)/(keys[0].handle_right.x-keys[0].co.x);s1=(keys[-1].handle_right.y-keys[-1].co.y)/(keys[-1].handle_right.x-keys[-1].co.x)
   curves.append({'path':fc.data_path,'index':fc.array_index,'keys':len(keys),'endpoint_value_error':float(keys[-1].co.y-keys[0].co.y),'endpoint_tangent_error_float':float(s1-s0)})
 assert len(vary)==6 and all(p.startswith(prefix) for p,i in vary);assert len(curves)==6
 assert max(abs(c['endpoint_tangent_error_float']) for c in curves)<1e-7
 r[name]={'varied_channels':vary,'root_cyclic_curves':curves,'fake_user':a.use_fake_user,'loop_period_frames':a['loop_period_frames']}
assert len(bpy.data.actions)==80
out.write_text(json.dumps({'action_count':len(bpy.data.actions),'actions':r},indent=2)+'\n');print(json.dumps({'action_count':len(bpy.data.actions),'new_action_names':list(r),'only_six_root_channels_vary':True,'root_endpoint_values_exact':True,'endpoint_tangent_max_error':max(abs(c['endpoint_tangent_error_float']) for a in r.values() for c in a['root_cyclic_curves'])}))
