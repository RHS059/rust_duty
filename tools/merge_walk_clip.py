#!/usr/bin/env python3
"""Append an imported walk to canonical locomotion, preserving every old clip byte.

The Blender importer uses Y-up rigid local vertices, while the canonical pack
uses Blender-local rigid transforms. The explicit right-hand basis conversion
below reconciles that convention; geometry and bind matrices stay untouched.
"""
import argparse
import copy
from pathlib import Path
import struct
import zlib
import vrpack
import vrview

BASIS=(1,0,0,0, 0,0,1,0, 0,-1,0,0, 0,0,0,1)


def clip_offset(data):
    """Return byte offset of clip count after validated VRA fixed definitions."""
    vrview.decode_vra(data)
    p=24+8; bc,=struct.unpack_from('<I',data,p);p+=4
    for _ in range(bc):
        n,=struct.unpack_from('<H',data,p);p+=2+n+4
    ac,=struct.unpack_from('<I',data,p);p+=4
    for _ in range(ac):
        n,=struct.unpack_from('<H',data,p);p+=2+n
        mc,=struct.unpack_from('<I',data,p);p+=4+4*mc+64
    return p


def merge(base, incoming, vrs, vrm, name='normal_walk_r1', expected_loop=True):
    original=vrview.decode_vra(base,vrs=vrs,vrm=vrm)
    new=vrview.decode_vra(incoming)
    require=vrpack.require
    require(name not in [c['name'] for c in original['clips']], 'walk already exists')
    matches=[c for c in new['clips'] if c['name']==name]
    require(len(matches)==1,'missing or ambiguous walk clip')
    clip=copy.deepcopy(matches[0]);require(clip['loop'] is expected_loop,'clip must loop' if expected_loop else 'clip must not loop')
    names=[n for n,_ in new['bones']]
    require(set(names)=={n for n,_ in original['bones']},'canonical bone names differ')
    for n,p in original['bones']:
        j=names.index(n); q=new['bones'][j][1]
        require((original['bones'][p][0] if p>=0 else None)==(names[q] if q>=0 else None),'bone parent differs')
    order=[names.index(n) for n,_ in original['bones']]
    actors=[a['name'] for a in new['actors']]
    require(set(actors)=={a['name'] for a in original['actors']},'actor names differ')
    actor_order=[actors.index(a['name']) for a in original['actors']]
    for f in clip['frames']:
        f['bones']=[f['bones'][i] for i in order]
        f['actors']=[vrview.decompose(vrpack.matmul(vrview.matrix(f['actors'][i]),BASIS)) for i in actor_order]
        f['visible']=[f['visible'][i] for i in actor_order]
    encoded=vrview.encode_vra(original['bones'],original['actors'],[clip],vrs,vrm)
    offset=clip_offset(base); new_offset=clip_offset(encoded)
    payload=bytearray(base[24:offset]);payload+=struct.pack('<I',len(original['clips'])+1)
    payload+=base[offset+4:];payload+=encoded[new_offset+4:]
    result=vrview.HEADER.pack(vrview.MAGIC,vrview.VERSION,len(payload),zlib.crc32(payload),0)+payload
    decoded=vrview.decode_vra(result,vrs=vrs,vrm=vrm)
    require(len(decoded['clips'])==len(original['clips'])+1,'merge count differs')
    require(result[offset+4:offset+4+len(base)-offset-4]==base[offset+4:],'old clip bytes changed')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('base',type=Path);p.add_argument('walk',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    vrs=args.base.with_suffix('.vrs').read_bytes();vrm=args.base.with_suffix('.vrm').read_bytes()
    data=merge(args.base.read_bytes(),args.walk.read_bytes(),vrs,vrm)
    for ext,raw in [('vra',data),('vrs',vrs),('vrm',vrm)]:
        (args.output/('asset.'+ext)).write_bytes(raw)

if __name__=='__main__':main()
