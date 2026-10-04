"""Reopen saved v9; verify original data and diagnostic evaluated witnesses. No rendering."""
import bpy,json,sys,hashlib
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
BASE=Path(__file__).resolve().parents[2]/'ads'
sys.path.insert(0,str(BASE));from source_integrity import snapshot,digest
def original_data():
 result={}
 for o in bpy.data.objects:
  if o.type=='MESH':
   m=o.data
   result[o.name]=digest({'vertices':[list(v.co) for v in m.vertices],'polygons':[list(p.vertices) for p in m.polygons],'uv':[[list(v.uv) for v in layer.data] for layer in m.uv_layers],'groups':[[[g.group,g.weight] for g in v.groups] for v in m.vertices],'group_names':[g.name for g in o.vertex_groups],'parent':o.parent.name if o.parent else None,'parent_bone':o.parent_bone})
 return result
bpy.ops.wm.open_mainfile(filepath=str(BASE/'ads.blend'))
before=snapshot(bpy);meshes=original_data();A=bpy.data.objects['Arms']
rest=digest({b.name:[list(r) for r in b.matrix_local] for b in A.data.bones})
cam=bpy.data.objects['RD First Person Review'];camera=digest({'matrix':[list(r) for r in cam.matrix_world],'lens':cam.data.lens,'sensor':cam.data.sensor_width})
manifest=json.loads((HERE/'v9_scene_manifest.json').read_text());p=HERE/Path(manifest['blend']).name
assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['sha256']
bpy.ops.wm.open_mainfile(filepath=str(p))
after=snapshot(bpy);newmeshes=original_data()
checks={'original_actions':all(after['actions'][k]==v for k,v in before['actions'].items()),'original_meshes_uv_weights_parents':all(newmeshes[k]==v for k,v in meshes.items()),'packed_images':after['packed_images']==before['packed_images'],'drivers':all(after['drivers'][k]==v for k,v in before['drivers'].items()),'source_nla':all(after['nla'][k]==v for k,v in before['nla'].items())}
A=bpy.data.objects['Arms'];checks['source_rest']=rest==digest({b.name:[list(r) for r in b.matrix_local] for b in A.data.bones})
cam=bpy.data.objects['RD First Person Review'];checks['camera']=camera==digest({'matrix':[list(r) for r in cam.matrix_world],'lens':cam.data.lens,'sensor':cam.data.sensor_width})
scene=bpy.data.scenes[manifest['scene']]
if bpy.context.window:bpy.context.window.scene=scene
rig=bpy.data.objects['DIAG_V9_Arms'];weapon=bpy.data.objects['DIAG_V9_hk416_weapon']
rows=[]
for frame in [1,15.75,22,31,61,91,125.75,126]:
 scene.frame_set(int(frame),subframe=frame%1);bpy.context.view_layer.update()
 rows.append({'frame':frame,'weapon_matrix':[list(r) for r in weapon.matrix_world],'hands_relative':{side:[list(r) for r in weapon.matrix_world.inverted()@rig.matrix_world@rig.pose.bones['hand_'+side].matrix] for side in ['l','r']}})
report={'candidate_id':manifest['candidate_id'],'source_sha256':manifest['sha256'],'checks':checks,'original_action_count':len(before['actions']),'original_mesh_count':len(meshes),'new_actions':sorted(set(after['actions'])-set(before['actions'])),'witnesses':rows,'rendered':False,'all_pass':all(checks.values()),'claim_limit':'Recovery/preservation and evaluated witness check, not visual or reference approval.'}
(HERE/'v9_reopen_verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='witnesses'}),flush=True)
assert all(checks.values()),checks
