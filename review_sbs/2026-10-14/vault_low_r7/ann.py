import cv2,numpy as np,subprocess,sys,os,json
sys.path.insert(0,'/workspace/sbs');from make_sbs import txt
O='/workspace/rsbs/review_sbs/2026-10-14/vault_low_r7';os.makedirs(O,exist_ok=True);os.makedirs('ann',exist_ok=True)
def P(p):V=cv2.imread(p);return V[48:768,0:1280].copy(),V[48:768,1280:2560].copy()
R7={f:P(f'fr/f{f-36:02d}.png') for f in range(37,45)}
R6={f:P(f'/workspace/v6/fr/v{f:02d}.png') for f in range(37,45)}
def mask(S,f):
  d=(np.abs(S[f][1][:,:420].astype(int)-S[39][1][:,:420].astype(int)).max(2)>=16).astype(np.uint8)
  if d.sum()<50:return None
  n,l,st,c=cv2.connectedComponentsWithStats(d);k=1+np.argmax(st[1:,4]);m=(l==k).astype(np.uint8)
  ys,xs=np.nonzero(m);row=np.nonzero(m[719])[0]
  return dict(m=m,bbox=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)],c=(float(xs.mean()),float(ys.mean())),px=int(m.sum()),bot=int(row.max()) if len(row) else None)
M7={f:mask(R7,f) for f in range(40,45)};M6={f:mask(R6,f) for f in range(40,45)}
TGT={41:(140,600),42:(215,598)}  # recommended centroid targets
def ph(f):return {37:'over-the-top (hand offscreen)',38:'over-the-top (hand offscreen)',39:'over-the-top (hand offscreen)',40:'free-hand entry: cuff at edge',41:'free-hand entry: glove in',42:'free-hand return',43:'free-hand return',44:'free-hand return'}[f]
meas={}
for f in range(37,45):
  c,k=R7[f];m=M7.get(f)
  if m:
    cnt,_=cv2.findContours(m['m'],cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);cv2.drawContours(k,cnt,-1,(0,200,255),2)
    cx,cy=map(int,m['c']);cv2.circle(k,(cx,cy),6,(0,255,0),-1)
    txt(k,f'hand mask centroid ({cx},{cy})  px {m["px"]}  right edge x={m["bbox"][2]}',(15,690),.7)
    if f-1 in M7 and M7[f-1]:
      px,py=map(int,M7[f-1]['c']);cv2.arrowedLine(k,(px,py),(cx,cy),(255,0,255),3,tipLength=.15)
      dx=cx-px;txt(k,f'step {f-1}->{f}: centroid {dx:+d}px, right edge {m["bbox"][2]-M7[f-1]["bbox"][2]:+d}px',(15,650),.7,(255,120,255))
      meas[f'{f-1}->{f}']=dict(centroid_dx=round(m['c'][0]-M7[f-1]['c'][0],1),right_edge=m['bbox'][2]-M7[f-1]['bbox'][2],bottom_row=(m['bot']-M7[f-1]['bot']))
  if f==41: cv2.circle(k,(cx,cy),120,(0,0,255),4);txt(k,'BLOCKING: glove fully in at edge, then snaps +165px to f42 (3x next step)',(20,170),.7,(80,80,255));cv2.circle(k,TGT[41],9,(255,255,0),2);txt(k,'fix target',(TGT[41][0]+12,TGT[41][1]),.6,(255,255,0))
  if f==42: cv2.circle(k,(cx,cy),120,(0,0,255),4);txt(k,'BLOCKING: arrival of the 41->42 snap',(20,170),.7,(80,80,255));cv2.circle(k,TGT[42],9,(255,255,0),2);txt(k,'fix target',(TGT[42][0]+12,TGT[42][1]),.6,(255,255,0))
  if f==40: cv2.circle(k,(10,700),60,(0,200,0),4);txt(k,'FIX landed: cuff sliver at edge, no glove-only frame',(20,170),.7,(120,255,120))
  for t,l in((c,'REF COD R3'),(k,'CAND vault-low r7 (cd94e2e9)')):
    txt(t,l,(15,40),1.0,(0,255,255) if 'REF' in l else (120,255,120));txt(t,f'f{f:02d}  n{7283+f}  {(f-1)*1000/60:.0f} ms',(15,80),.8);txt(t,'phase: '+ph(f),(15,115),.8,(255,220,120))
  s=cv2.hconcat([c,k]);cv2.imwrite(f'ann/f{f:02d}.png',cv2.resize(s,None,fx=.5,fy=.5,interpolation=cv2.INTER_AREA))
  if 40<=f<=43: cv2.imwrite(f'{O}/sbs_f{f}.png',cv2.resize(s,None,fx=.5,fy=.5,interpolation=cv2.INTER_AREA))
