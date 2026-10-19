"""Frozen v6 byte-exact complete rigid geometry chunks, serialized by native owner.
No rendering, source saves, FBX conversion or runtime-derived geometry.
"""
from pathlib import Path
import argparse, hashlib, json, math, sys
import bpy
import numpy as np
HERE=Path(__file__).resolve().parent;WORK=HERE.parent;ROOT=WORK.parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(WORK/'native-dense'))
from dense_contract import *
verify_inputs(ROOT);verify_recipes(ROOT)
for rel,digest in json.loads((HERE/'pins.json').read_text())['files'].items():
 require(file_sha(safe_child(ROOT,rel))==digest,'rigid recipe hash mismatch: '+rel)
sys.path.insert(0,str(HERE));from rigid_geometry import geometry_record
from rigid_bytes import canonical_buffers
I=ROOT/'recovery/animation-queue/runs/onehand-r5-from-reconstructed-r4/integrity';sys.path.insert(0,str(I))
from source_integrity import snapshot,action_fingerprint
from validate_directional_source import extra_snapshot,atom
p=argparse.ArgumentParser();p.add_argument('mode',choices=['chunk']);p.add_argument('--frame1-witness',type=Path,required=True);p.add_argument('--frame1-sha256',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--chunk-index',type=int)
args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);output=args.output.resolve()
require(output.is_relative_to(WORK) and not output.exists(),'fresh workspace output required')
require(args.mode=='chunk' or args.chunk_index is None,'frame1 takes no chunk index')
frames=selected_frames('sample',args.chunk_index)
require(args.frame1_witness.resolve()==ROOT/'onehand-runtime-20261016/rigid-frame1-v1.json','only the explicit shared original frame1 witness is admitted')
require(file_sha(args.frame1_witness)==args.frame1_sha256,'frame1 witness hash differs')
witness=json.loads(args.frame1_witness.read_text())
for key,value in {'schema':'rust-duty-private-onehand-rigid-frame1/v1','source_sha256':SOURCE_SHA,'rig_action':ACTION,'rig_action_fingerprint':ACTION_SHA,'source_frame':1}.items():
 require(witness[key]==value,'frame1 witness differs: '+key)
require(set(witness['actors'])==set(ACTORS),'frame1 actor inventory differs')
source=ROOT/SOURCE;sha=file_sha
assert bpy.app.version_string=='4.3.2' and bpy.app.background and not bpy.context.preferences.filepaths.use_scripts_auto_execute
assert Path(bpy.data.filepath).resolve()==source and sha(source)==SOURCE_SHA
source_i=sys.argv.index(str(source));assert sys.argv.index('--disable-autoexec')<source_i and sys.argv.index('--factory-startup')<source_i
assert_free(output.parent,32*MiB)
A=bpy.data.objects['Arms'];C=bpy.data.objects[CAMERA];S=bpy.context.scene
assert action_fingerprint(bpy.data.actions[ACTION])==ACTION_SHA and list(bpy.data.actions[ACTION].frame_range)==[1.,96.]
assert S.camera==C and (S.render.fps,S.render.fps_base)==(60,1.)
mat=lambda x:[list(r) for r in x]

def set_frame(f):
 S.frame_set(math.floor(f),subframe=f-math.floor(f));A.update_tag();C.update_tag();bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();return dg

def geometry(name,dg):
 obj=bpy.data.objects[name]
 assert obj.type=='MESH' and not any(m.type=='ARMATURE' for m in obj.modifiers)
 evaluated=obj.evaluated_get(dg);mesh=evaluated.to_mesh()
 try:
  local=np.empty(len(mesh.vertices)*3,dtype=np.float64);mesh.vertices.foreach_get('co',local)
  local=local.reshape(-1,3)
  starts=np.empty(len(mesh.polygons),dtype=np.int32);mesh.polygons.foreach_get('loop_start',starts)
  sizes=np.empty(len(mesh.polygons),dtype=np.int32);mesh.polygons.foreach_get('loop_total',sizes)
  indices=np.empty(len(mesh.loops),dtype=np.int32);mesh.loops.foreach_get('vertex_index',indices)
  return local,canonical_buffers(local,starts,sizes,indices)
 finally:evaluated.to_mesh_clear()

