"""r5 lateral-only response: bounded orientation refinement and measured cuff dip gap.
Does not estimate a visual score or solve reference 3D motion from screen landmarks.
"""
import argparse,copy,hashlib,json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from scipy.signal import savgol_filter
from scipy.optimize import brentq
P=argparse.ArgumentParser();P.add_argument('--baseline-dir',type=Path,default=Path('/workspace/shared/hip-feedback-r4-20261003/lateral'));P.add_argument('--output-dir',type=Path,default=Path(__file__).resolve().parent);args=P.parse_args();B=args.baseline_dir;O=args.output_dir;O.mkdir(parents=True,exist_ok=True)
old=json.loads((B/'directional_keyposes_r4_lateral.json').read_text());g=old['geometry'];pivot=np.array(g['points_camera']['support_wrist']);f=640/np.tan(g['angle_x']/2);points=np.array([g['points_camera'][n] for n in ['muzzle_tip','receiver_center','support_cuff_surface']])
def camera(p):return (points-pivot)@Rotation.from_euler('XYZ',p[2:5]).as_matrix().T+pivot+np.r_[p[:2],p[5]]
def project(p):
 q=camera(p);return q[:,:2]/-q[:,2,None]*[f,-f]+[640,360]
def smootherstep(t):
 t=np.clip(t,0,1);return t*t*t*(10+t*(-15+6*t))
def plateau(t,a,b,c,d):return smootherstep((t-a)/(b-a))*(1-smootherstep((t-c)/(d-c)))
def angles(q):
 v=q[:,1]-q[:,0];return np.degrees(np.unwrap(np.arctan2(v[:,1],v[:,0])))
