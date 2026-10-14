"""Explicit r6 pair binding for Aella's existing Eevee viewport capture.
Call bind_pair(), select_frame(frame) for each native frame, then restore_pair().
This helper performs no render, encoding, upload or runtime integration.
"""
import bpy,json,hashlib,math
from pathlib import Path
from source_integrity import action_fingerprint
P=Path(__file__).resolve().parent
_state=None

def bind_pair():
 global _state
 assert _state is None,'A prior binding must be restored first'
 c=json.loads((P/'correction_design.json').read_text());fm=json.loads((P/'frame_map.json').read_text())
 assert bpy.app.version_string=='4.3.2'
 assert hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()==fm['blend_sha256']
 assert all(action_fingerprint(bpy.data.actions[n])==v for n,v in fm['actions'].items())
 s=bpy.context.scene;r=bpy.data.objects[c['armature_object']];cam=bpy.data.objects[c['camera_object']]
 _state={'scene':(s.frame_start,s.frame_end,s.frame_current,s.frame_subframe,s.render.fps,s.render.fps_base,s.camera),
 'objects':{o.name:{k:list(getattr(o,k)) for k in ('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')} for o in bpy.data.objects},
 'pose':{b.name:{k:list(getattr(b,k)) for k in ('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')} for b in r.pose.bones},
 'pose_properties':{b.name:{k:v for k,v in b.items() if isinstance(v,(int,float,str))} for b in r.pose.bones},
 'animation':{o.name:None if o.animation_data is None else (o.animation_data.action,o.animation_data.use_nla,[(t,t.mute,t.is_solo) for t in o.animation_data.nla_tracks]) for o in bpy.data.objects}}
 for o in bpy.data.objects:
  if o.animation_data:
   o.animation_data.use_nla=False
   for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
 r.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];s.frame_set(1);bpy.context.view_layer.update()
 r.animation_data.action=bpy.data.actions[c['action']];cam.animation_data_create();cam.animation_data.action=bpy.data.actions[c['camera_action']]
 s.camera=cam;s.frame_start=1;s.frame_end=69;s.render.fps=60;s.render.fps_base=1
 select_frame(1)
 return fm

def select_frame(frame):
 assert _state is not None
 assert 1<=frame<=69 and frame==int(frame),'Native frame capture only'
 c=json.loads((P/'correction_design.json').read_text());s=bpy.context.scene
 for name,action in ((c['armature_object'],c['action']),(c['camera_object'],c['camera_action'])):
  assert bpy.data.objects[name].animation_data.action.name==action,'Missing required paired Action'
 s.frame_set(int(frame));bpy.context.view_layer.update()
 cam=bpy.data.objects[c['camera_object']];r=bpy.data.objects[c['armature_object']]
 return {'candidate_frame':int(frame),'reference_native_frame':2240+int(frame),'camera_world':[list(x) for x in cam.matrix_world],'rig_world':[list(x) for x in r.matrix_world], 'actions':{name:action_fingerprint(bpy.data.actions[name]) for name in (c['action'],c['camera_action'])}}

def restore_pair():
 global _state
 assert _state is not None
 c=json.loads((P/'correction_design.json').read_text());s=bpy.context.scene;r=bpy.data.objects[c['armature_object']]
 for n,state in _state['animation'].items():
  o=bpy.data.objects[n]
  if state is None:o.animation_data_clear();continue
  o.animation_data.action=state[0];o.animation_data.use_nla=state[1]
  for t,m,solo in state[2]:t.mute=m;t.is_solo=solo
 for b in r.pose.bones:
  for k,v in _state['pose'][b.name].items():setattr(b,k,v)
  for k,v in _state['pose_properties'][b.name].items():b[k]=v
 for n,values in _state['objects'].items():
  for k,v in values.items():setattr(bpy.data.objects[n],k,v)
 start,end,frame,sub,fps,base,camera=_state['scene'];s.frame_start=start;s.frame_end=end;s.render.fps=fps;s.render.fps_base=base;s.camera=camera;s.frame_set(frame,subframe=sub);bpy.context.view_layer.update();_state=None
