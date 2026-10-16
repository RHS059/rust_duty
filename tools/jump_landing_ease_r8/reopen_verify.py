"""Reopen exact saved files; compare structure, curves and evaluated witnesses. No rendering."""
import argparse
import bpy,json,hashlib,struct,sys,math
from pathlib import Path
import numpy as np
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--reports',type=Path,required=True)
parser.add_argument('--candidate',type=Path)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
if not __debug__:
 raise RuntimeError('Reopen validation requires Python assertions; do not use -O')
P=args.reports.resolve()
assert not args.output.exists(), 'Refuse to overwrite existing validation evidence'
REPORT=json.loads((P/'landing_ease_validation.json').read_text())
DENSE=json.loads((P/'dense_evaluation.json').read_text())
SOURCE=args.source.resolve();CANDIDATE=(args.candidate or Path(REPORT['candidate_path'])).resolve()

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def curve_record(fc):
 return {'path':fc.data_path,'index':fc.array_index,'extrapolation':fc.extrapolation,'mute':fc.mute,'points':[{'co':list(k.co),'left':list(k.handle_left),'right':list(k.handle_right),'left_type':k.handle_left_type,'right_type':k.handle_right_type,'interpolation':k.interpolation,'easing':k.easing,'amplitude':k.amplitude,'back':k.back,'period':k.period} for k in fc.keyframe_points]}
def action_record(a):return [curve_record(f) for f in a.fcurves]
def scalar(v):
 if isinstance(v,(str,int,float,bool)):return v
 if hasattr(v,'name'):return {'id':v.name}
 try:return [scalar(x) for x in v]
 except:return str(v)
def props(rna):
 out={}
 for p in rna.bl_rna.properties:
  if p.identifier=='rna_type' or p.type=='COLLECTION' or p.is_readonly:continue
  try:out[p.identifier]=scalar(getattr(rna,p.identifier))
  except:pass
 return out

def structure():
 meshes=[]
 for m in bpy.data.meshes:
  h=hashlib.sha256()
  for v in m.vertices:
   h.update(struct.pack('<3f',*v.co))
   for g in v.groups:h.update(struct.pack('<if',g.group,g.weight))
  for p in m.polygons:
   h.update(struct.pack('<ii',len(p.vertices),p.material_index))
   for i in p.vertices:h.update(struct.pack('<i',i))
  meshes.append((m.name,len(m.vertices),len(m.polygons),h.hexdigest()))
 mats=[]
 for m in bpy.data.materials:
  nodes=[];links=[]
  if m.node_tree:
   for n in m.node_tree.nodes:
    nodes.append({'name':n.name,'type':n.bl_idname,'props':props(n),'inputs':[(s.name,scalar(s.default_value)) for s in n.inputs if hasattr(s,'default_value')]})
   links=[(l.from_node.name,l.from_socket.name,l.to_node.name,l.to_socket.name) for l in m.node_tree.links]
  mats.append({'name':m.name,'props':props(m),'nodes':nodes,'links':links})
 arms=[]
 for a in bpy.data.armatures:
  arms.append({'name':a.name,'bones':[{'name':b.name,'parent':b.parent.name if b.parent else None,'matrix':np.array(b.matrix_local).tolist(),'use_deform':b.use_deform} for b in a.bones]})
 cameras=[{'name':o.name,'matrix':np.array(o.matrix_world).tolist(),'props':props(o.data)} for o in bpy.data.objects if o.type=='CAMERA']
 constraints={o.name:{'object':[props(c) for c in o.constraints], 'bone':{b.name:[props(c) for c in b.constraints] for b in o.pose.bones}} if o.type=='ARMATURE' else {'object':[props(c) for c in o.constraints]} for o in bpy.data.objects}
 return {'meshes':digest(meshes),'materials':digest(mats),'armature_rest':digest(arms),'cameras':digest(cameras),'constraints':digest(constraints)}

def prepare(action):
 arm=bpy.data.objects['Arms'];scene=bpy.context.scene
 for o in bpy.data.objects:
  if o.animation_data:
   for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
 arm.animation_data.use_nla=False
 for a in ['RD_00_Supplied_Base_Guarded_Recovered','RD_Locomotion_Normal_Entry_4419_4434_WIP2',action]:
  arm.animation_data.action=bpy.data.actions[a];scene.frame_set(1);bpy.context.view_layer.update()
 return arm,scene

