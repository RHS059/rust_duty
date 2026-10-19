import bpy,json,hashlib,sys
from pathlib import Path
P=Path(__file__).resolve().parent
sys.path.insert(0,str(P));import jump_landing_patch as jump_patch
bpy.ops.wm.read_factory_settings(use_empty=True);blank=list(bpy.data.scenes)
inputs=[('VAULT','low-vault-current.blend'),('ONEHAND','onehand-current.blend'),('PRONE','prone-entry-current.blend')]
repo=json.loads((P/'REPOSITORY_SOURCE_INPUTS.json').read_text())
for row in repo:
 path=row['path'];tag='ADS' if '/ads/' in path else 'LOCOMOTION' if '/locomotion/' in path else 'ADS_V9' if '/locomotion_ads/' in path else 'HIP_R5' if '/r5/' in path else 'HIP_R1' if '/locomotion_directional/' in path else 'RELOAD'
 inputs.append((tag,row['local_name']))
records=[];groups={};historical=[]
for tag,filename in inputs:
 with bpy.data.libraries.load(str(P/filename),link=False) as (src,dst):
  names=list(src.actions);dst.actions=list(names);dst.scenes=list(src.scenes)
 acts=dict(zip(names,dst.actions));scenes=dst.scenes
 for a in acts.values():a.use_fake_user=True
 for si,sc in enumerate(scenes):sc.name='LIBRARY | '+tag+(' | '+str(si+1) if len(scenes)>1 else '')
 scene=next((s for s in scenes if any(o.name.startswith('DIAG_V9_Arms') for o in s.objects)),scenes[0]) if tag=='ADS_V9' else scenes[0]
 rig=next(o for o in scene.objects if o.type=='ARMATURE' and (o.name.startswith('DIAG_V9_Arms') if tag=='ADS_V9' else o.name.split('.')[0]=='Arms'))
 originals={o.name:o.animation_data.action for sc in scenes for o in sc.objects if o.animation_data and o.animation_data.action}
 for sc in scenes:
  for o in sc.objects:
   if o.animation_data:
    for t in o.animation_data.nla_tracks:
     if not t.name.startswith('ARCHIVE::'):t.name='ARCHIVE::'+t.name
     t.is_solo=False;t.mute=True
 groups[tag]={'scene':scene,'rig':rig,'actions':acts,'originals':originals,'scenes':scenes,'source':filename}
 records.append({'tag':tag,'source':filename,'bytes':(P/filename).stat().st_size,'sha256':hashlib.sha256((P/filename).read_bytes()).hexdigest(),'scenes':[s.name for s in scenes],'actions':{k:v.name for k,v in acts.items()}})
for s in blank:bpy.data.scenes.remove(s)
# Materialize only the previously reviewed two-key r8 recipe on a retained r7 copy.
g=groups['PRONE'];r8=g['actions']['jump_land_r7'].copy();r8.name='jump_land_r8_ease_candidate';r8.use_fake_user=True
jump_patch._apply_key_recipe(r8);g['actions']['jump_land_r8_ease_candidate']=r8
clips=[]
def track(obj,name,action,start,end,freeze=None):
 obj.animation_data_create();t=obj.animation_data.nla_tracks.new();t.name=name;t.mute=True
 st=t.strips.new(name,int(start),action);st.action_frame_start=start;st.action_frame_end=max(start+0.001,end);st.frame_start=start;st.frame_end=max(start+0.001,end);st.blend_type='REPLACE';st.extrapolation='HOLD';st.use_auto_blend=False;st.influence=1
 if freeze is not None:st.use_animated_time=True;st.strip_time=freeze
 return t

def add(tag,id,action,start=None,end=None,cam=None,freeze=None,status='existing authored animation'):
 assert not any(c['id']==id for c in clips)
 g=groups[tag];s=g['scene'];rig=g['rig'];a=g['actions'][action]
 start=float(a.frame_range[0]) if start is None else start;end=float(a.frame_range[1]) if end is None else end
 assert float(start).is_integer() and float(end).is_integer();start=int(start);end=int(end)
 tn='EXPORT::'+id;track(rig,tn,a,start,end,freeze)
 base_names={'Arms','Actual arms mesh 0','Actual arms mesh 1','Actual arms mesh 2','hk416_weapon','hk416_magazine'}
 def original_name(o):
  n=o.name.rsplit('.',1)[0] if o.name.rsplit('.',1)[-1].isdigit() else o.name
  return n[len('DIAG_V9_'):] if tag=='ADS_V9' and n.startswith('DIAG_V9_') else n
 objs=[o for o in s.objects if original_name(o) in base_names and (o.name.startswith('DIAG_V9_') if tag=='ADS_V9' else not o.name.startswith('DIAG_V9_'))]
 assert len(objs)==6
 if s.camera and s.camera not in objs:objs.append(s.camera)
 if id=='reload_current_wip':
  outgoing=next(o for o in s.objects if original_name(o)=='hk416_magazine_outgoing')
  objs.append(outgoing)
 companions=[]
 for o in objs:
  if o==rig or o==s.camera:continue
  old=g['originals'].get(o.name)
  if old:track(o,tn,old,start,end,freeze);companions.append({'object':o.name,'action':old.name,'track_name':tn})
 row={'id':id,'scene':s.name,'rig':rig.name,'track_name':tn,'action':a.name,'source_action':action,'source_file':g['source'],'frame_start':start,'frame_end':end,'fps':s.render.fps,'fps_base':s.render.fps_base,'objects':[o.name for o in objs],'object_name_map':{o.name:original_name(o) for o in objs},'status':status,'companion_tracks':companions}
 if freeze is not None:row['freeze_at_source_frame']=freeze
 if s.camera:row['camera']=s.camera.name
 if cam:
  track(s.camera,tn,g['actions'][cam],start,end);row['camera_track_name']=tn;row['camera_action']=g['actions'][cam].name
 clips.append(row)

