import cv2,numpy as np,glob,json,sys
H0=48;W=1280
plate=cv2.imread('/workspace/rv/plate_oh_med.png')
hsv=cv2.cvtColor(plate,cv2.COLOR_BGR2HSV)
bad=((hsv[...,1]>40)).astype(np.uint8)*255
bad[560:,780:]=255; bad=cv2.dilate(bad,np.ones((15,15),np.uint8))
plate=cv2.inpaint(plate,bad,9,cv2.INPAINT_TELEA)
cv2.imwrite('/workspace/rv/plate.png',plate)
def cand_metrics(img):
    d=np.abs(img.astype(int)-plate.astype(int)).max(2)
    fg=(d>22).astype(np.uint8)
    fg=cv2.morphologyEx(fg,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    h=cv2.cvtColor(img,cv2.COLOR_BGR2HSV)
    skin=((h[...,0]<20)&(h[...,1]>60)&(fg>0)).astype(np.uint8)
    wpn=((fg>0)&(skin==0)).astype(np.uint8)
    occ=fg.mean()*100
    r={'occ':occ,'wocc':wpn.mean()*100}
    ys,xs=np.nonzero(wpn)
    if len(xs)<500: r.update(cx=None,cy=None,ang=None,top=None,attach=None,skin_c=None); return r,fg,skin,wpn
    r['cx'],r['cy']=float(xs.mean()),float(ys.mean())
    # sight line: upper edge of weapon -> top profile points of columns, fit line
    cols=np.unique(xs); tops=[(x,ys[xs==x].min()) for x in cols[::4]]
    t=np.array(tops,float)
    if len(t)>10:
        # robust fit
        vx,vy,x0,y0=cv2.fitLine(t.astype(np.float32),cv2.DIST_HUBER,0,0.01,0.01).ravel()
        r['ang']=float(np.degrees(np.arctan2(vy,vx)))
    else: r['ang']=None
    i=ys.argmin(); r['top']=(float(xs[i]),float(ys[i]))
    sy,sx=np.nonzero(skin)
    if len(sx)>300:
        r['skin_c']=(float(sx.mean()),float(sy.mean()))
        dil=cv2.dilate(wpn,np.ones((7,7),np.uint8))
        b=cv2.morphologyEx(skin,cv2.MORPH_GRADIENT,np.ones((3,3),np.uint8))
        r['attach']=float((dil[b>0]>0).mean())  # fraction of skin boundary touching weapon/glove
    else: r['skin_c']=None; r['attach']=None
    return r,fg,skin,wpn
class Tracker:
    def __init__(s,img,boxes): s.g=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY); s.b=[list(b) for b in boxes]; s.t=[s.g[y:y+h,x:x+w].copy() for x,y,w,h in boxes]
    def step(s,img,search=70):
        g=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY); out=[]
        for k,(x,y,w,h) in enumerate(s.b):
            X0=max(0,x-search);Y0=max(0,y-search);X1=min(W-1,x+w+search);Y1=min(719,y+h+search)
            reg=g[Y0:Y1,X0:X1]
            if reg.shape[0]<h or reg.shape[1]<w: out.append((x+w/2,y+h/2,0));continue
            m=cv2.matchTemplate(reg,s.t[k],cv2.TM_CCOEFF_NORMED); _,sc,_,p=cv2.minMaxLoc(m)
            nx,ny=X0+p[0],Y0+p[1]
            if sc>0.45:
                s.b[k]=[nx,ny,w,h]; s.t[k]=cv2.addWeighted(s.t[k],0.5,g[ny:ny+h,nx:nx+w],0.5,0)
            out.append((s.b[k][0]+w/2,s.b[k][1]+h/2,float(sc)))
        return out
