"""Exploratory actual-pixel receiver motion; no normalization or approval score."""
import sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).parent))
import cv2,numpy as np,json,zipfile,io,hashlib
from pathlib import Path
from PIL import Image,ImageDraw
import compare
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--native-evidence',type=Path,required=True,help='Verified original r7 ZIP and frame map folder')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();root=args.output;root.mkdir(parents=True,exist_ok=True);native=args.native_evidence
def file_hash(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while chunk:=f.read(1024*1024):h.update(chunk)
 return h.hexdigest()
if file_hash(args.source)!='491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46':raise ValueError('Wrong source bytes')
if file_hash(native/'jump_r7_native_frames.zip')!='12e5aee93e50a2bc2f5b1763ee5e5afee9b4fe2477102cd07db85469e8a7e504':raise ValueError('Wrong native archive bytes')
if file_hash(native/'reference_frame_map.json')!='58fa76a590d6f2c519f7b535938d09e985ce07a007ab4f48fc9f68de64d1f599':raise ValueError('Wrong original100-frame map bytes')
frame_map=json.load(open(native/'reference_frame_map.json'))['records']
cap=cv2.VideoCapture(str(args.source));cap.set(cv2.CAP_PROP_POS_FRAMES,4014);source=[]
for i in range(100):
 ok,bgr=cap.read();assert ok;source.append(bgr)
with zipfile.ZipFile(native/'jump_r7_native_frames.zip') as z:
 candidate=[cv2.imdecode(np.frombuffer(z.read(f"frames/{r['action']}/f{r['action_frame_1based']:04d}.png"),np.uint8),cv2.IMREAD_COLOR) for r in frame_map]
# Fixed sharp outer upper-right corner of charging-handle transverse body.
# Independently selected on each baseline; geometry correspondence is provisional.
seeds={'reference':[1002,549],'candidate':[1006,485]}
tracks={}
for side,images in [('reference',source),('candidate',candidate)]:
 current=np.array(seeds[side],np.float32).reshape(1,1,2);prev=cv2.cvtColor(images[0],cv2.COLOR_BGR2GRAY);values=[]
 for i,bgr in enumerate(images):
  gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
  if i:
   nxt,status,error=cv2.calcOpticalFlowPyrLK(prev,gray,current,None,winSize=(21,21),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.001))
   back,bs,be=cv2.calcOpticalFlowPyrLK(gray,prev,nxt,None,winSize=(21,21),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.001))
   fb=float(np.linalg.norm(back-current));current=nxt
  else:status=np.ones((1,1));error=np.zeros((1,1));fb=0
  x,y=current[0,0];values.append({'xy':[float(x),float(y)],'state':'uncertain' if status[0,0] and fb<1 else 'tracker_failed','uncertainty_px':6 if side=='reference' else 2,'method':'Actual-pixel LK; explicit native-frame point review pending','forward_backward_error_px':fb});prev=gray
 tracks[side]=values
proposal={'source_sha256':'491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46','candidate_archive_sha256':'12e5aee93e50a2bc2f5b1763ee5e5afee9b4fe2477102cd07db85469e8a7e504','point_definition':'Upper outer right corner of transverse charging-handle body, pixel-raster landmark, proposed homologous correspondence; source COD rifle and native HK416 geometry differ','initial_xy':seeds,'source_range':[4014,4114],'source_fps':[60,1],'tracks':tracks,'status':'Unreviewed predictions, no cross-camera normalization and no score'}
(root/'jump-receiver-proposals.json').write_text(json.dumps(proposal,indent=2))
for page in range(10):
 sheet=Image.new('RGB',(880,5*210),'white');draw=ImageDraw.Draw(sheet)
 for k,i in enumerate(range(page*10,min(100,page*10+10))):
  x=(k%2)*440;y=(k//2)*210
  for offset,side,images in [(0,'reference',source),(215,'candidate',candidate)]:
   px,py=tracks[side][i]['xy'];im=Image.fromarray(cv2.cvtColor(images[i],cv2.COLOR_BGR2RGB));d=ImageDraw.Draw(im);d.ellipse((px-3,py-3,px+3,py+3),outline='red',width=2)
   crop=im.crop((int(px)-45,int(py)-40,int(px)+60,int(py)+50)).resize((210,180));sheet.paste(crop,(x+offset,y+25));draw.text((x+offset+4,y+5),f'{4014+i} {side}',fill='black')
 sheet.save(root/f'jump-receiver-point-review-{page:02d}.jpg')
print('Saved source/candidate point proposals with all100 native-frame crop witnesses; no review inferred')
