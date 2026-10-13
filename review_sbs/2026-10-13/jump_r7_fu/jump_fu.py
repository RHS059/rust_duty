import cv2,json,numpy as np,math
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
from make_sbs import txt
R='/workspace/rust_duty/assets/authoring/jump/review/r7/';O='/workspace/sbs/jump_r7_fu/'
L=json.load(open(R+'delivered_r7_landmarks.json'))['records']
M={r['output_frame_0based']:r for r in json.load(open(R+'reference_frame_map.json'))['records']}
def png(o):r=M[o];return cv2.imread(f"/workspace/ex/frames/{r['action']}/f{r['action_frame_1based']:04d}.png")
cap=cv2.VideoCapture('/workspace/jump.mp4');V=[]
while True:
    ok,im=cap.read()
    if not ok:break
    V.append(im)
ns=list(range(4067,4096));ang={}
for n in ns:
    a=L[str(n)]['rear_sight']['xy'];f=L[str(n)]['front_sight']['xy'];ang[n]=-math.degrees(math.atan2(-(a[1]-f[1]),a[0]-f[0]))
vel={n:ang[n]-ang[n-1] for n in ns[1:]}
print('angle',{n:round(ang[n],2) for n in ns});print('vel',{n:round(vel[n],2) for n in vel})
def phase(o):
    for a,b,s in [(0,18,'ready hold (takeoff f01)'),(19,29,'takeoff'),(30,52,'air'),(53,56,'pre-contact'),(57,63,'impact build'),(64,65,'trough'),(66,74,'recovery'),(75,81,'settle/closure'),(82,99,'end hold (land f29)')]:
        if a<=o<=b:return s
# 1) sight line SBS 4068-4076 + plot
fig,ax=plt.subplots(2,1,figsize=(8,5),sharex=True)
ax[0].plot(ns,[ang[n] for n in ns],'o-');ax[0].set_ylabel('sight-line deg (image)');ax[0].axhline(-3.98,ls=':',c='g')
ax[1].bar(list(vel),list(vel.values()),color=['r' if n in(4071,4072) else 'C0' for n in vel]);ax[1].set_ylabel('deg/frame');ax[1].set_xlabel('COD source n (out = n-4014)')
for a in ax:a.axvspan(4070.5,4072.5,color='r',alpha=.1)
ax[0].set_title('r7 rear->front sight-line angle, from delivered_r7_landmarks.json (LK tracks)');plt.tight_layout();plt.savefig(O+'sight_angle_plot.png',dpi=110)
plot=cv2.imread(O+'sight_angle_plot.png')
tiles=[]
for n in range(4068,4077):
    o=n-4014;ref=V[o][96:816].copy();c=png(o).copy()
    a=tuple(map(int,L[str(n)]['rear_sight']['xy']));f=tuple(map(int,L[str(n)]['front_sight']['xy']))
    # extend line
    dx,dy=a[0]-f[0],a[1]-f[1];p0=(int(f[0]-dx*.8),int(f[1]-dy*.8));p1=(int(a[0]+dx*.8),int(a[1]+dy*.8))
    cv2.line(c,p0,p1,(0,255,255),2);cv2.circle(c,a,6,(0,255,0),-1);cv2.circle(c,f,6,(255,0,255),-1)
    r0=(902,344);f0=(744,355);cv2.line(c,f0,r0,(160,160,160),1);cv2.arrowedLine(c,r0,a,(0,140,255),2,tipLength=.2)
    txt(c,f'{ang[n]:.2f} deg  vel {vel.get(n,0):+.2f} deg/f',(15,690),0.8,(0,0,255) if n in(4071,4072) else (255,255,255))
    if n in(4071,4072):cv2.circle(c,a,80,(0,0,255),3);txt(c,'angular hard stop 4071-72',(a[0]-330,a[1]+120),0.8,(80,80,255))
    for t,lab in((ref,'REF COD'),(c,'CAND r7 native PNG')):
        txt(t,lab,(15,40),1.0,(0,255,255) if 'REF' in lab else (120,255,120));txt(t,f'out {o}  n{n}  land f{M[o]["action_frame_1based"]:02d}',(15,80),.8);txt(t,'phase: '+phase(o),(15,115),.8,(255,220,120))
    tiles.append(cv2.resize(cv2.hconcat([ref,c]),None,fx=.4,fy=.4))
