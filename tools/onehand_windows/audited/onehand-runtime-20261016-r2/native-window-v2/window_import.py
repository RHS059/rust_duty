"""Validate full raw/transformed clocks; retain only exact requested brackets.

Selection happens after full official transform conversion, so quaternion sign
history and Euler unwrapping are unchanged. The full FBX file is never rewritten.
"""
import hashlib,inspect,json,sys
from pathlib import Path
import numpy as np
from window_contract import *
PATCH_SHA={'blen_read_animations':'757bd21550d94e2190881ec6b0eb0ce80b275d2a230055cf7702044fe6dcc6e2',
           'blen_store_keyframes_multi':'793a389ebde0e71ec3cec54e731c861753aa08015355904777a8c39b70da3a4e'}
ACTION='aella_mantle_onehand_r6_camera_reconstructed_v6'
OWNERS=['Arms','hk416_weapon','hk416_magazine','hk416_magazine_outgoing','RD First Person Review']

def import_window(path,expected_sha,n,frames):
 import bpy
 import io_scene_fbx.import_fbx as imp
 from io_scene_fbx import parse_fbx
 sys.path.insert(0,str(ROOT/'onehand-runtime-20261016/importer-patch/tools'))
 import single_stack_fbx,import_fbx_viewmodel as converter
 require(sha(path)==expected_sha,'exact FBX input differs');require(bpy.app.version[:3]==(4,3,2),'audited Blender version required')
 plan=selection(frames,n);indices=np.asarray(plan['retained_indices'],dtype=np.int64);expected=native_grid(n)
 state={'parse_calls':0,'capture':None,'raw_curves':[],'stored_curves':[]};original_parse=parse_fbx.parse
 for name,value in PATCH_SHA.items():require(hashlib.sha256(inspect.getsource(getattr(imp,name)).encode()).hexdigest()==value,'import signature differs: '+name)
 def parse_once(filepath,*args,**kwargs):
  require(Path(filepath).resolve()==Path(path).resolve() and state['parse_calls']==0,'unexpected/duplicate parse')
  state['parse_calls']+=1;tree,version=original_parse(filepath,*args,**kwargs)
  state['capture']=single_stack_fbx.BindingCapture(single_stack_fbx.inspect_stack(tree,ACTION,OWNERS))
  objects=[x for x in tree.elems if x.id==b'Objects'];require(len(objects)==1,'ambiguous Objects')
  curves=[x for x in objects[0].elems if x.id==b'AnimationCurve'];require(len(curves)==RAW_CURVES,'raw curve count differs')
  ids=set()
  for curve in curves:
   require(curve.props[0] not in ids,'duplicate raw curve UUID');ids.add(curve.props[0])
   parts={x.id:x.props for x in curve.elems};require(len(parts)==len(curve.elems),'duplicate raw curve field')
   require(set(parts)=={b'Default',b'KeyVer',b'KeyTime',b'KeyValueFloat',b'KeyAttrFlags',b'KeyAttrDataFloat',b'KeyAttrRefCount'},'raw curve schema differs')
   require(parts[b'KeyVer']==[4008] and len(parts[b'Default'])==1 and np.isfinite(parts[b'Default']).all(),'raw curve version/default invalid')
   require(list(parts[b'KeyAttrDataFloat'][0])==[0.,0.,9.419963346924634e-30,0.],'raw attribute payload differs')
   record=validate_arrays(parts[b'KeyTime'][0],parts[b'KeyValueFloat'][0],n,parts[b'KeyAttrFlags'][0],parts[b'KeyAttrRefCount'][0])
   state['raw_curves'].append({'curve_uuid':curve.props[0],**record})
  state['fbx_version']=version
  return tree,version
 def observe(*args):
  require(state['capture'] is not None,'binding before raw admission');state['capture'](*args)
 patches=converter.patch_importer(observe);store=imp.blen_store_keyframes_multi
 def bounded_store(fbx_key_times,pairs,blen_start_offset,fps,fbx_ktime,fbx_start_offset=0):
  converted=imp._convert_fbx_time_to_blender_time(fbx_key_times,blen_start_offset,fbx_start_offset,fps,fbx_ktime).astype(np.float32)
  require(np.array_equal(converted,expected),'full transformed input clock differs')
  kept=[]
  for fc,values in pairs:
   values=np.asarray(values);require(values.ndim==1 and len(values)==len(expected) and np.isfinite(values).all(),'full transformed values invalid')
   state['stored_curves'].append({'owner_action':fc.id_data.name,'data_path':fc.data_path,'array_index':fc.array_index,
      'full_key_count':len(values),'full_time_sha256':array_hash(converted,'<f4'),'full_value_sha256':array_hash(values,'<f4'),
      'retained_value_sha256':array_hash(values[indices],'<f4')})
   kept.append((fc,values[indices]))
  store(fbx_key_times[indices],kept,blen_start_offset,fps,fbx_ktime,fbx_start_offset)
 parse_fbx.parse=parse_once;imp.blen_store_keyframes_multi=bounded_store
 try:
  require('FINISHED' in bpy.ops.import_scene.fbx(filepath=str(path),use_anim=True,anim_offset=0.,ignore_leaf_bones=False,
          automatic_bone_orientation=False,use_prepost_rot=True),'bounded import failed')
 finally:
  parse_fbx.parse=original_parse;imp.blen_store_keyframes_multi=store
 require(state['parse_calls']==1,'exact one full raw parse required')
 admission=state['capture'].verify([bpy.data.objects[x] for x in OWNERS],list(bpy.data.actions),[1.,96.])
 require(len(bpy.data.actions)==6,'Action inventory differs')
 count=0;actual_keys=expected[indices];actions=[]
 stored_by_key={}
 for r in state['stored_curves']:
  key=(r['owner_action'],r['data_path'],r['array_index']);require(key not in stored_by_key,'duplicate stored curve identity');stored_by_key[key]=r
 for action in bpy.data.actions:
  require(len(action.fcurves)>0,'empty Action')
  for fc in action.fcurves:
   require(len(fc.keyframe_points)==len(indices),'retained key count differs');pairs=np.empty(len(indices)*2,dtype=np.float32);fc.keyframe_points.foreach_get('co',pairs)
   require(np.array_equal(pairs[::2],actual_keys) and np.isfinite(pairs).all(),'retained exact clock/values differ')
   key=(action.name,fc.data_path,fc.array_index);require(key in stored_by_key,'retained curve missing input identity')
   require(array_hash(pairs[1::2],'<f4')==stored_by_key[key]['retained_value_sha256'],'retained values changed during storage')
   require(all(k.interpolation=='LINEAR' for k in fc.keyframe_points),'retained interpolation differs');count+=1
  actions.append({'action':action.name,'curves':len(action.fcurves),'frame_range':list(action.frame_range)})
 require(count==len(state['stored_curves']),'stored curve coverage mismatch')
 raw={'passed':True,'fbx_sha256':expected_sha,'fbx_version':state['fbx_version'],'curve_count':RAW_CURVES,'key_count':len(expected),
      'subdivisions':n,'all_times_values_finite_checked':True,'linear_flags':24836,'curves':state['raw_curves']}
 stored={'passed':True,'curve_count':count,'actions':actions,'curves':state['stored_curves'],
         'full_transform_sequence_preserved_before_selection':True,'all_full_input_times_values_checked':True}
 receipt={'schema':'rust-duty-fbx-bounded-key-window/v1','passed':True,'fbx_sha256':expected_sha,**plan,
     'full_raw_admission':raw,'full_raw_admission_sha256':digest(raw),'full_transformed_admission':stored,'full_transformed_admission_sha256':digest(stored),
     'retained_native_grid_sha256':array_hash(actual_keys,'<f4'),'imported_curve_count':count,'actions':actions,
     'linear_interpolation':True,'partial_instantiation_only':True,'full_clip_instantiated':False,
     'selection_stage':'after complete official transformation/hemisphere/unwrap sequence',
     'patches':patches,'single_stack_admission':admission,'recipe_pins_sha256':sha(HERE/'pins.json')}
 require(sha(path)==expected_sha,'FBX changed during import')
 return receipt
