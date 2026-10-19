"""Metadata-only outgoing-magazine export repair. Run with Blender 4.3.2.
blender -b --disable-autoexec --python-exit-code 1 --python repair_canonical_reload_export.py -- --root REPO
"""
import argparse,hashlib,json,sys
from pathlib import Path
import bpy
SOURCE_SHA256='e1388c5a6fd96de54ccb75e70d8ba1860b02d65eced327342b4fcc40c36d8c8d'
OBJ='hk416_magazine_outgoing.008'
ALIAS='hk416_magazine_outgoing'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def need(ok,message):
 if not ok: raise ValueError(message)
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
 folder=args.root.resolve()/'assets/authoring';source=folder/'weapon_animations.blend';sidecar=folder/'weapon_animations.export.json';receipt=folder/'weapon_animations.verification.json'
 need(digest(source)==SOURCE_SHA256,'Expected exact main 918e3fa canonical source')
 bpy.ops.wm.open_mainfile(filepath=str(source),use_scripts=False)
 old=json.loads(bpy.data.texts['EXPORT_MANIFEST'].as_string());need(old==json.loads(sidecar.read_text()),'Sidecar differs from embedded manifest')
 inventory=bpy.data.texts['ALL_ANIMATION_INVENTORY'].as_string()
 need(json.loads(inventory)==json.loads((folder/'weapon_animations.inventory.json').read_text()),'Inventory sidecar differs')
 expected=json.loads(json.dumps(old));clip=next(c for c in expected['clips'] if c['id']=='reload_current_wip')
 need(len(expected['clips'])==67 and len(clip['objects'])==7,'Unexpected existing export selection')
 need(clip['scene']=='LIBRARY | RELOAD' and clip['rig']=='Arms.008','Unexpected reload bindings')
 o=bpy.data.scenes[clip['scene']].objects.get(OBJ)
 need(o is not None and o.type=='MESH' and o.animation_data is None,'Expected retained rig-driven outgoing magazine')
 need(len(o.constraints)==1,'Unexpected outgoing constraints');c=o.constraints[0]
 need(c.type=='CHILD_OF' and c.target.name==clip['rig'] and c.subtarget=='OUT_magazine_outgoing' and c.influence==1 and not c.mute,'Outgoing magazine binding differs')
 need(OBJ not in clip['objects'] and OBJ not in clip['object_name_map'],'Already repaired or unexpected alias')
 clip['objects'].append(OBJ);clip['object_name_map'][OBJ]=ALIAS
 text=bpy.data.texts['EXPORT_MANIFEST'];text.clear();text.write(json.dumps(expected,indent=2))
 bpy.context.preferences.filepaths.save_version=0
 bpy.ops.wm.save_as_mainfile(filepath=str(source),compress=True)
 bpy.ops.wm.open_mainfile(filepath=str(source),use_scripts=False)
 need(json.loads(bpy.data.texts['EXPORT_MANIFEST'].as_string())==expected,'Saved manifest differs from exact two-field repair')
 need(bpy.data.texts['ALL_ANIMATION_INVENTORY'].as_string()==inventory,'Inventory changed')
 need(len(bpy.data.actions)==666 and all(a.use_fake_user for a in bpy.data.actions),'Retained Action structure differs')
 need(len(bpy.data.scenes)==10,'Scene count differs')
 need(all(i.packed_file for i in bpy.data.images if i.source=='FILE'),'Missing packed image')
 for cl in expected['clips']:
  sc=bpy.data.scenes[cl['scene']];rig=sc.objects[cl['rig']];track=rig.animation_data.nla_tracks[cl['track_name']]
  need(len(track.strips)==1 and track.strips[0].action.name==cl['action'],'Mapped Action differs')
  need(all(n in sc.objects for n in cl['objects']),'Selected object missing')
  need(set(cl['object_name_map'])==set(cl['objects']),'Object alias coverage differs')
  for cp in cl['companion_tracks']:
   need(sc.objects[cp['object']].animation_data.nla_tracks[cp['track_name']].strips[0].action.name==cp['action'],'Companion binding differs')
  if cl.get('camera_track_name'):
   need(sc.objects[cl['camera']].animation_data.nla_tracks[cl['camera_track_name']].strips[0].action.name==cl['camera_action'],'Camera binding differs')
 sidecar.write_text(json.dumps(expected,indent=2))
 result=json.loads(receipt.read_text());result.update({'status':'PASS','canonical_sha256':digest(source),'metadata_repair':{'input_sha256':SOURCE_SHA256,'clip':'reload_current_wip','added_object':OBJ,'exported_name':ALIAS,'scope':'Retained outgoing magazine added to explicit export selection only; no authored motion edited.'}})
 receipt.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
