"""Retarget measured foreground displacement onto existing weapon visual guides.
No background/camera arc enters the fit. A 2D reference does not uniquely recover
3D motion; constrained camera-space rigid motion is the stated retarget inference.
"""
import json,math,argparse,numpy as np
from pathlib import Path
from scipy.optimize import least_squares
from scipy.signal import savgol_filter
from scipy.spatial.transform import Rotation
parser=argparse.ArgumentParser();parser.add_argument('--measurements',type=Path,required=True);parser.add_argument('--geometry',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();track=json.loads(args.measurements.read_text());g=json.loads(args.geometry.read_text())
labels=['optic','receiver','support_hand']
points=np.array([g['own_points_camera']['optic_guide'],g['own_points_camera']['receiver_guide'],g['own_points_camera']['support_guide']]);pivot=points[2].copy();fx=g['fx'];fy=g['fy']
def project(q):return np.c_[640+fx*q[:,0]/(-q[:,2]),360-fy*q[:,1]/(-q[:,2])]
baseline=project(points)
def transform(par):
 x,y,z,pitch,yaw,roll=par;R=Rotation.from_euler('XYZ',[pitch,yaw,roll],degrees=True).as_matrix()
 return (points-pivot)@R.T+pivot+np.array([x,y,z])/1000
ns=np.arange(4033,4096);delta=np.array([[track['records'][str(n)][label]['dxdy'] for label in labels] for n in ns])
# Remove only the small residual end offset, during final eight source intervals,
# to connect to the unchanged normal-ready pose rather than copy unrelated idle drift.
raw_delta=delta.copy();end_delta=delta[-1].copy()
for i,n in enumerate(ns):
 t=np.clip((n-4087)/8,0,1);w=t*t*t*(t*(t*6-15)+10);delta[i]-=end_delta*w
rows=[];previous=np.zeros(6);scales=np.array([.04,.04,.055,.22,.22,.18])
for i,n in enumerate(ns):
 target=baseline+delta[i]
 def residual(par):
  data=(project(transform(par))-target)*np.array([[1,1],[1,1],[.8,.8]])
  return np.r_[data.ravel(),par*scales,(par-previous)*scales*.15]
 if i==0 or i==len(ns)-1:par=np.zeros(6)
 else:par=least_squares(residual,previous,bounds=([-35,-55,-65,-12,-12,-12],[35,55,65,12,12,12]),xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=250).x
 rows.append(par);previous=par
raw=np.array(rows)
# Native optical tracking can jitter by a pixel. Five-sample quadratic smoothing
# preserves the recorded peaks and full phase durations without retiming.
fit=savgol_filter(raw,5,2,axis=0,mode='interp');fit[0]=0;fit[-1]=0
# The prelaunch and final ready keys are exact, with ease tangents authored later.
records=[]
for i,n in enumerate(ns):
 par=fit[i];params=np.r_[par[:3]/1000,par[3:]]
 records.append({'source_frame':int(n),'source_seconds':float(n/60),'event_relative_seconds':float((n-4034)/60),'params':params.tolist(),'observed_delta_px':raw_delta[i].tolist(),'ready_closed_delta_px':delta[i].tolist(),'predicted_guide_delta_px':(project(transform(par))-baseline).tolist()})
out={'schema':'rust-duty-jump-reference-retarget/v1','reference_sha256':track['source_sha256'],'reference_frame_origin':0,'fps':60,'first_visible_takeoff_frame':4034,'anchor_frame':4033,'impact_frame':4067,'impact_uncertainty_frames':1,'final_frame':4095,'guide_order':labels,'own_guide_points_camera':points.tolist(),'own_guide_pixels':baseline.tolist(),'pivot_camera':pivot.tolist(),'camera_fx_fy':[fx,fy],'parameter_order':['camera_right_m','camera_up_m','camera_back_m','pitch_degrees','yaw_degrees','roll_degrees'],'rotation_order':'Rx @ Ry @ Rz','method':'Constrained camera-space rigid retarget of measured per-region foreground pixel displacement, using the existing rear sight, charging-handle and support-wrist visual guides. Five-frame quadratic smoothing of fitted parameters. No terrain/horizon optical flow enters the held-rig pose.','inference_limits':['Single-view footage does not uniquely recover true 3D weapon translation or rotation','Reference weapon/optic and existing iron-sighted model have different geometry; motion is retargeted, not model-identical','The final eight intervals remove the small remaining end offset to close exactly to existing normal_ready','No quantitative match score or artistic acceptance is claimed'],'final_offset_removed_px':end_delta.tolist(),'records':records}
args.output.write_text(json.dumps(out,indent=2)+'\n')
for n in [4033,4034,4038,4043,4044,4048,4054,4061,4067,4073,4078,4080,4087,4095]:
 i=n-4033;print(n,'params mm/deg',np.round(fit[i],3).tolist(),'guide residual px',np.round(project(transform(fit[i]))-(baseline+delta[i]),2).tolist())