meta={k:copy.deepcopy(v) for k,v in old.items() if k not in ['actions','revision','source_sha256','phase_policy','review_sources']}
meta.update({'revision':'r5 lateral-only creator candidate','source_sha256':'d220162819fb7267aa6b93b209afc8ce5212a0692e6a4e02c5c43602b08907e3','review_sources':['https://github.com/RHS059/dot_chat/pull/1#issuecomment-5972182972'],'phase_policy':'All r4 key times, 49-frame periods, reference cores and presentation mapping retained. No editing of existing Actions.','actions':{}})
changes={};gaps={'review_url':meta['review_sources'][0],'status':'Relative silhouette guide, not a shared-camera 3D solve or visual score','actions':{}}
for direction in ['left','right']:
 oname='hip_strafe_'+direction+'_r4';name='hip_strafe_'+direction+'_r5';a=old['actions'][oname];N=a['period_frames'];assert N==49;p0=np.array([k['params'] for k in a['keyframes'][:-1]]);q0=np.array([project(p) for p in p0]);ps=p0.copy();t=np.arange(N);raw=np.array(a['raw_reference_pixels']);smooth=savgol_filter(raw,5,2,axis=0,mode='wrap');ref_range=np.ptp(smooth,axis=0)*a['fixed_motion_scale_native_over_reference'];gap={'smoothed_reference_range_xy_pixels':np.ptp(smooth,axis=0).tolist(),'inherited_fixed_native_over_reference_scale':a['fixed_motion_scale_native_over_reference'],'scaled_reference_range_xy_pixels':ref_range.tolist(),'r4_native_key_range_xy_pixels':np.ptp(q0,axis=0).tolist()}
 if direction=='left':
  w=plateau(t,26,33,42,48);ps[:,3]+=np.deg2rad(.75)*w;ps[:,4]+=np.deg2rad(2)*w
  for i in range(N):
   q=camera(ps[i]);ps[i,0]+=((q0[i,2,0]-640)/f*(-q[2,2]))-q[2,0];ps[i,1]+=(-(q0[i,2,1]-360)/f*(-q[2,2]))-q[2,1]
  params={'additional_camera_yaw_degrees_at_plateau':.75,'additional_camera_roll_degrees_at_plateau':2.0,'cumulative_yaw_roll_addition_over_r3_degrees':[2.0,4.0],'envelope_key_offsets':[26,33,42,48],'preserve':['visible cuff screen XY','pitch','depth','key times','first-phase restored rightward travel'],'method':'same quintic envelope; camera XY compensates fixed cuff path'}
  notes=['Increase inward yaw by0.75 degree and inward roll by2 degrees beyond r4 at native-key plateau, bringing additions over r3 to2 degrees yaw and4 degrees roll.','Keep the existing upswing envelope26–33/33–42/42–48 and all reference/key timing. Hold visible cuff XY, pitch and depth.','Screen-angle analysis is deliberately not an angle-gap fit: from0.40s to0.60s, r4 muzzle/receiver angle already changes more than the different reference weapon. The bounded authored orientation increment follows the reviewer direction; no recovered3D deficit is claimed.']
  ar,an=angles(raw),angles(q0);gap.update({'reference_barrel_angle_degrees_at_offsets':{str(k):float(ar[k]) for k in [24,30,34,36,38,42]},'r4_barrel_angle_degrees_at_offsets':{str(k):float(an[k]) for k in [24,30,34,36,38,42]},'reference_barrel_angle_delta_0_4_to_0_6_degrees':float(ar[36]-ar[24]),'r4_barrel_angle_delta_0_4_to_0_6_degrees':float(an[36]-an[24]),'positive_projected_angle_deficit_identified':False,'interpretation':'The projected barrel proxy is already more angular during this interval; there is no calibrated positive screen-angle deficit. Reference3D yaw/roll cannot be identified from these different weapons/cameras. Additional yaw/roll is a bounded reviewer-directed visual candidate.'})
 else:
  w=plateau(t,7,17,19,28)+plateau(t,29,37,42,49)
  target=float(ref_range[2,1]);amp=float(brentq(lambda x:np.ptp(q0[:,2,1]+x*w)-target,0,30))
  for i in range(N):
   q=camera(ps[i]);ps[i,1]-=amp*w[i]*(-q[2,2])/f
  params={'additional_cuff_downward_pixels_plateau':amp,'cumulative_cuff_downward_addition_over_r3_pixels':14+amp,'first_envelope_offsets':[7,17,19,28],'second_envelope_offsets':[29,37,42,49],'target_native_key_cuff_vertical_range_pixels':target,'preserve':['all lateral screen paths','camera pitch/yaw/roll','depth','key times'],'modified':['camera Y translation only'],'amplitude_basis':'Close the inherited scaled smoothed reference cuff-range shortfall using the existing two-pulse envelope; it is an optical guide, not calibrated equivalence.'}
  notes=['Deepen both existing dips by the measured relative cuff-range shortfall, retaining the identical r4 pulse windows and side-peak coverage.','Only camera-Y translation changes. Lateral paths, camera rotations and depth remain r4.','Choose additional plateau amplitude by solving the existing pulse shape to the smoothed reference cuff vertical range under the inherited fixed scale. Muzzle/receiver ranges already differ from reference and are reported, not fitted away.']
  gap.update({'r4_cuff_vertical_shortfall_pixels':target-float(np.ptp(q0[:,2,1])),'additional_pulse_amplitude_pixels':amp,'interpretation':'Cuff range has a relative shortfall. Muzzle/receiver ranges are already larger than the inherited scaled reference guide, so the cuff target is not a claim of uniform agreement or calibrated depth.'})
 qs=np.array([project(p) for p in ps]);entry=copy.deepcopy(a);entry.update({'revision_of':oname,'revision_notes':'; '.join(notes),'revision_parameters':params,'prior_design_sha256':hashlib.sha256((B/'directional_keyposes_r4_lateral.json').read_bytes()).hexdigest(),'prior_params_bounds_min':p0.min(0).tolist(),'prior_params_bounds_max':p0.max(0).tolist(),'params_bounds_min':ps.min(0).tolist(),'params_bounds_max':ps.max(0).tolist(),'ideal_rigid_screen':qs.tolist(),'keyframes':[{'frame':i+1,'source_frame':a['source_range_half_open'][0]+i,'params':p.tolist()} for i,p in enumerate(ps)]+[{'frame':N+1,'source_frame':a['source_range_half_open'][1],'params':ps[0].tolist()}],'overlay_weight':w.tolist()});meta['actions'][name]=entry;gaps['actions'][name]=gap
 changes[name]={'notes':notes,'parameters':params,'r4_range_xy_pixels':np.ptp(q0,0).tolist(),'r5_range_xy_pixels':np.ptp(qs,0).tolist(),'r4_screen_min_offsets':np.argmin(q0,0).tolist(),'r4_screen_max_offsets':np.argmax(q0,0).tolist(),'r5_screen_min_offsets':np.argmin(qs,0).tolist(),'r5_screen_max_offsets':np.argmax(qs,0).tolist(),'max_y_trace_change_by_anchor_pixels':np.max(abs(qs[:,:,1]-q0[:,:,1]),0).tolist(),'max_x_trace_change_by_anchor_pixels':np.max(abs(qs[:,:,0]-q0[:,:,0]),0).tolist(),'max_camera_param_delta':np.max(abs(ps-p0),0).tolist()}
 print(name,json.dumps(changes[name],indent=2))
(O/'directional_keyposes_r5_lateral.json').write_text(json.dumps(meta,indent=2)+'\n');(O/'motion_changes_r5_lateral.json').write_text(json.dumps({'status':'Unscored WIP. Numeric constraints only; independent visual review pending.','point_order':['muzzle_tip','receiver_center','support_cuff_surface'],'actions':changes},indent=2)+'\n');(O/'reference_gap_analysis.json').write_text(json.dumps(gaps,indent=2)+'\n')
