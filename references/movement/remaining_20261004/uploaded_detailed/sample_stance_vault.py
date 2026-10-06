"""Reproducible native-index evidence sheets; scaling only, no image registration."""
import argparse, hashlib, json, subprocess
from pathlib import Path
from PIL import Image, ImageDraw
p=argparse.ArgumentParser(); p.add_argument('source_id'); p.add_argument('--root',default='/workspace/scratch/77741642cba4/rust_duty'); p.add_argument('--start',type=int,default=0);p.add_argument('--end',type=int);p.add_argument('--stride',type=int,default=30);a=p.parse_args()
base=Path(__file__).resolve().parent; catalog=json.loads((base.parent/'uploaded_references_inventory.json').read_text());s=next(s for s in catalog['sources'] if s['id']==a.source_id); src=Path(a.root)/s['path'];assert hashlib.sha256(src.read_bytes()).hexdigest()==s['sha256']
end=a.end or s['decoded_frame_count'];inds=list(range(a.start,end,a.stride));expr=f'between(n,{a.start},{end-1})*not(mod(n-{a.start},{a.stride}))';cmd=['ffmpeg','-v','error','-i',str(src),'-vf',f'select={expr.replace(chr(44),chr(92)+chr(44))},scale=320:180','-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','-'];raw=subprocess.check_output(cmd);assert len(raw)==len(inds)*320*180*3
stem=f'{a.source_id}_{a.start}_{end}_s{a.stride}';out=base/'sheets';out.mkdir(exist_ok=True)
for page in range((len(inds)+29)//30):
 sheet=Image.new('RGB',(1600,1200),'#171717');d=ImageDraw.Draw(sheet)
 for j,n in enumerate(inds[page*30:(page+1)*30]):
  k=page*30+j;im=Image.frombytes('RGB',(320,180),raw[k*172800:(k+1)*172800]);x=j%5*320;y=j//5*200;sheet.paste(im,(x,y));d.text((x+4,y+182),f'{a.source_id} n={n} PTS={n*256}',fill='white')
 sheet.save(out/f'{stem}_{page:02d}.jpg',quality=90)
(base/f'{stem}_samples.json').write_text(json.dumps({'source_id':a.source_id,'sha256':s['sha256'],'native_indices':inds,'pts_ticks':[i*256 for i in inds],'time_base':'1/15360','display':'320x180 unwarped full source'},indent=2)+'\n')
print(stem, len(inds), 'samples')
