"""Pure-Python contract and native PNG checks; no renderer imports."""
import hashlib
import json
import os
import struct
import zlib
from pathlib import Path, PurePosixPath

HERE=Path(__file__).resolve().parent
if not __debug__:
    raise RuntimeError('Capture validation requires Python assertions; do not use -O')
INPUT_ROOT=Path(os.environ.get('RUST_DUTY_CAPTURE_INPUT_ROOT', HERE/'inputs')).expanduser().resolve()
CONTRACTS=json.loads((HERE/'contracts.json').read_text())
TAKES={x['id']:x for x in CONTRACTS['takes']}

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for data in iter(lambda:f.read(1024*1024), b''): h.update(data)
    return h.hexdigest()

def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def configure_input_root(path):
    """Select a caller-owned private input directory; never download assets."""
    global INPUT_ROOT
    INPUT_ROOT=Path(path).expanduser().resolve()

def source_path(take):
    relative=PurePosixPath(take['source'])
    if relative.is_absolute() or not relative.parts or ':' in relative.parts[0] or '..' in relative.parts or '\\' in take['source']:
        raise ValueError('Source must be a portable relative path inside the input root')
    return INPUT_ROOT.joinpath(*relative.parts)

def validate_contract(take, *, verify_source=True):
    assert take['fps']==[60,1] and take['resolution']==[1280,720]
    assert take['time_base']==[1,15360] and take['pts_ticks_per_frame']==256
    assert take['frames_inclusive'][0]==1
    a,b=take['reference_unique_half_open']
    n=take['frames_inclusive'][1]
    assert b-a==take['unique_frame_count']
    assert n==b-a+(take['reference_closure'] is not None)
    assert take['reference_closure'] in (None,b)
    if verify_source:
        assert source_path(take).is_file(), f'Missing pinned source: {source_path(take)}'
        assert sha(source_path(take))==take['source_sha256'], 'Pinned source SHA-256 mismatch'
    assert take['camera']['name']=='RD First Person Review'

def frame_map(take):
    """Map pinned metadata without loading private assets; open_take verifies bytes."""
    validate_contract(take,verify_source=False)
    start=take['reference_unique_half_open'][0]
    return [dict(output_index=i,action=take['action'],action_frame=i+1,
                 source_frame=start+i,source_pts_ticks=(start+i)*256,
                 output_pts_ticks=i*256,closure_witness=i>=take['unique_frame_count'],
                 include_in_unique_playback=i<take['unique_frame_count'])
            for i in range(take['frames_inclusive'][1])]

def png_pixels(path):
    """Decode native RGB/RGBA8 PNG for exact same-pose comparison, without edits."""
    data=Path(path).read_bytes()
    assert data[:8]==b'\x89PNG\r\n\x1a\n'
    pos=8; chunks=[]; header=None
    while pos<len(data):
        n=struct.unpack('>I',data[pos:pos+4])[0]; tag=data[pos+4:pos+8]
        chunk=data[pos+8:pos+8+n]
        crc=struct.unpack('>I',data[pos+8+n:pos+12+n])[0]
        assert zlib.crc32(tag+chunk)&0xffffffff==crc,'PNG CRC mismatch'
        if tag==b'IHDR': header=struct.unpack('>IIBBBBB',chunk)
        if tag==b'IDAT': chunks.append(chunk)
        pos+=12+n
        if tag==b'IEND': break
    w,h,bits,ct,comp,filt,inter=header
    assert bits==8 and ct in (2,6) and comp==filt==inter==0
    channels=3 if ct==2 else 4; stride=w*channels
    raw=zlib.decompress(b''.join(chunks)); assert len(raw)==h*(stride+1)
    output=bytearray(); previous=bytearray(stride)
    for y in range(h):
        offset=y*(stride+1); kind=raw[offset]
        row=bytearray(raw[offset+1:offset+1+stride])
        assert kind in range(5)
        for x in range(stride):
            a=row[x-channels] if x>=channels else 0; b=previous[x]
            c=previous[x-channels] if x>=channels else 0
            if kind==1: add=a
            elif kind==2: add=b
            elif kind==3: add=(a+b)//2
            elif kind==4:
                p=a+b-c; pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
                add=a if pa<=pb and pa<=pc else b if pb<=pc else c
            else: add=0
            row[x]=(row[x]+add)&255
        output.extend(row); previous=row
    return (w,h,channels),bytes(output)

def visible_content_nonempty(shape,pixels):
    """Hard-reject empty, uniform RGB and wholly transparent readbacks.

    Passing this check proves no visual quality or correctness. Independent
    inspection of actual source-pinned pixels is still mandatory.
    """
    w,h,c=shape
    if w<=0 or h<=0 or c not in (3,4) or len(pixels)!=w*h*c:
        return False
    first=pixels[:3]
    nonuniform=any(pixels[i:i+3]!=first for i in range(0,len(pixels),c))
    visible=c==3 or any(pixels[i] for i in range(3,len(pixels),4))
    return bool(nonuniform and visible)

def pixel_evidence(path):
    shape,pixels=png_pixels(path)
    assert shape[:2]==(1280,720)
    assert visible_content_nonempty(shape,pixels),'Empty/uniform/transparent readback is unusable'
    return dict(path=str(path),sha256=sha(path),bytes=Path(path).stat().st_size,
                shape=list(shape),pixel_sha256=hashlib.sha256(pixels).hexdigest(),visible_content_nonempty=True)

def primer_review_valid(review, take, primers):
    """A reviewer must inspect the actual stable same-pose files in this process."""
    return (review.get('accepted') is True and review.get('source_sha256')==take['source_sha256']
            and review.get('take')==take['id'] and isinstance(review.get('review_note'),str) and bool(review['review_note'].strip())
            and review.get('primer_sha256')==[p['sha256'] for p in primers]
            and all(p.get('visible_content_nonempty') is True for p in primers)
            and len(primers)>=3 and primers[-1]['pixel_sha256']==primers[-2]['pixel_sha256'])