# r6 vs r7 hand strip with trajectory
rows=[]
for nm,S,MM in (('r6',R6,M6),('r7',R7,M7)):
  cs=[]
  for f in range(40,45):
    k=S[f][1].copy()
    pts=[tuple(map(int,MM[g]['c'])) for g in range(40,f+1) if MM[g]]
    for a,b in zip(pts,pts[1:]):cv2.arrowedLine(k,a,b,(255,0,255),3,tipLength=.2)
    for p in pts:cv2.circle(k,p,6,(0,255,0),-1)
    if nm=='r7' and f in TGT:cv2.circle(k,TGT[f],10,(255,255,0),3)
    if MM[f] and f-1 in MM and MM[f-1]:txt(k,f'{f-1}->{f}: {MM[f]["c"][0]-MM[f-1]["c"][0]:+.0f}px',(10,360),1.0,(255,120,255))
    elif f>40 and MM[f]:txt(k,f'{f-1}->{f}: appears ({MM[f]["px"]}px)',(10,360),.9,(80,80,255))
    k=k[300:720,0:560];txt(k,f'{nm} f{f}',(10,35),1.0,(0,255,255));cs.append(k)
  rows.append(cv2.hconcat(cs))
leg=np.zeros((60,rows[0].shape[1],3),np.uint8);txt(leg,'magenta = hand-mask centroid path & per-frame step; cyan ring = recommended r8 centroid target (f41 x~140, f42 x~215 -> steps ~133/75/72/45)',(10,40),.8,(255,255,0))
cv2.imwrite(f'{O}/vault_r7_hand_r6_vs_r7.jpg',cv2.resize(cv2.vconcat(rows+[leg]),None,fx=.6,fy=.6),[cv2.IMWRITE_JPEG_QUALITY,88])
ks=[cv2.imread(f'ann/f{f:02d}.png') for f in range(37,45)]
cv2.imwrite(f'{O}/vault_r7_keys.jpg',cv2.resize(cv2.vconcat([cv2.hconcat(ks[j:j+2]) for j in range(0,8,2)]),None,fx=.6,fy=.6),[cv2.IMWRITE_JPEG_QUALITY,85])
subprocess.run(f'ffmpeg -v error -y -framerate 2 -start_number 37 -i ann/f%02d.png -vf "fps=60,pad=ceil(iw/2)*2:ceil(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 20 {O}/vault_r7_slow30x.mp4',shell=True,check=True)
json.dump(dict(r7={f:dict(bbox=M7[f]['bbox'],centroid=[round(v,1) for v in M7[f]['c']],px=M7[f]['px'],bottom_row_right=M7[f]['bot']) for f in M7},r6={f:(dict(bbox=M6[f]['bbox'],centroid=[round(v,1) for v in M6[f]['c']],px=M6[f]['px']) if M6[f] else None) for f in M6},r7_steps=meas,fix_targets=TGT,method='max abs RGB diff vs f39 >=16 in x<420, largest component; same as packet'),open(f'{O}/vault_r7_measure.json','w'),indent=1)
print(json.dumps(meas))
