#!/usr/bin/env python3
"""Compare locomotion FBX runtime to the independent native source oracle.

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


from verify_fbx_segment import read_skin, read_rigid, python_sample


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('asset',type=Path);p.add_argument('source_witnesses',type=Path)
    p.add_argument('--canonical-companions',action='store_true')
    p.add_argument('--oracle-json',type=Path,required=True);p.add_argument('--clip',required=True)
    p.add_argument('--sampler',type=Path);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--position-limit-m',type=float,default=.001)
    args=p.parse_args()
    pack=vrview.decode_vra(args.asset.read_bytes(),vrs=args.asset.with_suffix('.vrs').read_bytes(),vrm=args.asset.with_suffix('.vrm').read_bytes())
    bones,pos,joints,weights=read_skin(args.asset.with_suffix('.vrs'))
    rigid=read_rigid(args.asset.with_suffix('.vrm'))
    mesh_actor={i:a for a,actor in enumerate(pack['actors']) for i in actor['meshes']}
    inverse_rest=[np.array(a['inverse_rest_global']).reshape(4,4).T for a in pack['actors']]
    source=np.load(args.source_witnesses)
    meta=json.loads(args.oracle_json.read_text())
    require=vrpack.require
    rows=meta['samples'][args.clip]
    frames=[r['frame'] for r in rows]
    expected=np.concatenate([source[args.clip+'__skin_'+str(i)] for i in range(len(meta['skin_objects']))],axis=1)
    # Source oracle rigid matrices map Blender-local mesh coordinates to Y-up
    # world. Runtime rigid vertices themselves are Y-up, so change input basis.
    actor_order=[meta['actors'].index(a['name']) for a in pack['actors']]
    props=source[args.clip+'__actors'][:,actor_order]
    if not args.canonical_companions: props=props@BASIS.T
    require(len(pack['actors'])==props.shape[1], 'source prop count mismatch')
    require(set(a['name'] for a in pack['actors'])==set(meta['actors']),'source prop ordering must be explicitly matched')
    times=[r['time'] for r in rows]
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
                           [int(a['visible']) for a in result['actors']],
                           [np.array(m['positions']) for m in result['rigid_meshes']])
                require(proc.wait()==0,'Rust sampler failed')
        else:
            for t in times:
                skin,actors,visible=python_sample(pack,bones,pos,joints,weights,args.clip,t)
                yield skin,actors,visible,[(m@(actors[mesh_actor[i]]@inverse_rest[mesh_actor[i]]).T)[:,:3] for i,m in enumerate(rigid)]
    records=[];correspondence=None;reverse=None
    for i,(skin,actors,visible,rigid_positions) in enumerate(run_samples()):
        require(i<len(frames),'sampler produced extra samples')
        if i==0:
            distance,correspondence=cKDTree(expected[0]).query(skin)
            reverse_distance,reverse=cKDTree(skin).query(expected[0])
            require(max(float(distance.max()),float(reverse_distance.max()))<=args.position_limit_m,'first-pose geometry correspondence exceeds declared limit')
        skin_error=max(float(np.linalg.norm(skin-expected[i,correspondence],axis=1).max()),float(np.linalg.norm(skin[reverse]-expected[i],axis=1).max()))
        expected_visible=[int(np.max(np.abs(m[:3,:3]))>=1e-10) for m in props[i]]
        mask_matches=visible==expected_visible
        origins=[];matrices=[];rigid_errors=[]
        for mesh_index,vertices in enumerate(rigid):
            actor=mesh_actor[mesh_index]
            if expected_visible[actor]:
                gold=(vertices@(props[i,actor]@inverse_rest[actor]).T)[:,:3]
                rigid_errors.append(float(np.linalg.norm(rigid_positions[mesh_index]-gold,axis=1).max()))
        for index,(actual,gold) in enumerate(zip(actors,props[i])):
            if not expected_visible[index]:continue
            origins.append(float(np.linalg.norm(actual[:3,3]-gold[:3,3])))
            matrices.append(float(np.max(np.abs(actual-gold))))
        records.append({'native_frame':float(frames[i]),'time':times[i], 'skin_error_m':skin_error,
                        'visible_prop_origin_error_m':max(origins,default=0.),'visible_rigid_vertex_error_m':max(rigid_errors,default=0.),'visible_prop_matrix_error':max(matrices,default=0.),
                        'visibility_matches':mask_matches,'visible':visible,'expected_visible':expected_visible})
        if i%100==0:print('PARITY',i,len(frames),skin_error,flush=True)
    require(len(records)==len(frames),'sampler sample count mismatch')
    maxima={key:max(r[key] for r in records) for key in ('skin_error_m','visible_prop_origin_error_m','visible_rigid_vertex_error_m','visible_prop_matrix_error')}
    failures=[r for r in records if r['skin_error_m']>args.position_limit_m or r['visible_prop_origin_error_m']>args.position_limit_m or r['visible_rigid_vertex_error_m']>args.position_limit_m or not r['visibility_matches']]
    report={'schema':'rust-duty-locomotion-fbx-parity/v1','backend':'Rust CPU sampler' if args.sampler else 'Python diagnostic only',
            'passed':not failures,'source_witnesses_sha256':hashlib.sha256(args.source_witnesses.read_bytes()).hexdigest(),
            'asset_sha256':hashlib.sha256(args.asset.read_bytes()).hexdigest(),
            'samples':len(records),'clip':args.clip,'source_sha256':meta['source_files_sha256'],
            'source_fbx_sha256':meta['fbx_sha256'],'maxima':maxima,'declared_position_limit_m':args.position_limit_m,
            'visibility_failures':sum(not r['visibility_matches'] for r in records),'records':records,
            'scope':'Exact immutable source witness times, including off-key and switch neighborhoods. No visual, missing-gap or whole-clip approval.'}
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
