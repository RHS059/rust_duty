#!/usr/bin/env python3
"""Private dense FBX export/fresh-import proof for a proven-equivalent r15 source.

Adapted from the verified original dense export algorithm. No rendering or source
save. New candidate/oracle identities remain explicit. A local immutable approved
oracle may be reused only behind strict source-equivalence admission.
"""
import argparse,hashlib,json,math,sys,traceback
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));sys.dont_write_bytecode=True
import prone_r15_regenerated_contract as contract
from prone_r15_source_native import non_action_hashes, action_hashes, atom
from export_prone_pair import action_fingerprint
from prone_r15_regenerated_contract import ACTION, CAMERA_ACTION, CAMERA, SKINS, ACTORS, SELECTED, GRID_SHA as SAMPLE_GRID_SHA
from prone_r15_source_delta import RIG_FINGERPRINT as ACTION_SHA, CAMERA_FINGERPRINT as CAMERA_SHA
FRAMES=contract.grid();SETTINGS=contract.DENSE_SETTINGS
snapshot=lambda bpy:{'actions':action_hashes(bpy),'static':non_action_hashes(bpy)}
extra_snapshot=lambda:{}
p=argparse.ArgumentParser();p.add_argument('mode',choices=['export','verify']);p.add_argument('--output-dir',type=Path,required=True)
p.add_argument('--source',type=Path,required=True);p.add_argument('--source-equivalence',type=Path,required=True)
p.add_argument('--source-equivalence-sha256',required=True);p.add_argument('--reference-oracle',type=Path)
args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);P=args.output_dir.resolve()
SOURCE_SHA=contract.sha(args.source);PROOF=contract.descriptor(args.source_equivalence,args.source_equivalence_sha256,args.source)
ORACLE=P if args.reference_oracle is None else args.reference_oracle.resolve()
REFERENCE_SOURCE_SHA=SOURCE_SHA
if args.reference_oracle is not None:
 contract.require(contract.sha(ORACLE/'source-samples.json')==contract.ORIGINAL_ORACLE_SHA,'Original private reference oracle identity differs')
 REFERENCE_SOURCE_SHA=contract.delta.APPROVED_SHA

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();mat=lambda x:[list(row) for row in x];err=lambda a,b:max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))
source=args.source.resolve();fbx=P/(ACTION+'.fbx')
assert bpy.app.version_string=='4.3.2' and bpy.app.background and not bpy.context.preferences.filepaths.use_scripts_auto_execute
assert sha(source)==SOURCE_SHA
recipe_pins={n:sha(HERE/n) for n in ['export_prone_r15_regenerated_dense.py','prone_r15_regenerated_contract.py']}

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

