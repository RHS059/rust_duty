"""Bounded landing-only retarget of the visible forward aiming feature.
The COD optic is the upper-weapon visual cue. The model has separate rear and
forward iron sights: preserve the already-close rear guide while matching the
forward sight's dip/recovery envelope. No camera/world-root translation is authored.
"""
import json,argparse,numpy as np
from pathlib import Path
from scipy.optimize import least_squares
from scipy.signal import savgol_filter
from scipy.spatial.transform import Rotation
p=argparse.ArgumentParser();p.add_argument('--baseline-retarget',type=Path,required=True);p.add_argument('--geometry',type=Path,required=True);p.add_argument('--forward-geometry',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
a=json.loads(args.baseline_retarget.read_text());g=json.loads(args.geometry.read_text());fg=json.loads(args.forward_geometry.read_text());rear=np.array(g['own_points_camera']['optic_guide']);front=np.array(fg['own_points_camera']['optic_guide']);pivot=np.array(g['own_points_camera']['support_guide']);fx=g['fx'];points=np.array([rear,front]);allpoints=np.array(a['own_guide_points_camera'])
def proj(q):return np.c_[640+fx*q[:,0]/(-q[:,2]),360-fx*q[:,1]/(-q[:,2])]
def transform(points,par):return (points-pivot)@Rotation.from_euler('XYZ',par[3:],degrees=True).as_matrix().T+pivot+par[:3]
basepixels=proj(points);allbase=proj(allpoints);data=a['records'];source_y=np.array([r['ready_closed_delta_px'][0][1] for r in data]);source_y=savgol_filter(source_y,5,2,mode='interp');source_y[0]=0;source_y[-1]=0
refinement=[]
for i,row in enumerate(data):
 n=row['source_frame'];par=np.array(row['params']);before=proj(transform(points,par));target=before.copy();correction=np.zeros(3)
 if 4070<=n<=4094 and source_y[i]>0:
  # Positive landing dip only. Target bounded by the observed COD upper-weapon
  # feature excursion; do not magnify the accepted airborne rise or takeoff.
  target[1,1]=max(before[1,1],basepixels[1,1]+source_y[i])
  def candidate(c):
   q=par.copy();q[0]+=c[0]/1000;q[1]+=c[1]/1000;q[3]+=c[2];return q
  def residual(c):
   q=proj(transform(points,candidate(c)))
   return np.array([q[0,0]-target[0,0],q[0,1]-target[0,1],q[1,1]-target[1,1]])
  correction=least_squares(residual,[0,-.001,-.001],bounds=([-4,-16,-4.5],[4,0,0]),xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=300).x
  par=candidate(correction)
 after=proj(transform(points,par));row['params']=par.tolist();row['predicted_guide_delta_px']=(proj(transform(allpoints,par))-allbase).tolist()
 refinement.append({'source_frame':n,'correction_mm_mm_degrees':correction.tolist(),'cod_upper_weapon_delta_y_px':float(source_y[i]),'model_forward_delta_y_before_px':float(before[1,1]-basepixels[1,1]),'model_forward_delta_y_after_px':float(after[1,1]-basepixels[1,1]),'rear_guide_change_px':(after[0]-before[0]).tolist()})
a['method']+=' R6 applies a bounded landing-only heave/pitch/lateral correction: the forward iron-sight dip/recovery follows the measured COD upper-weapon optic envelope while the already-close rear guide stays fixed in screen space. Takeoff and air parameters are untouched.'
a['landing_refinement']={'revision':'r6','review_url':'https://github.com/RHS059/dot_chat/pull/1#issuecomment-5974687035','phase_scope':'Landing only; source4070–4094; complete takeoff/air retained','reason':'Visible forward-aiming feature requires the reference upper-weapon envelope rather than the lower forward-rail envelope; geometry correspondence is an explicit retarget choice, not model identity','target_reference_region':'optic','model_forward_guide':front.tolist(),'model_forward_guide_ready_pixel':[744,355],'model_rear_guide':rear.tolist(),'bounds':{'lateral_correction_mm':[-4,4],'vertical_correction_mm':[-16,0],'pitch_correction_degrees':[-4.5,0]},'no_multiplication_of_motion_amplitude':True,'records':refinement}
args.output.write_text(json.dumps(a,indent=2)+'\n')
for n in [4067,4070,4073,4076,4078,4080,4084,4088,4092,4095]:
 r=refinement[n-4033];print(n, 'correction',np.round(r['correction_mm_mm_degrees'],4),'front before/after/reference',*[round(r[k],2) for k in ['model_forward_delta_y_before_px','model_forward_delta_y_after_px','cod_upper_weapon_delta_y_px']],'rear movement',np.round(r['rear_guide_change_px'],5))
