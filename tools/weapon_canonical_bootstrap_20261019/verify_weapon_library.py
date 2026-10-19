import bpy,json,hashlib
from pathlib import Path
p=Path(bpy.data.filepath).parent
m=json.loads(bpy.data.texts['EXPORT_MANIFEST'].as_string());inventory=json.loads(bpy.data.texts['ALL_ANIMATION_INVENTORY'].as_string())
assert m['schema']=='rust-duty-weapon-nla/v1';assert len(m['clips'])==67
assert len(set(c['id'] for c in m['clips']))==len(m['clips'])
assert len(bpy.data.actions)==666 and all(a.use_fake_user for a in bpy.data.actions)
for c in m['clips']:
 s=bpy.data.scenes[c['scene']];rig=s.objects[c['rig']];t=rig.animation_data.nla_tracks[c['track_name']]
 assert len(t.strips)==1 and t.strips[0].action.name==c['action']
 assert set(c['objects']).issubset(set(o.name for o in s.objects))
 assert isinstance(c['frame_start'],int) and isinstance(c['frame_end'],int)
 assert len(c['objects'])==7 and set(c['object_name_map'])==set(c['objects'])
 assert set(c['object_name_map'].values())=={'Arms','Actual arms mesh 0','Actual arms mesh 1','Actual arms mesh 2','hk416_weapon','hk416_magazine','RD First Person Review'}
 assert len([o for o in s.objects if o.name in c['objects'] and o.type=='ARMATURE'])==1
 if c.get('camera_track_name'):assert s.objects[c['camera']].animation_data.nla_tracks[c['camera_track_name']].strips[0].action.name==c['camera_action']
 for comp in c['companion_tracks']:assert s.objects[comp['object']].animation_data.nla_tracks[comp['track_name']].strips[0].action.name==comp['action']
for r in inventory['sources']:
 assert hashlib.sha256((p/r['source']).read_bytes()).hexdigest()==r['sha256']
 assert all(name in bpy.data.actions for name in r['actions'].values())
assert all(i.packed_file for i in bpy.data.images if i.source=='FILE')
result={'status':'PASS','scope':'Saved-file reopen, source preservation, export mapping and dependency presence only. No numerical motion/runtime certification.','source_sets':len(inventory['sources']),'scene_count':len(bpy.data.scenes),'action_count':len(bpy.data.actions),'export_clip_count':len(m['clips']),'packed_image_count':sum(bool(i.packed_file) for i in bpy.data.images),'default_scene':bpy.context.scene.name,'source_files_unchanged':True,'canonical_file':'assets/authoring/weapon_animations.blend'}
(p/'WEAPON_LIBRARY_REOPEN_VERIFICATION.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