if args.mode=='export':
 assert Path(bpy.data.filepath).resolve()==source
 assert not P.exists(),'Use a new output directory; no overwrite'
 P.mkdir(parents=True);A=bpy.data.objects['Arms'];C=bpy.data.objects[CAMERA];S=bpy.context.scene
 assert C.type=='CAMERA'
 assert action_fingerprint(bpy.data.actions[ACTION])==ACTION_SHA and action_fingerprint(bpy.data.actions[CAMERA_ACTION])==CAMERA_SHA
 assert list(bpy.data.actions[ACTION].frame_range)==[1.,69.] and list(bpy.data.actions[CAMERA_ACTION].frame_range)==[1.,69.]
 assert (S.render.fps,S.render.fps_base)==(60,1.)
 fields=('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')
 before=json.loads(json.dumps({'snapshot':snapshot(bpy),'extra':extra_snapshot()},sort_keys=True))
 frame_saved=(S.frame_current,S.frame_subframe);scene_saved={'name':S.name,'frame_start':S.frame_start,'frame_end':S.frame_end,'frame_step':S.frame_step,'camera':S.camera};obj_saved={o.name:{k:tuple(getattr(o,k)) for k in fields} for o in bpy.data.objects}
 pose_saved={b.name:({k:tuple(getattr(b,k)) for k in fields},{k:atom(v) for k,v in b.items() if k!='_RNA_UI'}) for b in A.pose.bones};ad_saved={o.name:(o.animation_data.action,o.animation_data.use_nla,[(t,t.mute,t.is_solo) for t in o.animation_data.nla_tracks]) for o in bpy.data.objects if o.animation_data};selected_saved={o.name:o.select_get() for o in bpy.data.objects};active_saved=bpy.context.view_layer.objects.active
 for o in bpy.data.objects:
  if o.animation_data:
   o.animation_data.use_nla=False
   for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
 A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);A.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()
 A.animation_data.action=bpy.data.actions[ACTION];C.animation_data_create();C.animation_data.use_nla=False;C.animation_data.action=bpy.data.actions[CAMERA_ACTION]
 S.camera=C;S.name=ACTION;S.frame_start=1;S.frame_end=69;S.frame_step=1;S.frame_set(1);A.update_tag();C.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()
 C0=C.matrix_world.copy();R0=A.matrix_world.copy();rest={b.name:A.matrix_world@b.matrix_local for b in A.data.bones};projection=camera_projection(C,S);rows={};skin={};topology=None;failure=None;result=None
 try:
  if args.reference_oracle is None:(P/'sample-rows').mkdir();(P/'skin-rows').mkdir()
  for f in (FRAMES if args.reference_oracle is None else []):
   S.frame_set(math.floor(f),subframe=f-math.floor(f));A.update_tag();C.update_tag();bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();CW=C.matrix_world.copy();CI=CW.inverted()
   row={'source_frame':f,'time_seconds':(f-1)/60,'reference_frame_position':2240+f,'camera_world':mat(CW),'rig_world':mat(A.matrix_world),'camera_world_delta_from_frame1':mat(CW@C0.inverted()),'rig_world_delta_from_frame1':mat(A.matrix_world@R0.inverted()),'bone_world':{b.name:mat(A.matrix_world@b.matrix) for b in A.pose.bones},'bone_deformation_world':{b.name:mat((A.matrix_world@b.matrix)@rest[b.name].inverted()) for b in A.pose.bones},'actors_world':{n:mat(bpy.data.objects[n].matrix_world) for n in ACTORS},'actors_camera_relative':{n:mat(CI@bpy.data.objects[n].matrix_world) for n in ACTORS}}
   assert camera_projection(C,S)==projection,'Animated lens/projection requires explicit per-frame contract'
   samples,top=mesh_samples(dg)
   if topology is None:topology=top
   assert topology==top
   skin={f'm{i}':samples[n] for i,n in enumerate(SKINS)}
   assert all(math.isfinite(v) for mm in row['bone_world'].values() for rr in mm for v in rr)
   idx=len(rows);rp=P/'sample-rows'/f'{idx:04d}.json';sp=P/'skin-rows'/f'{idx:04d}.npz'
   rp.write_text(json.dumps(row,separators=(',',':'))+'\n');np.savez_compressed(sp,**skin)
   rows[str(f)]={'source_frame':f,'row_path':rp.relative_to(P).as_posix(),'row_sha256':sha(rp),'skin_path':sp.relative_to(P).as_posix(),'skin_sha256':sha(sp)}
   if idx%64==0:print('DENSE_SOURCE',idx,len(FRAMES),flush=True)
  # The source rig has object co-motion. Export with its frame-1 bind state,
  # not the final sampled object transform, to avoid a silent rest-basis shift.
  S.frame_set(1);A.update_tag();C.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()
  assert err(A.matrix_world,R0)==0 and err(C.matrix_world,C0)==0
  bpy.ops.object.select_all(action='DESELECT')
  for n in SELECTED:bpy.data.objects[n].select_set(True)
  bpy.context.view_layer.objects.active=A
  result=bpy.ops.export_scene.fbx(filepath=str(fbx),**SETTINGS);assert 'FINISHED' in result
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
 if args.reference_oracle is None:(P/'source-samples.json').write_text(json.dumps(expected,indent=2)+'\n')
 else:expected=json.loads((ORACLE/'source-samples.json').read_text())
 camera_contract={'schema':'prone-r7-paired-camera-contract/v1','source_sha256':SOURCE_SHA,'fbx_sha256':sha(fbx),'rig_action':ACTION,'camera_action':CAMERA_ACTION,'camera_included_in_fbx':True,'sample_rate_fps':[60,1],'source_frames_inclusive':[1,69],'reference_decoded_range_half_open':[2241,2310],'frame1_time_seconds':0,'source_camera_world_frame1':mat(C0),'source_rig_world_frame1':mat(R0),'projection':projection,'source_samples_sha256':sha(ORACLE/'source-samples.json'),'world_consumer':'Use the exported rig/object animation and exported camera world track together. Do not add another camera descent or a second shared co-motion transform.','viewmodel_consumer':'For a camera-local presentation, use inverse(camera_world) times each world actor/skin transform and apply the camera once. Do not multiply the camera delta into already-exported world motion.','camera_height_policy':'The paired camera is the authored absolute source track; any game-relative stance replacement needs a separately verified mapping. Generic stance easing must not be added on top.','interpolation_scope':'FBX baked every 1/64 source frame; fresh import verified at all 1944 independently evaluated source times, including protected dense neighborhoods. No arbitrary continuous-time claim.','runtime_support_verified':False}
 (P/'paired-camera-contract.json').write_text(json.dumps(camera_contract,indent=2)+'\n');take=take_contract();(P/'fbx-take-contract.json').write_text(json.dumps(take,indent=2)+'\n');assert take['matches']
 receipt={'source_sha256':SOURCE_SHA,'fbx_sha256':sha(fbx),'fbx_bytes':fbx.stat().st_size,'rig_action':ACTION,'camera_action':CAMERA_ACTION,'selected':SELECTED,'frames':[1,69],'fps':[60,1],'export_bind_frame':1,'settings':{k:sorted(v) if isinstance(v,set) else v for k,v in SETTINGS.items()},'recipes':recipe_pins,'evidence_sha256':{n:sha(P/n) for n in ['paired-camera-contract.json','fbx-take-contract.json']},'source_samples_sha256':sha(ORACLE/'source-samples.json'),'oracle_source_sha256':REFERENCE_SOURCE_SHA,'source_bytes_unchanged':True,'in_memory_source_state_restored':True,'source_saved':False,'rendered':False,'runtime_verified':False,'sample_grid_sha256':SAMPLE_GRID_SHA,'source_sample_count':len(FRAMES),'fbx_bake_step':1/64}
 receipt.update(source_equivalence_sha256=args.source_equivalence_sha256,source_equivalence_descriptor=PROOF)
 (P/'export-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2),flush=True)
else:
 receipt=json.loads((P/'export-receipt.json').read_text());assert receipt['source_sha256']==SOURCE_SHA and sha(fbx)==receipt['fbx_sha256'];assert receipt['recipes']==recipe_pins
 for n,expected_sha in receipt['evidence_sha256'].items():assert sha(P/n)==expected_sha,n
 expected=json.loads((ORACLE/'source-samples.json').read_text());assert sha(ORACLE/'source-samples.json')==receipt['source_samples_sha256'];assert take_contract()['matches']
 bpy.ops.wm.read_factory_settings(use_empty=True);S=bpy.context.scene;S.render.fps=60;S.render.fps_base=1
 r=bpy.ops.import_scene.fbx(filepath=str(fbx),anim_offset=0,automatic_bone_orientation=False,use_prepost_rot=True);assert 'FINISHED' in r
 A=bpy.data.objects['Arms'];C=bpy.data.objects[CAMERA];assert C.type=='CAMERA';S.camera=C
 x,y,percent=expected['projection']['resolution'];S.render.resolution_x=x;S.render.resolution_y=y;S.render.resolution_percentage=percent;S.render.pixel_aspect_x,S.render.pixel_aspect_y=expected['projection']['pixel_aspect']
 S.frame_set(1);A.update_tag();C.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update();rest={b.name:A.matrix_world@b.matrix_local for b in A.data.bones};names=set(expected['source_rest_world']);hierarchy={b.name:b.parent.name if b.parent else None for b in A.data.bones}
 checks={'bone_inventory':set(A.pose.bones.keys())==names,'hierarchy':hierarchy==expected['hierarchy'],'animated_camera_bound':C.animation_data is not None and C.animation_data.action is not None,'animated_rig_bound':A.animation_data is not None and A.animation_data.action is not None,'single_exact_take':take_contract()['matches']};assert all(checks.values()),checks
 projection=camera_projection(C,S);ray_error=float(np.max(np.abs(np.array(projection['ray_directions'])-np.array(expected['projection']['ray_directions']))));maxima={k:0. for k in ['bone_deformation_world_matrix','bone_head_world_m','actor_world_matrix','actor_camera_relative_matrix','camera_world_matrix','rig_world_matrix','skin_world_m','skin_camera_relative_m']};worst={};finite=True;count=0;topology=None
 def record(k,v,where):
  if v>maxima[k]:maxima[k]=v;worst[k]=where
 if True:
  for f in FRAMES:
   S.frame_set(math.floor(f),subframe=f-math.floor(f));bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();entry=expected['frames'][str(f)];rp=ORACLE/entry['row_path'];sp=ORACLE/entry['skin_path'];assert sha(rp)==entry['row_sha256'] and sha(sp)==entry['skin_sha256'];row=json.loads(rp.read_text());skin=np.load(sp,allow_pickle=False);EC=Matrix(row['camera_world']);CI=C.matrix_world.inverted();ECI=EC.inverted();record('camera_world_matrix',err(C.matrix_world,EC),f);record('rig_world_matrix',err(A.matrix_world,Matrix(row['rig_world'])),f)
   for b in A.pose.bones:
    world=A.matrix_world@b.matrix;deform=world@rest[b.name].inverted();wanted=Matrix(row['bone_deformation_world'][b.name]);record('bone_deformation_world_matrix',err(deform,wanted),[f,b.name]);record('bone_head_world_m',(world.translation-(wanted@Matrix(expected['source_rest_world'][b.name])).translation).length,[f,b.name]);finite &= all(math.isfinite(v) for rr in world for v in rr)
   for n in ACTORS:
    record('actor_world_matrix',err(bpy.data.objects[n].matrix_world,Matrix(row['actors_world'][n])),[f,n]);record('actor_camera_relative_matrix',err(CI@bpy.data.objects[n].matrix_world,Matrix(row['actors_camera_relative'][n])),[f,n])
   samples,top=mesh_samples(dg)
   if topology is None:topology=top
   assert topology==top
   ci=np.array(CI);eci=np.array(ECI)
   for i,n in enumerate(SKINS):
    actual=samples[n];wanted=skin[f'm{i}'];assert actual.shape==wanted.shape;count+=len(actual);dist=np.linalg.norm(actual-wanted,axis=1);record('skin_world_m',float(dist.max()),[f,n,int(np.argmax(dist))]);view=actual@ci[:3,:3].T+ci[:3,3];refview=wanted@eci[:3,:3].T+eci[:3,3];vd=np.linalg.norm(view-refview,axis=1);record('skin_camera_relative_m',float(vd.max()),[f,n,int(np.argmax(vd))])
   skin.close()
   assert camera_projection(C,S)==projection,'Unexpected animated projection after import'
   if count%(10234*64)==0:print('DENSE_IMPORT',count//10234,len(FRAMES),flush=True)
 actions={a.name:list(a.frame_range) for a in bpy.data.actions};checks.update({k:maxima[k]<1e-4 for k in maxima});checks.update(finite_bones=bool(finite),skin_topology=topology==expected['topology'],camera_projection_rays=ray_error<1e-5,camera_type=projection['type']==expected['projection']['type'],single_native_clock=all(v==[1.,69.] for v in actions.values()),fps=S.render.fps==60 and S.render.fps_base==1,source_unchanged=sha(source)==SOURCE_SHA,fbx_unchanged=sha(fbx)==receipt['fbx_sha256'])
 out={'source_sha256':SOURCE_SHA,'fbx_sha256':sha(fbx),'samples':len(FRAMES),'sample_grid_sha256':SAMPLE_GRID_SHA,'fbx_bake_step':1/64,'skin_vertex_samples':count,'checks':checks,'passed':all(checks.values()),'maxima':maxima,'worst':worst,'camera_projection_ray_error':ray_error,'source_projection':expected['projection'],'imported_projection':projection,'imported_actions':actions,'source_total_bones_including_helpers':len(names),'topology':topology,'import_settings':{'anim_offset':0,'automatic_bone_orientation':False,'use_prepost_rot':True},'camera_included_and_measured':True,'camera_relative_geometry_measured':True,'subframe_parity':True,'runtime_support_verified':False};out.update(source_equivalence_sha256=args.source_equivalence_sha256,source_equivalence_descriptor=PROOF);assert not (P/'fresh-import-parity.json').exists();(P/'fresh-import-parity.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2),flush=True);assert out['passed'],[k for k,v in checks.items() if not v]
