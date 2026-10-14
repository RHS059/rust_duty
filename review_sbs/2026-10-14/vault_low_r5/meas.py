import cv2,numpy as np,json,math
F=[cv2.imread(f'fr/v{i:02d}.png') for i in range(1,65)]
cod=[f[48:768,0:1280] for f in F];cand=[f[48:768,1280:2560] for f in F]
def chain(fr,poly,anchor):
    g=[cv2.cvtColor(x,cv2.COLOR_BGR2GRAY) for x in fr];poly=np.array(poly,np.float32);Mc=np.eye(3);out=[];anc=np.array(anchor,float)
    for i in range(len(g)):
        if i==0: out.append({'xy':anc.tolist(),'rot':0.0,'n':0,'poly':poly.tolist()});continue
        m=np.zeros_like(g[i-1]);cur=cv2.transform(poly[None],Mc[:2])[0];cv2.fillPoly(m,[cur.astype(np.int32)],255)
        p=cv2.goodFeaturesToTrack(g[i-1],300,.005,4,mask=m)
        if p is None or len(p)<4:
            out.append({'xy':None,'rot':None,'n':0,'poly':None,'lost':True});continue
        cr=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,50,.001)
        n,st,_=cv2.calcOpticalFlowPyrLK(g[i-1],g[i],p,None,winSize=(31,31),maxLevel=5,criteria=cr)
        b,bs,_=cv2.calcOpticalFlowPyrLK(g[i],g[i-1],n,None,winSize=(31,31),maxLevel=5,criteria=cr)
        ok=(st.ravel()>0)&(bs.ravel()>0)&(np.linalg.norm(b-p,axis=2).ravel()<1)
        if ok.sum()<4:
            out.append({'xy':None,'rot':None,'n':int(ok.sum()),'poly':None,'lost':True});continue
        M,ins=cv2.estimateAffinePartial2D(p.reshape(-1,2)[ok],n.reshape(-1,2)[ok],method=cv2.RANSAC,ransacReprojThreshold=2)
        Mc=np.vstack([M,[0,0,1]])@Mc
        xy=(Mc@np.r_[anc,1])[:2];out.append({'xy':xy.tolist(),'rot':math.degrees(math.atan2(Mc[1,0],Mc[0,0])),'n':int(ins.sum()),'poly':cv2.transform(poly[None],Mc[:2])[0].tolist()})
    return out
CP=[[700,330],[1000,330],[1000,720],[700,720]];CA=[850,450]   # COD scope+receiver
KP=[[740,300],[1280,330],[1280,720],[740,720]];KA=[902,344]   # cand rear sight/receiver
tc=chain(cod,CP,CA);tk=chain(cand,KP,KA)
# candidate background-subtraction mask
plate=np.median(np.stack(cand[::2]),0).astype(np.uint8)
rows=[]
for i in range(64):
    d=cv2.absdiff(cand[i],plate).max(2);m=(d>18).astype(np.uint8);m=cv2.morphologyEx(m,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
    hsv=cv2.cvtColor(cand[i],cv2.COLOR_BGR2HSV)
    skin=((hsv[...,0]<20)&(hsv[...,1]>60)&(hsv[...,2]>80)&(m>0)).astype(np.uint8)
    glove=((hsv[...,1]<40)&(hsv[...,2]>200)&(m>0)).astype(np.uint8)
    fg=m&(1-skin);occ=float(m.mean()*100)
    ys,xs=np.nonzero(fg);cx,cy=(xs.mean(),ys.mean()) if len(xs) else (None,None)
    if len(xs)>50:
        c=np.cov(np.vstack([xs,ys]));w,v=np.linalg.eigh(c);ax=v[:,1];pa=math.degrees(math.atan2(-ax[1],ax[0]));pa=(pa+90)%180-90
        x0,x1,y0,y1=int(xs.min()),int(xs.max()),int(ys.min()),int(ys.max())
    else: pa=None;x0=x1=y0=y1=None
    # glove blobs: count components of glove pixels > 800px, and whether each touches skin (dilated)
    n,lab,st,cen=cv2.connectedComponentsWithStats(glove);sk=cv2.dilate(skin,np.ones((25,25),np.uint8))
    blobs=[]
    for j in range(1,n):
        if st[j,4]>800: blobs.append({'area':int(st[j,4]),'c':cen[j].round().tolist(),'touch_arm':bool((sk[lab==j]).any())})
    rows.append({'f':i+1,'n':7284+i,'occ_pct':occ,'centroid':[cx,cy],'axis_deg':pa,'bbox':[x0,y0,x1,y1],'skin_px':int(skin.sum()),'glove_blobs':blobs,
      'edge_touch':[x0 is not None and x0<=2, y0 is not None and y0<=2, x1 is not None and x1>=1277, y1 is not None and y1>=717]})
json.dump({'cod_track':tc,'cand_track':tk,'cand_mask':rows},open('vault_measure.json','w'))
for i in range(64):
    r=rows[i];c=tc[i];k=tk[i]
    fx=lambda t:'LOST' if t['xy'] is None else '%5.0f,%5.0f rot %6.1f n%3d'%(t['xy'][0],t['xy'][1],t['rot'],t['n'])
    print(r['f'],r['n'],'COD',fx(c),'| CAND',fx(k),'| occ %4.1f%% axis %s bbox %s skin %d gloves %s'%(r['occ_pct'],None if r['axis_deg'] is None else round(r['axis_deg'],1),r['bbox'],r['skin_px'],[(b['area'],b['c'],b['touch_arm']) for b in r['glove_blobs']]))
