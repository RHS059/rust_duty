#!/usr/bin/env python3
"""Compare a cropped FBX runtime pack to immutable Blender skin/prop witnesses.

A Rust sampler is required for runtime verification. Without --sampler this is
explicitly a Python converter diagnostic. Vertex correspondence is fixed at the
first source pose and tested throughout; UV/normal splits may duplicate vertices.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import numpy as np
from scipy.spatial import cKDTree
import vrpack
import vrskin
import vrview

BASIS=np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]],dtype=float)


def read_skin(path):
    data=path.read_bytes(); vrskin.inspect_vrs(data); p=24
    def unpack(fmt):
        nonlocal p
        value=struct.unpack_from(fmt,data,p);p+=struct.calcsize(fmt);return value
    count,=unpack('<I'); bones=[]
    for _ in range(count):
        size,=unpack('<H'); name=data[p:p+size].decode();p+=size
        parent,=unpack('<i'); rest=np.array(unpack('<16f')).reshape(4,4).T
        inverse=np.array(unpack('<16f')).reshape(4,4).T
        bones.append((name,parent,rest,inverse))
    count,=unpack('<I'); vertices=[]
    for _ in range(count):
        unpack('<6f'); w,h,size=unpack('<III');p+=size
        vc,ic=unpack('<II')
        vertices.extend(unpack('<8f8H8f') for _ in range(vc));p+=ic*4
    v=np.asarray(vertices)
    return bones,np.c_[v[:,:3],np.ones(len(v))],v[:,8:16].astype(int),v[:,16:24]


def python_sample(pack,bones,positions,joints,weights,name,time):
    pose=vrview.sample(pack,name,time,clamp=True); globals_=[]
    for (_,parent,_,_),trs in zip(bones,pose['bones']):
        m=np.array(vrview.matrix(trs)).reshape(4,4)
        globals_.append(globals_[parent]@m if parent>=0 else m)
    palette=np.array([g@b[3] for g,b in zip(globals_,bones)])
    xyz=np.einsum('vwij,vj->vwi',palette[joints],positions)[:,:,:3]
    skin=np.sum(xyz*weights[:,:,None],axis=1)
    return skin,[np.array(vrview.matrix(t)).reshape(4,4) for t in pose['actors']],pose['visible']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('asset',type=Path);p.add_argument('source_witnesses',type=Path)
    p.add_argument('--native-start',type=int,required=True);p.add_argument('--clip',required=True)
    p.add_argument('--sampler',type=Path);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--position-limit-m',type=float,default=.001)
    args=p.parse_args()
    pack=vrview.decode_vra(args.asset.read_bytes(),vrs=args.asset.with_suffix('.vrs').read_bytes(),vrm=args.asset.with_suffix('.vrm').read_bytes())
    bones,pos,joints,weights=read_skin(args.asset.with_suffix('.vrs'))
    source=np.load(args.source_witnesses)
    frames=source['frames']; skin_keys=[k for k in source.files if k.startswith('Actual arms mesh')]
    expected=np.concatenate([source[k] for k in skin_keys],axis=1)@BASIS[:3,:3].T
    props=BASIS@source['props']@BASIS.T
    require=vrpack.require
    require(len(pack['actors'])==props.shape[1], 'source prop count mismatch')
    require([a['name'] for a in pack['actors']]==['hk416_weapon','hk416_magazine','hk416_magazine_outgoing'],'source prop ordering must be explicitly matched')
    times=[float((f-args.native_start)*1001/60000) for f in frames]
    def run_samples():
        if args.sampler:
            # Stream stdout instead of collecting a multi-gigabyte sample JSON.
            command=[str(args.sampler.resolve()),str(args.asset.resolve()),args.clip,*map(str,times),'--clamp']
            with subprocess.Popen(command,stdout=subprocess.PIPE,text=True) as proc:
                for line in proc.stdout:
                    result=json.loads(line)
                    require(result['clip']==args.clip,'sampler returned wrong clip')
                    yield (np.array([p for m in result['skin_meshes'] for p in m['positions']]),
                           [np.array(a['global']).reshape(4,4).T for a in result['actors']],
                           [int(a['visible']) for a in result['actors']])
                require(proc.wait()==0,'Rust sampler failed')
        else:
            for t in times:yield python_sample(pack,bones,pos,joints,weights,args.clip,t)
    records=[];correspondence=None;reverse=None
    for i,(skin,actors,visible) in enumerate(run_samples()):
        require(i<len(frames),'sampler produced extra samples')
        if i==0:
            distance,correspondence=cKDTree(expected[0]).query(skin)
            reverse_distance,reverse=cKDTree(skin).query(expected[0])
            require(max(float(distance.max()),float(reverse_distance.max()))<=args.position_limit_m,'first-pose geometry correspondence exceeds declared limit')
        skin_error=max(float(np.linalg.norm(skin-expected[i,correspondence],axis=1).max()),float(np.linalg.norm(skin[reverse]-expected[i],axis=1).max()))
        expected_visible=[int(np.max(np.abs(m[:3,:3]))>=1e-10) for m in props[i]]
        mask_matches=visible==expected_visible
        origins=[];matrices=[]
        for index,(actual,gold) in enumerate(zip(actors,props[i])):
            if not expected_visible[index]:continue
            origins.append(float(np.linalg.norm(actual[:3,3]-gold[:3,3])))
            matrices.append(float(np.max(np.abs(actual-gold))))
        records.append({'native_frame':float(frames[i]),'time':times[i], 'skin_error_m':skin_error,
                        'visible_prop_origin_error_m':max(origins,default=0.),'visible_prop_matrix_error':max(matrices,default=0.),
                        'visibility_matches':mask_matches,'visible':visible,'expected_visible':expected_visible})
        if i%100==0:print('PARITY',i,len(frames),skin_error,flush=True)
    require(len(records)==len(frames),'sampler sample count mismatch')
    maxima={key:max(r[key] for r in records) for key in ('skin_error_m','visible_prop_origin_error_m','visible_prop_matrix_error')}
    failures=[r for r in records if r['skin_error_m']>args.position_limit_m or r['visible_prop_origin_error_m']>args.position_limit_m or not r['visibility_matches']]
    report={'schema':'rust-duty-fbx-segment-parity/v1','backend':'Rust CPU sampler' if args.sampler else 'Python diagnostic only',
            'passed':not failures,'source_witnesses_sha256':hashlib.sha256(args.source_witnesses.read_bytes()).hexdigest(),
            'asset_sha256':hashlib.sha256(args.asset.read_bytes()).hexdigest(),
            'samples':len(records),'maxima':maxima,'declared_position_limit_m':args.position_limit_m,
            'visibility_failures':sum(not r['visibility_matches'] for r in records),'records':records,
            'scope':'Exact immutable source witness times, including off-key and switch neighborhoods. No visual, missing-gap or whole-clip approval.'}
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
