"""Extract exact integer camera pixels from verified lossless window screenshots.

No resampling, registration, interpolation, warping, color conversion or retiming.
This remains a live-viewport framebuffer capture, not render.opengl output.
"""
import argparse,hashlib,json,struct,zlib
from pathlib import Path
if __package__:
    from .capture_common import sha,png_pixels,visible_content_nonempty,TAKES
else:
    from capture_common import sha,png_pixels,visible_content_nonempty,TAKES

def require_visual_review(proof_path,proof):
    """Stable hashes and valid geometry alone must never accept a capture."""
    assert not (proof_path.parent/'visual-rejection.json').exists(),'Existing visual rejection blocks extraction'
    review_path=proof_path.parent/'visual-review.json'
    assert review_path.is_file(),'Independent visible-content review required'
    review=json.loads(review_path.read_text())
    assert review.get('accepted') is True
    assert isinstance(review.get('review_note'),str) and review['review_note'].strip()
    assert review.get('proof_sha256')==sha(proof_path),'Visual review belongs to a different proof'
    assert review.get('source_sha256')==proof['source_sha256']
    assert review.get('action')==proof['action'] and review.get('action_frame')==1
    assert review.get('screenshot_sha256')==[x['sha256'] for x in proof['screenshots']]
    return review

def encode_png(w,h,c,pixels):
    assert c in (3,4) and len(pixels)==w*h*c
    def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    stride=w*c
    raw=b''.join(b'\0'+pixels[y*stride:(y+1)*stride] for y in range(h))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2 if c==3 else 6,0,0,0))+chunk(b'IDAT',zlib.compress(raw,6))+chunk(b'IEND',b'')

def extract(proof_path,out):
    proof=json.loads(proof_path.read_text())
    assert proof['schema']=='rust-duty-live-eevee-native-pixel-witness/v1'
    take=TAKES['vault-low-r3']
    assert proof['source_sha256']==take['source_sha256'], 'Proof source does not match pinned vault take'
    assert proof['action']==take['action'] and proof.get('action_frame')==1, 'Proof must show exact vault frame one'
    assert proof['integer_camera_border_confirmed_by_projection']
    assert proof['render_operator_used'] is False and proof['source_saved'] is False
    assert proof['source_sha256']==sha(proof['source_path'])
    assert proof['engine']=='BLENDER_EEVEE_NEXT' and proof['viewport_shading']=='RENDERED'
    assert proof['same_pose_camera_crop_pixels_equal'] is True
    assert len(proof['screenshots']) in (2,3) and not out.exists()
    review=require_visual_review(proof_path,proof)
    # Reject before creating any output directory. All-black stable files were
    # observed from screen.screenshot on the current software-GL desktop.
    for row in proof['screenshots']:
        assert sha(row['path'])==row['sha256']
        shape,pixels=png_pixels(row['path'])
        assert visible_content_nonempty(shape,pixels),'Empty/uniform screenshot cannot be accepted'
    candidates=[]
    for i,row in enumerate(proof['screenshots']):
        source=Path(row['path']);assert sha(source)==row['sha256']
        (w,h,c),pixels=png_pixels(source);assert [w,h,c]==row['dimensions']
        x0,y0,x1,y1=row['camera_crop_top_left']
        assert all(isinstance(v,int) for v in [x0,y0,x1,y1])
        assert x1-x0==1280 and y1-y0==720 and 0<=x0<x1<=w and 0<=y0<y1<=h
        stride=w*c
        crop=b''.join(pixels[y*stride+x0*c:y*stride+x1*c] for y in range(y0,y1))
        assert visible_content_nonempty((1280,720,c),crop),'Empty/uniform camera crop cannot be accepted'
        assert hashlib.sha256(crop).hexdigest()==row['native_camera_pixels_sha256']
        candidates.append((source,row,c,crop))
    assert candidates[-1][2:]==candidates[-2][2:], 'Settled camera crops differ despite proof claim'
    out.mkdir(parents=True)
    records=[]
    for i,(source,row,c,crop) in enumerate(candidates):
        x0,y0,x1,y1=row['camera_crop_top_left']
        path=out/f'vault-r3-frame1-repeat-{i+1:02d}.png'
        with path.open('xb') as f:f.write(encode_png(1280,720,c,crop))
        assert png_pixels(path)==((1280,720,c),crop)
        records.append(dict(source_window=str(source),source_window_sha256=sha(source),crop_top_left=[x0,y0,x1,y1],
            output=str(path),sha256=sha(path),decoded_pixels_sha256=hashlib.sha256(crop).hexdigest(),pixel_preservation_exact=True,
            part_of_verified_same_pose_pair=i>=len(proof['screenshots'])-2))
    result=dict(schema='rust-duty-lossless-live-viewport-camera-crop/v1',method='Unscaled integer crop of Blender screen.screenshot PNG',
        original_window_proof=str(proof_path),original_window_proof_sha256=sha(proof_path),
        source_sha256=proof['source_sha256'],action=proof['action'],action_frame=1,reference_source_frame=7284,
        resolution=[1280,720],same_pose_stable=True,stable_repeat_indices=[len(records)-2,len(records)-1],
        render_opengl_output=False,native_frame_corpus=False,
        resampling=False,color_conversion=False,camera_or_geometry_changed=False,visual_review=review,records=records)
    (out/'crop-proof.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--proof',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();print(json.dumps(extract(a.proof,a.output),indent=2))
