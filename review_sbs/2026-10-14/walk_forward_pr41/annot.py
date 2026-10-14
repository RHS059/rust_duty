import sys;sys.path.insert(0,'.')
from measure import *
import os
r=json.load(open('meas.json'))
PH={'oh':[(1,8,'ready/approach'),(9,20,'drop+one-hand plant'),(21,44,'low carry / vault-over'),(45,52,'transition push'),(53,72,'raise/recover'),(73,96,'settled hold')],
    'wf':[(1,12,'step A dip'),(13,22,'step A rise/peak'),(23,32,'step B dip'),(33,38,'step B rise/seam')],
    'wb':[(1,6,'contact A'),(7,17,'dip A'),(18,26,'rise'),(27,37,'dip B'),(38,45,'rise/seam')]}
NAME={'oh':'onehand_r3','wf':'walk_forward','wb':'walk_backward'}
def phase(k,f): return next(p for a,b,p in PH[k] if a<=f<=b)
def flags(k,row,rows):
    c=row['cand'];fl=[]
    if k=='oh':
        if c['occ']<8: fl.append('weapon mostly below frame (occ %.1f%%)'%c['occ'])
        if c.get('attach') is None and row['f'] not in range(1,9): fl.append('no visible hand on weapon')
    else:
        R=np.array([x['ref']['rcv'][1] for x in rows]);C=np.array([x['cand']['cy'] for x in rows])
        i=row['f']-1; e=(C[i]-C.mean())-(R[i]-R.mean())
        if abs(e)>8: fl.append('vertical offset %+.0fpx vs source'%e)
    return fl
for k in ['oh','wf','wb']:
    out=f'/workspace/sbs/{NAME[k]}'; os.makedirs(out,exist_ok=True)
    fs=sorted(glob.glob(k+'/*.png')); rows=r[k]
    pan=[('SOURCE',0),('CANDIDATE',1280)] if k=='oh' else [('SOURCE',0),('BASELINE r5',1280),('CANDIDATE',2560)]
    for f,row in zip(fs,rows):
        im=cv2.imread(f); tiles=[]
        for nm,x in pan:
            t=im[H0:H0+720,x:x+W].copy()
            if nm=='SOURCE':
                m=tuple(map(int,row['ref']['muz']));rc=tuple(map(int,row['ref']['rcv']))
                cv2.circle(t,m,8,(0,255,255),2);cv2.circle(t,rc,10,(0,255,0),2);cv2.line(t,m,rc,(0,255,255),2)
                cv2.putText(t,'muz/rcv track sc %.2f/%.2f  ang %.1f'%(*row['ref']['score'],row['ref']['ang']),(10,700),0,0.7,(0,255,255),2)
            else:
                key='cand' if nm=='CANDIDATE' else 'base'; c=row[key]
                _,fg,skin,wpn=cand_metrics(t.copy())
                cs,_=cv2.findContours(fg,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE); cv2.drawContours(t,cs,-1,(255,200,0),1)
                if c.get('cx'):
                    p=(int(c['cx']),int(c['cy']));cv2.circle(t,p,10,(0,255,0),2)
                    tp=tuple(map(int,c['top']));cv2.circle(t,tp,8,(0,255,255),2)
                    rc=tuple(map(int,row['ref']['rcv']));cv2.arrowedLine(t,rc,p,(255,0,255),2,tipLength=0.15)
                    cv2.circle(t,rc,5,(255,0,255),-1)
                    if c.get('ang') is not None:
                        a=np.radians(c['ang']);cv2.line(t,(int(p[0]-200*np.cos(a)),int(p[1]-200*np.sin(a))),(int(p[0]+200*np.cos(a)),int(p[1]+200*np.sin(a))),(0,128,255),2)
                cv2.putText(t,'occ %.1f%%  ang %s  attach %s'%(c['occ'],None if c.get('ang') is None else round(c['ang'],1),None if c.get('attach') is None else round(c['attach'],2)),(10,700),0,0.7,(0,255,255),2)
                if nm=='CANDIDATE':
                    for j,s in enumerate(flags(k,row,rows)):
                        cv2.putText(t,'DEFECT: '+s,(10,90+30*j),0,0.8,(0,0,255),2)
                        cc=(int(c['cx']),int(c['cy'])) if c.get('cx') else (640,700)
                        cv2.circle(t,cc,120,(0,0,255),4)
            cv2.rectangle(t,(0,0),(W,40),(20,20,20),-1)
            cv2.putText(t,f'{nm} | frame {row["f"]:02d}/{len(rows)} | {phase(k,row["f"])}',(10,28),0,0.8,(255,255,255),2)
            tiles.append(t)
        sb=np.hstack(tiles)
        cv2.putText(sb,'magenta arrow = source receiver -> candidate centroid offset; cyan = muzzle/top, orange = sight-line fit; frame-based, packet d9ae83f',(10,60),0,0.6,(255,255,255),1)
        cv2.imwrite(f'{out}/sbs_{row["f"]:03d}.png',sb)
    # contact sheet keyframes
    keys={'oh':[1,9,13,26,40,45,48,50,57,65,77,88,96],'wf':[1,6,11,17,21,27,30,32,35,38],'wb':[1,8,15,21,24,28,32,36,41,45]}[k]
    th=[cv2.resize(cv2.imread(f'{out}/sbs_{i:03d}.png'),None,fx=0.33,fy=0.33) for i in keys]
    while len(th)%2: th.append(np.zeros_like(th[0]))
    sheet=np.vstack([np.hstack(th[i:i+2]) for i in range(0,len(th),2)])
    cv2.imwrite(f'{out}/contact_sheet.png',sheet)
    os.system(f'ffmpeg -v error -y -framerate 2 -i {out}/sbs_%03d.png -vf "scale=trunc(iw/2/2)*2:trunc(ih/2/2)*2,fps=60" -c:v libx264 -crf 20 -pix_fmt yuv420p /workspace/sbs/{NAME[k]}_slow30x.mp4')
    print(k,'done')
