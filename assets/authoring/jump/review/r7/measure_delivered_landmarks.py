"""Measure actual frozen r7 foreground native Eevee pixels. No render or image modification."""
import json,argparse,hashlib
from pathlib import Path
import cv2,numpy as np
p=argparse.ArgumentParser();p.add_argument('--frames',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();cv2.setNumThreads(1)
frames=[]
for n in range(4033,4096):
 action,frame=('jump_takeoff_r7',n-4032) if n<4044 else ('jump_air_r7',n-4043) if n<4067 else ('jump_land_r7',n-4066)
 path=args.frames/action/f'f{frame:04d}.png';im=cv2.imread(str(path));assert im is not None;frames.append(cv2.cvtColor(im,cv2.COLOR_BGR2GRAY))
regions={'rear_sight':{'polygon':[[878,320],[927,320],[933,360],[914,370],[875,366]],'anchor':[902,344]},'front_sight':{'polygon':[[725,348],[751,348],[775,399],[729,401]],'anchor':[744,355]},'receiver':{'polygon':[[842,476],[1008,480],[1015,494],[1013,524],[894,519],[842,502]],'anchor':[952,500]}}
records={n:{} for n in range(4033,4096)}
for label,reg in regions.items():
 mask=np.zeros_like(frames[0]);cv2.fillPoly(mask,[np.array(reg['polygon'],np.int32)],255)
 pts=cv2.goodFeaturesToTrack(frames[0],120,.002,2,mask=mask);orig=pts.reshape(-1,2).copy();cur=pts.copy();alive=np.ones(len(pts),bool)
 records[4033][label]={'xy':reg['anchor'],'dxdy':[0,0],'surviving':len(pts)}
 for i in range(1,len(frames)):
  if 4033+i<4067:continue
  cur=pts.copy();alive=np.ones(len(pts),bool)
  new,st,err=cv2.calcOpticalFlowPyrLK(frames[0],frames[i],cur,None,winSize=(25,25),maxLevel=5,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,50,.001))
  back,bst,_=cv2.calcOpticalFlowPyrLK(frames[i],frames[0],new,None,winSize=(25,25),maxLevel=5,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,50,.001))
  alive &= (st.ravel()>0)&(bst.ravel()>0)&(np.linalg.norm(back-cur,axis=2).ravel()<1)&(err.ravel()<24)
  assert alive.sum()>=2,(label,i,int(alive.sum()))
  M,ins=cv2.estimateAffinePartial2D(orig[alive],new.reshape(-1,2)[alive],method=cv2.RANSAC,ransacReprojThreshold=2,maxIters=5000,confidence=.995,refineIters=25)
  assert M is not None,(label,i,int(alive.sum()));xy=M@np.r_[reg['anchor'],1]
  res=(orig[alive]@M[:,:2].T+M[:,2])-new.reshape(-1,2)[alive]
  records[4033+i][label]={'xy':xy.tolist(),'dxdy':(xy-reg['anchor']).tolist(),'surviving':int(alive.sum()),'inliers':int(ins.sum()),'median_error_px':float(np.median(np.linalg.norm(res[ins.ravel()>0],axis=1)))};cur=new
out={'schema':'jump-actual-eevee-landmark-tracks/v1','revision':'r7','source_sha256':'a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b','frames':'Genuine foreground Eevee native 1280x720; source map 4033..4095','method':'Foreground-only Lucas-Kanade, forward/backward filtered, robust region similarity; actual image features, not fitted source-control predictions. Tiny front sight has fewer features and subpixel uncertainty.','regions':regions,'records':records}
args.output.write_text(json.dumps(out,indent=2)+'\n')
for n in [4067,4070,4073,4076,4078,4080,4084,4088,4092,4095]:print(n,{k:[round(x,2) for x in v['dxdy']] for k,v in records[n].items()})
