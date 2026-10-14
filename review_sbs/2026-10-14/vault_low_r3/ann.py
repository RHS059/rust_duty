import cv2,json,numpy as np,subprocess,sys
sys.path.insert(0,'/workspace/sbs');from make_sbs import txt
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
D=json.load(open('vault_measure.json'));tc,tk,mk=D['cod_track'],D['cand_track'],D['cand_mask']
def ph(f):
    for a,b,s in [(1,6,'approach/hold'),(7,11,'plant: hands release'),(12,18,'lift: weapon low'),(19,27,'rise'),(28,41,'over-the-top'),(42,50,'free-hand return/regrip'),(51,64,'recovery/settle')]:
        if a<=f<=b:return s
DEF=[(12,18,'C',(950,640),'weapon drops to lower edge (sight y~590-612 vs COD ~490-515)'),
     (28,40,'C',(1000,260),'weapon raised & enlarged (occ 15% vs 9%), COD goes DOWN'),
     (41,45,'C',(150,620),'free glove enters from left with no forearm visible'),]
fr=[]
for f in range(1,65):
    V=cv2.imread(f'fr/v{f:02d}.png');c=V[48:768,0:1280].copy();k=V[48:768,1280:2560].copy();i=f-1;m=mk[i]
    if tc[i]['xy'] and f<=11:
        p=np.array(tc[i]['poly'],np.int32);cv2.polylines(c,[p],True,(0,200,255),2);cx,cy=map(int,tc[i]['xy']);cv2.circle(c,(cx,cy),7,(0,255,0),-1);cv2.arrowedLine(c,(850,450),(cx,cy),(0,140,255),2,tipLength=.1)
        txt(c,f'tracked weapon offset {cx-850:+d},{cy-450:+d}px  rot {tc[i]["rot"]:+.1f} (chained LK)',(15,690),.7)
    if m['bbox'][0] is not None:
        x0,y0,x1,y1=m['bbox'];cv2.rectangle(k,(x0,y0),(x1,y1),(0,200,255),2)
    if tk[i]['xy'] and (f<=6 or f>=58):
        cx,cy=map(int,tk[i]['xy']);cv2.circle(k,(cx,cy),7,(0,255,0),-1);cv2.arrowedLine(k,(902,344),(cx,cy),(0,140,255),2,tipLength=.1)
        txt(k,f'rear-sight offset {cx-902:+d},{cy-344:+d}px',(15,650),.7)
    else: txt(k,'LK sight track not trusted here (QA fail) - mask metrics only',(15,650),.7,(80,80,255))
    txt(k,f'mask occ {m["occ_pct"]:.1f}%  axis {m["axis_deg"]:.1f} deg  bbox top y={m["bbox"][1]}  arm px {m["skin_px"]}',(15,690),.7)
    for a,b,w,pt,note in DEF:
        if a<=f<=b: cv2.circle(k,pt,90,(0,0,255),4);txt(k,note,(20,170),.75,(80,80,255))
    for t,l in((c,'REF COD R3'),(k,'CAND vault-low r3')):
        txt(t,l,(15,40),1.0,(0,255,255) if 'REF' in l else (120,255,120));txt(t,f'f{f:02d}  n{7283+f}  {(f-1)*1000/60:.0f} ms',(15,80),.8);txt(t,'phase: '+ph(f),(15,115),.8,(255,220,120))
    s=cv2.hconcat([c,k]);fr.append(s);cv2.imwrite(f'ann/f{f:02d}.png',cv2.resize(s,None,fx=.5,fy=.5,interpolation=cv2.INTER_AREA))
K=[1,8,12,14,16,20,28,32,36,41,43,46,50,64]
ks=[cv2.resize(fr[f-1],None,fx=.3,fy=.3,interpolation=cv2.INTER_AREA) for f in K]
cv2.imwrite('vault_r3_keys.jpg',cv2.vconcat([cv2.hconcat(ks[j:j+2]) for j in range(0,14,2)]),[cv2.IMWRITE_JPEG_QUALITY,85])
f=np.arange(1,65)
fig,ax=plt.subplots(3,1,figsize=(10,8),sharex=True)
ax[0].plot(f,[m['bbox'][1] for m in mk],'g-o',ms=3,label='cand weapon+arm bbox top y');ax[0].plot(f,[m['centroid'][1] for m in mk],'b-o',ms=3,label='cand weapon centroid y');ax[0].plot(f,[m['centroid'][0] for m in mk],'c-o',ms=3,label='cand weapon centroid x');ax[0].set_ylabel('px');ax[0].invert_yaxis();ax[0].legend(fontsize=7)
ax[1].plot(f,[m['axis_deg'] for m in mk],'g-o',ms=3,label='cand weapon mask axis');ax[1].set_ylabel('deg');ax[1].legend(fontsize=7)
ax[2].plot(f,[m['occ_pct'] for m in mk],'g-o',ms=3,label='cand fg occupancy %');ax[2].plot(f,[m['skin_px']/1000 for m in mk],'r-',label='cand forearm px /1000');ax[2].legend(fontsize=7);ax[2].set_xlabel('native frame')
for a in ax:
    for s,e in [(12,18),(28,41),(41,45)]:a.axvspan(s,e,color='r',alpha=.07)
plt.tight_layout();plt.savefig('vault_r3_plot.png',dpi=110)
subprocess.run('ffmpeg -v error -y -framerate 2 -i ann/f%02d.png -vf "fps=60,pad=ceil(iw/2)*2:ceil(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 20 /workspace/sbs/vault_r3_slow30x.mp4',shell=True,check=True)
subprocess.run('ffmpeg -v error -y -framerate 60 -i ann/f%02d.png -vf "pad=ceil(iw/2)*2:ceil(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 20 /workspace/sbs/vault_r3_sbs_native60.mp4',shell=True,check=True)
