#!/usr/bin/env python3
"""CPU depth-tested review renders of the exact runtime mesh (not concept art)."""
import argparse,gzip,json,struct
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from numba import njit
ROOT=Path(__file__).resolve().parents[1]
@njit
def raster(points, colors, triangles, width, height, perspective):
    out=np.empty((height,width,3),dtype=np.uint8)
    depth=np.full((height,width),1e20)
    for y in range(height):
        for x in range(width):
            t=y/height;out[y,x,0]=int(151+45*t);out[y,x,1]=int(177+25*t);out[y,x,2]=int(185+14*t)
    for f in triangles:
        a,b,c=points[f[0]],points[f[1]],points[f[2]]
        if a[2]<.05 or b[2]<.05 or c[2]<.05:continue
        x0=max(0,int(np.floor(min(a[0],b[0],c[0]))));x1=min(width-1,int(np.ceil(max(a[0],b[0],c[0]))))
        y0=max(0,int(np.floor(min(a[1],b[1],c[1]))));y1=min(height-1,int(np.ceil(max(a[1],b[1],c[1]))))
        den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-6:continue
        for y in range(y0,y1+1):
            for x in range(x0,x1+1):
                u=((b[1]-c[1])*(x+.5-c[0])+(c[0]-b[0])*(y+.5-c[1]))/den
                v=((c[1]-a[1])*(x+.5-c[0])+(a[0]-c[0])*(y+.5-c[1]))/den
                w=1-u-v
                if min(u,v,w)<0:continue
                z=1/(u/a[2]+v/b[2]+w/c[2]) if perspective else u*a[2]+v*b[2]+w*c[2]
                if z<depth[y,x]:
                    depth[y,x]=z
                    for k in range(3):out[y,x,k]=int(min(255,max(0,(u*colors[f[0],k]+v*colors[f[1],k]+w*colors[f[2],k])*255)))
    return out

def load(path):
    b=path.read_bytes();b=gzip.decompress(b) if b[:2]==b'\x1f\x8b' else b;count=struct.unpack_from('<I',b,8)[0];off=12;vs=[];fs=[];start=0
    for _ in range(count):
        *bounds,n,m=struct.unpack_from('<6fII',b,off);off+=32
        v=np.frombuffer(b,'<f4',n*10,off).reshape(n,10).copy();off+=n*40
        f=np.frombuffer(b,'<u2',m,off).reshape(-1,3).astype(np.int64)+start;off+=m*2;start+=n
        vs.append(v);fs.append(f)
    return np.concatenate(vs),np.concatenate(fs)
def render(v,f,eye,target,path,title,ortho=None,baked=False):
    eye=np.array(eye);forward=np.array(target)-eye;forward=forward/np.linalg.norm(forward)
    right=np.cross(forward,[0,1,0]);right/=np.linalg.norm(right);up=np.cross(right,forward)
    local=v[:,:3]-eye;p=np.column_stack((local@right,local@up,local@forward));W,H=1600,1000
    light=np.array([-.3,.8,.5]);light/=np.linalg.norm(light)
    col=v[:,6:9] if baked else v[:,6:9]*(.35+.65*np.maximum(0,v[:,3:6]@light))[:,None]
    if not ortho:
        visible=p[f,2]>=.06
        keep=f[visible.all(axis=1)];extra=[];ec=[];ef=[]
        for face in f[visible.any(axis=1)&~visible.all(axis=1)]:
            poly=[p[i] for i in face];clipped=[]
            for i,a in enumerate(poly):
                b=poly[(i+1)%3];ina=a[2]>=.06;inb=b[2]>=.06
                if ina:clipped.append(a)
                if ina!=inb:clipped.append(a+(b-a)*((.06-a[2])/(b[2]-a[2])))
            start=len(p)+len(extra)
            extra.extend(clipped);ec.extend([col[face[0]]]*len(clipped))
            for i in range(1,len(clipped)-1):ef.append([start,start+i,start+i+1])
        if extra:
            p=np.concatenate((p,np.array(extra)));col=np.concatenate((col,np.array(ec)))
            f=np.concatenate((keep,np.array(ef,dtype=np.int64)))
        else:f=keep
    if ortho:p[:,:2]*=W/ortho
    else:p[:,:2]*=(W/2/np.tan(np.radians(70)/2))/np.maximum(p[:,2:3],.001)
    p[:,0]+=W/2;p[:,1]=H/2-p[:,1]
    im=Image.fromarray(raster(p,col,f,W,H,not bool(ortho)));d=ImageDraw.Draw(im)
    d.rectangle((0,H-70,W,H),fill='#223137');d.text((30,H-54),title,fill='#f4ead4',font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',24))
    d.text((30,H-25),'CEDAR JUNCTION  /  Exact exported geometry · CPU review render',fill='#a9bec1')
    im.save(path)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=ROOT);args=ap.parse_args()
    out=args.root/'assets/levels/cedar_junction';v,f=load(out/'meshes.bin');review=out/'review';review.mkdir(exist_ok=True)
    render(v,f,[140,160,165],[0,0,0],review/'overview.jpg','Downtown, Cedar Commons and Market Square',280)
    render(v,f,[1,1.8,39],[0,3,-10],review/'main_street.jpg','Main Street · street-level view')
    render(v,f,[15,1.9,5],[20,2,20],review/'shopfronts.jpg','Shopfronts · open entrances and upper floors')
    render(v,f,[83,2.2,55],[91,1.7,25],review/'park.jpg','Cedar Commons · neighborhood park')
    render(v,f,[-43,1.82,-49],[-48,1.4,-43],review/'coffee_interior.jpg','Union Coffee · furnished ground floor')
    render(v,f,[-40,5.15,-43.5],[-48,4.4,-46],review/'upstairs.jpg','Union Coffee · upstairs interior')
    print('Rendered six views from runtime meshes.')
if __name__=='__main__':main()
