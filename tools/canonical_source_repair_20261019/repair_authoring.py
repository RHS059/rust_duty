"""Pinned editor-only repair, run Blender --python SCRIPT -- --root REPO."""
import argparse,hashlib,json,sys
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))
import canonical_authoring_usability as usability
INPUT='d86fcb25ef625922c4cce4dcec1ec9fb228d4ea6fd769647e424f2b6eec43d2e'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def plain(v):
 if hasattr(v,'to_dict'):return {k:plain(x) for k,x in v.to_dict().items()}
 if hasattr(v,'to_list'):return v.to_list()
 return v
def historical():return {a.name:{k:plain(v) for k,v in a.items() if k not in usability.FIELDS} for a in bpy.data.actions}
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);folder=args.root.resolve()/'assets/authoring';source=folder/'weapon_animations.blend'
 assert digest(source)==INPUT,'Expected published d133ec0 source'
 bpy.ops.wm.open_mainfile(filepath=str(source),use_scripts=False)
 before_manifest=bpy.data.texts['EXPORT_MANIFEST'].as_string();before_inventory=bpy.data.texts['ALL_ANIMATION_INVENTORY'].as_string();before_props=historical()
 changes=usability.apply(bpy);usability.verify(bpy)
 bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str(source),compress=True)
 bpy.ops.wm.open_mainfile(filepath=str(source),use_scripts=False);usability.verify(bpy)
 assert bpy.data.texts['EXPORT_MANIFEST'].as_string()==before_manifest
 assert bpy.data.texts['ALL_ANIMATION_INVENTORY'].as_string()==before_inventory
 assert historical()==before_props,'Historical properties changed'
 assert len(bpy.data.actions)==666 and len(bpy.data.scenes)==10 and all(a.use_fake_user for a in bpy.data.actions)
 assert all(i.packed_file for i in bpy.data.images if i.source=='FILE')
 receipt=folder/'weapon_animations.verification.json';value=json.loads(receipt.read_text());value['canonical_sha256']=digest(source);value['authoring_usability_repair']={'input_sha256':INPUT,**changes,'saved_reopen':'PASS','manifest_unchanged':True,'historical_properties_preserved':True,'scope':'Enable declared NLA owners without active Action mixing; add manifest-derived labels and editor guidance only.'};receipt.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value,indent=2))
if __name__=='__main__':main()
