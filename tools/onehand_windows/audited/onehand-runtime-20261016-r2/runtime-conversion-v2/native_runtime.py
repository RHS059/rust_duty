"""One bounded native geometry or frame-block conversion; never fullkey instantiation."""
from pathlib import Path
import argparse,json,math,struct,sys
import bpy,numpy as np
from mathutils import Matrix
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from runtime_contract import *
recipe_sha=verify_pins()
sys.path.insert(0,str(WORK/'native-window-v2'))
from window_contract import verify_pins as verify_window_pins
from window_import import import_window
verify_window_pins()
sys.path.insert(0,str(ROOT/'onehand-runtime-20261016/importer-patch/tools'))
import vrpack,vrskin,vrview,export_viewmodel
p=argparse.ArgumentParser();p.add_argument('stage',choices=['geometry','block']);p.add_argument('--block-index',type=int);a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
require(bpy.app.background and bpy.app.version[:3]==(4,3,2) and not bpy.context.preferences.filepaths.use_scripts_auto_execute,'safe inspected native process required')
require('--factory-startup' in sys.argv and '--disable-autoexec' in sys.argv,'safe native flags missing')
if a.stage=='geometry':require(a.block_index is None,'geometry has no block index');frames=[1.]
else:lo,hi=block_range(a.block_index);frames=[1+i/256 for i in range(lo,hi+1)]
bpy.ops.wm.read_factory_settings(use_empty=True);S=bpy.context.scene;S.render.fps=60;S.render.fps_base=1
window=import_window(FBX,FBX_SHA,256,frames)
A=bpy.data.objects['Arms'];actors=[bpy.data.objects[n] for n in ACTORS];skins=[bpy.data.objects[n] for n in SKINS]
skeleton=vrview.decode_vra(CANONICAL.read_bytes())['bones'];keep={n for n,_ in skeleton}
require(len(skeleton)==72,'canonical72 required')
for name,parent in skeleton:
 b=A.data.bones[name];require((b.parent.name if b.parent else None)==(skeleton[parent][0] if parent>=0 else None),'canonical parent differs')
B=Matrix(BASIS);BI=B.inverted();flat=lambda m:tuple(float(v) for row in m for v in row)
def set_frame(f):
 require(f in window['allowed_evaluation_frames'],'runtime sample outside admitted key window')
 S.frame_set(math.floor(f),subframe=f-math.floor(f));A.update_tag();bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();return dg
set_frame(1.)
rig_world=flat(A.matrix_world);rest={n:flat(A.matrix_world@A.data.bones[n].matrix_local) for n,_ in skeleton}
weights={};geometry_signature={};weight_digests={};skin_world={o.name:flat(o.matrix_world) for o in skins}
for obj in skins+actors:
 require(obj.type=='MESH','required geometry missing');mesh=obj.data;parts=[]
 for collection,attr,dtype,width in ((mesh.vertices,'co','<f4',3),(mesh.loops,'vertex_index','<i4',1),(mesh.polygons,'loop_start','<i4',1),(mesh.polygons,'loop_total','<i4',1)):
  values=np.empty(len(collection)*width,dtype=dtype);collection.foreach_get(attr,values);require(np.isfinite(values).all(),'nonfinite static geometry');parts.append(__import__('hashlib').sha256(values.tobytes()).hexdigest())
 geometry_signature[obj.name]={'vertices':len(mesh.vertices),'polygons':len(mesh.polygons),'arrays_sha256':parts}
 if obj in skins:
  rows=[[(obj.vertex_groups[g.group].name,g.weight) for g in v.groups if g.weight>0] for v in mesh.vertices]
  require(all(n in keep for row in rows for n,w in row),'weighted noncanonical bone');maximum=max(map(len,rows));require(maximum<=8,'unsupported influence count')
  weight_digests[obj.name]=digest(rows)
  weights[obj.name]={'vertices':len(rows),'maximum_influences':maximum,'vertices_over_four':sum(len(r)>4 for r in rows)}
