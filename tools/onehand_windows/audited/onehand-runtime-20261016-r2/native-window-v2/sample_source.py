"""Exact frozen one-hand dense FBX and bounded fresh-import chunk parity.

Derived from the pinned native exporter; no motion edits or tolerance changes.

No rendering, source save, runtime activation or authoring. Source mode preserves
all saved state. Verification imports the produced bytes into a factory scene.
The static camera is exported as a CAMERA object and independently recorded.
"""
import argparse,hashlib,json,math,sys,traceback
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];DENSE=HERE.parent/'native-dense';sys.path.insert(0,str(DENSE));sys.path.insert(0,str(HERE));sys.dont_write_bytecode=True
from window_contract import verify_pins as verify_window_pins
verify_window_pins()
from dense_contract import *
from dense_backend import export_exact_grid,raw_key_grid,import_exact_grid,imported_key_grid
verify_inputs(ROOT)
verify_recipes(ROOT)
I=ROOT/'recovery/animation-queue/runs/onehand-r5-from-reconstructed-r4/integrity';sys.path.insert(0,str(I))
from source_integrity import snapshot,action_fingerprint
from validate_directional_source import extra_snapshot,atom
p=argparse.ArgumentParser();p.add_argument('mode',choices=['sample','focus-sample']);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--dense-dir',type=Path);p.add_argument('--chunk-index',type=int);args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);P=args.output_dir.resolve();assert P.is_relative_to(HERE.parent),'output must stay in new proof root'
FRAMES=selected_frames(args.mode,args.chunk_index)
assert '--factory-startup' in sys.argv and '--disable-autoexec' in sys.argv
assert args.mode=='export' or args.dense_dir is not None
D=P if args.mode=='export' else args.dense_dir.resolve();assert D.is_relative_to(HERE.parent),'dense input must stay in new proof root'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();mat=lambda x:[list(row) for row in x];err=lambda a,b:max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))
source=ROOT/'recovery/onehand-camera-solve-v6/candidate-v1/onehand-r6-camera-reconstructed-v6.blend';fbx=D/'aella_onehand_camera_reconstructed_v6.fbx'
assert bpy.app.version_string=='4.3.2' and bpy.app.background and not bpy.context.preferences.filepaths.use_scripts_auto_execute
assert sha(source)==SOURCE_SHA
recipe_pins={n:sha(DENSE/n) for n in ['export_and_verify.py','dense_contract.py','dense_backend.py']}
if args.mode!='export':
 dense_receipt=json.loads((D/'export-receipt.json').read_text());assert dense_receipt['source_sha256']==SOURCE_SHA and dense_receipt['fbx_sha256']==sha(fbx)
 assert dense_receipt['recipes']==recipe_pins and dense_receipt['fbx_bake_step']==1/256
 assert dense_receipt['mode']=='export'
 if args.mode in ('sample','verify'):
  focus=HERE.parent/'focus-output-v2/fresh-import-parity.json'
  from window_gate import validate_focus_window
  validate_focus_window(json.loads(focus.read_text()),dense_receipt['fbx_sha256'])
  for label in ('sample','verify'):
   prior=json.loads((HERE.parent/'logs/focus-v2'/(label+'.exit.json')).read_text());assert prior['exit_code']==0 and prior['completed'] is True
assert_free(P.parent, EXPORT_BUDGET if args.mode=='export' else CHUNK_BUDGET)

def camera_projection(C,S):
 return {'ray_directions':[list(v.normalized()) for v in C.data.view_frame(scene=S)],'type':C.data.type,'lens':C.data.lens,'sensor_fit':C.data.sensor_fit,'sensor_width':C.data.sensor_width,'sensor_height':C.data.sensor_height,'shift_x':C.data.shift_x,'shift_y':C.data.shift_y,'clip_start':C.data.clip_start,'clip_end':C.data.clip_end,'resolution':[S.render.resolution_x,S.render.resolution_y,S.render.resolution_percentage],'pixel_aspect':[S.render.pixel_aspect_x,S.render.pixel_aspect_y]}
