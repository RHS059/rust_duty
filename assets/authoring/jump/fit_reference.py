"""Landing-only fit to the remaining measured near-camera receiver dip.
Actual r6 Eevee upper aiming cues already follow the source optic. Preserve their
screen paths while correcting the receiver/body mass, rather than scaling all motion.
"""
import argparse,json,numpy as np
from pathlib import Path
from scipy.optimize import least_squares
from scipy.signal import savgol_filter
from scipy.spatial.transform import Rotation
p=argparse.ArgumentParser();p.add_argument('--baseline-retarget',type=Path,required=True);p.add_argument('--geometry',type=Path,required=True);p.add_argument('--forward-geometry',type=Path,required=True);p.add_argument('--rendered-tracks',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
a=json.loads(args.baseline_retarget.read_text());g=json.loads(args.geometry.read_text());fg=json.loads(args.forward_geometry.read_text());pix=json.loads(args.rendered_tracks.read_text())
points=np.array([g['own_points_camera']['optic_guide'],fg['own_points_camera']['optic_guide'],g['own_points_camera']['receiver_guide']]);pivot=np.array(g['own_points_camera']['support_guide']);fx=g['fx'];allpoints=np.array(a['own_guide_points_camera'])
def proj(q):return np.c_[640+fx*q[:,0]/(-q[:,2]),360-fx*q[:,1]/(-q[:,2])]
def transform(points,par):return (points-pivot)@Rotation.from_euler('XYZ',par[3:],degrees=True).as_matrix().T+pivot+par[:3]
base=proj(points);allbase=proj(allpoints);data=a['records'];cod=np.array([r['ready_closed_delta_px'][1][1] for r in data]);cod=savgol_filter(cod,5,2,mode='interp');cod[0]=cod[-1]=0
# Native image measurements expose the guide-to-visible-feature residual.
residual=np.zeros(len(data))
for i,r in enumerate(data):
 n=r['source_frame']
 if 4067<=n<=4095:residual[i]=cod[i]-pix['records'][str(n)]['receiver']['dxdy'][1]
residual=savgol_filter(residual,5,2,mode='interp');refinement=[]
for i,row in enumerate(data):
 n=row['source_frame'];par=np.array(row['params']);before=proj(transform(points,par));target=before.copy();c=np.zeros(5)
 if 4071<=n<=4094 and cod[i]>0 and residual[i]>0:
  target[2,1]+=residual[i]
  def candidate(c):
   q=par.copy();q[:3]+=c[:3]/1000;q[3:5]+=c[3:];return q
  def fun(c):
   q=proj(transform(points,candidate(c)));return np.r_[(q[:2]-target[:2]).ravel(),q[2,1]-target[2,1]]
  c=least_squares(fun,[0,0,0,0,0],bounds=([-10,-10,-20,-3,-3],[10,10,20,3,3]),xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=500).x
  par=candidate(c)
 after=proj(transform(points,par));row['params']=par.tolist();row['predicted_guide_delta_px']=(proj(transform(allpoints,par))-allbase).tolist()
 refinement.append({'source_frame':n,'correction_dx_dy_dz_mm_pitch_yaw_degrees':c.tolist(),'cod_receiver_closed_delta_y_px':float(cod[i]),'baseline_rendered_receiver_delta_y_px':pix['records'].get(str(n),{}).get('receiver',{}).get('dxdy',[None,None])[1],'target_additional_receiver_dip_px':float(target[2,1]-before[2,1]),'predicted_additional_receiver_dip_px':float(after[2,1]-before[2,1]),'preserved_sight_change_px':(after[:2]-before[:2]).tolist()})
a['method']+=' R7 corrects only the positive landing receiver residual measured in actual r6 Eevee pixels, using bounded coupled depth/heave/pitch/yaw/lateral travel and preserving both upper aiming-cue screen paths. Complete takeoff and air are untouched.'
a['landing_refinement']={'revision':'r7','review_url':'https://github.com/RHS059/dot_chat/pull/1#issuecomment-5974993270','phase_scope':'Landing-only source4071–4094; complete takeoff and air retained','reason':'Actual native Eevee sight cues already match the source upper optic envelope. The near-camera receiver/handle remains approximately7–8px shallower at the trough and3–6px on the shoulders. Correct that visible mass independently using a bounded coupled 3D retarget, not an arbitrary amplitude multiplier.','target_reference_region':'receiver','preserved_model_guides':['rear_sight','front_sight'],'bounds':{'translation_correction_mm':[-10,10],'depth_correction_mm':[-20,20],'pitch_yaw_correction_degrees':[-3,3]},'inference':'Single-view image-fit retarget between differing models; no unique 3D correspondence claim. Actual baseline image residual is applied to the corresponding virtual receiver guide; artistic judgment remains with Elara.','records':refinement}
args.output.write_text(json.dumps(a,indent=2)+'\n')
for n in [4067,4070,4073,4076,4078,4080,4084,4088,4092,4095]:
 r=refinement[n-4033];print(n,np.round(r['correction_dx_dy_dz_mm_pitch_yaw_degrees'],4),'dip',round(r['predicted_additional_receiver_dip_px'],3),'sights',np.round(r['preserved_sight_change_px'],5))
