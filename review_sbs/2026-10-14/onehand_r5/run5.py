import sys; sys.path.insert(0,'.')
from measure import *
cfg={'o5':dict(panels={'ref':0,'cand':1280},boxes=[(700,370,160,110),(770,560,140,110)])}


# walk ref weapon boxes: adjust by frame1 check
res={}
for k,c in cfg.items():
    fs=sorted(glob.glob(k+'/*.png')); imgs=[cv2.imread(f) for f in fs]
    P=lambda im,x:im[H0:H0+720,x:x+W]
    tr=Tracker(P(imgs[0],0),c['boxes'])
    out=[]
    for i,im in enumerate(imgs):
        row={'f':i+1}
        t=tr.step(P(im,0)) if i else [(b[0]+b[2]/2,b[1]+b[3]/2,1.0) for b in c['boxes']]
        (mx,my,ms),(rx,ry,rs)=t
        row['ref']={'muz':(mx,my),'rcv':(rx,ry),'score':(ms,rs),'ang':float(np.degrees(np.arctan2(ry-my,rx-mx)))}
        for nm,x in c['panels'].items():
            if nm=='ref':continue
            r,_,_,_=cand_metrics(P(im,x)); row[nm]=r
        out.append(row)
    res[k]=out
json.dump(res,open('meas5.json','w'),default=float)