for tag,config in [('LOCOMOTION','locomotion'),('ADS','ads'),('HIP_R5','directional'),('PRONE','jump')]:
 for take in json.loads((P/(config+'-export-config.json')).read_text())['source_takes']:
  add(tag,take['name'],take['action'],take['frame_start'],take['frame_end'],freeze=take.get('freeze_at_source_frame'),status=take.get('role','authored'))
add('LOCOMOTION','normal_settle','RD_Normal_Exit_Connected',1,25,status='existing runtime alias of normal_exit_connected')
add('VAULT','low_vault','aella_vault_low_entry_reconstructed_v3',1,64,status='Elara83 PASS')
add('ONEHAND','onehand_mantle','aella_mantle_onehand_r6_camera_reconstructed_v6',1,96,status='Elara81 PASS')
add('PRONE','prone_entry','aella_prone_crawl_enter_r15_roll_v1',1,69,cam='aella_prone_crawl_enter_camera_r9_viewray_v3',status='Elara82 PASS')
for name in ['prone_crawl_forward_segment_r1','prone_crawl_backward_segment_r1','prone_crawl_left_segment_r1','prone_crawl_right_segment_r1']:add('PRONE',name,name,status='existing authored crawl segment')
for id,action,start,end,status in [('reload_current_wip','RD_Reload_Tactical_HandApproach_AndReturn_WIP',1,157,'full authored WIP; not approved finished reload'),('reload_opening_wip','RD_Reload_Tactical_Hands_Opening_WIP',1,31,'separate authored opening WIP'),('canonical_reset','RD_00_Supplied_Base_Guarded_Recovered',1,1,'static reset'),('pickup_pose_inspection','RD_Pose_Tactical_Pickup54_Guarded',55,55,'static pose')]:add('RELOAD',id,action,start,end,status=status)
add('ADS_V9','ads_walk_forward_v9_diagnostic','DIAG_v9_forward_native15_output',1,126,status='unreviewed existing diagnostic WIP; not artistic approval')
# Clear active Actions so selected export tracks drive playback without double application.
for o in bpy.data.objects:
 if o.animation_data:o.animation_data.action=None
for tag,g in groups.items():
 selected=next((c for c in clips if c['scene']==g['scene'].name),None)
 if selected:
  for o in g['scene'].objects:
   if o.animation_data:
    for t in o.animation_data.nla_tracks:t.mute=t.name!=selected['track_name']
  g['scene'].frame_start=int(selected['frame_start']);g['scene'].frame_end=int(selected['frame_end']);g['scene'].frame_set(int(selected['frame_start']))
bpy.context.window.scene=groups['VAULT']['scene']
bpy.ops.file.pack_all()
missing=[{'name':i.name,'filepath':i.filepath} for i in bpy.data.images if i.source=='FILE' and not i.packed_file]
manifest={'schema':'rust-duty-weapon-nla/v1','clips':clips,'unavailable_not_authored':['fire','empty_reload','tactical_sprint','slide','dive','mount','ledge','pistol','pull_up','hang_drop'],'notes':['All historical source Actions retained with fake users. ARCHIVE tracks are not canonical exports.','Approved deterministic jump landing r8 recipe materialized on a copy; original r7 retained.','normal_settle is an existing runtime alias, not new animation.','Authored WIP and diagnostic status is retained honestly. No new artistic or gameplay approval.']}
allactions=[{'name':a.name,'frames':list(a.frame_range),'fake_user':a.use_fake_user} for a in bpy.data.actions]
report={'sources':records,'actions':allactions,'action_count':len(allactions),'scene_count':len(bpy.data.scenes),'object_count':len(bpy.data.objects),'export_clip_count':len(clips),'packed_image_count':sum(bool(i.packed_file) for i in bpy.data.images),'missing_images':missing,'jump_patch':jump_patch.PATCH_PROVENANCE}
for name,data in [('EXPORT_MANIFEST',manifest),('ALL_ANIMATION_INVENTORY',report)]:
 t=bpy.data.texts.new(name);t.write(json.dumps(data,indent=2));(P/(name+'.json')).write_text(json.dumps(data,indent=2))
t=bpy.data.texts.new('WEAPON_LIBRARY_README');t.write('AUTHORITATIVE EDITABLE WEAPON ANIMATION LIBRARY\n\nThis single file retains all recovered source sets and revisions. Use the Scene selector to choose a library family. EXPORT::<id> tracks are the canonical per-FBX selections; ARCHIVE::<name> tracks preserve source history. Solo one export track at a time with its same-named weapon/magazine/camera companions. Each clip and exact object list is embedded in EXPORT_MANIFEST. All Actions have fake users. Original source BLENDs remain unchanged.\n\nCurrent authored families: ready, sprint and transitions/bridges, walking, HIP directions, ADS entry/hold/exit, ADS forward diagnostic, jump including approved r8 landing, tactical reload WIP and opening/poses, low vault, prone entry/camera/crawl, onehand mantle. Features explicitly marked unavailable in the runtime manifest have no invented animation. WIP/diagnostic labels remain WIP/diagnostic.\n\nNine recovered source inputs; all images packed if available. No retargeting or new motion design. Reopen/structural validation only, not gameplay certification.\n')
import canonical_authoring_usability as usability
usability.apply(bpy)
usability.verify(bpy)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(P/'weapon_animations.blend'),compress=True)
print('CANONICAL',len(clips),'clips',len(allactions),'Actions',len(bpy.data.scenes),'scenes',len(missing),'missing images')