def mesh_samples(dg):
 samples={};topology={}
 for name in SKINS:
  obj=bpy.data.objects[name].evaluated_get(dg);mesh=obj.to_mesh()
  try:
   local=np.empty(len(mesh.vertices)*3,dtype=np.float64);mesh.vertices.foreach_get('co',local);local=local.reshape(-1,3);M=np.asarray(obj.matrix_world,dtype=np.float64);world=local@M[:3,:3].T+M[:3,3];assert np.isfinite(world).all();samples[name]=world
   topology[name]={'vertices':len(mesh.vertices),'edges':len(mesh.edges),'polygons':len(mesh.polygons)}
  finally:obj.to_mesh_clear()
 return samples,topology

def take_contract():
 from io_scene_fbx import parse_fbx
 root,version=parse_fbx.parse(str(fbx));stacks=[]
 for node in root.elems:
  if node.id==b'Objects':
   for ob in node.elems:
    if ob.id==b'AnimationStack':stacks.append(ob.props[1].split(b'\x00\x01')[0].decode('utf8'))
 return {'version':version,'animation_stacks':stacks,'expected_single_stack':ACTION,'matches':stacks==[ACTION]}

if args.mode in ('export','sample','focus-sample'):
 assert Path(bpy.data.filepath).resolve()==source
 source_i=sys.argv.index(str(source));assert sys.argv.index('--disable-autoexec')<source_i and sys.argv.index('--factory-startup')<source_i
 assert not P.exists(),'Use a new output directory; no overwrite'
 P.mkdir(parents=True);A=bpy.data.objects['Arms'];C=bpy.data.objects[CAMERA];S=bpy.context.scene
 assert S.camera==C and C.type=='CAMERA'
 assert action_fingerprint(bpy.data.actions[ACTION])==ACTION_SHA
 assert list(bpy.data.actions[ACTION].frame_range)==[1.,96.]
 assert (S.render.fps,S.render.fps_base)==(60,1.)
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
 C0=C.matrix_world.copy();R0=A.matrix_world.copy();rest={b.name:A.matrix_world@b.matrix_local for b in A.data.bones};projection=camera_projection(C,S);rows={};skin={};topology=None;failure=None;result=None
 try:
  (P/'sample-rows').mkdir();(P/'skin-rows').mkdir()
  for idx,f in enumerate(FRAMES):
   assert_free(P, ROW_BUDGET)
   S.frame_set(math.floor(f),subframe=f-math.floor(f));A.update_tag();C.update_tag();bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();CW=C.matrix_world.copy();CI=CW.inverted()
   row={'source_frame':f,'time_seconds':(f-1)/60,'reference_frame_position':7786+f,'camera_world':mat(CW),'rig_world':mat(A.matrix_world),'camera_world_delta_from_frame1':mat(CW@C0.inverted()),'rig_world_delta_from_frame1':mat(A.matrix_world@R0.inverted()),'bone_world':{b.name:mat(A.matrix_world@b.matrix) for b in A.pose.bones},'bone_deformation_world':{b.name:mat((A.matrix_world@b.matrix)@rest[b.name].inverted()) for b in A.pose.bones},'actors_world':{n:mat(bpy.data.objects[n].matrix_world) for n in ACTORS},'actors_camera_relative':{n:mat(CI@bpy.data.objects[n].matrix_world) for n in ACTORS}}
   assert camera_projection(C,S)==projection,'Animated lens/projection requires explicit per-frame contract'
   assert err(CW,C0)==0 and err(A.matrix_world,R0)==0,'This one-hand export requires unchanged static camera and rig world basis'
   samples,top=mesh_samples(dg)
   if topology is None:topology=top
   assert topology==top
   skin={f'm{i}':samples[n] for i,n in enumerate(SKINS)}
   assert sum(top[n]['vertices'] for n in SKINS)==10234
   assert all(math.isfinite(v) for mm in row['bone_world'].values() for rr in mm for v in rr)
   rp=P/'sample-rows'/f'{idx:04d}.json';sp=P/'skin-rows'/f'{idx:04d}.npz'
   data=(json.dumps(row,separators=(',',':'))+'\n').encode();assert len(data)<=ROW_JSON_BUDGET
   rp.write_bytes(data);np.savez_compressed(sp,**skin);assert sp.stat().st_size<=ROW_SKIN_BUDGET
   rows[str(f)]={'source_frame':f,'row_path':str(rp.relative_to(P)),'row_sha256':sha(rp),'skin_path':str(sp.relative_to(P)),'skin_sha256':sha(sp)}
   print('DENSE_SOURCE',idx+1,len(FRAMES),flush=True)
  # The source rig has object co-motion. Export with its frame-1 bind state,
  # not the final sampled object transform, to avoid a silent rest-basis shift.
  S.frame_set(1);A.update_tag();C.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()
  assert err(A.matrix_world,R0)==0 and err(C.matrix_world,C0)==0
  bpy.ops.object.select_all(action='DESELECT')
  for n in SELECTED:bpy.data.objects[n].select_set(True)
  bpy.context.view_layer.objects.active=A
  if args.mode=='export':
   assert_free(P, FBX_BUDGET)
   result,backend=export_exact_grid(fbx,SETTINGS);assert 'FINISHED' in result
   raw_grid=raw_key_grid(fbx)
   assert fbx.stat().st_size<=FBX_BUDGET,'FBX exceeded declared disk budget'
  else:
   assert sha(fbx)==dense_receipt['fbx_sha256']
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
 if not restoration:(P/'restoration-failure.json').write_text(json.dumps({'before':before,'after':after},indent=2)+'\n')
 assert restoration and sha(source)==SOURCE_SHA
 expected={'source_sha256':SOURCE_SHA,'rig_action':ACTION,'rig_action_fingerprint':ACTION_SHA,'camera_action':CAMERA_ACTION,'camera_action_fingerprint':CAMERA_SHA,'source_rest_world':{n:mat(m) for n,m in rest.items()},'hierarchy':{b.name:b.parent.name if b.parent else None for b in A.data.bones},'projection':projection,'topology':topology,'frames':rows}
 (P/'source-samples.json').write_text(json.dumps(expected,indent=2)+'\n')
 contract={'schema':'onehand-camera-contract/v1','source_sha256':SOURCE_SHA,'fbx_sha256':sha(fbx),'rig_action':ACTION,'camera_action':CAMERA_ACTION,'camera_included_in_fbx':True,'sample_rate_fps':[60,1],'source_frames_inclusive':[1,96],'reference_decoded_range_half_open':[7787,7883],'frame1_time_seconds':0,'source_camera_world_frame1':mat(C0),'source_rig_world_frame1':mat(R0),'projection':projection,'source_samples_sha256':sha(P/'source-samples.json'),'world_consumer':'The source camera and rig world basis are static. Use the camera as the measured view basis; apply runtime camera placement exactly once.','viewmodel_consumer':'For a camera-local presentation, use inverse(camera_world) times each world actor/skin transform and apply the camera once. Do not multiply the camera delta into already-exported world motion.','camera_height_policy':'The one-hand source has no authored camera descent. Runtime stance or camera mapping needs separate validation.','interpolation_scope':'FBX bake step 1/256 source frame; this source receipt is not parity. Verify every exact independent 4240-grid witness in bounded chunks before aggregate acceptance.','runtime_support_verified':False}
 (P/'camera-contract.json').write_text(json.dumps(contract,indent=2)+'\n');take=take_contract();(P/'fbx-take-contract.json').write_text(json.dumps(take,indent=2)+'\n');assert take['matches']
 receipt={'source_sha256':SOURCE_SHA,'fbx_sha256':sha(fbx),'fbx_bytes':fbx.stat().st_size,'rig_action':ACTION,'camera_action':CAMERA_ACTION,'selected':SELECTED,'frames':[1,96],'fps':[60,1],'export_bind_frame':1,'settings':{k:sorted(v) if isinstance(v,set) else v for k,v in SETTINGS.items()},'recipes':recipe_pins,'evidence_sha256':{n:sha(P/n) for n in ['source-samples.json','camera-contract.json','fbx-take-contract.json']},'source_bytes_unchanged':True,'in_memory_source_state_restored':True,'source_saved':False,'rendered':False,'artistic_approval':False,'runtime_verified':False,'mode':args.mode,'chunk_index':args.chunk_index,'sample_frames':FRAMES,'source_sample_count':len(FRAMES),'sample_grid_sha256':sample_grid_sha(args.mode),'independent_grid_sha256':GRID_SHA,'fbx_bake_step':1/256,'handoff_sha256':HANDOFF_SHA}
 receipt.update(source_window_recipe_sha256=sha(HERE/'sample_source.py'),window_recipe_pins_sha256=sha(HERE/'pins.json'))
 (P/'export-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2),flush=True)
