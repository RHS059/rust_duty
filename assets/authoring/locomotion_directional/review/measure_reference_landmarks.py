import sys, json, csv, os
# Dependencies: Python3, opencv-python-headless, numpy, scipy
import cv2,numpy as np
from pathlib import Path
from scipy.signal import find_peaks
media=Path(os.environ['REFERENCE_MEDIA_DIR']);out=Path(os.environ.get('REFERENCE_REVIEW_OUTPUT','reference_review_local'));out.mkdir(parents=True,exist_ok=True)
cfg=[('R2','5KM0XSKxTWw','forward',24,102,[(688,405),(886,599),(638,692)]),('R2','5KM0XSKxTWw','backward',150,336,[(706,378),(891,547),(610,654)]),('R2','5KM0XSKxTWw','right',720,786,[(695,382),(873,514),(598,652)]),('R2','5KM0XSKxTWw','left',828,948,[(715,385),(917,548),(650,674)]),('R1','9RRgXvRx43s','forward',30,102,[(669,387),(846,590),(630,699)]),('R1','9RRgXvRx43s','backward',132,270,[(707,379),(896,570),(617,666)]),('R1','9RRgXvRx43s','right',330,450,[(690,403),(885,537),(612,674)]),('R1','9RRgXvRx43s','left',492,630,[(721,386),(924,563),(643,674)])]
summary={}; rows=[]
for r,v,d,a,b,marks in cfg:
 cap=cv2.VideoCapture(str(media/(v+'.mp4'))); cap.set(cv2.CAP_PROP_POS_FRAMES,a); ok,base=cap.read();gray=cv2.cvtColor(base,cv2.COLOR_BGR2GRAY);cv2.imwrite(str(out/f'{r}_{a}.png'),base)
 # Gun outline conservative, plus support wrist area. Muzzle group is forward wooden forestock inside silhouette.
 m0,m1,m2=np.array(marks,dtype=float)
 axis=m1-m0; norm=np.array([-axis[1],axis[0]])/np.linalg.norm(axis)
 groups=[]
 for k,m in enumerate(marks):
  mask=np.zeros_like(gray)
  if k==0:
   p=m0+axis*.31; cv2.ellipse(mask,tuple(p.astype(int)),(40,45),0,0,360,255,-1)
   # Limit to internal gun region using polygon
   poly=np.array([m0+axis*.10-norm*7,m0+axis*.6-norm*12,m0+axis*.62+norm*28,m0+axis*.18+norm*18],np.int32)
   mask[:]=0;cv2.fillPoly(mask,[poly],255)
  else: cv2.circle(mask,tuple(np.array(m,dtype=int)),35,255,-1)
  pts=cv2.goodFeaturesToTrack(gray,60,.01,4,mask=mask,blockSize=5)
  groups.append(pts)
 pts=np.concatenate(groups); lens=np.cumsum([0]+[len(x) for x in groups]); data=[]; frames=[]; prevgray=gray.copy(); curpts=pts.copy(); curmarks=np.array(marks,dtype=float)
 cap.set(cv2.CAP_PROP_POS_FRAMES,a)
 for n in range(a,b):
  ok,im=cap.read()
  if not ok: raise RuntimeError(n)
  g=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
  outmarks=[];counts=[]
  for k,m in enumerate(marks):
   # Fixed, manually chosen anchor template, no cumulative retemplating.
   x,y=map(int,m); left,right,top,bottom=((-8,20,-5,30) if k==0 else (-20,20,-20,20))
   
   temp=gray[y+top:y+bottom,x+left:x+right]
   if r=='R1' and k==0 and d!='backward':
    rr=next(c for c in cfg if c[0]=='R2' and c[2]==d);gg=cv2.imread(str(out/f'R2_{rr[3]}.png'),0);xx,yy=rr[5][0];temp=gg[yy+top:yy+bottom,xx+left:xx+right]
   px,py=curmarks[k];sx=max(0,int(px+left-20));sy=max(0,int(py+top-20));ex=min(1280,int(px+right+21));ey=min(720,int(py+bottom+21))
   if r=='R1' and k==0 and d in ['left','backward']:
    sx=max(sx,x+left-25);ex=min(ex,x+right+26);sy=max(sy,y+top-20);ey=min(ey,y+bottom+21)
   res=cv2.matchTemplate(g[sy:ey,sx:ex],temp,cv2.TM_CCOEFF_NORMED)
   _,score,_,loc=cv2.minMaxLoc(res)
   xy=np.array([sx+loc[0]-left,sy+loc[1]-top],float)
   outmarks.append(xy);counts.append(round(score*1000))
  if r=='R1' and d!='left':
   pp=curmarks.astype(np.float32).reshape(-1,1,2)
   qq,_,_=cv2.calcOpticalFlowPyrLK(prevgray,g,pp,None,winSize=(31,31),maxLevel=3,criteria=(3,50,.001))
   # Preserve independent wrist template; use direct consecutive KLT for geometric barrel and receiver points.
   outmarks[1]=qq[1,0]
  prevgray=g.copy();curmarks=np.array(outmarks)
  row=dict(reference=r,source=v,direction=d,frame=n,pts_ticks=n*256,t_seconds=n/60)
  for k,name in enumerate(['muzzle','receiver','support_wrist']):
   row[name+'_x'],row[name+'_y']=map(float,outmarks[k]);row[name+'_inliers']=counts[k]
  data.append(row);rows.append(row)
  if (n-a)%3==0:
   crop=im[330:720,480:1110].copy()
   for k,p in enumerate(outmarks):
    if np.all(np.isfinite(p)):cv2.circle(crop,(int(p[0]-480),int(p[1]-330)),5,[(0,0,255),(0,255,0),(255,0,0)][k],2)
   cv2.putText(crop,f'{r} {d} n{n}',(8,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
   frames.append(cv2.resize(crop,(420,260)))
  if n==a:
   maskshow=base.copy()
   for p in pts[:,0]:cv2.circle(maskshow,tuple(p.astype(int)),2,(0,255,255),-1)
   cv2.imwrite(str(out/f'{r}_{d}_features.jpg'),maskshow)
 cap.release()
 arr=np.array([[r1[k+'_'+c] for k in ['muzzle','receiver','support_wrist'] for c in ['x','y']] for r1 in data])
 angle=np.degrees(np.arctan2(arr[:,1]-arr[:,3],arr[:,0]-arr[:,2])); angle=np.unwrap(angle*np.pi/180)*180/np.pi
 sm=dict(frame_range=[a,b],samples=len(arr),means=np.nanmean(arr,0).tolist(),peak_to_peak=np.ptp(arr,0).tolist(),axis_angle_mean=float(angle.mean()),axis_angle_peak_to_peak=float(np.ptp(angle)))
 # compare lagged full tracks without time warping; report candidate lags and local minima
 z=arr-arr.mean(0); errors=[]
 for lag in range(20,min(91,len(arr)-15)):
  err=float(np.sqrt(np.mean((z[lag:]-z[:-lag])**2)));errors.append([lag,err])
 ii,_=find_peaks(-np.array(errors)[:,1],distance=10)
 sm['lag_error_local_minima']=[errors[i] for i in ii]; sm['track_return_errors']=errors
 sm['min_inliers']={k:int(min(x[k+'_inliers'] for x in data)) for k in ['muzzle','receiver','support_wrist']}
 summary[r+'_'+d]=sm
 for j in range(0,len(frames),20):
  part=frames[j:j+20];sheet=np.full((260*((len(part)+3)//4),420*4,3),28,np.uint8)
  for i,im in enumerate(part):sheet[(i//4)*260:(i//4+1)*260,(i%4)*420:(i%4+1)*420]=im
  cv2.imwrite(str(out/f'{r}_{d}_tracked_{j//20+1}.jpg'),sheet)
 print(r,d,json.dumps(sm)[:650],flush=True)
with open(out/'reference_tracks_60fps.csv','w') as f:
 w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
(out/'reference_metrics_initial.json').write_text(json.dumps(summary,indent=2))
