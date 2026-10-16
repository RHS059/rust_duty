"""Four small, pixel-reviewed spatial hypotheses; no registration or score fit."""
import json,copy,math,sys,hashlib
from pathlib import Path
import numpy as np
HERE=Path(__file__).parent; OUT=Path(sys.argv[1]);OUT.mkdir(exist_ok=True)
long=json.loads((HERE/'longitudinal-r5-design.json').read_text());lat=json.loads((HERE/'lateral-r5-design.json').read_text());assert long['geometry']==lat['geometry']
g=long['geometry'];pivot=np.array(g['points_camera']['support_wrist']);cuff=np.array(g['points_camera']['support_cuff_surface']);f=640/math.tan(g['angle_x']/2)
def rotate(p):
 x,y,z=p[2:5];return np.array([[1,0,0],[0,math.cos(x),-math.sin(x)],[0,math.sin(x),math.cos(x)]])@np.array([[math.cos(y),0,math.sin(y)],[0,1,0],[-math.sin(y),0,math.cos(y)]])@np.array([[math.cos(z),-math.sin(z),0],[math.sin(z),math.cos(z),0],[0,0,1]])
def point(p):return rotate(p)@(cuff-pivot)+pivot+np.r_[p[:2],p[5]]
def smooth(x):x=np.clip(x,0,1);return x*x*x*(10+x*(-15+6*x))
def pulse(t,start,full,release,end):return smooth((t-start)/(full-start))*(1-smooth((t-release)/(end-release)))
D={k:copy.deepcopy(v) for k,v in long.items() if k!='actions'};D.update(source_sha256='36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d',revision='Colab visual v1 diagnostic from current-r5 pixel review',actions={})
contracts={}
for base,old in {**long['actions'],**lat['actions']}.items():
 name=base.removesuffix('_r5')+'_colab_visual_v1';a=copy.deepcopy(old);P=np.array([r['params'] for r in a['keyframes']]);Q=P.copy();t=np.arange(1,len(P)+1,dtype=float);kind=a['direction'];allowed=['location']
 if base=='hip_strafe_right_r5':
  mean=float(P[:-1,0].mean());Q[:,0]=mean+.875*(P[:,0]-mean)
  contract={'hypothesis':'Reduce excessive lateral hand/receiver sweep against observed R1frames373–397; no exact cross-model ratio target.','operation':'0.875 horizontal camera-translation excursion around fixed baseline mean','fixed_mean_camera_dx_m':mean,'gain':.875,'protected_camera_controls':['Y','depth','pitch','yaw','roll'],'reviewed_window_action_frames':[13,37]}
 elif base=='hip_strafe_left_r5':
  w=pulse(t,24,33,42,49);Q[:,2:5]=P[0,2:5]+(P[:,2:5]-P[0,2:5])*(1-.075*w[:,None]);allowed=['location','rotation_euler']
  # Hold actual native cuff surface projection; not a cross-model correspondence.
  for i in range(len(P)):
   oldc=point(P[i]);newc=point(Q[i]);target=oldc[:2]/(-oldc[2])*(-newc[2]);Q[i,:2]+=target-newc[:2]
  contract={'hypothesis':'Late rail-axis change is visibly stronger/flatter than source barrel-axis change; compare angle change only.','operation':'Reduce late camera-angle excursion7.5% relative to initial pose; quintic envelope24→33/42→49; XY compensation holds native cuff path','gain_at_plateau':.925,'envelope_action_frames':[24,33,42,49],'protected_camera_controls':['depth'],'native_rail_delta_note':'Manual baseline~23deg→6deg versus source~43deg→35deg; ±2–3deg angular uncertainty, different weapon geometry; no absolute-angle alignment.'}
 elif base=='hip_walk_forward_r5':
  dy_px=3.5*pulse(t,26,30,32,35)
  for i in range(len(P)):Q[i,1]-=dy_px[i]*(-point(P[i])[2])/f
  contract={'hypothesis':'Second support-hand dip is weaker/later in r5 than source ordering around Actions30–32.','operation':'3.5pixel maximum native-cuff downward pulse, zero outside26–35, plateau30–32','max_cuff_vertical_edit_px':3.5,'envelope_action_frames':[26,30,32,35],'protected_camera_controls':['X','depth','pitch','yaw','roll'],'protected_action_frames':'1–26 and35–closure unchanged'}
 else:
  assert base=='hip_walk_backward_r5';dy_px=-3*pulse(t,23,26,29,32)+3*pulse(t,30,34,38,42)
  for i in range(len(P)):Q[i,1]-=dy_px[i]*(-point(P[i])[2])/f
  contract={'hypothesis':'Support-hand down motion peaks too early versus later source trough; receiver already swings deeply.','operation':'Spatial redistribution at fixed frames: reduce early dip by≤3px around26–29; retain≤3px more down displacement34–38; no global retiming/amplitude multiplier','max_cuff_vertical_edit_px':3.0,'early_envelope_action_frames':[23,26,29,32],'late_envelope_action_frames':[30,34,38,42],'protected_camera_controls':['X','depth','pitch','yaw','roll']}
 Q[-1]=Q[0];delta=Q-P
 assert float(abs(delta[:,:2]).max())<.005 and float(abs(delta[:,2:5]).max())<math.radians(1) and np.array_equal(Q[:,5],P[:,5])
 for row,v in zip(a['keyframes'],Q):row['params']=v.tolist()
 a['protected_key_ranges']=([[1,26],[35,len(P)]] if base=='hip_walk_forward_r5' else [[1,23],[42,len(P)]] if base=='hip_walk_backward_r5' else [[1,24],[49,len(P)]] if base=='hip_strafe_left_r5' else []);a['allowed_root_channels']=allowed;a['revision_of']=base;a['revision_notes']=contract['operation'];a['trial_contract']=contract
 contract.update(source_action=base,candidate_action=name,unique_frames=len(P)-1,source_window_half_open=a['source_range_half_open'],source_sha256=a['reference_sha256'],max_camera_translation_edit_m=float(abs(delta[:,:2]).max()),max_camera_angle_edit_degrees=float(np.degrees(abs(delta[:,2:5]).max())),camera_locked=True,key_times_unchanged=True,phase_map_unchanged=True,reference_alignment_unchanged=True,status='visual hypothesis; genuine Eevee before-after review required')
 contracts[name]=contract;D['actions'][name]=a
(OUT/'visual-design.json').write_text(json.dumps(D,indent=2)+'\n');(OUT/'visual-hypotheses.json').write_text(json.dumps(contracts,indent=2)+'\n');print(json.dumps(contracts,indent=2))
