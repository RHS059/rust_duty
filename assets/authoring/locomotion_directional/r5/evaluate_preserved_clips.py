"""Evaluate 44 legacy clips and four frozen clips from each of r1, r2, r3 and r4 without export or source mutation.

Derived from the PR16 exporter, using the candidate source-integrity sidecar and
frozen baseline export config. Compare output with the frozen baseline oracle.
"""
import bpy, json, math, hashlib, sys, argparse
from pathlib import Path
import numpy as np
from mathutils import Matrix

parser=argparse.ArgumentParser()
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--config',type=Path,default=Path(__file__).resolve().with_name('prior_evaluation_config.json'))
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
OUT=args.output_dir.resolve();OUT.mkdir(parents=True,exist_ok=True)
config=json.loads(args.config.read_text())
assert bpy.app.version_string==config['blender_version'], 'Use Blender 4.3.2'
FPS=config['source_fps']
BAKE_HZ=config['bake_hz']
assert FPS==60 and BAKE_HZ==480
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from source_integrity import snapshot
integrity=json.loads(Path(__file__).resolve().with_name('source_integrity.json').read_text())
assert snapshot(bpy)==integrity['preserved'], 'Frozen source data differs; review and update the source contract first'
C=Matrix(((1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))
scene=bpy.context.scene
rig=bpy.data.objects[config['armature']]
skin_names=config['skin_objects']
actor_names=config['rigid_actors']
names=[config['armature']]+skin_names+actor_names
clips=[(row['name'],row['action'],row['frame_start'],row['frame_end'],row['loop']) for row in config['source_takes']]
assert len(clips)==config['source_take_count']
assert len({row[0] for row in clips})==config['source_take_count']
assert config['purpose']=='prior_evaluated_motion_preservation'
assert len(clips)==60
assert sum(row['role']=='preserved_r4' for row in config['source_takes'])==4
assert sum(row['role']=='preserved_r3' for row in config['source_takes'])==4
assert sum(row['role']=='preserved_r2' for row in config['source_takes'])==4
assert sum(row['role']=='preserved_r1' for row in config['source_takes'])==4
assert sum(row['role']=='diagnostic' for row in config['source_takes'])==1
assert sum(row['role']=='gameplay' for row in config['source_takes'])==43
assert {row[0] for row in clips if row[0].startswith('normal_exit_bridge_')}=={'normal_exit_bridge_%03d'%i for i in range(35)}
source_file=Path(bpy.data.filepath)
source_hash=hashlib.sha256(source_file.read_bytes()).hexdigest()
assert source_hash==integrity['portable_source_sha256'], 'Unexpected source bytes'
hashes={source_file.name:source_hash}
assert all(not (OUT/name).exists() for name in ('locomotion.fbx','native_oracle.json','native_oracle.npz')), 'Refuse overwrite'
assert all(action in bpy.data.actions for _,action,*_ in clips), 'Missing source Action'
base=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered']
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
rig.animation_data.use_nla=False
rig.animation_data.action=base
scene.render.fps=FPS;scene.render.fps_base=1
scene.frame_set(1);bpy.context.view_layer.update()
base_basis={p.name:p.matrix_basis.copy() for p in rig.pose.bones}
ready=bpy.data.actions[clips[0][1]].copy();ready.name='__runtime_exact_entry_start_ready__'
for fc in ready.fcurves:
 v=fc.evaluate(1)
 fc.keyframe_points.clear()
 for f in (1,2):
  k=fc.keyframe_points.insert(f,v);k.interpolation='LINEAR'
 for m in list(fc.modifiers):fc.modifiers.remove(m)
actions={n:(ready if n=='normal_ready' else bpy.data.actions[a]) for n,a,*_ in clips}
deform=[b.name for b in rig.data.bones if b.use_deform]
assert len(deform)==config['deform_bone_count']==72

def set_action(action):
 rig.animation_data.action=None
 for p in rig.pose.bones:p.matrix_basis=base_basis[p.name].copy()
 rig.animation_data.action=base
 scene.frame_set(1);bpy.context.view_layer.update()
 rig.animation_data.action=action

def set_frame(frame):
 i=math.floor(frame);scene.frame_set(i,subframe=frame-i)
 bpy.context.view_layer.update()
 deps=bpy.context.evaluated_depsgraph_get();deps.update();return deps

def mat(m):return np.array(m,dtype=np.float32)
def positions(o,deps):
 eo=o.evaluated_get(deps);me=eo.to_mesh()
 vals=np.empty(len(me.vertices)*3,dtype=np.float32);me.vertices.foreach_get('co',vals)
 vals=vals.reshape(-1,3)
 world=mat(C@eo.matrix_world)
 ans=vals@world[:3,:3].T+world[:3,3]
 eo.to_mesh_clear();return ans

meta={'schema':'rust-duty-native-locomotion-oracle/v1','source_files_sha256':hashes,
      'blender':bpy.app.version_string,'fps':FPS,'bake_hz':BAKE_HZ,'selected_loop':'AngleFix',
      'clip_names':[c[0] for c in clips],'deform_bones':deform,'skin_objects':skin_names,
      'actors':actor_names,'excluded_actor':'hk416_magazine_outgoing: reload-only duplicate has zero scale throughout locomotion',
      'matrix_layout':'row-major; Blender world converted by C=(x,z,-y); runtime applies Ry(pi) once',
      'contact_acceptance':False,'samples':{},'contact_samples':{},'source_owner_actions':{o.name:o.animation_data.action.name if o.animation_data and o.animation_data.action else None for o in bpy.data.objects if o.name in names}}
arrays={}
for name,source,start,end,loop in clips:
 set_action(actions[name])
 # Both exact bake frames and intervening half-steps, independently reevaluated.
 exact=sorted(set([start,end]+[start+(end-start)*i/12 for i in range(13)]))
 exact=[round((f-start)*4)/4+start for f in exact]
 if name=='normal_diagnostic_sequence':exact=sorted(set(exact+[31.,55.,90.,125.,160.,169.,193.]))
 half_step=FPS/BAKE_HZ/2
 mid=[f+half_step for f in exact[:-1] if f+half_step<end]
 frames=sorted(set(exact+mid))
 rows=[];sk=[[] for _ in skin_names];bone=[];actors=[]
 for f in frames:
  deps=set_frame(f);er=rig.evaluated_get(deps)
  rows.append({'frame':f,'time':(f-start)/FPS,'stored_bake_frame':abs((f-start)*BAKE_HZ/FPS-round((f-start)*BAKE_HZ/FPS))<1e-8})
  bone.append([mat(C@er.matrix_world@er.pose.bones[n].matrix) for n in deform])
  actors.append([mat(C@bpy.data.objects[n].evaluated_get(deps).matrix_world) for n in actor_names])
  for i,n in enumerate(skin_names):sk[i].append(positions(bpy.data.objects[n],deps))
 arrays[name+'__bones']=np.asarray(bone);arrays[name+'__actors']=np.asarray(actors)
 for i,n in enumerate(skin_names):arrays[name+'__skin_'+str(i)]=np.asarray(sk[i])
 meta['samples'][name]=rows
 contact=[]
 for f in np.linspace(start,end,int((end-start)*4)+1):
  deps=set_frame(float(f));er=rig.evaluated_get(deps);row={'frame':float(f),'time':float((f-start)/FPS),'nodes':{}}
  for n in ['righthand_prop','hand_l','hand_r','MCH_lowerarm_l','MCH_lowerarm_r']:
   m=er.matrix_world@er.pose.bones[n].matrix
   row['nodes'][n]={'position':list(m.translation),'quaternion_wxyz':list(m.to_quaternion())}
  row['follow']={n:float(rig.pose.bones[n]['weapon_follow']) for n in ['righthand_prop_lefthand','righthand_prop_righthand','lefthand_prop']}
  row['wrist_solve_error_m']={side:((er.matrix_world@er.pose.bones['hand_'+side].matrix).translation-(er.matrix_world@er.pose.bones['righthand_prop_'+('left' if side=='l' else 'right')+'hand'].matrix).translation).length for side in ['l','r']}
  row['guard_error_degrees']={side:math.degrees(er.pose.bones['MCH_hand_guarded_'+side].matrix.to_quaternion().rotation_difference(er.pose.bones['MCH_attach_goal_'+side].matrix.to_quaternion()).angle) for side in ['l','r']}
  assert all(v==1 for v in row['follow'].values())
  contact.append(row)
 meta['contact_samples'][name]=contact
 assert all(fc.driver.is_valid for o in bpy.data.objects if o.animation_data for fc in o.animation_data.drivers)
 print('ORACLE_CLIP',name,len(frames),len(contact),flush=True)

# Capture source rigid local geometry and current fixed material properties.
for n in actor_names:
 o=bpy.data.objects[n];v=np.empty(len(o.data.vertices)*3,dtype=np.float32);o.data.vertices.foreach_get('co',v);arrays[n+'__local_vertices']=v.reshape(-1,3)
meta['material_projection']='Explicit converter --base-color-only: renderer opaque base color projection; source metallic/roughness properties are not reproduced'


np.savez_compressed(OUT/'native_oracle.npz',**arrays)
meta['source_take_count']=config['source_take_count']
meta['supplied_files_unchanged']=hashlib.sha256(source_file.read_bytes()).hexdigest()==source_hash
assert meta['supplied_files_unchanged']
(OUT/'native_oracle.json').write_text(json.dumps(meta,indent=2)+'\n')
print('EVALUATED_PRESERVED_CLIPS',str(OUT),flush=True)