fields=('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')
before=json.loads(json.dumps({'snapshot':snapshot(bpy),'extra':extra_snapshot()},sort_keys=True))
frame_saved=(S.frame_current,S.frame_subframe);scene_saved={'name':S.name,'frame_start':S.frame_start,'frame_end':S.frame_end,'frame_step':S.frame_step};obj_saved={o.name:{k:tuple(getattr(o,k)) for k in fields} for o in bpy.data.objects}
pose_saved={b.name:({k:tuple(getattr(b,k)) for k in fields},{k:atom(v) for k,v in b.items() if k!='_RNA_UI'}) for b in A.pose.bones};ad_saved={o.name:(o.animation_data.action,o.animation_data.use_nla,[(t,t.mute,t.is_solo) for t in o.animation_data.nla_tracks]) for o in bpy.data.objects if o.animation_data};selected_saved={o.name:o.select_get() for o in bpy.data.objects};active_saved=bpy.context.view_layer.objects.active
for o in bpy.data.objects:
 if o.animation_data:
  o.animation_data.use_nla=False
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);A.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()
A.animation_data.action=bpy.data.actions[ACTION];C.animation_data_create();C.animation_data.use_nla=False;C.animation_data.action=None
S.name=ACTION;S.frame_start=1;S.frame_end=96;S.frame_step=1;S.frame_set(1);A.update_tag();C.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()

try:
 dg=set_frame(1.)
 actors={}
 for name in ACTORS:
  local,buffers=geometry(name,dg)
  record=geometry_record(local.tolist(),buffers.polygons())
  baseline=witness['actors'][name]
  require(record['geometry_sha256']==baseline['geometry_sha256'],'frame1 geometry differs from pinned independent witness')
  require(record['vertex_count']==baseline['vertex_count'] and record['polygon_count']==baseline['polygon_count'],'frame1 topology count differs')
  require(mat(bpy.data.objects[name].matrix_world)==baseline['world_at_frame1'],'frame1 actor matrix differs')
  require(not baseline['hide_render'] and not bpy.data.objects[name].hide_render,'hidden frame1 actor')
  actors[name]={'geometry_sha256':record['geometry_sha256'],'buffers':buffers}
 rows=[]
 for f in frames:
  dg=set_frame(f);record={}
  for name in ACTORS:
   _local,buffers=geometry(name,dg)
   assert buffers==actors[name]['buffers'],'source rigid float64 coordinate/topology bytes changed'
   assert not bpy.data.objects[name].hide_render,'unexpected rigid hide_render'
   record[name]={'geometry_sha256':actors[name]['geometry_sha256'],'hide_render':False}
  rows.append({'source_frame':f,'actors':record})
finally:
 for o in bpy.data.objects:
  if o.name not in ad_saved and o.animation_data:o.animation_data_clear()
 for n,(act,nla,tracks) in ad_saved.items():
  ad=bpy.data.objects[n].animation_data;ad.action=act;ad.use_nla=nla
  for t,m,solo in tracks:t.mute=m;t.is_solo=solo
 for o in bpy.data.objects:
  for k,v in obj_saved[o.name].items():setattr(o,k,v)
  o.select_set(selected_saved[o.name])
 for b in A.pose.bones:
  for k,v in pose_saved[b.name][0].items():setattr(b,k,v)
  for k,v in pose_saved[b.name][1].items():b[k]=v
 for k,v in scene_saved.items():setattr(S,k,v)
 bpy.context.view_layer.objects.active=active_saved
 S.frame_set(frame_saved[0],subframe=frame_saved[1]);A.update_tag();C.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()
after=json.loads(json.dumps({'snapshot':snapshot(bpy),'extra':extra_snapshot()},sort_keys=True));restoration=after==before
if not restoration:raise RuntimeError('exact source restoration failed')
assert restoration and sha(source)==SOURCE_SHA

base={'source_sha256':SOURCE_SHA,'rig_action':ACTION,'rig_action_fingerprint':ACTION_SHA}
result={**base,'schema':'rust-duty-private-onehand-rigid-chunk/v1','sample_grid_sha256':GRID_SHA,
 'chunk_index':args.chunk_index,'source_frames':frames,'samples':rows,'passed':True,
 'verification_method':'exact_float64_and_topology_bytes_vs_verified_frame1',
 'frame1_witness_sha256':args.frame1_sha256,'frame1_buffer_digests':{n:a['buffers'].digests() for n,a in actors.items()}}
data=(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode();assert len(data)<=32*MiB
assert_free(output.parent,len(data)+MiB);output.parent.mkdir(parents=True,exist_ok=True)
with output.open('xb') as stream:stream.write(data)
receipt={'schema':'rust-duty-onehand-rigid-process/v1','mode':args.mode,'chunk_index':args.chunk_index,
 'source_sha256':sha(source),'rig_action_fingerprint':ACTION_SHA,'sample_grid_sha256':GRID_SHA,
 'output_sha256':sha(output),'output_bytes':len(data),'samples':len(frames),
 'source_bytes_unchanged':True,'in_memory_source_state_restored':True,'source_saved':False,'rendered':False,
 'recipe_pins_sha256':sha(HERE/'pins.json'),'frame1_witness_sha256':args.frame1_sha256,'verification_method':result['verification_method'],'passed':True}
with output.with_name(output.stem+'.receipt.json').open('x') as stream:json.dump(receipt,stream,indent=2);stream.write('\n')
print(json.dumps(receipt,indent=2),flush=True)
