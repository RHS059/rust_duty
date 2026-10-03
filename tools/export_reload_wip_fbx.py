#!/usr/bin/env python3
"""Export an explicitly named canonical Action as current WIP, without joining clips.
Run in Blender 4.3.2. An explicit range is a requested delivery scope, not approval.
"""
import argparse
import hashlib
import inspect
import json
import math
from pathlib import Path
import sys
import bpy
import numpy as np

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True);p.add_argument('--source-sha256',required=True)
p.add_argument('--action',required=True);p.add_argument('--native-start',type=int,required=True);p.add_argument('--native-end',type=int,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
assert not a.output.exists(), 'use a fresh output directory'
assert hashlib.sha256(a.source.read_bytes()).hexdigest()==a.source_sha256
assert bpy.app.version[:3]==(4,3,2)
bpy.ops.wm.open_mainfile(filepath=str(a.source.resolve()),use_scripts=False)
A=bpy.data.objects['Arms'];S=bpy.context.scene
def action_record(action):
 curves=[{'path':f.data_path,'index':f.array_index,'extrapolation':f.extrapolation,'keys':[{'co':list(k.co),'left':list(k.handle_left),'right':list(k.handle_right),'interpolation':k.interpolation,'left_type':k.handle_left_type,'right_type':k.handle_right_type} for k in f.keyframe_points]} for f in action.fcurves]
 return {'name':action.name,'stored_range':list(action.frame_range),'curve_sha256':hashlib.sha256(json.dumps(curves,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'fcurves':len(curves)}
inventory=[action_record(action) for action in bpy.data.actions]
A.animation_data.action=bpy.data.actions[a.action]
selected=action_record(A.animation_data.action)
for t in A.animation_data.nla_tracks:t.mute=True
S.frame_start=a.native_start+1;S.frame_end=a.native_end+1;S.render.fps=60;S.render.fps_base=1.001
skins=['Actual arms mesh '+str(i) for i in range(3)]
props=['hk416_weapon','hk416_magazine','hk416_magazine_outgoing'];names=['Arms']+skins+props
bones=list(A.data.bones.keys())
frames=set(np.arange(a.native_start,a.native_end+.01,.25).tolist())
frames.update(np.arange(a.native_start+.0703125,a.native_end,.25).tolist())
frames.update([f for f in [15.609375,44.,111.95,111.975,111.98,111.981,111.9825,111.985,111.99,111.995,111.9975,111.999,111.9995,111.9999,112.,112.0001,112.001,112.005,112.01,112.02,112.05] if a.native_start<=f<=a.native_end])
frames=np.array(sorted(frames));a.output.mkdir(parents=True)
def setframe(n):
 f=float(n)+1;S.frame_set(math.floor(f),subframe=f-math.floor(f));A.update_tag();bpy.context.view_layer.update();return bpy.context.evaluated_depsgraph_get()
def vertexworld(o,dg):
 e=o.evaluated_get(dg);m=e.to_mesh();v=np.empty(len(m.vertices)*3,dtype=np.float64);m.vertices.foreach_get('co',v);v=v.reshape(-1,3);mw=np.array(e.matrix_world);r=v@mw[:3,:3].T+mw[:3,3];e.to_mesh_clear();return r
source={n:[] for n in skins+['bones','props']}
for i,n in enumerate(frames):
 dg=setframe(n)
 for name in skins:source[name].append(vertexworld(bpy.data.objects[name],dg))
 ae=A.evaluated_get(dg)
 source['bones'].append(np.array([ae.matrix_world@ae.pose.bones[b].matrix for b in bones]))
 source['props'].append(np.array([bpy.data.objects[p].evaluated_get(dg).matrix_world for p in props]))
 if i%128==0:print('SOURCE_WITNESS',i,len(frames),flush=True)
np.savez_compressed(a.output/'source-witnesses.npz',frames=frames,**{k:np.array(v) for k,v in source.items()})
import io_scene_fbx.export_fbx_bin as exp
src=inspect.getsource(exp.fbx_animations_do)
before='currframes = np.arange(f_start, np.nextafter(f_end, np.inf), step=bake_step)'
assert src.count(before)==1
exp._rd_extra_frames=[float(f)+1 for f in frames]+[112.99999,112.999999]
src=src.replace(before,'currframes = np.unique(np.concatenate((np.arange(f_start, np.nextafter(f_end, np.inf), step=bake_step), np.array([f for f in _rd_extra_frames if f_start <= f <= f_end]))))')
old='scene.frame_set(int_currframe, subframe=subframe)';assert src.count(old)==1
src=src.replace(old,old+'\n            bpy.data.objects["Arms"].update_tag()\n            bpy.context.view_layer.update()')
exec(src,exp.__dict__)
setframe(a.native_start);bpy.ops.object.select_all(action='DESELECT')
for name in names:
 o=bpy.data.objects[name];o.hide_set(False);o.select_set(True)
bpy.context.view_layer.objects.active=A
fbx=a.output/'current-full-wip.fbx'
bpy.ops.export_scene.fbx(filepath=str(fbx),use_selection=True,object_types={'ARMATURE','MESH'},use_mesh_modifiers=True,add_leaf_bones=False,use_armature_deform_only=False,bake_anim=True,bake_anim_use_all_bones=True,bake_anim_use_nla_strips=False,bake_anim_use_all_actions=False,bake_anim_force_startend_keying=True,bake_anim_step=.015625,bake_anim_simplify_factor=0.,axis_forward='-Y',axis_up='Z',path_mode='STRIP',embed_textures=False)
assert hashlib.sha256(a.source.read_bytes()).hexdigest()==a.source_sha256
r={'schema':'rust-duty-current-reload-fbx/v1','status':'WIP','source_sha256':a.source_sha256,'action':a.action,
   'source_action':selected,'action_inventory':inventory,'action_stored_range':list(A.animation_data.action.frame_range),'native_requested_range':[a.native_start,a.native_end],
   'native_fps':[60000,1001],
   'reviewed_subranges':[[max(lo,a.native_start),min(hi,a.native_end)] for lo,hi in ({'RD_Reload_Tactical_Hands_Opening_WIP':[[0,30]],'RD_Reload_Tactical_HandApproach_AndReturn_WIP':[[48,156]]}.get(a.action,[])) if max(lo,a.native_start)<=min(hi,a.native_end)],
   'review_scope_note':'Review ranges belong to this exact Action only. Opening is a separate current Action; full HandApproach keeps its authored base-to-48 prefix. Stored extents do not imply approval.',
   'scope':'Direct evaluation of a single canonical Action across requested full WIP range. No reconstructed gap, joined clips, or full-motion approval.',
   'bones':bones,'skin_objects':skins,'actors':props,'source_witness_samples':len(frames),
   'files':{x.name:{'sha256':hashlib.sha256(x.read_bytes()).hexdigest(),'bytes':x.stat().st_size} for x in [fbx,a.output/'source-witnesses.npz']}}
(a.output/'export-manifest.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2),flush=True)
