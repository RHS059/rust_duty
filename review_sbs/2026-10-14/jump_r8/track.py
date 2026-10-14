import cv2,numpy as np,json,math
R={'rear_sight':[[878,320],[927,320],[933,360],[914,370],[875,366]],'front_sight':[[725,348],[751,348],[775,399],[729,401]],'receiver':[[842,476],[1008,480],[1015,494],[1013,524],[894,519],[842,502]]}
A={'rear_sight':[902,344],'front_sight':[744,355],'receiver':[952,500]}
def track(frames,base,regions=R,anchors=A):
    g=[cv2.cvtColor(f,cv2.COLOR_BGR2GRAY) for f in frames];b=g[base];out=[]
    P={}
    for k,poly in regions.items():
        m=np.zeros_like(b);cv2.fillPoly(m,[np.array(poly,np.int32)],255);P[k]=cv2.goodFeaturesToTrack(b,120,.002,2,mask=m)
    for i in range(len(g)):
        rec={}
        for k,pts in P.items():
            cr=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,50,.001)
            new,st,err=cv2.calcOpticalFlowPyrLK(b,g[i],pts,None,winSize=(25,25),maxLevel=5,criteria=cr)
            bk,bs,_=cv2.calcOpticalFlowPyrLK(g[i],b,new,None,winSize=(25,25),maxLevel=5,criteria=cr)
            al=(st.ravel()>0)&(bs.ravel()>0)&(np.linalg.norm(bk-pts,axis=2).ravel()<1)
            M,ins=cv2.estimateAffinePartial2D(pts.reshape(-1,2)[al],new.reshape(-1,2)[al],method=cv2.RANSAC,ransacReprojThreshold=2)
            xy=M@np.r_[anchors[k],1];rot=math.degrees(math.atan2(M[1,0],M[0,0]))
            rec[k]={'xy':xy.tolist(),'rot':rot,'n':int(al.sum())}
        out.append(rec)
    return out
def ang(r):
    a=r['rear_sight']['xy'];f=r['front_sight']['xy'];return math.degrees(math.atan2(a[1]-f[1],a[0]-f[0]))*-1*-1
