"""Inspect original R3 frames; this does not render or author an animation."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from PIL import Image,ImageDraw
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
sha=hashlib.sha256(a.source.read_bytes()).hexdigest();assert sha=='491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46';a.output.mkdir(parents=True,exist_ok=True)
for name,start,end in [('low_obstacle',7284,7348),('one_hand',7787,7883),('vehicle_roof',8507,8583)]:
 out=a.output/('climb' if name=='vehicle_roof' else 'mantle')/'source_evidence';out.mkdir(parents=True,exist_ok=True)
 expr=f'between(n,{start},{end-1})'.replace(',',r'\,');raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(a.source),'-vf',f'select={expr},scale=320:180','-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','-']);assert len(raw)==(end-start)*172800
 for page in range((end-start+29)//30):
  sheet=Image.new('RGB',(1600,1200),'#181818');d=ImageDraw.Draw(sheet)
  for j,n in enumerate(range(start+page*30,min(end,start+(page+1)*30))):
   k=n-start;x=j%5*320;y=j//5*200;im=Image.frombytes('RGB',(320,180),raw[k*172800:(k+1)*172800]);sheet.paste(im,(x,y));d.text((x+3,y+182),f'R3 n={n} B={n-start+1} PTS={n*256}',fill='white')
  sheet.save(out/f'{name}_{page:02}.jpg',quality=92)
 (out/f'{name}_frame_map.json').write_text(json.dumps({'source_sha256':sha,'fps':'60/1','time_base':'1/15360','start':start,'end_exclusive':end,'display':'source only, entire frame scaled320x180, no registration','frames':[{'native_frame':n,'pts_ticks':n*256,'blender_frame':n-start+1} for n in range(start,end)]},indent=2)+'\n')
 print(name,end-start)
