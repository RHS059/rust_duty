import json,sys
sys.path.insert(0,'/workspace/sbs');from make_sbs import *
P2=[(96,816),(928,1648)];P3=[(80,800),(880,1600),(1680,2400)]
which=sys.argv[1]
MARKS=json.loads(os.environ.get("MARKS","[]"))
def rng(tbl):
    def f(n):
        for a,b,s in tbl:
            if a<=n<=b:return s
        return '-'
    return f
if which=='jump':
    m={r['output_frame_0based']:r for r in json.load(open('/workspace/rust_duty/assets/authoring/jump/review/r7/reference_frame_map.json'))['records']}
    rc={r['source_frame']:r for r in json.load(open('/workspace/rust_duty/assets/authoring/jump/review/r7/delivered_receiver_check.json'))['records']}
    ph=rng([(0,18,'ready hold'),(19,52,'takeoff/air (accepted)'),(53,56,'pre-contact anticipation'),(57,63,'impact build'),(64,65,'TROUGH'),(66,74,'recovery'),(75,81,'settle'),(82,99,'end hold')])
    def src(n):r=m[n];return f"n{r['source_frame_0based']} {r['action'][5:-3]} f{r['action_frame_1based']:02d}"
    def ov(n,lab,t):
        s=m[n]['source_frame_0based']
        if 'CAND' in lab and s in rc:
            r=rc[s];ax,ay=952,500
            cv2.line(t,(ax-60,ay),(ax+60,ay),(200,200,200),1);txt(t,'ready',(ax+65,ay+5),0.5)
            yc=int(ay+r['COD_receiver_drop_px']);yr=int(ay+r['r7_receiver_drop_px'])
            cv2.circle(t,(ax-25,yc),7,(0,165,255),-1);cv2.circle(t,(ax+25,yr),7,(0,255,0),-1)
            d=r['remaining_raw_difference_px']
            txt(t,f"receiver drop COD {r['COD_receiver_drop_px']:.1f} / r7 {r['r7_receiver_drop_px']:.1f} px  (d {d:+.2f})",(15,690),0.75,(0,0,255) if abs(d)>2 else (120,255,120))
            txt(t,'orange=COD target, green=r7 (packet data)',(15,650),0.6)
    marks={'list':[('CAND r7',75,81,(952,500),'settles early vs COD (3-6.5px)'),('CAND r7',53,55,(952,450),'extra pre-contact rise 3.6-5px')]}
    run('jump_r7_land',sys.argv[2],P2,['REF COD','CAND r7'],ph,src,marks,ov,[53,56,60,64,66,70,75,78,81,82])
if which=='prone':
    ph=rng([(0,20,'standing/HIP start'),(21,40,'drop/kneel'),(41,55,'roll-in (r4 change f41-55)'),(56,68,'prone settle/hold')])
    run('prone_entry_r4',sys.argv[2],P2,['REF COD','CAND entry r4'],ph,lambda n:f'COD n{2241+n}  r4 f{n+1}',{'list':MARKS},None,[0,20,30,41,46,50,55,60,64,68])
if which=='vault':
    ph=rng([(0,11,'approach'),(12,27,'plant/lift'),(28,41,'over-the-top'),(42,50,'hand return/regrip'),(51,63,'recovery')])
    run('low_vault_r3',sys.argv[2],P2,['REF COD','CAND low-vault r3'],ph,lambda n:f'native f{n+1}',{'list':MARKS},None,[0,12,20,28,36,42,46,50,56,63])
if which.startswith('walk_'):
    d=which[5:];N=int(sys.argv[3])
    ph=rng([(0,N//4,'step 1 contact'),(N//4+1,N//2,'passing'),(N//2+1,3*N//4,'step 2 contact'),(3*N//4+1,N,'passing/loop')])
    run(which,sys.argv[2],P3,['REF','APPROVED r5','CAND colab v1'],ph,lambda n:f'native f{n+1}/{N}',{'list':MARKS},None,[0,N//4,N//2,3*N//4,N-1,0],scale=0.4)
