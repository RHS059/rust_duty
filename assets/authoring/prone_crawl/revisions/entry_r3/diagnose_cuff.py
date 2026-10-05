import bpy,json,math
from pathlib import Path
r=bpy.data.objects['Arms'];s=bpy.context.scene
for o in bpy.data.objects:
 if o.animation_data:
  o.animation_data.use_nla=False
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
r.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];s.frame_set(1);bpy.context.view_layer.update();r.animation_data.action=bpy.data.actions['prone_crawl_enter_r3'];rows=[]
for frame in [35,36,36.25,36.5,36.75,37,37.25,37.5,37.75,38,39]:
 s.frame_set(math.floor(frame),subframe=frame%1);bpy.context.view_layer.update()
 rows.append({'frame':frame,'bones':{n:{'location_keys':list(r.pose.bones[n].location),'head_world':list(r.matrix_world@r.pose.bones[n].matrix.translation),'tail_world':list(r.matrix_world@r.pose.bones[n].tail)} for n in ['righthand_prop','clavicle_l','upperarm_l','lowerarm_l','hand_l']}})
out={'action':'prone_crawl_enter_r3','native_source_frames':[2276,2277,2278],'rows':rows};Path('/workspace/shared/prone-entry-r3/cuff_after.json').write_text(json.dumps(out,indent=2))
for row in rows:
 if row['frame'] in [36,37,38]:print(json.dumps(row))
