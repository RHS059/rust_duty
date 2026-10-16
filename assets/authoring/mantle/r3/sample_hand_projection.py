"""Evaluated skinned left-hand projection diagnostics, never rendering or visual approval."""
import bpy,json,sys,math,argparse,hashlib
from pathlib import Path
from bpy_extras.object_utils import world_to_camera_view
P=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
D=json.loads((P/'design.json').read_text());A=bpy.data.objects['Arms'];C=bpy.data.objects['RD First Person Review'];S=next(s for s in bpy.data.scenes if C.name in s.objects);bpy.context.window.scene=S
for o in bpy.data.objects:
 if o.animation_data:
  for t in o.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();A.animation_data.action=bpy.data.actions[D['action']]
selected=[]
for o in bpy.data.objects:
 if o.type!='MESH' or not any(m.type=='ARMATURE' and m.object==A for m in o.modifiers):continue
 groups={g.index for g in o.vertex_groups if g.name=='hand_l' or (g.name.endswith('_l') and any(s in g.name for s in ['thumb','index','middle','ring','pinky']))}
 ids=[v.index for v in o.data.vertices if any(g.group in groups and g.weight>.001 for g in v.groups)]
 if ids:selected.append((o,ids))
count=sum(len(ids) for _,ids in selected);assert count>500,('Missing hand mask',count)
rows=[]
for native in [7284,7291,7292,7293,7296,7299,7303,7307,7310,7315,7320,7323,7326,7328,7331,7332,7347]:
 S.frame_set(native-7284+1);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();points=[]
 for o,ids in selected:
  ev=o.evaluated_get(dg);mesh=ev.to_mesh();assert len(mesh.vertices)==len(o.data.vertices)
  for i in ids:
   q=world_to_camera_view(S,C,ev.matrix_world@mesh.vertices[i].co);points.append((q.x,1-q.y,q.z))
  ev.to_mesh_clear()
 xs=[p[0] for p in points];ys=[p[1] for p in points];zs=[p[2] for p in points];box=[min(xs)*1280,min(ys)*720,max(xs)*1280,max(ys)*720]
 disjoint=box[2]<0 or box[0]>1280 or box[3]<0 or box[1]>720 or max(zs)<=0
 rows.append({'native':native,'blender_frame':native-7283,'selected_vertex_count':len(points),'projected_bbox_pixels':box,'bbox_disjoint_from_viewport':disjoint,'min_depth':min(zs),'claims':'Evaluated mesh projection only; no renderer visibility/occlusion, silhouette or anatomical approval'})
report={'source_sha256':hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),'action':D['action'],'selection':'All original skin vertices with any weight >0.001 on hand_l or left thumb/index/middle/ring/pinky bones, preserving vertex order','selected_vertex_count':count,'samples':rows}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print('HAND_PROJECTION',json.dumps(report))
