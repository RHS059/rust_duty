"""Read evaluated control metadata without rendering, executing Text, or saving source."""
import bpy,json,sys
from pathlib import Path
A=bpy.data.objects['Arms']; out={}
for p in A.pose.bones:
 if any(s in p.name.lower() for s in ['attach','hand','forearm','lowerarm','upperarm','pole']):
  out[p.name]={'parent':p.parent.name if p.parent else None,'rotation_mode':p.rotation_mode,'location':list(p.location),'rotation':list(p.rotation_euler),'custom':{k:v for k,v in p.items() if isinstance(v,(int,float,str))},'constraints':[]}
  for c in p.constraints:
   d={'type':c.type,'name':c.name}
   for k in ['target','subtarget','owner_space','target_space','influence','mute','mix_mode','use_offset','use_x','use_y','use_z','use_transform_limit','chain_count','pole_subtarget','pole_angle']:
    if hasattr(c,k):
     v=getattr(c,k);d[k]=v.name if hasattr(v,'name') else v
   out[p.name]['constraints'].append(d)
print('CONTROLS',json.dumps(out))
print('GUARDS',json.dumps({k:v for k,v in A.items() if 'guard' in k}))
print('DRIVERS',json.dumps([{'path':f.data_path,'index':f.array_index,'expression':f.driver.expression,'variables':[{'name':v.name,'type':v.type,'targets':[{'path':t.data_path,'bone':t.bone_target,'transform':t.transform_type} for t in v.targets]} for v in f.driver.variables]} for f in A.animation_data.drivers]))
