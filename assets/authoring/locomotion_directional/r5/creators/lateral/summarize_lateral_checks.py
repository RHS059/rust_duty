"""Read-only native constraint/timestamp check summary. No visual score."""
import csv,hashlib,json
from pathlib import Path
import numpy as np
B=Path(__file__).resolve().parent;D=json.loads((B/'directional_keyposes_r5_lateral.json').read_text());S=json.loads((B/'validation/native_validation.json').read_text());rows=list(csv.DictReader((B/'validation/candidate_tracks_480fps.csv').open()));result={'source_sha256':hashlib.sha256((B/'halcyon_hip_lateral_r5.blend').read_bytes()).hexdigest(),'sample_rate_hz':480,'status':'Native numerical authoring checks only; independent visual review pending','point_order':['muzzle_tip','receiver_center','support_cuff_surface'],'actions':{}}
for label in ['left','right']:
 name='hip_strafe_'+label+'_r5';sel={v:[r for r in rows if r['action']=='hip_strafe_'+label+'_'+v] for v in ['r4','r5']};A={v:np.array([[[float(r[n+'_'+axis]) for axis in ['x','y']] for n in result['point_order']] for r in rr]) for v,rr in sel.items()};delta=A['r5']-A['r4'];ks=A['r5'][:-1:8];native_key_error=float(abs(ks-np.array(D['actions'][name]['ideal_rigid_screen'])).max());xmax=abs(delta[:,:,0]).max(0).tolist();ymax=abs(delta[:,:,1]).max(0).tolist()
 detail={'samples_per_revision':len(sel['r4']),'max_x_delta_pixels':xmax,'max_y_delta_pixels':ymax,'max_native_key_design_delta_pixels':native_key_error,'r4_native_key_min_offsets':np.argmin(A['r4'][:-1:8],0).tolist(),'r4_native_key_max_offsets':np.argmax(A['r4'][:-1:8],0).tolist(),'r5_native_key_min_offsets':np.argmin(ks,0).tolist(),'r5_native_key_max_offsets':np.argmax(ks,0).tolist(),'r4_native_range_xy_pixels':np.ptp(A['r4'],0).tolist(),'r5_native_range_xy_pixels':np.ptp(A['r5'],0).tolist(),'contact_and_loop':S['actions'][name]}
 assert native_key_error<.01
 if label=='left':
  detail['max_cuff_xy_constraint_error_pixels']=float(abs(delta[:,2]).max());assert detail['max_cuff_xy_constraint_error_pixels']<.01
  # Rightward first-phase travel stays unchanged outside the onset neighborhood.
  detail['max_first_0_4s_muzzle_xy_delta_pixels']=float(abs(delta[:193,0]).max());assert detail['max_first_0_4s_muzzle_xy_delta_pixels']<.01
  assert np.array_equal(np.argmin(ks,0)[[0,2],0],np.argmin(A['r4'][:-1:8],0)[[0,2],0]);assert np.array_equal(np.argmax(ks,0)[[0,2],0],np.argmax(A['r4'][:-1:8],0)[[0,2],0])
 else:
  assert max(xmax)<.01
  detail['cuff_y_delta_at_requested_offsets_pixels']={str(k):float(delta[k*8,2,1]) for k in [17,18,19,37,42]}
  amp=D['actions'][name]['revision_parameters']['additional_cuff_downward_pixels_plateau'];assert all(abs(v-amp)<.01 for v in detail['cuff_y_delta_at_requested_offsets_pixels'].values())
  assert np.array_equal(np.argmin(ks,0)[:,0],np.argmin(A['r4'][:-1:8],0)[:,0]);assert np.array_equal(np.argmax(ks,0)[:,0],np.argmax(A['r4'][:-1:8],0)[:,0])
 c=detail['contact_and_loop'];assert max(c['max_wrist_error_m'])<1e-6;assert max(c['max_guard_error_degrees'])==0;assert not c['invalid_drivers'];assert all(c[k]==0 for k in ['loop_endpoint_root_matrix_error','loop_endpoint_actor_matrix_error','loop_endpoint_hand_matrix_error'])
 result['actions'][name]=detail
(B/'dense_constraint_comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
# Verify the comparison media actually seen by the reviewer, with no inferred offset or phase shift.
R=Path('/workspace/shared/hip-feedback-r4-20261003/render/publication');maps={}
for label,start,ref in [('left',886,'5KM0XSKxTWw'),('right',361,'9RRgXvRx43s')]:
 p=R/f'hip_strafe_{label}_r4_frame_map.csv';rr=list(csv.DictReader(p.open()));assert len(rr)==98
 for i,r in enumerate(rr):
  assert int(r['output_frame'])==i and int(r['reference_raw_frame'])==start+i%49 and int(r['blender_frame'])==1+i%49 and r['reference_id']==ref and abs(float(r['source_time_s'])-(i%49)/60)<1e-8
 offsets=[30,42] if label=='left' else [17,18,37,42]
 maps[label]={'map_path':str(p),'map_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'all98_entries_verified':True,'period_frames':49,'fps':60,'reference_core_half_open':[start,start+49],'repeated_endpoint_blender_frame':50,'witnesses':[{'output_time_s':k/60,'blender_frame':k+1,'reference_raw_frame':start+k,'reference_time_s':(start+k)/60} for k in offsets]}
(B/'timestamp_verification.json').write_text(json.dumps({'source':'r4 maps tied to reviewed videos','phase_changed':False,'actions':maps},indent=2)+'\n')
