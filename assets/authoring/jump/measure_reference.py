import argparse,hashlib
import cv2,numpy as np,json
from pathlib import Path
from PIL import Image,ImageDraw
cv2.setNumThreads(1)
parser=argparse.ArgumentParser();parser.add_argument('--reference',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args();p=args.output_dir;p.mkdir(parents=True,exist_ok=True);source=str(args.reference);assert hashlib.sha256(args.reference.read_bytes()).hexdigest()=='491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46'
start,end,anchor=4033,4105,4033
c=cv2.VideoCapture(source);c.set(cv2.CAP_PROP_POS_FRAMES,start)
frames=[]
for n in range(start,end+1):
 ok,im=c.read();assert ok;frames.append(im)
grays=[cv2.cvtColor(im,cv2.COLOR_BGR2GRAY) for im in frames]
regions={
 'optic':{'polygon':[[747,350],[770,326],[830,315],[884,322],[916,346],[916,396],[885,423],[831,426],[777,408],[748,402]],'anchor':[856,372]},
 'receiver':{'polygon':[[793,552],[976,549],[1003,566],[1002,595],[793,606]],'anchor':[904,578]},
 'support_hand':{'polygon':[[657,470],[682,435],[710,458],[748,509],[744,546],[704,566],[672,536]],'anchor':[694,512]}
}
records={n:{} for n in range(start,end+1)};features={}
for label,reg in regions.items():
 mask=np.zeros_like(grays[0]);cv2.fillPoly(mask,[np.array(reg['polygon'],np.int32)],255)
 pts=cv2.goodFeaturesToTrack(grays[0],120,.008,4,mask=mask);original=pts.reshape(-1,2).copy();features[label]=original.tolist();current=pts.copy();alive=np.ones(len(pts),bool)
 records[start][label]={'xy':reg['anchor'],'dxdy':[0,0],'surviving_features':len(pts),'median_error_px':0,'affine':[[1,0,0],[0,1,0]]}
 for k in range(1,len(frames)):
  new,st,err=cv2.calcOpticalFlowPyrLK(grays[k-1],grays[k],current,None,winSize=(25,25),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,50,.001))
  back,bst,berr=cv2.calcOpticalFlowPyrLK(grays[k],grays[k-1],new,None,winSize=(25,25),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,50,.001))
  alive &= (st.ravel()>0)&(bst.ravel()>0)&(np.linalg.norm(back-current,axis=2).ravel()<1.0)&(err.ravel()<24)
  M,inliers=cv2.estimateAffinePartial2D(original[alive],new.reshape(-1,2)[alive],method=cv2.RANSAC,ransacReprojThreshold=2.5,maxIters=5000,confidence=.995,refineIters=25)
  assert M is not None
  target=M@np.array(reg['anchor']+[1]);res=(original[alive]@M[:,:2].T+M[:,2])-new.reshape(-1,2)[alive]
  records[start+k][label]={'xy':target.tolist(),'dxdy':(target-reg['anchor']).tolist(),'surviving_features':int(alive.sum()),'inliers':int(inliers.sum()),'median_error_px':float(np.median(np.linalg.norm(res[inliers.ravel()>0],axis=1))),'affine':M.tolist()}
  current=new
# Annotated sample crops are local analysis evidence, not a substitute for source frames.
for n in [4033,4038,4042,4048,4054,4060,4067,4072,4076,4080,4090,4095]:
 im=Image.fromarray(cv2.cvtColor(frames[n-start],cv2.COLOR_BGR2RGB));dr=ImageDraw.Draw(im)
 for label,color in [('optic','red'),('receiver','yellow'),('support_hand','cyan')]:
  x,y=records[n][label]['xy'];dr.ellipse((x-5,y-5,x+5,y+5),outline=color,width=2);dr.text((x+7,y),label,fill=color)
 im.crop((580,250,1110,720)).save(p/f'tracked_{n}.png')
out={'schema':'cod-jump-weapon-tracks/v1','source_sha256':'491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46','fps':60,'frame_origin':0,'anchor_frame':anchor,'regions':regions,'features':features,'records':records,'method':'Foreground-only Lucas-Kanade tracks with forward-backward filtering; robust per-region similarity transform from fixed n4033 anchor. Coordinates are source pixels. Camera world motion is not applied to the held-rig track.'}
(p/'reference_weapon_tracks.json').write_text(json.dumps(out,indent=2)+'\n')
for n in [4033,4034,4038,4042,4045,4048,4054,4060,4067,4072,4076,4080,4085,4090,4095,4100,4105]:print(n,[(label,[round(v,2) for v in records[n][label]['dxdy']],records[n][label]['surviving_features']) for label in regions])
