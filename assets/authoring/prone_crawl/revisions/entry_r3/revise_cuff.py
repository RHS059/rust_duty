import bpy,sys,json,math,hashlib
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parent))
from source_integrity import snapshot
from validate_source_structure import extra_snapshot
P=Path(__file__).parent;source=Path(bpy.data.filepath);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();assert sha(source)=='fd5b55b21acdcd73ff39cafd258c6d7281f8dc51359e65cadc76f769909f74e4'
before=snapshot(bpy);struct=extra_snapshot();old=bpy.data.actions['prone_crawl_enter_r2'];new=old.copy();new.name='prone_crawl_enter_r3';new.use_fake_user=True
fc=next(c for c in new.fcurves if c.data_path=='pose.bones["righthand_prop"].location' and c.array_index==2)
k0=next(k for k in fc.keyframe_points if k.co.x==36);k1=next(k for k in fc.keyframe_points if k.co.x==38)
y0=float(k0.co.y);y1=float(k1.co.y);d0=float((k0.handle_right.y-k0.co.y)/(k0.handle_right.x-k0.co.x));d1=float((k1.co.y-k1.handle_left.y)/(k1.co.x-k1.handle_left.x));mid=(y0+y1)/2;sec=(y1-y0)/2
# Quintic pieces preserve boundary pose and derivative, meet at monotonic native
# midpoint, and have matching first/second derivatives there. No timing change.
def coeff(a,b,da,db):
 c=np.array([a,da,0.,0.,0.,0.]);c[3:]=np.linalg.solve([[1,1,1],[3,4,5],[6,12,20]],[b-a-da,db-da,0]);return c
cs=[coeff(y0,mid,d0,sec),coeff(mid,y1,sec,d1)]
def value(f):
 j=0 if f<=37 else 1;t=f-36-j;c=cs[j];return sum(c[k]*t**k for k in range(6)),sum(k*c[k]*t**(k-1) for k in range(1,6))
for i in range(len(fc.keyframe_points)-1,-1,-1):
 if 36<fc.keyframe_points[i].co.x<38:fc.keyframe_points.remove(fc.keyframe_points[i],fast=True)
fc.update();samples=[]
for i in range(17):
 f=36+i/8;v,d=value(f);k=next((k for k in fc.keyframe_points if k.co.x==f),None)
 if k is None:k=fc.keyframe_points.insert(f,v,options={'FAST'})
 k.interpolation='BEZIER';k.handle_left_type='FREE';k.handle_right_type='FREE'
 if f>36:k.handle_left=(f-1/24,v-d/24)
 if f<38:k.handle_right=(f+1/24,v+d/24)
 samples.append({'frame':f,'before':next(c for c in old.fcurves if c.data_path==fc.data_path and c.array_index==2).evaluate(f),'after':v,'derivative':d})
fc.update();new['acceptance_status']='WIP r3; cuff depth spike correction; review pending'
after=snapshot(bpy);extras=extra_snapshot();checks={k:after[k]==before[k] for k in before if k!='actions'};checks['all_109_prior_actions']=all(after['actions'][n]==v for n,v in before['actions'].items())
for k,v in struct.items():checks[k]=all(extras[k].get(n)==x for n,x in v.items()) if k in ('actions_metadata','actions_extended') else extras[k]==v
assert all(checks.values()),checks
out=P/'halcyon_prone_crawl_r3.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out),compress=True)
(P/'revision_report.json').write_text(json.dumps({'source_sha256':sha(source),'candidate_sha256':sha(out),'checks':checks,'changed_action':new.name,'changed_curve':fc.data_path,'axis':2,'bounded_frames':[36,38],'before_frame37':samples[8]['before'],'after_frame37':samples[8]['after'],'samples':samples,'reason':'Confirmed unobserved inferred-depth excursion caused support-arm IK/cuff surge. Only root-depth curve changes within f36–38; boundary poses and derivatives retained. R2 late-stock correction retained.'},indent=2));print(sha(out))
