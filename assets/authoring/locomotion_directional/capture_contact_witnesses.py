"""Render diagnostic side and underside views in memory; never save/change source."""
import bpy,json,sys,math,csv
from pathlib import Path
from mathutils import Vector
args=sys.argv[sys.argv.index('--')+1:];OUT=Path(args[0]);TRACKS=Path(args[1]);OUT.mkdir(parents=True,exist_ok=True)
s=bpy.context.scene;r=bpy.data.objects['Arms'];rows=list(csv.DictReader(TRACKS.open()));r.animation_data.use_nla=False
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
for o in bpy.data.objects:
 if o.name.startswith('RD_REFERENCE_ONLY'):o.hide_render=True
s.render.resolution_x=1280;s.render.resolution_y=720;s.render.resolution_percentage=100;s.render.engine='CYCLES';s.cycles.samples=32;s.cycles.use_denoising=False;s.render.image_settings.file_format='PNG'
camera_data=bpy.data.cameras.new('Directional contact witness only');camera_data.type='ORTHO';camera_data.ortho_scale=.60;camera=bpy.data.objects.new('Directional contact witness only',camera_data);s.collection.objects.link(camera);s.camera=camera
base=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];r.animation_data.action=base;s.frame_set(1);bpy.context.view_layer.update();basis={p.name:p.matrix_basis.copy() for p in r.pose.bones};manifest=[]
for name in sorted({row['action'] for row in rows}):
 subset=[row for row in rows if row['action']==name];N=int(bpy.data.actions[name]['loop_period_frames']);subset=[row for row in subset if int(row['frame'])<=N]
 field='support_cuff_surface' if 'support_cuff_surface_x' in subset[0] else 'support_wrist'
 extrema=sorted(set(int(op(subset,key=lambda row:float(row[field+'_'+axis]))['frame']) for axis in ['x','y'] for op in [min,max]))
 r.animation_data.action=None
 for p in r.pose.bones:p.matrix_basis=basis[p.name].copy()
 r.animation_data.action=base;s.frame_set(1);bpy.context.view_layer.update();r.animation_data.action=bpy.data.actions[name]
 for frame in extrema:
  s.frame_set(frame);bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();deps.update();er=r.evaluated_get(deps)
  target=.6*(er.matrix_world@er.pose.bones['hand_l'].matrix.translation)+.4*(er.matrix_world@er.pose.bones['hand_r'].matrix.translation)
  for view,offset in [('side',Vector((.65,0,0))),('underside',Vector((0,0,-.65)))]:
   camera.location=target+offset;camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler();s.render.filepath=str(OUT/f'{name}_{view}_f{frame:03d}.png');bpy.ops.render.render(write_still=True)
   manifest.append({'action':name,'frame':frame,'phase':(frame-1)/N,'view':view,'filename':Path(s.render.filepath).name,'camera_world':list(map(list,camera.matrix_world)),'ortho_scale_m':.60,'scope':'Diagnostic native contact witness; not source/reference-view scoring'})
(OUT/'contact_witness_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
