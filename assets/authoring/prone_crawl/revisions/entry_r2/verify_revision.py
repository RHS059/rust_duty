import bpy,sys,json,math,hashlib
from pathlib import Path
import numpy as np
P=Path(__file__).parent;s=bpy.context.scene;r=bpy.data.objects['Arms']
for o in bpy.data.objects:
 if o.animation_data:
  o.animation_data.use_nla=False
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
poses={}; contacts=[]
for name in ['prone_crawl_enter_r1','prone_crawl_enter_r2']:
 r.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];s.frame_set(1);bpy.context.view_layer.update()
 r.animation_data.action=bpy.data.actions[name];data=[]
 for i in range(545):
  f=1+i/8;s.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update();data.append(np.array([list(map(list,b.matrix)) for b in r.pose.bones]))
  if name.endswith('r2'):contacts.append({side:(r.pose.bones['hand_'+side].matrix.translation-r.pose.bones['righthand_prop_'+('left' if side=='l' else 'right')+'hand'].matrix.translation).length for side in ['l','r']})
 poses[name]=np.array(data)
err=float(np.max(np.abs(poses['prone_crawl_enter_r1'][:321]-poses['prone_crawl_enter_r2'][:321])))
assert err==0.0,err
out={'source_sha256':hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),'early_f1_through_41_all_bones_max_difference':err,'all_545_subframe_bone_matrices_finite':all(np.isfinite(x).all() for x in poses.values()),'contact_480hz_max_m':{side:max(c[side] for c in contacts) for side in ['l','r']},'contact_240hz_max_m':{side:max(c[side] for c in contacts[::2]) for side in ['l','r']},'action_count':len(bpy.data.actions),'no_render':True}
assert out['all_545_subframe_bone_matrices_finite'] and max(out['contact_480hz_max_m'].values())<.0001
(P/'fresh_reopen_checks.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
