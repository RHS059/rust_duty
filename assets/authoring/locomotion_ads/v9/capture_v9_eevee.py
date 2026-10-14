"""Foreground true rendered Eevee viewport only. Never run in background."""
import bpy,hashlib,json,time,traceback
from pathlib import Path
HERE=Path(__file__).resolve().parent
assert not bpy.app.background
manifest=json.loads((HERE/'v9_scene_manifest.json').read_text())
source=HERE/Path(manifest['blend']).name
assert Path(bpy.data.filepath)==source
assert hashlib.sha256(source.read_bytes()).hexdigest()==manifest['sha256']
window=bpy.context.window
scene=bpy.data.scenes[manifest['scene']];window.scene=scene
assert scene.camera.name==manifest['camera']
scene.render.engine='BLENDER_EEVEE_NEXT';scene.eevee.taa_samples=8;scene.eevee.taa_render_samples=8
scene.render.resolution_x=960;scene.render.resolution_y=540;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGB'
scene.render.fps=60;scene.render.fps_base=1;scene.render.film_transparent=False
area=bpy.context.area;area.type='VIEW_3D';space=area.spaces.active
space.shading.type='RENDERED';space.shading.use_scene_world_render=True;space.shading.use_scene_lights_render=True
space.overlay.show_overlays=False;space.show_gizmo=False
space.region_3d.view_perspective='CAMERA';space.region_3d.view_camera_offset=(0,0)
mode=json.loads((HERE/'capture_request.json').read_text())['mode']
out=HERE/'eevee_frames';out.mkdir(exist_ok=True)
queue=[1] if mode=='smoke' else list(range(1,127))
state={'candidate_id':manifest['candidate_id'],'mode':mode,'status':'running','foreground':not bpy.app.background,'render_method':'bpy.ops.render.opengl(write_still=True,view_context=True), actual foreground RENDERED Eevee viewport','engine':scene.render.engine,'viewport_shading':space.shading.type,'viewport_samples':8,'resolution':[960,540],'fps':'60/1','blend_sha256':manifest['sha256'],'source_ads_sha256':manifest['source_ads_sha256'],'source_hip_sha256':manifest['source_hip_sha256'],'camera':scene.camera.name,'camera_matrix':[[float(v) for v in row] for row in scene.camera.matrix_world],'planned_frames':len(queue),'completed_frames':0,'frames':[],'started_unix':time.time()}
status=HERE/('viewport_capture_'+mode+'.json')
index=0;stage='set'
def tick():
 global index,stage
 try:
  assert scene.render.engine=='BLENDER_EEVEE_NEXT' and space.shading.type=='RENDERED'
  if index>=len(queue):
   state['status']='completed';state['finished_unix']=time.time()
   state['source_blend_bytes_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==manifest['sha256']
   status.write_text(json.dumps(state,indent=2)+'\n');return None
  frame=queue[index];path=out/f'f{frame:06d}.png'
  if stage=='set':
   scene.frame_set(frame);bpy.context.view_layer.update();area.tag_redraw();stage='capture';return .20
  region=next(r for r in area.regions if r.type=='WINDOW');scene.render.filepath=str(path)
  with bpy.context.temp_override(window=window,screen=window.screen,area=area,region=region):bpy.ops.render.opengl(write_still=True,view_context=True)
  assert path.is_file() and path.stat().st_size>1000
  state['frames'].append({'output_frame':frame-1,'blender_frame':frame,'reference_frame':2297+frame,'reference_pts':(2297+frame)*256,'file':str(path.relative_to(HERE)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
  index+=1;state['completed_frames']=index;status.write_text(json.dumps(state,indent=2)+'\n');stage='set';return .01
 except Exception:
  state['status']='failed';state['error']=traceback.format_exc();status.write_text(json.dumps(state,indent=2)+'\n');return None
status.write_text(json.dumps(state,indent=2)+'\n')
bpy.app.timers.register(tick,first_interval=2.0)
