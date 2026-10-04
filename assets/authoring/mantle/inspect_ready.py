"""Blender4.3.2 non-render baseline diagnostic. Never saves or authors a BLEND."""
import bpy,argparse,hashlib,json,math,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);assert not a.output.exists();assert bpy.app.version_string=='4.3.2'
src=Path(bpy.data.filepath);sha=hashlib.sha256(src.read_bytes()).hexdigest();assert sha=='a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b'
rig=bpy.data.objects['Arms'];scene=bpy.context.scene
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
rig.animation_data.use_nla=False;rig.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];scene.frame_set(1);bpy.context.view_layer.update()
rig.animation_data.action=bpy.data.actions['RD_Locomotion_Normal_Entry_4419_4434_WIP2'];scene.frame_set(1);rig.update_tag();bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();deps.update();er=rig.evaluated_get(deps)
names=['righthand_prop','righthand_prop_lefthand','righthand_prop_righthand','lefthand_prop','hand_l','hand_r','MCH_hand_guarded_l','MCH_hand_guarded_r','MCH_attach_goal_l','MCH_attach_goal_r','MCH_lowerarm_l','MCH_lowerarm_r']
def matrix(m):return [list(r) for r in m]
def atom(x):
 if isinstance(x,(str,int,float,bool)):return x
 return list(x) if hasattr(x,'__iter__') else str(x)
rows={}
for n in names:
 b=rig.pose.bones[n];m=er.matrix_world@er.pose.bones[n].matrix
 rows[n]={'parent':b.parent.name if b.parent else None,'rotation_mode':b.rotation_mode,'world_matrix':matrix(m),'properties':{k:{'value':atom(b[k]),'python_type':type(b[k]).__name__} for k in b.keys()},'constraints':[{'name':c.name,'type':c.type,'influence':c.influence,'target':c.target.name if hasattr(c,'target') and c.target else None,'subtarget':getattr(c,'subtarget',None)} for c in b.constraints]}
skin={}
for n in ['Actual arms mesh 0','Actual arms mesh 1','Actual arms mesh 2']:
 obj=bpy.data.objects[n].evaluated_get(deps);m=obj.to_mesh();verts=[list(obj.matrix_world@v.co) for v in m.vertices];skin[n]={'vertices':len(verts),'all_finite':all(math.isfinite(x) for v in verts for x in v),'evaluated_world_vertices_sha256':hashlib.sha256(json.dumps(verts).encode()).hexdigest()};obj.to_mesh_clear()
errors={s:(er.pose.bones['hand_'+s].matrix.translation-er.pose.bones['righthand_prop_'+side+'hand'].matrix.translation).length for s,side in [('l','left'),('r','right')]}
drivers=[d for o in bpy.data.objects if o.animation_data for d in o.animation_data.drivers]
out={'schema':'rust-duty-mantle-ready-baseline/v1','status':'baseline','source_sha256':sha,'source_saved':False,'render_performed':False,'new_actions_created':0,'camera':{'name':scene.camera.name,'world_matrix':matrix(scene.camera.matrix_world),'lens_mm':scene.camera.data.lens,'sensor_width_mm':scene.camera.data.sensor_width,'resolution':[scene.render.resolution_x,scene.render.resolution_y],'resolution_percentage':scene.render.resolution_percentage},'units':{'system':scene.unit_settings.system,'scale_length':scene.unit_settings.scale_length},'action':'RD_Locomotion_Normal_Entry_4419_4434_WIP2','frame':1,'nodes':rows,'skin':skin,'wrist_to_attachment_position_error_rig_units':errors,'driver_count':len(drivers),'invalid_drivers':[d.data_path for d in drivers if not d.driver.is_valid],'limit':'Single ready pose only. Matrix attachment agreement is not finger-surface contact, anatomy review, detached-hand branch verification, or animation acceptance.'}
assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;assert all(v['all_finite'] for v in skin.values());a.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({'source_unchanged':True,'skin':skin,'wrist_errors':errors,'driver_count':len(drivers),'invalid_drivers':out['invalid_drivers']}))