require(sum(v['vertices'] for v in weights.values())==10234,'three-skin coverage differs')
static={'canonical_bones':[list(x) for x in skeleton],'rest_world':rest,'rig_world':rig_world,'geometry':geometry_signature,'weights':weights,'skin_weight_sha256':weight_digests,'skin_object_world':skin_world}
static_sha=digest(static)
output=WORK/'runtime-v1'
if a.stage=='geometry':
 require(not output.exists(),'fresh runtime geometry directory required')
 for obj in S.objects:obj.animation_data_clear()
 A.data.pose_position='REST'
 for obj in actors:obj.parent=None;obj.matrix_world=Matrix.Identity(4)
 bpy.context.view_layer.objects.active=A;bpy.ops.object.select_all(action='DESELECT');A.select_set(True)
 bpy.ops.object.mode_set(mode='EDIT')
 for bone in list(A.data.edit_bones):
  if bone.name not in keep:A.data.edit_bones.remove(bone)
 bpy.ops.object.mode_set(mode='OBJECT')
 require(all(max(abs(a-b) for a,b in zip(rest[n],flat(A.matrix_world@A.data.bones[n].matrix_local)))<1e-6 for n in keep),'rest changed during helper pruning')
 for obj in skins+actors+[A]:obj.hide_set(False);obj.select_set(True)
 slots={o.name:[m.name if m else None for m in o.data.materials] for o in skins+actors};wanted=sorted({n for names in slots.values() for n in names if n})
 with bpy.data.libraries.load(str(SOURCE),link=False) as (available,loaded):
  require(set(wanted)<=set(available.materials),'material source missing slot');loaded.materials=list(wanted)
 restored=dict(zip(wanted,loaded.materials))
 for obj in skins+actors:
  for i,name in enumerate(slots[obj.name]):
   if name:obj.data.materials[i]=restored[name]
 output.mkdir();glb=output/'geometry-only.glb';export_viewmodel.export_glb(bpy,glb,animation=False)
 doc,blob=vrpack.parse_glb(glb.read_bytes());require(not doc.get('animations'),'geometry has animation')
 geometry=vrview.Scene(doc,blob,armature=A.name,base_color_only=True,single_sided_materials=True)
 vrs,vrm,definitions=geometry.companions(ACTORS);bones=geometry.skin.bones
 require({b[0] for b in bones}==keep,'companion skeleton selection differs')
 for name in keep:
  expected=B@A.matrix_world@A.data.bones[name].matrix_local;actual=geometry.rest_globals[geometry.node_named(name)]
  require(max(abs(x-y) for x,y in zip(flat(expected),actual))<1e-5,'companion joint rest/basis differs')
 for name,data in [('asset.vrs',vrs),('asset.vrm',vrm)]:
  with (output/name).open('xb') as f:f.write(data)
 metadata={'schema':'rust-duty-onehand-bounded-runtime-geometry/v1','source_sha256':SOURCE_SHA,'fbx_sha256':FBX_SHA,'canonical_sha256':CANONICAL_SHA,
   'clip_name':ACTION,'loop':False,'ticks_per_second':15360,'last_tick':24320,
   'bones':[[b[0],b[1]] for b in bones],'actors':definitions,'weights':weights,'basis':[list(r) for r in BASIS],'static_import':static,'static_import_sha256':static_sha,
   'window_admission':window,'recipe_pins_sha256':recipe_sha,'files':{n:{'sha256':sha(output/n),'bytes':(output/n).stat().st_size} for n in ('asset.vrs','asset.vrm','geometry-only.glb')},'passed':True}
 write_new(output/'geometry-metadata.json',metadata)
 print(json.dumps({'geometry_complete':True,'metadata_sha256':sha(output/'geometry-metadata.json'),'retained_keys':window['retained_key_count']}),flush=True)
else:
 metadata_path=output/'geometry-metadata.json';metadata=json.loads(metadata_path.read_text())
 require(metadata['passed'] is True and metadata['fbx_sha256']==FBX_SHA and metadata['static_import_sha256']==static_sha,'static rest/canonical/geometry identity differs across blocks')
 for name,record in metadata['files'].items():require(sha(output/name)==record['sha256'],'fixed geometry companion changed')
 bones=metadata['bones'];require(len(bones)==72 and {x[0] for x in bones}==keep,'encoded skeleton differs')
 folder=WORK/'runtime-blocks-v2'/f'block-{a.block_index:03d}';require(not folder.exists(),'fresh runtime block required');folder.mkdir(parents=True)
 with (folder/'frames.bin').open('xb') as stream:
  for tick,f in zip(range(lo,hi+1),frames):
   dg=set_frame(f);ae=A.evaluated_get(dg);require(flat(A.matrix_world)==rig_world,'static rig changed')
   require(all(flat(o.evaluated_get(dg).matrix_world)==skin_world[o.name] for o in skins),'static skin object world changed')
   worlds=[flat(B@ae.matrix_world@ae.pose.bones[name].matrix) for name,_ in bones]
   locals_=[vrpack.matmul(vrview.inverse(worlds[parent]),world) if parent>=0 else world for (_,parent),world in zip(bones,worlds)]
   values=[vrview.decompose(m) for m in locals_];visibility=[]
   for obj in actors:
    m=flat(B@obj.evaluated_get(dg).matrix_world@BI);hidden=max(abs(m[r*4+c]) for r in range(3) for c in range(3))<1e-10
    values.append(vrview.decompose(vrpack.IDENTITY if hidden else m));visibility.append(int(not hidden))
   record=struct.pack('<f',tick/15360)+b''.join(vrview.TRANSFORM.pack(*vrview.validate_transform(v)) for v in values)+bytes(visibility)
   require(len(record)==FRAME_BYTES,'runtime record size differs');stream.write(record)
  stream.flush()
 block={'schema':'rust-duty-onehand-bounded-runtime-block/v1','passed':True,'block_index':a.block_index,'start_tick':lo,'end_tick':hi,'frames':hi-lo+1,'frame_bytes':FRAME_BYTES,
   'source_sha256':SOURCE_SHA,'fbx_sha256':FBX_SHA,'canonical_sha256':CANONICAL_SHA,'geometry_metadata_sha256':sha(metadata_path),'static_import_sha256':static_sha,
   'frame_file_sha256':sha(folder/'frames.bin'),'frame_file_bytes':(folder/'frames.bin').stat().st_size,'window_admission':window,'recipe_pins_sha256':recipe_sha,
   'final_full_key_count':TOTAL_KEYS,'full_clip_instantiated':False}
 write_new(folder/'receipt.json',block);print(json.dumps({'block_complete':a.block_index,'frames':hi-lo+1,'retained_keys':window['retained_key_count'],'bytes':block['frame_file_bytes']}),flush=True)
require(sha(SOURCE)==SOURCE_SHA and sha(FBX)==FBX_SHA,'immutable input changed')
