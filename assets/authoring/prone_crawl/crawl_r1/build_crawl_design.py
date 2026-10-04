"""Prepare four native-duration, non-looping HIP crawl WIP segments.
Manual image-space axis witnesses, not a three-anchor motion score.
"""
from pathlib import Path
import json, numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
P=Path(__file__).parent
# x/y values are selections on an unwarped 400x225 display of 1280x720 pixels.
# Each pair identifies visible leading barrel end and a longitudinal weapon-axis guide.
# The latter is deliberately not claimed as a homologous anatomical/receiver landmark.
F=[(47,166,209,145),(70,144,230,165),(117,122,289,148),(217,98,347,158),(220,136,270,207),(203,158,256,220),(136,184,216,158),(47,172,211,150),(82,151,241,158),(133,122,301,152),(227,105,355,167),(230,145,283,209),(187,172,241,225),(106,193,218,153),(76,188,207,180),(87,154,249,154),(168,121,315,166),(234,140,302,205),(224,152,271,216),(205,162,252,225),(76,170,231,142)]
B=[(181,88,342,149),(97,135,265,141),(77,155,216,155),(98,172,224,135),(186,151,250,217),(225,112,294,174),(234,101,355,173),(141,110,314,151),(86,151,253,151),(64,168,206,164),(118,179,215,141),(199,150,270,212),(226,103,301,168),(234,94,355,155),(155,113,321,140),(80,143,222,147),(55,160,210,143),(130,166,214,135),(189,151,268,215),(222,113,290,177)]
R=[(257,103,309,150),(341,110,385,163),(342,117,398,167),(290,104,371,156),(230,126,311,180),(170,134,246,181),(132,146,194,202),(140,119,207,177),(234,105,287,166),(333,114,380,164),(365,100,400,158),(305,106,383,165),(289,107,379,165)]
L=[(128,115,165,178),(103,135,160,193),(114,139,188,187),(191,136,257,192),(242,140,300,205),(252,151,320,213)]
ranges={'forward':(4932,5173,F),'backward':(5280,5509,B),'right':(5628,5767,R),'left':(5844,5899,L)}
g=json.loads((P/'model_guides.json').read_text());tip=np.array(g['guide_front_camera']);rear=np.array(g['guide_rear_virtual_camera']);points=np.stack([tip,rear]);pivot=np.array(g['pivot_camera']);fx=819.1626469882023

def project(q):return np.c_[640+fx*q[:,0]/(-q[:,2]),360-fx*q[:,1]/(-q[:,2])]
def transformed(par):
 x,y,pitch,yaw=par; rot=Rotation.from_euler('XYZ',[pitch,yaw,0],degrees=True).as_matrix()
 return (points-pivot)@rot.T+pivot+np.array([x,y,0])
records=[];actions={};witness={};fitnotes={}
for name,(a,b,obs) in ranges.items():
 ns=list(range(a,b,12));
 if ns[-1]!=b-1:ns.append(b-1)
 assert len(ns)==len(obs),(name,len(ns),len(obs))
 xy=np.array(obs,dtype=float).reshape(-1,2,2)*3.2;interp=PchipInterpolator(ns,xy,axis=0)
 previous=np.array([0,-.07,5,20.]);res=[];params=[]
 for n in range(a,b):
  target=interp(n)
  def fun(q):
   posed=transformed(q);delta=(project(posed)-target).ravel()
   return np.r_[delta,[(q[0]-previous[0])*3,(q[1]-previous[1])*3,(q[2]-previous[2])*.08,(q[3]-previous[3])*.08],q[:2]*.4]
  best=least_squares(fun,previous,bounds=([-.45,-.4,-65,-70],[.45,.25,65,110]),max_nfev=250,ftol=1e-9,xtol=1e-9,gtol=1e-9).x
  previous=best;par=[float(best[0]),float(best[1]),0,float(best[2]),float(best[3]),0]
  records.append({'source_frame':n,'params':par});params.append(par);res.append(float(np.max(np.linalg.norm(project(transformed(best))-target,axis=1))))
 act=f'prone_crawl_{name}_segment_r1';actions[act]={'runtime_id':'UNASSIGNED_AELLA_INTEGRATION_PENDING','frame_range':[1,b-a],'duration_seconds':(b-a-1)/60,'loop':False,'hold_after_end':True,'source_frame_range_inclusive':[a,b-1],'purpose':f'Observed {name} HIP crawl segment; no cyclic endpoint approved','beats':[{'frame':1,'label':'observed segment start; not a loop seam'},{'frame':b-a,'label':'observed segment end; hold only'}]}
 witness[name]={'source_frames':ns,'guide_selections_source_pixels':xy.tolist(),'half_open_source_range':[a,b],'selection_uncertainty_pixels':16,'guide_meaning':['visible leading barrel end','longitudinal weapon-axis proxy, not a homologous receiver landmark'],'native_source_fps':60,'interpolation':'shape-preserving cubic, evaluated at every original source frame; no retiming','loop_approved':False}
 fitnotes[name]={'max_axis_guide_fit_error_px':max(res),'parameter_min':np.min(params,axis=0).tolist(),'parameter_max':np.max(params,axis=0).tolist(),'note':'Numerical guide residual only, not an animation score or reviewer judgment'}
base={'baseline_action': 'RD_Locomotion_Normal_Entry_4419_4434_WIP2', 'baseline_frame': 1, 'guarded_initialization': 'RD_00_Supplied_Base_Guarded_Recovered', 'animated_control': 'righthand_prop', 'camera': 'RD First Person Review', 'parameter_order': ['camera_right_m', 'camera_up_m', 'camera_back_m', 'pitch_degrees', 'yaw_degrees', 'roll_degrees']};d={k:base[k] for k in ['baseline_action','baseline_frame','guarded_initialization','animated_control','camera','parameter_order']};d.update({'source_sha256':'793546897db5634fca6ba6da7cefd5240e3712932c239bbabea7dfaa0f03419e','source_action_count':104,'native_parameters':records,'reference':{'youtube_id':'5KM0XSKxTWw','sha256':'cff413d8d114b611bbe6f50cc553ef109d61eb8eb1fff960425f506b84d6767e','anchor_frame':4932,'end_frame':5898,'fps':60,'validation_handoff':'https://github.com/RHS059/dot_chat/pull/1#issuecomment-5983841299'},'motion_origin':'Observed fixed-view HIP crawl barrel path; visible 2D axis WIP retarget with inferred 3D rigid pose, no world/camera motion','actions':actions})
(P/'crawl_design.json').write_text(json.dumps(d,indent=2)+'\n');(P/'source_axis_witnesses.json').write_text(json.dumps(witness,indent=2)+'\n');(P/'retarget_diagnostics.json').write_text(json.dumps({'guide_front_camera':tip.tolist(),'guide_rear_virtual_camera':rear.tolist(),'pivot_camera':pivot.tolist(),'fit':fitnotes,'limits':'Virtual longitudinal guides are animation construction aids, not a three-physical-landmark diagnostic or a fidelity pass. Models differ. No hidden anatomy or alternate-camera claims.'},indent=2)+'\n')
print(json.dumps(fitnotes,indent=2))
