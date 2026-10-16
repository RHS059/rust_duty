"""Single-region diagnostic WIP retarget. No background camera curve or score."""
import json,math
import numpy as np
from scipy.signal import savgol_filter
from scipy.spatial.transform import Rotation
from pathlib import Path
P=Path(__file__).parent
track=json.loads((P/'reference_weapon_tracks.json').read_text())
g=json.loads((P/'reference_geometry.json').read_text());q=np.array(g['own_points_camera']['optic_guide']);pivot=np.array(g['own_points_camera']['support_guide']);fx=g['fx'];base=np.array([640+fx*q[0]/(-q[2]),360-fx*q[1]/(-q[2])])
rows=[]
for n in range(2241,2310):
 r=track['records'][str(n)]['optic'];M=np.array(r['affine']);scale=np.linalg.norm(M[:2,0]);angle=-math.degrees(math.atan2(M[1,0],M[0,0]));rows.append(r['dxdy']+[scale,angle])
sm=savgol_filter(rows,5,2,axis=0,mode='interp');sm[0]=[0,0,1,0];out=[]
for i,(dx,dy,scale,angle) in enumerate(sm):
 # Region's measured apparent scale is mapped to depth, with only camera-Z roll.
 # This is underdetermined 3D inference from visible foreground, explicitly WIP.
 rz=Rotation.from_euler('Z',angle,degrees=True).as_matrix();rot=(q-pivot)@rz.T+pivot
 z=q[2]/scale;target=base+[dx,dy];desired=np.array([(target[0]-640)*(-z)/fx,(360-target[1])*(-z)/fx,z]);translation=desired-rot
 params=list(translation)+[0,0,float(angle)]
 if i==0:params=[0]*6
 out.append({'source_frame':2241+i,'params':params,'observed_optic_delta_px':[float(dx),float(dy)],'observed_optic_similarity_scale':float(scale),'inferred_roll_degrees':float(angle)})
(P/'reference_retarget.json').write_text(json.dumps({'method':'Native optic-region foreground track, five-frame quadratic smoothing, camera-space displacement plus inferred depth from apparent scale and roll from similarity angle. Does not independently measure receiver/hand deformation; independent visual review required. No endpoint neutralization.','records':out},indent=2)+'\n')
base_design={'baseline_action': 'RD_Locomotion_Normal_Entry_4419_4434_WIP2', 'baseline_frame': 1, 'guarded_initialization': 'RD_00_Supplied_Base_Guarded_Recovered', 'animated_control': 'righthand_prop', 'camera': 'RD First Person Review', 'parameter_order': ['camera_right_m', 'camera_up_m', 'camera_back_m', 'pitch_degrees', 'yaw_degrees', 'roll_degrees']};d={k:base_design[k] for k in ['baseline_action','baseline_frame','guarded_initialization','animated_control','camera','parameter_order']}
d.update({'source_sha256':'a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b','source_action_count':103,'native_parameters':out,'reference':{'youtube_id':'V_QT_cnlBHU','sha256':track['source_sha256'],'anchor_frame':2241,'end_frame':2309,'fps':60,'source_map_commit':'fe5ab7cc6793a9fe2964fd9fc00d10e534e66ed8','half_open_frames':[2241,2310]},'motion_origin':'Observed R3 prone-entry foreground motion; isolated first-person WIP, no body/camera trajectory','actions':{'prone_crawl_enter_r1':{'runtime_id':'UNASSIGNED_AELLA_INTEGRATION_PENDING','frame_range':[1,69],'duration_seconds':68/60,'loop':False,'hold_after_end':True,'source_frame_range_inclusive':[2241,2309],'purpose':'R3 observed prone entry, preserving distinct low-ready endpoint; independent review pending','beats':[{'frame':5,'label':'descent onset ±3 source frames'},{'frame':49,'label':'low camera established ±3 source frames'},{'frame':64,'label':'low ready settled ±3 source frames'}]}}})
(P/'entry_design.json').write_text(json.dumps(d,indent=2)+'\n')
print('params ranges',np.array([r['params'] for r in out]).min(0),np.array([r['params'] for r in out]).max(0))
