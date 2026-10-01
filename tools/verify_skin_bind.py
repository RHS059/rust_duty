#!/usr/bin/env python3
"""Compare a source GLB and VRS bind pose locally, without writing source data.

Includes every vertex and every joint. Optional --rest-metadata cross-checks
independently exported world_rest_transform_column_major matrices as well.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import vrpack
import vrskin


def multiply(a, b):
    return tuple(sum(a[k*4+r]*b[c*4+k] for k in range(4)) for c in range(4) for r in range(4))


def point(m,p):
    return tuple(sum(m[c*4+r]*p[c] for c in range(3))+m[12+r] for r in range(3))


def vrs_records(data):
    vrskin.inspect_vrs(data)
    cursor=24
    def unpack(fmt):
        nonlocal cursor
        value=struct.unpack_from('<'+fmt,data,cursor); cursor+=struct.calcsize('<'+fmt); return value
    bones=[]
    for _ in range(unpack('I')[0]):
        size=unpack('H')[0]; name=data[cursor:cursor+size].decode(); cursor+=size
        parent=unpack('i')[0]; rest=unpack('16f'); bind=unpack('16f')
        bones.append((name,parent,rest,bind))
    meshes=[]
    for _ in range(unpack('I')[0]):
        unpack('6f'); _,_,size=unpack('III'); cursor+=size
        vc,ic=unpack('II'); vertices=[unpack('8f8H8f') for _ in range(vc)]; cursor+=ic*4
        meshes.append(vertices)
    return bones,meshes


def verify(glb, vrs, metadata=None, tolerance=2e-5):
    doc,blob=vrpack.parse_glb(glb)
    source=vrskin.Converter(doc,blob,base_color_only=True)
    bones,meshes=vrs_records(vrs)
    # Independent hierarchy reconstruction: build parent links from source nodes,
    # not Converter.hierarchy, then compose each source joint up to its root.
    parents={}
    for index,node in enumerate(doc['nodes']):
        for child in node.get('children',[]):
            if child in parents: raise ValueError('multiple source parents')
            parents[child]=index
    def source_global(index):
        result=vrskin.transpose(vrpack.node_matrix(doc['nodes'][index])); seen={index}
        while index in parents:
            index=parents[index]
            if index in seen: raise ValueError('source hierarchy cycle')
            seen.add(index)
            result=multiply(vrskin.transpose(vrpack.node_matrix(doc['nodes'][index])),result)
        return result
    def output_global(index):
        result=bones[index][2]; seen={index}
        while bones[index][1]!=-1:
            index=bones[index][1]
            if index in seen: raise ValueError('output hierarchy cycle')
            seen.add(index); result=multiply(bones[index][2],result)
        return result
    joint_nodes=doc['skins'][0]['joints']
    assert len(bones)==len(joint_nodes)
    gold_globals=[source_global(node) for node in joint_nodes]
    output_globals=[output_global(i) for i in range(len(bones))]
    max_matrix_error=max(abs(a-b) for gold,actual in zip(gold_globals,output_globals) for a,b in zip(gold,actual))
    if max_matrix_error>tolerance: raise AssertionError(f'joint global error {max_matrix_error}')
    metadata_error=None
    if metadata:
        joints=metadata['joints']; assert len(joints)==len(bones)
        metadata_error=max(abs(a-b) for i,j in enumerate(joints) for a,b in zip(j['world_rest_transform_column_major'],output_globals[i]))
        if metadata_error>tolerance: raise AssertionError(f'external rest metadata error {metadata_error}')
    source_binds=source.skin_accessor(doc['skins'][0]['inverseBindMatrices'],'inverseBindMatrices') if 'inverseBindMatrices' in doc['skins'][0] else [vrpack.IDENTITY]*len(bones)
    gold_skin=[multiply(g,b) for g,b in zip(gold_globals,source_binds)]
    actual_skin=[multiply(g,b[3]) for g,b in zip(output_globals,bones)]
    # Deterministic scene pre-order used by the file format.
    scene=doc['scenes'][doc.get('scene',0)]
    scene_nodes=[]
    def walk(idx):
        scene_nodes.append(idx)
        for child in doc['nodes'][idx].get('children',[]): walk(child)
    for root in scene.get('nodes',[]): walk(root)
    all_primitives=[p for idx in scene_nodes if 'mesh' in doc['nodes'][idx] for p in doc['meshes'][doc['nodes'][idx]['mesh']]['primitives']]
    assert len(all_primitives)==len(meshes)
    max_position_error=max_bind_displacement=max_weight_error=0.0
    checked=with_extra=0
    for primitive,vertices in zip(all_primitives,meshes):
        attrs=primitive['attributes']; positions=source.accessor(attrs['POSITION'],'POSITION')
        js=source.skin_accessor(attrs['JOINTS_0'],'JOINTS_0'); ws=source.skin_accessor(attrs['WEIGHTS_0'],'WEIGHTS_0')
        if 'JOINTS_1' in attrs:
            j1=source.skin_accessor(attrs['JOINTS_1'],'JOINTS_1'); w1=source.skin_accessor(attrs['WEIGHTS_1'],'WEIGHTS_1')
            js=[a+b for a,b in zip(js,j1)]; ws=[a+b for a,b in zip(ws,w1)]
        assert len(vertices)==len(positions)
        for pos,joints,weights,vertex in zip(positions,js,ws,vertices):
            weights=tuple(w/sum(weights) for w in weights)
            expected_joints=tuple(joints)+(0,)*(8-len(joints))
            expected_weights=weights+(0.,)*(8-len(weights))
            assert vertex[8:16]==expected_joints and vertex[:3]==tuple(pos)
            max_weight_error=max(max_weight_error,*(abs(a-b) for a,b in zip(expected_weights,vertex[16:24])))
            gold=[sum(w*point(gold_skin[j],pos)[axis] for j,w in zip(joints,weights)) for axis in range(3)]
            actual=[sum(w*point(actual_skin[j],vertex[:3])[axis] for j,w in zip(vertex[8:16],vertex[16:24])) for axis in range(3)]
            max_position_error=max(max_position_error,*(abs(a-b) for a,b in zip(gold,actual)))
            max_bind_displacement=max(max_bind_displacement,*(abs(a-b) for a,b in zip(gold,pos)))
            with_extra+=int(any(w>0 for w in expected_weights[4:])); checked+=1
    if max_position_error>tolerance: raise AssertionError(f'skinned vertex error {max_position_error}')
    if max_weight_error>1e-6: raise AssertionError(f'weight loss {max_weight_error}')
    return {'checked_bones':len(bones),'checked_vertices':checked,'vertices_using_influences_5_to_8':with_extra,
            'max_joint_global_component_error':max_matrix_error,'max_skinned_position_component_error':max_position_error,
            'max_normalized_weight_error':max_weight_error,'source_bind_pose_max_displacement_from_raw_positions':max_bind_displacement,
            'external_rest_metadata_max_component_error':metadata_error,'tolerance':tolerance,'passed':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('glb',type=Path); parser.add_argument('vrs',type=Path)
    parser.add_argument('--rest-metadata',type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(vrpack.read_limited(args.glb),vrpack.read_limited(args.vrs),json.loads(args.rest_metadata.read_text()) if args.rest_metadata else None),indent=2,sort_keys=True))
