#!/usr/bin/env python3
"""Create independently authored two-bone triangle fixtures. No third-party data.

The GLB deliberately puts the child first in skin.joints, includes transformed
non-joint ancestors, and uses a transformed mesh node. Binary VRS is constructed
independently, without importing the converter or its helpers.
"""
import json
from pathlib import Path
import struct
import zlib


def matrix(tx=0, ty=0, tz=0):
    return [1., 0, 0, 0, 0, 1., 0, 0, 0, 0, 1., 0, tx, ty, tz, 1.]


def build():
    blob = bytearray()
    views, accessors = [], []
    def acc(fmt, rows, component, kind):
        while len(blob) % 4: blob.append(0)
        start = len(blob)
        for row in rows: blob.extend(struct.pack('<' + fmt, *row))
        view = len(views)
        views.append({'buffer': 0, 'byteOffset': start, 'byteLength': len(blob) - start})
        accessors.append({'bufferView': view, 'componentType': component, 'count': len(rows), 'type': kind})
        return len(accessors) - 1
    positions = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
    # Child global translation is (2,3,4), root global is (2,0,0).
    # Each inverse bind cancels that translation at rest.
    binds = [matrix(-2,-3,-4), matrix(-2,0,0)]
    attrs = {
        'POSITION': acc('3f', positions, 5126, 'VEC3'),
        'NORMAL': acc('3f', [(0.,0.,1.)] * 3, 5126, 'VEC3'),
        'TEXCOORD_0': acc('2f', [(0.,0.),(1.,0.),(0.,1.)], 5126, 'VEC2'),
        'JOINTS_0': acc('4B', [(0,1,0,0)] * 3, 5121, 'VEC4'),
        'WEIGHTS_0': acc('4f', [(.75,.25,0.,0.)] * 3, 5126, 'VEC4'),
    }
    indices = acc('H', [(0,),(1,),(2,)], 5123, 'SCALAR')
    inverse = acc('16f', binds, 5126, 'MAT4')
    doc = {'asset': {'version':'2.0', 'generator':'Original two-bone test fixture'},
           'buffers':[{'byteLength':len(blob)}], 'bufferViews':views, 'accessors':accessors,
           'nodes':[
               {'name':'origin_helper','translation':[2,0,0],'children':[1,4]},
               {'name':'root','children':[2]},
               {'name':'elbow_helper','translation':[0,3,0],'children':[3]},
               {'name':'tip','translation':[0,0,4]},
               {'name':'mesh','mesh':0,'skin':0,'translation':[17,19,23]}],
           'skins':[{'joints':[3,1],'inverseBindMatrices':inverse,'skeleton':1}],
           'meshes':[{'primitives':[{'attributes':attrs,'indices':indices}]}],
           'scenes':[{'nodes':[0]}], 'scene':0}
    j = json.dumps(doc,separators=(',',':')).encode()
    j += b' ' * ((-len(j)) % 4)
    blob.extend(b'\0' * ((-len(blob)) % 4))
    glb = struct.pack('<4sII',b'glTF',2,12+8+len(j)+8+len(blob))
    glb += struct.pack('<II',len(j),0x4e4f534a)+j+struct.pack('<II',len(blob),0x004e4942)+blob
    p = bytearray(struct.pack('<I',2))
    for name,parent,rest,bind in [('tip',1,matrix(0,3,4),binds[0]),('root',-1,matrix(2,0,0),binds[1])]:
        name=name.encode(); p.extend(struct.pack('<H',len(name))+name+struct.pack('<i32f',parent,*rest,*bind))
    p.extend(struct.pack('<I6fIIIII',1,1.,1.,1.,1.,1.,1.,0,0,0,3,3))
    for pos,uv in zip(positions,[(0.,0.),(1.,0.),(0.,1.)]):
        p.extend(struct.pack('<8f8H8f',*pos,0.,0.,1.,*uv,0,1,0,0,0,0,0,0,.75,.25,0.,0.,0.,0.,0.,0.))
    p.extend(struct.pack('<III',0,1,2))
    vrs = struct.pack('<8sIIII',b'VRSKIN02',2,len(p),zlib.crc32(p),0)+p
    return glb, vrs


if __name__ == '__main__':
    target = Path(__file__).resolve().parent.parent / 'tests' / 'fixtures'
    target.mkdir(parents=True,exist_ok=True)
    glb,vrs = build()
    (target/'two_bone_triangle.glb').write_bytes(glb)
    (target/'two_bone_triangle.vrs').write_bytes(vrs)
    print(f'Wrote original fixture: {len(glb)} GLB bytes, {len(vrs)} VRS bytes')
