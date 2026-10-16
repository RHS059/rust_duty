import argparse,hashlib
import cv2,numpy as np,json
from pathlib import Path
from PIL import Image,ImageDraw
cv2.setNumThreads(1)
parser=argparse.ArgumentParser();parser.add_argument('--reference',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args();p=args.output_dir;p.mkdir(parents=True,exist_ok=True);source=str(args.reference);assert hashlib.sha256(args.reference.read_bytes()).hexdigest()=='491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46'
start,end,anchor=2241,2309,2241
c=cv2.VideoCapture(source);c.set(cv2.CAP_PROP_POS_FRAMES,start)
frames=[]
for n in range(start,end+1):
 ok,im=c.read();assert ok;frames.append(im)
grays=[cv2.cvtColor(im,cv2.COLOR_BGR2GRAY) for im in frames]
regions={
 'optic':{'polygon':[[739,373],[782,351],[852,352],[896,380],[902,450],[873,480],[794,483],[744,454]],'anchor':[841,419]}
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
out={'schema':'prone-entry-foreground-tracks/v1','source_sha256':'491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46','fps':60,'frame_origin':0,'anchor_frame':anchor,'regions':regions,'features':features,'records':records,'method':'Foreground optic-region native-frame Lucas-Kanade tracks with forward-backward rejection and robust similarity fit. No background trajectory included. Single-view inferred retarget, not a matching score.'}
(p/'reference_weapon_tracks.json').write_text(json.dumps(out,indent=2)+'\n')
for n in [2241,2245,2251,2257,2263,2269,2275,2281,2289,2295,2304,2309]: print(n,records[n])
# Diagnostic only: no source clip generation.
sheet=Image.new('RGB',(1280,4*264))
for i,n in enumerate([2241,2245,2251,2257,2263,2269,2275,2281,2289,2295,2304,2309]):
 im=Image.fromarray(cv2.cvtColor(frames[n-start],cv2.COLOR_BGR2RGB));dr=ImageDraw.Draw(im);x,y=records[n]['optic']['xy'];dr.ellipse((x-8,y-8,x+8,y+8),outline='red',width=3);im.thumbnail((426,240));sheet.paste(im,(i%3*426,i//3*264+24));ImageDraw.Draw(sheet).text((i%3*426+3,i//3*264+3),str(n),fill='white')
sheet.save(p/'tracking_diagnostic.jpg')
