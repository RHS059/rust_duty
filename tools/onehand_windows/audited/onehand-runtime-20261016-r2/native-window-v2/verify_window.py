"""Bounded same-file control or complete-geometry nine-time/chunk fresh import."""
from pathlib import Path
import argparse,json,math,sys,struct
import bpy,numpy as np
from mathutils import Matrix
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from window_contract import *
from window_import import import_window
sys.path.insert(0,str(WORK/'native-dense'))
from dense_contract import (SOURCE,ACTION,CAMERA,ACTORS,SKINS,GRID_SHA,FOCUS_GRID_SHA,MAXIMA,verify_inputs,verify_recipes,selected_frames)
verify_pins();verify_inputs();verify_recipes()
p=argparse.ArgumentParser();p.add_argument('mode',choices=['control','focus','chunk']);p.add_argument('--chunk-index',type=int);a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
require(bpy.app.background and bpy.app.version[:3]==(4,3,2) and not bpy.context.preferences.filepaths.use_scripts_auto_execute,'safe inspected Blender required')
require('--factory-startup' in sys.argv and '--disable-autoexec' in sys.argv,'factory/disabled-autoexec required')
FRAMES=selected_frames('verify',a.chunk_index) if a.mode=='chunk' else list(FOCUS)
if a.mode!='chunk':require(a.chunk_index is None,'only chunk requires index')
output=WORK/'window-control-v2' if a.mode=='control' else WORK/'focus-output-v2' if a.mode=='focus' else WORK/'chunks'/f'chunk-{a.chunk_index:03d}'
report_path=output/('full-import-control.json' if a.mode=='control' else 'fresh-import-parity.json')
require(not report_path.exists(),'fresh verification report required')
if a.mode=='control':expected=json.loads(FULL_CONTROL.read_text());fbx=OLD_FBX;fbx_sha=OLD_SHA;n=64
else:
 fbx=NEW_FBX;fbx_sha=NEW_SHA;n=256;expected=json.loads((output/'source-samples.json').read_text())
 receipt=json.loads((output/'export-receipt.json').read_text());require(receipt['fbx_sha256']==fbx_sha and receipt['source_sha256']==SOURCE_SHA,'source oracle identity differs')
 require(receipt['sample_frames']==FRAMES,'source sample clock differs')
 require(receipt.get('source_window_recipe_sha256')==sha(HERE/'sample_source.py') and receipt.get('window_recipe_pins_sha256')==sha(HERE/'pins.json'),'window source producer identity differs')
 for name,value in receipt['evidence_sha256'].items():require(sha(output/name)==value,'source descriptor differs')
 require(list(expected['frames'])==[str(f) for f in FRAMES],'source rows differ')
if a.mode!='control':
 control=WORK/'window-control-v2/full-import-control.json';require(control.is_file(),'actual full-import control required first')
 c=json.loads(control.read_text());require(c['passed'] is True and c['fbx_sha256']==OLD_SHA and c['full_import_control_sha256']==sha(FULL_CONTROL),'bounded/full control failed')
 cr=json.loads((WORK/'logs/window-control-v2/verify.exit.json').read_text());require(cr['completed'] is True and cr['exit_code']==0,'normal control exit required')
bpy.ops.wm.read_factory_settings(use_empty=True);S=bpy.context.scene;S.render.fps=60;S.render.fps_base=1
window=import_window(fbx,fbx_sha,n,FRAMES)
A=bpy.data.objects['Arms'];C=bpy.data.objects[CAMERA];S.camera=C
mat=lambda m:[list(r) for r in m]
err=lambda x,y:max(abs(x[i][j]-y[i][j]) for i in range(4) for j in range(4))
def set_frame(f):
 require(f in window['allowed_evaluation_frames'],'sample outside admitted exact window')
 S.frame_set(math.floor(f),subframe=f-math.floor(f));A.update_tag();C.update_tag();bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();return dg