grid=cv2.vconcat([cv2.hconcat(tiles[i:i+3]) for i in range(0,9,3)])
p=cv2.resize(plot,(grid.shape[1],int(plot.shape[0]*grid.shape[1]/plot.shape[1])))
cv2.imwrite(O+'1_sight_4068_4076.jpg',cv2.vconcat([grid,p]),[cv2.IMWRITE_JPEG_QUALITY,85])
# 2) glove crops land f1-f6 + f7 control
cr=[]
for k in range(1,9):
    im=cv2.imread(f'/workspace/ex/frames/jump_land_r7/f{k:04d}.png');z=cv2.resize(im[520:720,300:900],None,fx=1.5,fy=1.5,interpolation=cv2.INTER_NEAREST)
    g=cv2.cvtColor(im[640:720,300:900],cv2.COLOR_BGR2GRAY);dark=(g<70).sum()
    txt(z,f'land f{k:02d} out {52+k} n{4066+k}  crop x300-900 y520-720 x1.5',(10,30),.7);(k<=6) and (cv2.circle(z,(840,230),95,(0,0,255),3), txt(z,'real glove mesh (grip hand) entering/leaving bottom edge',(330,350),.65,(80,80,255)))
    print('glove',k,dark);cr.append(z)
cv2.imwrite(O+'2_bottom_edge_f01_f08.jpg',cv2.vconcat([cv2.hconcat(cr[i:i+2]) for i in range(0,8,2)]),[cv2.IMWRITE_JPEG_QUALITY,88])
# 3) seams
def mad(a,b):return float(np.abs(a.astype(float)-b.astype(float)).mean())
rows=[];seam={}
for o in list(range(15,24))+list(range(78,86)):
    nat=mad(png(o),png(o-1));mp=mad(V[o][928:1648],V[o-1][928:1648]);seam[o]=(nat,mp)
print('seam (out: native MAD, mp4 cand-panel MAD)',{o:(round(a,2),round(b,2)) for o,(a,b) in seam.items()})
for pair in((18,19),(19,20),(81,82),(80,81)):
    a,b=png(pair[0]),png(pair[1]);d=cv2.applyColorMap(np.clip(cv2.absdiff(a,b).max(2)*8,0,255).astype(np.uint8),cv2.COLORMAP_INFERNO)
    for t,s in((a,f'out {pair[0]} {phase(pair[0])}'),(b,f'out {pair[1]} {phase(pair[1])}'),(d,f'|diff| x8  native MAD {seam[pair[1]][0]:.2f}  mp4 {seam[pair[1]][1]:.2f}')):txt(t,s,(15,40),.9)
    rows.append(cv2.resize(cv2.hconcat([a,b,d]),None,fx=.35,fy=.35))
cv2.imwrite(O+'3_seams.jpg',cv2.vconcat(rows),[cv2.IMWRITE_JPEG_QUALITY,85])
# 4) full-range per-frame strip: MAD + phases
o_all=list(range(1,100));nat=[mad(png(o),png(o-1)) for o in o_all]
plt.figure(figsize=(10,3));plt.plot(o_all,nat,'.-');plt.xlabel('output frame');plt.ylabel('native MAD vs prev');
for a,b,s in [(0,18,'hold'),(19,29,'takeoff'),(30,52,'air'),(53,63,'land/impact'),(64,65,'trough'),(66,81,'recovery/closure'),(82,99,'hold')]:plt.axvspan(a,b,alpha=.08);plt.text(a,max(nat)*0.95,s,fontsize=7)
plt.tight_layout();plt.savefig(O+'4_full_range_frame_diff.png',dpi=110)
print('nat MAD',[round(x,2) for x in nat])
