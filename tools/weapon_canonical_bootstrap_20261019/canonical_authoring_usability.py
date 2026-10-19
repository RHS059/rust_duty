"""Set editor playback switches and manifest-derived labels; never edit motion."""
import json
FIELDS=('canonical_status','export_id','source_set','canonical_exports')
GUIDANCE='''\nCANONICAL EDITOR PLAYBACK AND STATUS\nChoose a LIBRARY scene, then unmute/solo the desired EXPORT::<id> on the rig and its same-named companion tracks (including the declared paired camera). Keep other export and ARCHIVE tracks muted. Active Actions are empty, so NLA is the sole playback source. After changing clips, set scene Start/End to frame_start/frame_end in EXPORT_MANIFEST; the saved scene range belongs to its initial selected clip. For example LOCOMOTION initially shows normal_ready at 1-2; normal_loop needs 1-36. PRONE initially shows jump_takeoff at 1-12; prone_entry needs 1-69 and forward crawl 1-241.\n\nAction properties canonical_status, export_id and source_set summarize the embedded export manifest. canonical_exports preserves each exact clip/status/source association, including aliases. These labels repeat existing manifest status; they do not grant new artistic or gameplay approval. All other inherited Action properties remain unchanged historical authoring notes and may predate the manifest's recorded review. WIP and diagnostic status is unchanged.\n\nHistorical revisions may exist only as retained Actions, not ARCHIVE tracks. Use ALL_ANIMATION_INVENTORY to identify the source scene and mapped Action. To inspect one, disable export tracks, assign the historical Action on its proper rig or camera in Action Editor, and use its frame range. Restore the export setup afterward. HIP_R1 and ADS_V9 | 1 are retained archive scenes with no canonical export selection.\n'''
def owners(scene):
 seen=set()
 for obj in scene.objects:
  for owner in (obj,obj.data,getattr(obj.data,'shape_keys',None)):
   if owner is not None and owner.as_pointer() not in seen:
    seen.add(owner.as_pointer())
    if getattr(owner,'animation_data',None):yield owner

def apply(bpy):
 m=json.loads(bpy.data.texts['EXPORT_MANIFEST'].as_string());inv=json.loads(bpy.data.texts['ALL_ANIMATION_INVENTORY'].as_string())
 tags={s['source']:s['tag'] for s in inv['sources']};records={};enabled=[]
 for clip in m['clips']:
  scene=bpy.data.scenes[clip['scene']]
  for owner in owners(scene):
   ad=owner.animation_data
   if any(t.name==clip['track_name'] or (clip.get('camera_track_name') and t.name==clip['camera_track_name']) for t in ad.nla_tracks):
    if ad.action is not None:raise ValueError('Active Action would mix with NLA: '+owner.name)
    if not ad.use_nla:enabled.append(owner.name)
    ad.use_nla=True
  for action in [clip['action']]+([clip['camera_action']] if clip.get('camera_action') else []):
   records.setdefault(action,[]).append({'export_id':clip['id'],'canonical_status':clip['status'],'source_set':tags[clip['source_file']]})
 for name,rows in records.items():
  a=bpy.data.actions[name]
  a['export_id']=', '.join(dict.fromkeys(r['export_id'] for r in rows))
  a['canonical_status']=' | '.join(dict.fromkeys(r['canonical_status'] for r in rows))
  a['source_set']=', '.join(dict.fromkeys(r['source_set'] for r in rows))
  a['canonical_exports']=json.dumps(rows,sort_keys=True)
 readme=bpy.data.texts['WEAPON_LIBRARY_README']
 if 'CANONICAL EDITOR PLAYBACK AND STATUS' not in readme.as_string():readme.write(GUIDANCE)
 return {'enabled_nla_owners':sorted(set(enabled)),'labeled_actions':len(records)}

def verify(bpy):
 m=json.loads(bpy.data.texts['EXPORT_MANIFEST'].as_string());inv=json.loads(bpy.data.texts['ALL_ANIMATION_INVENTORY'].as_string());tags={s['source']:s['tag'] for s in inv['sources']}
 for clip in m['clips']:
  sc=bpy.data.scenes[clip['scene']]
  for owner in owners(sc):
   ad=owner.animation_data
   if any(t.name==clip['track_name'] or (clip.get('camera_track_name') and t.name==clip['camera_track_name']) for t in ad.nla_tracks):
    assert ad.use_nla and ad.action is None,(clip['id'],owner.name)
  for name in [clip['action']]+([clip['camera_action']] if clip.get('camera_action') else []):
   rows=json.loads(bpy.data.actions[name]['canonical_exports'])
   assert {'export_id':clip['id'],'canonical_status':clip['status'],'source_set':tags[clip['source_file']]} in rows
 assert 'CANONICAL EDITOR PLAYBACK AND STATUS' in bpy.data.texts['WEAPON_LIBRARY_README'].as_string()