set_frame(1.)
rest={b.name:A.matrix_world@b.matrix_local for b in A.data.bones}
if a.mode=='control':
 require(expected['fbx_sha256']==fbx_sha and expected['source_frames']==FRAMES,'full-import control identity differs')
 mismatches=[];maximum=0.;checked=0;rows=[]
 for f,wanted in zip(FRAMES,expected['samples']):
  set_frame(f);actual={b.name:mat((A.matrix_world@b.matrix)@rest[b.name].inverted()) for b in A.pose.bones}
  require(set(actual)==set(wanted['deformation_world']) and len(actual)==148,'control bone coverage differs')
  for name,m in actual.items():
   for i in range(4):
    for j in range(4):
     x=wanted['deformation_world'][name][i][j];y=m[i][j];checked+=1;maximum=max(maximum,abs(x-y))
     if struct.pack('<d',x)!=struct.pack('<d',y):mismatches.append({'source_frame':f,'bone':name,'row':i,'column':j,'full':x,'bounded':y,'difference':y-x})
  focus={}
  for name in wanted['focus_bones']:
   b=A.pose.bones[name];local=b.parent.matrix.inverted()@b.matrix if b.parent else b.matrix;loc,rot,scale=local.decompose()
   focus[name]={'parent':b.parent.name if b.parent else None,'rotation_mode':b.rotation_mode,'location':list(b.location),
      'rotation_quaternion':list(b.rotation_quaternion),'rotation_euler':list(b.rotation_euler),'scale':list(b.scale),
      'matrix_basis':mat(b.matrix_basis),'pose_parent_relative':mat(local),'pose_parent_relative_decomposition':{'location':list(loc),'rotation_quaternion':list(rot),'scale':list(scale)}}
  def compare_values(x,y,path):
   if isinstance(x,dict):
    require(set(x)==set(y),'focus channel structure differs')
    for key in x:compare_values(x[key],y[key],path+'/'+key)
   elif isinstance(x,list):
    require(len(x)==len(y),'focus channel length differs')
    for i,(a0,b0) in enumerate(zip(x,y)):compare_values(a0,b0,path+'/'+str(i))
   elif isinstance(x,float):
    if struct.pack('<d',x)!=struct.pack('<d',y):mismatches.append({'source_frame':f,'focus_channel':path,'full':x,'bounded':y,'difference':y-x})
   elif x!=y:mismatches.append({'source_frame':f,'focus_channel':path,'full':x,'bounded':y})
  compare_values(wanted['focus_bones'],focus,'focus_bones')
  rows.append({'source_frame':f,'deformation_world':actual,'focus_bones':focus})
 result={'schema':'rust-duty-fbx-bounded-full-import-control/v1','passed':not mismatches,'fbx_sha256':fbx_sha,
   'full_import_control_sha256':sha(FULL_CONTROL),'source_frames':FRAMES,'bones':148,'matrix_components_checked':checked,
   'matrix_component_bit_mismatch_count':sum('row' in m for m in mismatches),'focus_channel_bit_mismatch_count':sum('focus_channel' in m for m in mismatches),'maximum_component_difference':maximum,'mismatches':mismatches,'samples':rows,
   'window_admission':window,'scope':'same old FBX; bit-exact all148 deformation matrices versus actual full-import control'}
