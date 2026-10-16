"""Foreground-only rendered Eevee VIEW_3D capture. No Cycles or offline render operator.

Run in the foreground Blender Python console after explicit viewport authorization.
The authoring BLEND is opened read-only and never saved.
"""
import bpy, hashlib, json, traceback
from pathlib import Path
P=Path(__file__).resolve().parent
SOURCE=P/'candidate/aella_mantle_r2.blend'
EXPECTED='740e7e2b16d6947075c321467cfe21d36314f68b93829cf8a2d954b4d382cdb5'
OUT=P/'viewport';OUT.mkdir(exist_ok=True)
assert not bpy.app.background
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==EXPECTED
bpy.ops.wm.open_mainfile(filepath=str(SOURCE),load_ui=False,use_scripts=False)
A=bpy.data.objects['Arms'];C=bpy.data.objects['RD First Person Review']
window=bpy.context.window or next(iter(bpy.context.window_manager.windows),None)
assert window is not None,'Foreground window is not ready; run capture from the UI timer'
S=next(s for s in bpy.data.scenes if C.name in s.objects);window.scene=S
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False
A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update()
A.animation_data.action=bpy.data.actions['aella_vault_low_r2']
S.camera=C;S.render.engine='BLENDER_EEVEE_NEXT';S.eevee.taa_samples=8
S.render.resolution_x=1280;S.render.resolution_y=720;S.render.resolution_percentage=100
S.render.fps=60;S.render.fps_base=1;S.render.image_settings.file_format='PNG'
area=max(window.screen.areas,key=lambda a:a.width*a.height);area.type='VIEW_3D'
space=area.spaces.active;space.shading.type='RENDERED';space.shading.use_scene_world_render=True;space.shading.use_scene_lights_render=True
space.overlay.show_overlays=False;space.show_gizmo=False;space.region_3d.view_perspective='CAMERA'
manifest={'status':'capturing','source_sha256':EXPECTED,'action':'aella_vault_low_r2','engine':'BLENDER_EEVEE_NEXT','method':'foreground VIEW_3D rendered shading, bpy.ops.render.opengl(view_context=True)','background':False,'camera':{'name':C.name,'world':[list(r) for r in C.matrix_world],'lens':C.data.lens,'sensor_width':C.data.sensor_width,'resolution':[1280,720]},'fps':[60,1],'time_base':[1,15360],'source_start':7284,'source_end_exclusive':7348,'frames':[]}
state={'frame':1,'stage':'set'}
def write(): (OUT/'viewport_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
def tick():
 try:
  assert not bpy.app.background and S.render.engine=='BLENDER_EEVEE_NEXT' and space.shading.type=='RENDERED'
  f=state['frame']
  if state['stage']=='set':
   S.frame_set(f);bpy.context.view_layer.update();area.tag_redraw();state['stage']='capture';return 0.5 if f>1 else 3.
  path=OUT/f'frame_{f:04}.png';assert not path.exists()
  S.render.filepath=str(path);region=next(r for r in area.regions if r.type=='WINDOW')
  with bpy.context.temp_override(window=window,area=area,region=region):bpy.ops.render.opengl(write_still=True,view_context=True)
  assert path.exists();native=7283+f
  manifest['frames'].append({'blender_frame':f,'native_frame':native,'source_pts':native*256,'candidate_pts':(f-1)*256,'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
  if f==64:
   assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==EXPECTED
   manifest['status']='complete';write();return None
  write();state['frame']=f+1;state['stage']='set';return 0.1
 except Exception:
  manifest['status']='failed';manifest['error']=traceback.format_exc();write();return None
write();bpy.app.timers.register(tick,first_interval=1.)
