import bpy,json,sys,hashlib,argparse
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
sys.path.insert(0,str(P));from source_integrity import action_fingerprint
ap=argparse.ArgumentParser();ap.add_argument('--old',type=Path,required=True);ap.add_argument('--new',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);old=args.old;new=args.new
names={'prone_crawl_forward_segment_r1':241,'prone_crawl_backward_segment_r1':229,'prone_crawl_right_segment_r1':139,'prone_crawl_left_segment_r1':55}
def collect(path):
 bpy.ops.wm.open_mainfile(filepath=str(path));r=bpy.data.objects['Arms'];s=bpy.context.scene
 actions={a.name:action_fingerprint(a) for a in bpy.data.actions}
 protected={}
 for name in names:
  protected[name]=[(c.data_path,c.array_index,[(list(k.co),list(k.handle_left),list(k.handle_right),k.interpolation) for k in c.keyframe_points]) for c in bpy.data.actions[name].fcurves if c.data_path!='pose.bones["clavicle_r"].location']
 for o in bpy.data.objects:
  if o.animation_data:
   for t in o.animation_data.nla_tracks:t.mute=True;t.is_solo=False
 r.animation_data.use_nla=False;r.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];s.frame_set(1);bpy.context.view_layer.update();basis={p.name:p.matrix_basis.copy() for p in r.pose.bones};matrices={}
 for name,end in names.items():
  r.animation_data.action=None
  for p in r.pose.bones:p.matrix_basis=basis[p.name].copy()
  r.animation_data.action=bpy.data.actions[name];rows=[]
  for frame in range(1,end+1):
   s.frame_set(frame);bpy.context.view_layer.update();rows.append(np.array([p.matrix[:] for p in r.pose.bones],dtype=np.float64))
  matrices[name]=np.stack(rows)
 return actions,protected,matrices
A,AC,AM=collect(old);B,BC,BM=collect(new)
prior_unchanged=all(A[n]==B[n] for n in A if n not in names);protected=AC==BC
diffs={n:float(np.max(np.abs(AM[n]-BM[n]))) for n in names}
report={'old_source_sha256':hashlib.sha256(old.read_bytes()).hexdigest(),'new_source_sha256':hashlib.sha256(new.read_bytes()).hexdigest(),'action_count':len(B),'all_104_older_actions_unchanged':prior_unchanged,'all_non_shoulder_curves_identical':protected,'native_all_bone_matrix_max_absolute_difference':diffs,'native_tolerance':1e-6,'source_saved':False,'render_performed':False,'passed':prior_unchanged and protected and all(x<=1e-6 for x in diffs.values())}
args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));assert report['passed']