else:
 def camera_projection(C,S):
  return {'ray_directions':[list(v.normalized()) for v in C.data.view_frame(scene=S)],'type':C.data.type,'lens':C.data.lens,'sensor_fit':C.data.sensor_fit,'sensor_width':C.data.sensor_width,'sensor_height':C.data.sensor_height,'shift_x':C.data.shift_x,'shift_y':C.data.shift_y,'clip_start':C.data.clip_start,'clip_end':C.data.clip_end,'resolution':[S.render.resolution_x,S.render.resolution_y,S.render.resolution_percentage],'pixel_aspect':[S.render.pixel_aspect_x,S.render.pixel_aspect_y]}
 def mesh_samples(dg):
  samples={};topology={}
  for name in SKINS:
   obj=bpy.data.objects[name].evaluated_get(dg);mesh=obj.to_mesh()
   try:
    local=np.empty(len(mesh.vertices)*3,dtype=np.float64);mesh.vertices.foreach_get('co',local);local=local.reshape(-1,3);M=np.asarray(obj.matrix_world,dtype=np.float64);world=local@M[:3,:3].T+M[:3,3];require(np.isfinite(world).all(),'nonfinite skin');samples[name]=world
    topology[name]={'vertices':len(mesh.vertices),'edges':len(mesh.edges),'polygons':len(mesh.polygons)}
   finally:obj.to_mesh_clear()
  return samples,topology
 x,y,percent=expected['projection']['resolution'];S.render.resolution_x=x;S.render.resolution_y=y;S.render.resolution_percentage=percent;S.render.pixel_aspect_x,S.render.pixel_aspect_y=expected['projection']['pixel_aspect']
 names=set(expected['source_rest_world']);hierarchy={b.name:b.parent.name if b.parent else None for b in A.data.bones}
 checks={'bone_inventory':set(A.pose.bones.keys())==names and len(names)==148,'hierarchy':hierarchy==expected['hierarchy'],
         'animated_camera_bound':C.animation_data is not None and C.animation_data.action is not None,'animated_rig_bound':A.animation_data is not None and A.animation_data.action is not None,
         'single_exact_take':window['single_stack_admission']['logical_stack']==ACTION,'bounded_window_admitted':window['passed']}
 require(all(checks.values()),'fresh-import inventory failed')
 projection=camera_projection(C,S);ray_error=float(np.max(np.abs(np.array(projection['ray_directions'])-np.array(expected['projection']['ray_directions']))));maxima={k:0. for k in MAXIMA};worst={};finite=True;count=0;topology=None
 def record(k,v,where):
  require(math.isfinite(v) and v>=0,'nonfinite measured metric')
  if v>maxima[k]:maxima[k]=v;worst[k]=where
 for f in FRAMES:
  dg=set_frame(f);entry=expected['frames'][str(f)];rp=output/entry['row_path'];sp=output/entry['skin_path'];require(rp.resolve().is_relative_to(output) and sp.resolve().is_relative_to(output),'oracle path escapes')
  require(sha(rp)==entry['row_sha256'] and sha(sp)==entry['skin_sha256'],'oracle bytes differ');row=json.loads(rp.read_text());require(row['source_frame']==f,'oracle time differs');skin=np.load(sp,allow_pickle=False)
  EC=Matrix(row['camera_world']);CI=C.matrix_world.inverted();ECI=EC.inverted();record('camera_world_matrix',err(C.matrix_world,EC),f);record('rig_world_matrix',err(A.matrix_world,Matrix(row['rig_world'])),f)
  for b in A.pose.bones:
   world=A.matrix_world@b.matrix;deform=world@rest[b.name].inverted();wanted=Matrix(row['bone_deformation_world'][b.name]);record('bone_deformation_world_matrix',err(deform,wanted),[f,b.name]);record('bone_head_world_m',(world.translation-(wanted@Matrix(expected['source_rest_world'][b.name])).translation).length,[f,b.name]);finite &= all(math.isfinite(v) for rr in world for v in rr)
  for name in ACTORS:
   W=bpy.data.objects[name].matrix_world;finite &= all(math.isfinite(v) for rr in W for v in rr)
   record('actor_world_matrix',err(W,Matrix(row['actors_world'][name])),[f,name]);record('actor_camera_relative_matrix',err(CI@W,Matrix(row['actors_camera_relative'][name])),[f,name])
  samples,top=mesh_samples(dg)
  if topology is None:topology=top
  require(top==topology,'skin topology changed');ci=np.array(CI);eci=np.array(ECI)
  for i,name in enumerate(SKINS):
   actual=samples[name];wanted=skin[f'm{i}'];require(actual.shape==wanted.shape,'skin shape differs');count+=len(actual);dist=np.linalg.norm(actual-wanted,axis=1);record('skin_world_m',float(dist.max()),[f,name,int(np.argmax(dist))]);view=actual@ci[:3,:3].T+ci[:3,3];ref=wanted@eci[:3,:3].T+eci[:3,3];vd=np.linalg.norm(view-ref,axis=1);record('skin_camera_relative_m',float(vd.max()),[f,name,int(np.argmax(vd))])
  skin.close();finite &= all(math.isfinite(v) for M in (C.matrix_world,A.matrix_world) for rr in M for v in rr);require(camera_projection(C,S)==projection,'animated projection')
 checks.update({k:v<1e-4 for k,v in maxima.items()});checks.update(finite_bones=bool(finite),finite_all_measured_transforms=bool(finite),skin_topology=topology==expected['topology'],camera_projection_rays=ray_error<1e-5,camera_type=projection['type']==expected['projection']['type'],single_native_clock=all(list(x.frame_range)==[1.,96.] for x in bpy.data.actions),fps=S.render.fps==60 and S.render.fps_base==1,source_unchanged=sha(ROOT/SOURCE)==SOURCE_SHA,fbx_unchanged=sha(fbx)==fbx_sha)
 result={'source_sha256':SOURCE_SHA,'fbx_sha256':fbx_sha,'samples':len(FRAMES),'chunk_index':a.chunk_index,'sample_frames':FRAMES,'sample_grid_sha256':FOCUS_GRID_SHA if a.mode=='focus' else GRID_SHA,'independent_grid_sha256':GRID_SHA,
  'source_oracle_sha256':sha(output/'source-samples.json'),'source_receipt_sha256':sha(output/'export-receipt.json'),'skin_vertex_samples':count,'checks':checks,'passed':all(checks.values()),'maxima':maxima,'worst':worst,'camera_projection_ray_error':ray_error,
  'source_projection':expected['projection'],'imported_projection':projection,'source_total_bones_including_helpers':148,'topology':topology,'runtime_support_verified':False,'artistic_approval':False,
  'proof_scope':'focused-nine-time-key-and-offkey' if a.mode=='focus' else 'exact-independent-grid-chunk','window_admission':window,'full_import_control_receipt_sha256':sha(control),'off_key_source_frames':[f for f in FRAMES if f*256!=int(f*256)],
  'camera_included_and_measured':True,'camera_relative_geometry_measured':True,'subframe_parity':True,'coverage_scope':'only explicitly allowed window samples; full clip was not instantiated'}
 require(count==len(FRAMES)*10234,'skin coverage incomplete')
require(sha(ROOT/SOURCE)==SOURCE_SHA and sha(fbx)==fbx_sha,'immutable input changed')
result['window_recipe_pins_sha256']=sha(HERE/'pins.json');output.mkdir(parents=True,exist_ok=True)
with report_path.open('x') as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
print(json.dumps({'report':str(report_path),'passed':result['passed'],'retained_keys':window['retained_key_count'],'imported_curves':window['imported_curve_count'],'maximum_control_difference':result.get('maximum_component_difference'),'maxima':result.get('maxima')}),flush=True)
require(result['passed'],'bounded control/parity failed; preserve evidence')
