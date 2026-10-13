import cv2, numpy as np, json, sys, subprocess, os
F=cv2.FONT_HERSHEY_SIMPLEX
def txt(im,s,xy,sc=0.8,col=(255,255,255)):
    cv2.putText(im,s,xy,F,sc,(0,0,0),4,cv2.LINE_AA);cv2.putText(im,s,xy,F,sc,col,2,cv2.LINE_AA)
def run(name,mp4,panels,labels,phase_of,src_of,marks={},overlay=None,keys=[],scale=0.5):
    out=f'/workspace/sbs/{name}';os.makedirs(out,exist_ok=True)
    c=cv2.VideoCapture(mp4);n=0;frames=[]
    while True:
        ok,im=c.read()
        if not ok:break
        tiles=[]
        for (y0,y1),lab in zip(panels,labels):
            t=im[y0:y1].copy()
            if overlay: overlay(n,lab,t)
            for (who,fr0,fr1,pt,note) in marks.get('list',[]):
                if who==lab and fr0<=n<=fr1:
                    pt=tuple(pt);cv2.circle(t,pt,70,(0,0,255),4)
                    txt(t,note,(max(10,pt[0]-300),min(700,pt[1]+105)),0.8,(80,80,255))
            txt(t,lab,(15,40),1.1,(0,255,255) if 'REF' in lab else (120,255,120))
            txt(t,f'out {n}  {src_of(n)}',(15,80),0.8)
            txt(t,f'phase: {phase_of(n)}',(15,115),0.8,(255,220,120))
            tiles.append(t)
        sbs=cv2.hconcat(tiles);sbs=cv2.resize(sbs,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
        cv2.imwrite(f'{out}/f{n:03d}.png',sbs);frames.append(sbs);n+=1
    subprocess.run(['ffmpeg','-v','error','-y','-framerate','60','-i',f'{out}/f%03d.png','-c:v','libx264','-pix_fmt','yuv420p','-crf','20','-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2',f'/workspace/sbs/{name}_sbs.mp4'],check=True)
    ks=[frames[k] for k in keys]
    while len(ks)%2: ks.append(np.zeros_like(ks[0]))
    rows=[cv2.hconcat(ks[i:i+2]) for i in range(0,len(ks),2)]
    sheet=cv2.vconcat(rows);s=min(1.0,2400/sheet.shape[1]);sheet=cv2.resize(sheet,None,fx=s,fy=s,interpolation=cv2.INTER_AREA)
    cv2.imwrite(f'/workspace/sbs/{name}_keys.jpg',sheet,[cv2.IMWRITE_JPEG_QUALITY,85])
    print(name,n)
