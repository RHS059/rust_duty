"""Reopen the saved ADS source, verify frozen data, and render actual source camera frames."""
import bpy,json,math,sys,hashlib
from pathlib import Path
import numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
P=Path(__file__).resolve().parent;sys.dont_write_bytecode=True;sys.path.insert(0,str(P))
from source_integrity import snapshot,digest
I=json.loads((P/'source_integrity.json').read_text());V=json.loads((P/'preservation.json').read_text());ALIGN=json.loads((P/'sight_alignment.json').read_text())
assert hashlib.sha256((P/'ads.blend').read_bytes()).hexdigest()==I['portable_source_sha256']
assert snapshot(bpy)==I['preserved']
assert all(snapshot(bpy)['actions'][n]==v for n,v in V['prior_snapshot']['actions'].items())
A=bpy.data.objects['Arms'];S=bpy.context.scene;CAM=bpy.data.objects['RD First Person Review'];C=CAM.matrix_world.copy();W=bpy.data.objects['hk416_weapon']
assert [list(r) for r in C]==ALIGN['camera_world']
A.animation_data.use_nla=False
for t in A.animation_data.nla_tracks:t.mute=True
A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();basis={p.name:p.matrix_basis.copy() for p in A.pose.bones}
def select(action,f):
 A.animation_data.action=None
 for p in A.pose.bones:p.matrix_basis=basis[p.name].copy()
 A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();A.animation_data.action=bpy.data.actions[action];i=math.floor(f);S.frame_set(i,subframe=f-i);bpy.context.view_layer.update()

def pose():
 dg=bpy.context.evaluated_depsgraph_get();dg.update();ar=A.evaluated_get(dg)
 out={'bones':np.array([ar.matrix_world@p.matrix for p in ar.pose.bones if p.bone.use_deform]),'actors':np.array([bpy.data.objects[n].evaluated_get(dg).matrix_world for n in ['hk416_weapon','hk416_magazine']])}
 for n in ['Actual arms mesh 0','Actual arms mesh 1','Actual arms mesh 2']:
  o=bpy.data.objects[n].evaluated_get(dg);m=o.to_mesh();out[n]=np.array([o.matrix_world@v.co for v in m.vertices]);o.to_mesh_clear()
 return out
endpoints={}
for n,a,f in [('ready','RD_Locomotion_Normal_Entry_4419_4434_WIP2',1),('entry_start','ads_entry_r1',1),('entry_end','ads_entry_r1',16),('hold_start','ads_hold_r1',1),('hold_mid','ads_hold_r1',31),('hold_end','ads_hold_r1',61),('exit_start','ads_exit_r1',1),('exit_end','ads_exit_r1',16)]:select(a,f);endpoints[n]=pose()
links=[('ready','entry_start'),('entry_end','hold_start'),('hold_start','hold_mid'),('hold_mid','hold_end'),('hold_end','exit_start'),('exit_end','ready')]
errors={a+'__'+b:{n:float(np.max(np.abs(endpoints[a][n]-endpoints[b][n]))) for n in endpoints[a]} for a,b in links}
assert max(v for d in errors.values() for v in d.values())<1e-6
select('ads_hold_r1',1);points={}
for key in ['front','rear']:
 q=world_to_camera_view(S,CAM,W.matrix_world@Vector(ALIGN[key+'_landmark_local']));points[key]={'pixel':[q.x*1280,(1-q.y)*720],'center_error_px':math.hypot(q.x*1280-640,(1-q.y)*720-360)}
assert max(x['center_error_px'] for x in points.values())<.001
assert all(fc.driver.is_valid for o in bpy.data.objects if o.animation_data for fc in o.animation_data.drivers)
(P/'reopen_validation.json').write_text(json.dumps({'source_hash_verified':True,'full_source_integrity_snapshot_matches':True,'prior_action_fingerprints_match':62,'valid_driver_count':sum(len(o.animation_data.drivers) for o in bpy.data.objects if o.animation_data),'source_camera_unchanged':True,'endpoint_errors':errors,'sight_alignment':points},indent=2)+'\n')
S.camera=CAM;S.render.engine='CYCLES';S.cycles.samples=96;S.cycles.use_denoising=False;S.render.resolution_x=1280;S.render.resolution_y=720;S.render.resolution_percentage=100;S.render.image_settings.file_format='PNG'
OUT=P/'renders';OUT.mkdir(exist_ok=True)
for name,act,f in [('ready','ads_entry_r1',1),('entry_mid','ads_entry_r1',8.5),('aimed_hold','ads_hold_r1',31),('exit_mid','ads_exit_r1',8.5),('exit_ready','ads_exit_r1',16)]:
 select(act,f);S.render.filepath=str(OUT/(name+'.png'));bpy.ops.render.render(write_still=True)
assert hashlib.sha256((P/'ads.blend').read_bytes()).hexdigest()==I['portable_source_sha256']
print('REOPEN_AND_RENDER_OK',flush=True)
