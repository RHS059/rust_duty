import sys;sys.path.insert(0,'.')
from measure import *
def ext(img):
    r,fg,skin,wpn=cand_metrics(img)
    ys,xs=np.nonzero(wpn)
    if len(xs)<500: return r,None
    P=np.c_[xs,ys].astype(float); m=P.mean(0); u,s,vt=np.linalg.svd(P-m,full_matrices=False); ax=vt[0]
    if ax[0]>0: ax=-ax   # point left
    t=(P-m)@ax; muz=P[t.argmax()]
    a=np.degrees(np.arctan2(-ax[1],-ax[0]))  # angle of muzzle dir measured above horizontal toward left
    # skin components
    n,lab,st,cen=cv2.connectedComponentsWithStats(skin)
    blobs=[(st[i,4],tuple(cen[i].round())) for i in range(1,n) if st[i,4]>800]
    return r,dict(muz=muz.tolist(),axis_up_left_deg=float(a),blobs=sorted(blobs,reverse=True)[:3],elong=float(s[0]/max(s[1],1)))
if __name__=='__main__':
    out={}
    for k in ['oh','o5']:
        rows=[]
        for f in sorted(glob.glob(k+'/*.png')):
            r,e=ext(cv2.imread(f)[48:768,1280:2560]); rows.append((r,e))
        out[k]=rows
    json.dump(out,open('pca.json','w'),default=float)