def pose_matches(action,expected):
 arm,scene=prepare(action);maxerr=0
 for row in expected:
  f=row['frame'];scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
  matrix=np.array(arm.matrix_world@arm.pose.bones['righthand_prop'].matrix)
  maxerr=max(maxerr,float(np.max(np.abs(matrix-np.array(row['root_world'])))))
 return maxerr

def hand_skin(action):
 arm,scene=prepare(action)
 names={b.name for b in arm.pose.bones if b.name in ('hand_l','hand_r') or b.name.startswith(('index_','thumb_','middle_','ring_','pinky_')) and b.name.endswith(('_l','_r'))}
 selected={}
 for ob in bpy.data.objects:
  if ob.type!='MESH' or not ob.name.startswith('Actual arms mesh'):continue
  group_ids={g.index for g in ob.vertex_groups if g.name in names}
  selected[ob.name]=[v.index for v in ob.data.vertices if sum(g.weight for g in v.groups if g.group in group_ids)>.999]
 result={}
 for k in range(49):
  f=4+k/16;scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
  dep=bpy.context.evaluated_depsgraph_get();ri=(arm.matrix_world@arm.pose.bones['righthand_prop'].matrix).inverted()
  result[f]={}
  for name,indices in selected.items():
   ob=bpy.data.objects[name].evaluated_get(dep);mesh=ob.to_mesh();mat=ri@ob.matrix_world
   result[f][name]=np.array([list(mat@mesh.vertices[i].co) for i in indices])
   ob.to_mesh_clear()
 return selected,result

assert sha(SOURCE)==REPORT['source_sha256'];assert sha(CANDIDATE)==REPORT['candidate_sha256']
bpy.ops.wm.open_mainfile(filepath=str(SOURCE),load_ui=False,use_scripts=False)
base_structure=structure();base_hashes={a.name:digest(action_record(a)) for a in bpy.data.actions}
original_match=pose_matches('jump_land_r7',DENSE['baseline'])
selected_before,skin_before=hand_skin('jump_land_r7')
bpy.ops.wm.open_mainfile(filepath=str(CANDIDATE),load_ui=False,use_scripts=False)
candidate_structure=structure()
assert base_structure==candidate_structure,(base_structure,candidate_structure)
assert all(digest(action_record(bpy.data.actions[n]))==v for n,v in base_hashes.items())
assert digest(action_record(bpy.data.actions[REPORT['candidate_action']]))==digest(json.loads((P/'candidate_action_curves.json').read_text()))
saved_baseline_match=pose_matches('jump_land_r7',DENSE['baseline'])
saved_candidate_match=pose_matches(REPORT['candidate_action'],DENSE['candidate'])
assert max(original_match,saved_baseline_match,saved_candidate_match)==0
selected_after,skin_after=hand_skin(REPORT['candidate_action']);assert selected_before==selected_after
skin_max={name:0.0 for name in selected_before}
for f,objects in skin_before.items():
 for name,vs in objects.items():
  if len(vs):skin_max[name]=max(skin_max[name],float(np.max(np.linalg.norm(vs-skin_after[f][name],axis=1))))
assert max(skin_max.values())<.00001,skin_max
out={'status':'saved candidate reopened and numeric witnesses verified; visual review still pending','candidate_sha256':sha(CANDIDATE),'source_sha256':sha(SOURCE),'static_structure_digests_equal':base_structure,'original_action_count_preserved':len(base_hashes),'all_original_action_curve_hashes_equal':True,'candidate_curves_equal_presave':True,'original_source_evaluated_root_matches_prior_samples':original_match,'saved_baseline_evaluated_root_max_delta':saved_baseline_match,'saved_candidate_evaluated_root_max_delta':saved_candidate_match,'sample_count_each':len(DENSE['candidate']),'hand_skin_check':{'selection':'Vertices of actual arms meshes with >0.999 total weight to hand or finger deform bones. This verifies preservation of the baseline contact region, not absolute intersection-free contact or anatomy.','vertex_counts':{n:len(v) for n,v in selected_before.items()},'samples':49,'frame_range':[4,7],'sample_rate_hz':960,'max_weapon_relative_displacement_m':skin_max},'files_unchanged_during_reopen':sha(SOURCE)==REPORT['source_sha256'] and sha(CANDIDATE)==REPORT['candidate_sha256'],'no_render':True,'no_source_save':True}
args.output.parent.mkdir(parents=True,exist_ok=True)
with args.output.open('x') as receipt:
 receipt.write(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
