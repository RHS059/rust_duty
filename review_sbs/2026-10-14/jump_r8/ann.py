import cv2,json,numpy as np,math,subprocess,sys
sys.path.insert(0,'/workspace/sbs');from make_sbs import txt
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
res=json.load(open('r8_measure.json'))
rc={r['source_frame']:r for r in json.load(open('/workspace/rust_duty/assets/authoring/jump/review/r7/delivered_receiver_check.json'))['records']}
def ph(k):
    for a,b,s in [(1,4,'pre-contact'),(5,6,'IMPACT (r8 change f5/f6)'),(7,11,'impact build'),(12,13,'trough'),(14,22,'recovery'),(23,29,'settle/closure (ready_closed)')]:
        if a<=k<=b:return s
def draw(img,R,i,col):
    a=tuple(map(int,R['rear'][i]));f=tuple(map(int,R['front'][i]));dx,dy=a[0]-f[0],a[1]-f[1]
    cv2.line(img,(int(f[0]-dx*.8),int(f[1]-dy*.8)),(int(a[0]+dx*.8),int(a[1]+dy*.8)),col,2)
    cv2.circle(img,a,6,(0,255,0),-1);cv2.circle(img,f,6,(255,0,255),-1)
    cv2.line(img,(744,355),(902,344),(170,170,170),1);cv2.arrowedLine(img,(952,500),(952,int(500+R['recv_dy'][i])),(0,140,255),2,tipLength=.15)
v=lambda R,i:(R['ang'][i]-R['ang'][i-1]) if i else 0.0
frames=[]
for k in range(1,30):
    i=k-1;n=4066+k;V=cv2.imread(f'fr/v{k:02d}.png');cod=V[40:760,0:1280].copy();r8=V[40:760,1280:2560].copy()
    r7=cv2.imread(f'/workspace/ex/frames/jump_land_r7/f{k:04d}.png')
    draw(r7,res['r7png'],i,(0,255,255));draw(r8,res['r8'],i,(0,255,255))
    for t,lab,R in((cod,'REF COD',None),(r7,'r7 native PNG (prior)','r7png'),(r8,'CAND r8 (proxy MP4)','r8')):
        txt(t,lab,(15,40),1.0,(0,255,255) if 'REF' in lab else (120,255,120));txt(t,f'f{k:02d}  n{n}  {k/60*1000-1000/60:.0f} ms',(15,80),.8);txt(t,'phase: '+ph(k),(15,115),.8,(255,220,120))
        if R:
            col=(0,0,255) if abs(v(res[R],i))>1.5 and k in(5,6) else (255,255,255)
            txt(t,f'sight {res[R]["ang"][i]:.2f} deg  w {v(res[R],i):+.2f} deg/f',(15,650),.8,col)
            txt(t,f'receiver dy {res[R]["recv_dy"][i]:.2f}px (COD pkt {rc[n]["COD_receiver_drop_px"]:.2f})',(15,690),.75)
    if k in(5,6):
        cv2.circle(r7,tuple(map(int,res['r7png']['rear'][i])),80,(0,0,255),3);txt(r7,'r7 hard stop' if k==6 else 'r7 +3.42 deg/f',(560,260),.9,(80,80,255))
        cv2.circle(r8,tuple(map(int,res['r8']['rear'][i])),80,(0,200,0),3);txt(r8,'r8 eased: +2.13 then +0.84' if k==5 else 'r8 +0.84 deg/f',(480,260),.9,(120,255,120))
    if k==12:
        for t in(r7,r8):txt(t,'TROUGH 76.56px (COD 75.96)',(560,580),.9,(120,255,120))
    sbs=cv2.hconcat([cod,r7,r8]);frames.append(sbs)
    cv2.imwrite(f'ann/f{k:02d}.png',cv2.resize(sbs,None,fx=.5,fy=.5,interpolation=cv2.INTER_AREA))
# keys
ks=[cv2.resize(frames[k-1],None,fx=.33,fy=.33,interpolation=cv2.INTER_AREA) for k in [3,4,5,6,7,8,12,18,25,29]]
cv2.imwrite('jump_r8_keys.jpg',cv2.vconcat(ks),[cv2.IMWRITE_JPEG_QUALITY,85])
# plot
ns=list(range(4067,4096))
fig,ax=plt.subplots(3,1,figsize=(9,8),sharex=True)
for nm,c in(('r7png','C3'),('r8','C2')):
    ax[0].plot(ns,res[nm]['ang'],'o-',c=c,label=nm.replace('png',' native'));ax[1].plot(ns[1:],np.diff(res[nm]['ang']),'o-',c=c,label=nm)
    ax[2].plot(ns,res[nm]['recv_dy'],'o-',c=c,label=nm)
ax[2].plot(ns,[rc[n]['COD_receiver_drop_px'] for n in ns],'k--',label='COD (packet)')
ax[1].plot(ns[1:],np.diff(res['cod']['rot']),'x:',c='gray',label='COD weapon-region rot (noisy, not used)')
ax[0].set_ylabel('sight-line deg');ax[1].set_ylabel('deg/frame');ax[2].set_ylabel('receiver dy px')
for a in ax:a.axvspan(4070.5,4072.5,color='y',alpha=.15);a.legend(fontsize=7)
ax[0].set_title('Jump r8 vs r7: sight angle, angular velocity, receiver (same LK method, base = f29 ready)')
plt.tight_layout();plt.savefig('jump_r8_angle_plot.png',dpi=110)
# diff heatmaps f5 f6
rows=[]
for k in(4,5,6,7):
    a=cv2.imread(f'fr/v{k:02d}.png')[40:760,1280:2560];b=cv2.imread(f'/workspace/ex/frames/jump_land_r7/f{k:04d}.png')
    d=cv2.applyColorMap(np.clip(cv2.absdiff(a,b).max(2).astype(int)*6,0,255).astype(np.uint8),cv2.COLORMAP_INFERNO)
    txt(d,f'|r8 - r7| x6  f{k:02d}  MAD {np.abs(a.astype(float)-b).mean():.2f} (baseline ~2.0 = path/codec)',(15,40),.8)
    rows.append(cv2.resize(cv2.hconcat([b,a,d]),None,fx=.33,fy=.33))
cv2.imwrite('jump_r8_vs_r7_diff.jpg',cv2.vconcat(rows),[cv2.IMWRITE_JPEG_QUALITY,85])
# hand contact crops f1-f8
cr=[]
for k in range(1,9):
    a=cv2.imread(f'fr/v{k:02d}.png')[40:760,1280:2560][300:720,450:1150].copy();txt(a,f'r8 f{k:02d} n{4066+k} hand/grip crop',(10,30),.8);cr.append(cv2.resize(a,None,fx=.5,fy=.5))
cv2.imwrite('jump_r8_hand_f01_f08.jpg',cv2.vconcat([cv2.hconcat(cr[i:i+4]) for i in (0,4)]),[cv2.IMWRITE_JPEG_QUALITY,88])
subprocess.run('ffmpeg -v error -y -framerate 2 -i ann/f%02d.png -vf "fps=60,pad=ceil(iw/2)*2:ceil(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 20 /workspace/sbs/jump_r8_slow30x.mp4',shell=True,check=True)
subprocess.run('ffmpeg -v error -y -framerate 60 -i ann/f%02d.png -vf "pad=ceil(iw/2)*2:ceil(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 20 /workspace/sbs/jump_r8_sbs_native60.mp4',shell=True,check=True)
