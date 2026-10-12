"""Numeric two-input policy oracle from native r5; no rendering."""
import bpy,json,math,hashlib
from pathlib import Path
from mathutils import Matrix,Vector,Quaternion
P=Path(__file__).resolve().parent
probe=P/'probe_v9_articulation.py'
exec(compile(probe.read_text().split('connected=[]',1)[0],str(probe),'exec'),globals())
R=Matrix.Diagonal((-1.,1.,-1.,1.))
def rows(m):return [list(r) for r in m]
def target_from_delta(d):
 m=Quaternion().slerp(d.to_quaternion(),.4).to_matrix().to_4x4();m.translation=d.translation*.4
 return m@p0
cases=[]
for j in [0,3,7,8,12,18,24,28,31,32,39,40,41.5,41.75,42,47,55,58,64,72,78,79,95,103,113,125]:
 primary=1+((j+5.75)*.8)%38;secondary=1+((j+5.75)*.8+19)%38
 select('hip_walk_forward_r5',primary);d0=(C.inverted()@W.matrix_world)@ready.inverted()
 select('hip_walk_forward_r5',secondary);d1=(C.inverted()@W.matrix_world)@ready.inverted()
 a=target_from_delta(d0);b=target_from_delta(d1)
 u=u0+(a.x/-a.z-u0)*.25;v=b.y/-b.z
 angle=math.atan2(v,u)-math.atan2(p0.y,p0.x);angle=math.atan2(math.sin(angle),math.cos(angle))
 depth=-math.hypot(p0.x,p0.y)/math.hypot(u,v)-p0.z
 offset=Matrix.Rotation(angle,4,'Z');offset.translation=Vector((0,0,depth))
 cases.append({'output_frame':j,'primary_native_frame':primary,'secondary_native_frame':secondary,'primary_delta_camera':rows(d0),'secondary_delta_camera':rows(d1),'primary_delta_asset':rows(R@d0@R),'secondary_delta_asset':rows(R@d1@R),'expected_offset_camera':rows(offset),'expected_offset_asset':rows(R@offset@R)})
camera_matrix=C.copy();held_weapon=baseW.copy()
scene_path=P/'ads_v9_depthphase_public47_hipr5_diagnostic.blend';sha=hashlib.sha256(scene_path.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(scene_path))
s=bpy.data.scenes['ADS V9 Depth Phase Diagnostic']
if bpy.context.window:bpy.context.window.scene=s
weapon=bpy.data.objects['DIAG_V9_hk416_weapon'];maximum=0.
for case in cases:
 f=case['output_frame']+1;s.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
 actual=camera_matrix.inverted()@weapon.matrix_world@held_weapon.inverted()@camera_matrix
 err=max(abs(a-b) for ra,rb in zip(actual,Matrix(case['expected_offset_camera'])) for a,b in zip(ra,rb))
 case['saved_actor_offset_max_component_residue']=err;maximum=max(maximum,err)
out={'candidate_id':'ads-v9-depthphase-forward-public47-r5','status':'native-input numeric policy oracle; no source-match or runtime approval','source_blend_sha256':sha,'r5_source_sha256':'36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d','receiver_point_camera':list(p0),'camera_to_asset_basis':rows(R),'convention':'row-major4x4 arrays; column-vector multiplication; metres; camera right/up/back. Asset change of basis R=diag(-1,1,-1,1), same contract as prior v4/v6 oracle; integrator must retain its verified binding.','mapping':'TRS attenuate each camera delta at0.4. Primary supplies projected X displacement scaled0.25 around held u0. Secondary supplies projected Y. Solve roll/depth about optical axis as prior mapping.','phase':'One primary accumulated phase; second native lookup is +half period, not a second advancing clock. Forward only tested.','known_bake_caveat':'LocalLRS skin bake still fails1e-5 deform tolerance at4.108e-5; this actor-policy oracle does not erase that failure.','saved_actor_max_component_residue':maximum,'cases':cases}
(P/'v9_native_runtime_oracle.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'cases':len(cases),'saved_actor_max_component_residue':maximum}),flush=True)
assert maximum<1e-5
