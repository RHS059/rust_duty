#!/usr/bin/env python3
"""Compile evaluated Blender glTF clips to VRSKIN02 + VRMESH01 + VRANIM01.

Geometry helpers stay unchanged. All tracks are glTF Y-up; the runtime alone
applies Ry(pi). Animation is baked source data, never runtime IK or pose edits.
"""
from __future__ import annotations
import argparse
import bisect
import copy
import json
import math
from pathlib import Path
import struct
import sys
import zlib
import vrpack as core
import vrskin
from vrpack import AssetError, require, uint, number, objects, at, matmul

from collections import OrderedDict
from copy import deepcopy
import hashlib
from threading import RLock


class ValidationMemo:
    """Bounded in-process successes keyed by validator, mode and actual bytes.

    Retains small defensive-copied metadata only, never input/decoded arrays.
    New processes start empty: no older validator approval persists on disk.
    Paths, metadata, source identity and destination validation stay with callers.
    """
    def __init__(self, capacity=24):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("validation memo capacity must be positive")
        self.capacity = capacity
        self._entries = OrderedDict()
        self._lock = RLock()

    def validated(self, validator, *blobs, context=()):
        # Snapshot mutable buffers before hashing/validation. Byte inputs incur
        # no copy and no input blob is retained by the cache.
        if any(not isinstance(blob, (bytes, bytearray, memoryview)) for blob in blobs):
            raise TypeError("validation memo accepts byte buffers only")
        blobs = tuple(bytes(blob) for blob in blobs)
        key = (validator, context, tuple(
            (len(blob), hashlib.sha256(blob).digest()) for blob in blobs))
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return deepcopy(self._entries[key])
            # Insert only after the real validator returns successfully.
            result = validator(*blobs)
            self._entries[key] = deepcopy(result)
            self._entries.move_to_end(key)
            while len(self._entries) > self.capacity:
                self._entries.popitem(last=False)
            return result

    def clear(self):
        with self._lock:
            self._entries.clear()


validation_memo = ValidationMemo()


MAGIC = b'VRANIM01'
VERSION = 1
HEADER = struct.Struct('<8sIIII')
TRANSFORM = struct.Struct('<10f')
MAX_TRANSFORMS = 2_000_000
SCHEMA = 'rust-duty-viewmodel-export/v1'


def string(value, label='name', maximum=128):
    require(isinstance(value, str) and 1 <= len(value.encode('utf-8')) <= maximum and '\0' not in value,
            f'{label} must be 1..{maximum} UTF-8 bytes without NUL')
    return value


def inverse(m):
    """Invert a row-major affine matrix, rejecting singular matrices."""
    vrskin.matrix_valid(vrskin.transpose(m), 'affine matrix')
    n = core.normal_matrix(m)
    r = (n[0], n[3], n[6], 0, n[1], n[4], n[7], 0, n[2], n[5], n[8], 0, 0, 0, 0, 1)
    r = list(r)
    for i in range(3):
        r[4*i+3] = -sum(r[4*i+j] * m[4*j+3] for j in range(3))
    return tuple(r)


def validate_transform(trs):
    require(len(trs) == 10 and all(math.isfinite(v) for v in trs), 'non-finite or invalid TRS')
    require(all(abs(v) <= 10000 for v in trs[:3]), 'translation exceeds +/-10000')
    require(abs(math.hypot(*trs[3:7])-1) <= 1e-4, 'quaternion must be normalized within 1e-4')
    require(all(1e-8 < v <= 10000 for v in trs[7:]), 'scale must be positive, >1e-8 and <=10000')
    return tuple(trs[:3]) + core.normalized(trs[3:7], 'quaternion') + tuple(trs[7:])


def decompose(m):
    """TRS only: reject reflected/singular/sheared matrices instead of losing data."""
    vrskin.matrix_valid(vrskin.transpose(m), 'animated matrix')
    t = (m[3], m[7], m[11])
    s = tuple(math.hypot(*(m[r*4+c] for r in range(3))) for c in range(3))
    require(all(v > 1e-8 for v in s) and core.determinant(m) > 0, 'negative or singular animated scale')
    r = tuple(m[row*4+c]/s[c] for row in range(3) for c in range(3))
    require(all(abs(sum(r[k*3+i]*r[k*3+j] for k in range(3)) - (i == j)) <= 2e-5
                for i in range(3) for j in range(3)), 'animated transform contains shear')
    trace = r[0]+r[4]+r[8]
    if trace > 0:
        h = 2*math.sqrt(trace+1)
        q = ((r[7]-r[5])/h, (r[2]-r[6])/h, (r[3]-r[1])/h, h/4)
    else:
        i = max(range(3), key=lambda k: r[k*3+k]); j=(i+1)%3; k=(i+2)%3
        h = 2*math.sqrt(max(0, 1+r[i*3+i]-r[j*3+j]-r[k*3+k]))
        require(h > 0, 'invalid rotation matrix')
        v = [0.0]*4; v[i]=h/4; v[j]=(r[i*3+j]+r[j*3+i])/h
        v[k]=(r[i*3+k]+r[k*3+i])/h; v[3]=(r[k*3+j]-r[j*3+k])/h
        q = tuple(v)
    return validate_transform(t + core.normalized(q, 'rotation') + s)


def matrix(trs):
    return core.node_matrix({'translation': list(trs[:3]), 'rotation': list(trs[3:7]), 'scale': list(trs[7:])})


def slerp(a, b, factor):
    dot = sum(x*y for x,y in zip(a,b))
    if dot < 0: b=tuple(-v for v in b); dot=-dot
    dot = max(-1, min(1, dot))
    if dot > .9995:
        return core.normalized(tuple(x+(y-x)*factor for x,y in zip(a,b)), 'interpolated quaternion')
    theta=math.acos(dot); divisor=math.sin(theta)
    return tuple((math.sin((1-factor)*theta)*x+math.sin(factor*theta)*y)/divisor for x,y in zip(a,b))


def interpolate(a, b, factor):
    return tuple(x+(y-x)*factor for x,y in zip(a[:3],b[:3])) + slerp(a[3:7],b[3:7],factor) + tuple(x+(y-x)*factor for x,y in zip(a[7:],b[7:]))


class Scene:
    """A strict sampled glTF scene. Original node indices remain unchanged."""
    def __init__(self, doc, blob, *, base_color_only=False, single_sided_materials=False, armature=None, rigid_armatures=()):
        self.doc, self.blob = doc, blob
        core.reject_extensions(doc)
        source_nodes=objects(doc.get('nodes',[]),'nodes')
        skins=objects(doc.get('skins',[]),'skins'); require(skins,'at least one skin is required')
        # Ownership follows actual glTF ancestry, never hardcoded rig/bone names.
        direct_parents={}
        for i,node in enumerate(source_nodes):
            children=node.get('children',[]); require(isinstance(children,list),'node children must be an array')
            for child in children:
                at(source_nodes,child,'child node'); require(child not in direct_parents,'node has multiple parents')
                direct_parents[child]=i
        def belongs(skin_index,owner):
            matches=[i for i,n in enumerate(source_nodes) if n.get('name')==owner]
            require(len(matches)==1,f'armature name must be unique in glTF: {owner}')
            joints=skins[skin_index].get('joints')
            require(isinstance(joints,list) and joints,'skin has no joints')
            for joint in joints:
                at(source_nodes,joint,'skin joint'); current=joint; seen=set()
                while current!=matches[0] and current in direct_parents:
                    require(current not in seen,'cycle in skin ancestry'); seen.add(current); current=direct_parents[current]
                if current!=matches[0]: return False
            return True
        named=[i for i,s in enumerate(skins) if s.get('name')==armature] if armature else []
        primary=named or ([i for i in range(len(skins)) if belongs(i,armature)] if armature else list(range(len(skins))))
        require(len(primary)==1,'deform armature must identify exactly one skin')
        self.primary_skin=primary[0]; self.rigid_skins={}
        require(isinstance(rigid_armatures,(list,tuple)) and all(isinstance(n,str) for n in rigid_armatures) and len(set(rigid_armatures))==len(rigid_armatures),'invalid rigid_armatures')
        for i,skin in enumerate(skins):
            if i==self.primary_skin: continue
            if not any(n.get('skin')==i for n in source_nodes): continue
            require(any(belongs(i,owner) for owner in rigid_armatures),'extra skin requires explicit rigid_armatures authorization')
            require(isinstance(skin.get('joints'),list) and 1<=len(skin['joints'])<=128,'rigid skin joint count outside 1..128')
            self.rigid_skins[i]=skin
        sanitized = copy.deepcopy(doc)
        self.warnings=[]
        if single_sided_materials:
            for index,material in enumerate(objects(sanitized.get('materials',[]),'materials')):
                if material.get('doubleSided') is True:
                    material['doubleSided']=False
                    self.warnings.append(f'SINGLE-SIDED-MATERIALS: material {index} {material.get("name", "<unnamed>")}: doubleSided omitted')
        sanitized.pop('animations', None); sanitized['skins']=[copy.deepcopy(skins[self.primary_skin])]
        for node in objects(sanitized.get('nodes', []), 'nodes'):
            if 'skin' in node:
                at(skins,node['skin'],'node skin')
                if node['skin']==self.primary_skin: node['skin']=0
                else: node.pop('mesh',None); node.pop('skin')
            else: node.pop('mesh',None)
        self.skin = vrskin.Converter(sanitized, blob, base_color_only=base_color_only)
        self.vrs = self.skin.convert()
        self.parents, self.rest_globals, self.rest_locals = self.skin.hierarchy()
        self.nodes = objects(doc.get('nodes', []), 'nodes')
        self.joints = self.skin.skin['joints']
        self.joint_map = {n:i for i,n in enumerate(self.joints)}
        self.names = {}
        for idx in self.parents:
            name = self.nodes[idx].get('name')
            if name is not None:
                require(isinstance(name,str), 'node name must be a string')
                self.names.setdefault(name, []).append(idx)
        # A separate validation view retains sanitized materials from the skin
        # helper and removes skin attributes only when compiling rigid meshes.
        geom = copy.deepcopy(self.skin.doc)
        geom.pop('skins', None)
        for n in geom['nodes']: n.pop('skin', None)
        self.geometry = core.Converter(self._materials(geom, base_color_only), blob)
        self.rigid_bindings={}
        for skin_index,skin in self.rigid_skins.items():
            joints=skin['joints']; weighted=set(); nodes=[]
            require(len(set(joints))==len(joints),'duplicate rigid skin joints')
            require(all(type(j) is int and j in self.parents for j in joints),'rigid skin joints must be in selected scene')
            binds=self.skin.skin_accessor(skin['inverseBindMatrices'],'inverseBindMatrices') if 'inverseBindMatrices' in skin else [core.IDENTITY]*len(joints)
            require(len(binds)==len(joints),'rigid inverse bind count mismatch')
            for bind in binds: vrskin.matrix_valid(bind,'rigid inverse bind')
            for idx,node in enumerate(self.nodes):
                if node.get('skin')!=skin_index: continue
                require(idx in self.parents,'rigid skin must be in selected scene'); nodes.append(idx)
                mesh=at(self.skin.meshes,node.get('mesh'),'rigid skin mesh')
                for primitive in objects(mesh.get('primitives',[]),'rigid primitives'):
                    # The unchanged skin validator checks all eight indices,
                    # vertex counts and finite weights before rigid conversion.
                    self.skin.skin_primitive(primitive,len(joints))
                    attrs=primitive['attributes']
                    js=self.skin.skin_accessor(attrs['JOINTS_0'],'JOINTS_0')
                    ws=self.skin.skin_accessor(attrs['WEIGHTS_0'],'WEIGHTS_0')
                    if 'JOINTS_1' in attrs:
                        js=[a+b for a,b in zip(js,self.skin.skin_accessor(attrs['JOINTS_1'],'JOINTS_1'))]
                        ws=[a+b for a,b in zip(ws,self.skin.skin_accessor(attrs['WEIGHTS_1'],'WEIGHTS_1'))]
                    require(all(abs(sum(row)-1)<=1e-4 for row in ws),'rigid skin weights must sum to one')
                    weighted.update(j for jr,wr in zip(js,ws) for j,w in zip(jr,wr) if w>0)
            require(len(weighted)==1,'rigid skin must have exactly one positively weighted joint across all meshes')
            joint_index=next(iter(weighted))
            for idx in nodes: self.rigid_bindings[idx]=(joints[joint_index],vrskin.transpose(binds[joint_index]))
        self.channels = {}
        self.parse_animation()

    @staticmethod
    def _materials(doc, base_color_only):
        if base_color_only:
            for m in doc.get('materials', []):
                m.pop('normalTexture',None); m.pop('occlusionTexture',None)
                m.get('pbrMetallicRoughness',{}).pop('metallicRoughnessTexture',None)
            for s in doc.get('samplers',[]):
                if s.get('minFilter') in (9985,9987): s['minFilter']=9729
        return doc

    def node_named(self, name):
        string(name, 'actor name')
        matches = self.names.get(name, [])
        require(len(matches) == 1, f'node name must identify exactly one exported node: {name}')
        return matches[0]

    def accessor(self, index, kind):
        acc = at(self.skin.accessors, index, 'animation accessor')
        require(acc.get('componentType') == 5126 and acc.get('type') == kind and acc.get('normalized',False) is False,
                f'animation accessor requires unnormalized FLOAT {kind}')
        require('sparse' not in acc, 'sparse animation accessors are unsupported')
        n = {'SCALAR':1,'VEC3':3,'VEC4':4}[kind]
        count = uint(acc.get('count'),'animation accessor count',65536)
        require(count > 0, 'empty animation accessor')
        view, base, length = self.skin.view(acc.get('bufferView'))
        require('byteStride' not in view, 'animation accessors must be tightly packed')
        offset = uint(acc.get('byteOffset',0),'animation byte offset')
        require((base+offset)%4 == 0 and offset%4 == 0, 'unaligned animation accessor')
        require(offset <= length and count*n*4 <= length-offset, 'animation accessor exceeds bufferView')
        rows = [struct.unpack_from('<'+'f'*n,self.blob,base+offset+i*n*4) for i in range(count)]
        require(all(math.isfinite(x) for row in rows for x in row), 'non-finite animation accessor')
        return rows

    def parse_animation(self):
        animations = objects(self.doc.get('animations',[]),'animations')
        require(len(animations) <= 1, 'each GLB must contain one independently baked SCENE animation')
        if not animations: return
        samplers = objects(animations[0].get('samplers',[]),'animation samplers')
        channels = objects(animations[0].get('channels',[]),'animation channels')
        require(channels and len(channels) <= len(self.parents)*3, 'empty or excessive animation channels')
        used=set()
        for channel in channels:
            target=channel.get('target'); require(isinstance(target,dict),'animation target must be an object')
            idx=uint(target.get('node'),'animation target node'); path=target.get('path')
            require(idx in self.parents, 'animation targets node outside selected scene')
            require(path in ('translation','rotation','scale'),'only evaluated TRS animation is supported')
            require('matrix' not in self.nodes[idx], 'animated nodes must use TRS, not matrix')
            require((idx,path) not in self.channels, 'duplicate animation channel')
            sampler_index=uint(channel.get('sampler'),'animation sampler')
            sampler=at(samplers,sampler_index,'animation sampler'); used.add(sampler_index)
            mode=sampler.get('interpolation','LINEAR')
            require(mode in ('LINEAR','STEP'), 'animation must be baked LINEAR/STEP, not cubic')
            times=[r[0] for r in self.accessor(sampler.get('input'),'SCALAR')]
            require(times[0] >= 0 and all(b>a for a,b in zip(times,times[1:])), 'animation times must be nonnegative and strictly increasing')
            values=self.accessor(sampler.get('output'),'VEC4' if path=='rotation' else 'VEC3')
            require(len(times)==len(values),'animation input/output count mismatch')
            if path=='rotation':
                require(all(abs(math.hypot(*v)-1)<=1e-4 for v in values),'animation quaternion must be normalized')
                values=[core.normalized(v,'animation rotation') for v in values]
            elif path=='scale': require(all(1e-8<x<=10000 for v in values for x in v),'invalid animation scale')
            else: require(all(abs(x)<=10000 for v in values for x in v),'animation translation exceeds bounds')
            self.channels[idx,path]=(times,values,mode)
        require(used==set(range(len(samplers))), 'unreferenced animation sampler')

    def sample(self, time):
        locals_={}
        for idx in self.parents:
            node=self.nodes[idx]
            if not any((idx,p) in self.channels for p in ('translation','rotation','scale')):
                locals_[idx]=self.rest_locals[idx]; continue
            values={p:node.get(p,d) for p,d in [('translation',[0,0,0]),('rotation',[0,0,0,1]),('scale',[1,1,1])]}
            for path in values:
                if (idx,path) not in self.channels: continue
                times,rows,mode=self.channels[idx,path]
                i=max(0,bisect.bisect_right(times,time)-1)
                if i==len(times)-1 or time<=times[0] or mode=='STEP': value=rows[i]
                else:
                    f=(time-times[i])/(times[i+1]-times[i])
                    value=slerp(rows[i],rows[i+1],f) if path=='rotation' else tuple(a+(b-a)*f for a,b in zip(rows[i],rows[i+1]))
                values[path]=list(value)
            locals_[idx]=core.node_matrix(values)
        globals_={}
        for idx,parent in self.parents.items():
            globals_[idx]=matmul(globals_[parent],locals_[idx]) if parent!=-1 else locals_[idx]
        bones=[]
        for idx in self.joints:
            local=locals_[idx]; parent=self.parents[idx]
            while parent!=-1 and parent not in self.joint_map:
                local=matmul(locals_[parent],local); parent=self.parents[parent]
            bones.append(decompose(local))
        return bones, globals_

    def rigid_signature(self, name):
        """Compare local geometry/materials, separate from animated placement."""
        idx=self.node_named(name); node=self.nodes[idx]
        binding=self.rigid_bindings.get(idx)
        result=[]
        if 'mesh' in node:
            validator=core.Converter(self.geometry.doc,self.blob)
            mesh=at(validator.meshes,node['mesh'],'actor mesh')
            for primitive in objects(mesh.get('primitives',[]),'actor primitives'):
                if binding:
                    primitive=dict(primitive)
                    primitive['attributes']={k:v for k,v in primitive['attributes'].items() if k in ('POSITION','NORMAL','TEXCOORD_0')}
                result.append(validator.primitive(primitive,core.IDENTITY))
        return result, (self.nodes[binding[0]].get('name'),binding[1]) if binding else None

    def actor_node(self, idx):
        return self.rigid_bindings[idx][0] if idx in self.rigid_bindings else idx

    def companions(self, actor_names):
        actors=[]; meshes=[]; assigned=set()
        for name in actor_names:
            idx=self.node_named(name); node=self.nodes[idx]
            require(idx not in self.joint_map and ('skin' not in node or idx in self.rigid_bindings),'actors cannot be deform joints or deform-skinned meshes')
            require(idx not in assigned,'duplicate actor node'); assigned.add(idx)
            bound=[]
            if 'mesh' in node:
                mesh=at(self.geometry.meshes,node['mesh'],'actor mesh')
                primitives=objects(mesh.get('primitives',[]),'actor primitives')
                require(primitives, 'actor mesh has no primitives')
                for primitive in primitives:
                    require(len(meshes)<core.MAX_MESHES,'too many rigid primitives')
                    bound.append(len(meshes))
                    world=self.rest_globals[idx]
                    if idx in self.rigid_bindings:
                        joint,bind=self.rigid_bindings[idx]
                        attrs=primitive.get('attributes',{})
                        world=matmul(self.rest_globals[joint],bind)
                        primitive=dict(primitive)
                        primitive['attributes']={k:v for k,v in attrs.items() if k in ('POSITION','NORMAL','TEXCOORD_0')}
                    meshes.append(self.geometry.primitive(primitive,world))
            animated_idx=self.actor_node(idx)
            actors.append({'name':name,'meshes':bound,'inverse_rest_global':vrskin.transpose(inverse(self.rest_globals[animated_idx]))})
        require(all(i in assigned for i in self.parents if 'mesh' in self.nodes[i] and ('skin' not in self.nodes[i] or i in self.rigid_bindings)),
                'every rigid mesh node must be assigned to an actor')
        require(meshes, 'VRMESH01 requires at least one rigid mesh')
        return self.vrs,core.encode_vrm(meshes),actors


def encode_vra(bones, actors, clips, vrs, vrm):
    require(1<=len(bones)<=128 and len(actors)<=256 and 1<=len(clips)<=128,'invalid animation set counts')
    total=0
    for clip in clips:
        frames=clip.get('frames',[]); require(1<=len(frames)<=65536,'invalid frame count')
        total+=len(frames)*(len(bones)+len(actors)); require(total<=MAX_TRANSFORMS,'aggregate transform budget exceeded')
        require(type(clip.get('loop')) is bool,'clip loop must be boolean')
        for frame in frames:
            require(len(frame['bones'])==len(bones) and len(frame['actors'])==len(actors) and len(frame['visible'])==len(actors),'frame channel count mismatch')
            require(all(type(v) is int and v in (0,1) for v in frame['visible']),'invalid visibility')
    payload=bytearray(struct.pack('<III',zlib.crc32(vrs),zlib.crc32(vrm),len(bones)))
    def name(s):
        raw=string(s).encode(); payload.extend(struct.pack('<H',len(raw))); payload.extend(raw)
    for b in bones: name(b[0]); payload.extend(struct.pack('<i',b[1]))
    payload.extend(struct.pack('<I',len(actors)))
    for actor in actors:
        name(actor['name']); meshes=actor['meshes']
        payload.extend(struct.pack('<I',len(meshes)))
        for i in meshes: payload.extend(struct.pack('<I',i))
        payload.extend(struct.pack('<16f',*actor['inverse_rest_global']))
    payload.extend(struct.pack('<I',len(clips)))
    for clip in clips:
        name(clip['name']); frames=clip['frames']
        payload.extend(struct.pack('<II',int(clip['loop']),len(frames)))
        for frame in frames:
            payload.extend(struct.pack('<f',frame['time']))
            for value in frame['bones']+frame['actors']: payload.extend(TRANSFORM.pack(*validate_transform(value)))
            payload.extend(bytes(frame['visible']))
            require(len(payload)+HEADER.size<=core.MAX_FILE,'VRA exceeds 128 MiB')
    result=HEADER.pack(MAGIC,VERSION,len(payload),zlib.crc32(payload),0)+payload
    decode_vra(result,vrs=vrs,vrm=vrm)
    return result


def decode_vra(data, *, vrs=None, vrm=None):
    require(HEADER.size<=len(data)<=core.MAX_FILE,'VRA truncated or exceeds 128 MiB')
    magic,version,length,checksum,reserved=HEADER.unpack_from(data)
    require(magic==MAGIC and version==VERSION,'invalid VRA magic/version')
    require(reserved==0 and length==len(data)-HEADER.size,'invalid VRA header')
    payload=memoryview(data)[HEADER.size:]; require(zlib.crc32(payload)==checksum,'VRA checksum mismatch')
    cursor=0
    def take(n):
        nonlocal cursor
        require(0<=n<=len(payload)-cursor,'truncated VRA payload')
        result=payload[cursor:cursor+n]; cursor+=n; return result
    def unpack(fmt): return struct.unpack(fmt,take(struct.calcsize(fmt)))
    def name():
        n,=unpack('<H'); require(1<=n<=128,'invalid VRA string length')
        try: return string(bytes(take(n)).decode('utf-8'))
        except UnicodeDecodeError as exc: raise AssetError('invalid VRA UTF-8') from exc
    skin_crc,mesh_crc,bc=unpack('<III'); require(1<=bc<=128,'bone count outside 1..128')
    bones=[(name(),unpack('<i')[0]) for _ in range(bc)]; vrskin.validate_parents([b[1] for b in bones])
    ac,=unpack('<I'); require(ac<=256,'actor count exceeds 256')
    actors=[]; actor_names=set(); assigned=set()
    for _ in range(ac):
        n=name(); require(n not in actor_names,'duplicate actor name'); actor_names.add(n)
        count,=unpack('<I'); require(count<=256,'too many actor meshes'); meshes=[]
        for _ in range(count):
            i,=unpack('<I'); require(i<256 and i not in assigned,'invalid or duplicate actor mesh assignment')
            assigned.add(i); meshes.append(i)
        inv=unpack('<16f'); vrskin.matrix_valid(inv,'actor inverse rest global')
        actors.append({'name':n,'meshes':meshes,'inverse_rest_global':inv})
    cc,=unpack('<I'); require(1<=cc<=128,'clip count outside 1..128')
    clips=[]; names=set(); total=0
    for _ in range(cc):
        n=name(); require(n not in names,'duplicate clip name'); names.add(n)
        flags,fc=unpack('<II'); require(flags<=1 and 1<=fc<=65536,'invalid clip flags/frame count')
        total+=fc*(bc+ac); require(total<=MAX_TRANSFORMS,'aggregate transform budget exceeded')
        require(fc*(4+(bc+ac)*40+ac)<=len(payload)-cursor,'truncated animation frames')
        frames=[]; previous=-1
        for i in range(fc):
            t,=unpack('<f'); require(math.isfinite(t) and (t==0 if i==0 else t>previous),'invalid frame times'); previous=t
            values=[validate_transform(unpack('<10f')) for _ in range(bc+ac)]
            visible=list(take(ac)); require(all(v in (0,1) for v in visible),'invalid visibility')
            frames.append({'time':t,'bones':values[:bc],'actors':values[bc:],'visible':visible})
        clips.append({'name':n,'loop':bool(flags),'frames':frames})
    require(cursor==len(payload),'trailing VRA payload bytes')
    if vrs is not None:
        validation_memo.validated(vrskin.inspect_vrs, vrs); require(zlib.crc32(vrs)==skin_crc,'VRS companion checksum mismatch')
        p=28; actual=[]; count=struct.unpack_from('<I',vrs,24)[0]
        for _ in range(count):
            size=struct.unpack_from('<H',vrs,p)[0]; p+=2
            n=vrs[p:p+size].decode(); p+=size; parent=struct.unpack_from('<i',vrs,p)[0]; p+=132; actual.append((n,parent))
        require(actual==bones,'VRS companion skeleton mismatch')
    if vrm is not None:
        info=validation_memo.validated(core.inspect_vrm, vrm); require(zlib.crc32(vrm)==mesh_crc,'VRM companion checksum mismatch')
        require(assigned==set(range(info['meshes'])),'rigid companion meshes must be assigned exactly once')
    return {'bones':bones,'actors':actors,'clips':clips,'skin_crc':skin_crc,'mesh_crc':mesh_crc}


def _clip_summary(data, vrs, vrm):
    pack = decode_vra(data, vrs=vrs, vrm=vrm)
    return [{'name': clip['name'], 'loop': clip['loop'],
             'frame_count': len(clip['frames']),
             'duration': clip['frames'][-1]['time']} for clip in pack['clips']]


def validated_clip_summary(data, *, vrs, vrm):
    """Run the full decoder once per exact byte triple in this process.

    All binary checks still use decode_vra; only its small immutable facts are
    reused. Caller metadata/source checks deliberately remain outside the memo.
    Validator identities also invalidate results in test/instrumentation runs.
    """
    return validation_memo.validated(_clip_summary, data, vrs, vrm,
        context=(decode_vra, vrskin.inspect_vrs, core.inspect_vrm))


def sample(pack, clip_name, time, *, clamp=False):
    clips=[c for c in pack['clips'] if c['name']==clip_name]; require(len(clips)==1,'unknown clip')
    clip=clips[0]; frames=clip['frames']; duration=frames[-1]['time']; time=core.f32(number(time,'sample time'))
    time=(time%duration) if clip['loop'] and duration>0 and not clamp else max(0,min(time,duration))
    i=max(0,bisect.bisect_right([f['time'] for f in frames],time)-1); a=frames[i]
    if i==len(frames)-1: return copy.deepcopy(a)
    b=frames[i+1]; t=(time-a['time'])/(b['time']-a['time'])
    return {'time':time,'bones':[interpolate(x,y,t) for x,y in zip(a['bones'],b['bones'])],
            'actors':[interpolate(x,y,t) for x,y in zip(a['actors'],b['actors'])],'visible':list(a['visible'])}


def read_json(path):
    try: return json.loads(core.read_limited(path).decode('utf-8'),object_pairs_hook=core._no_duplicate_keys,parse_constant=core._bad_constant)
    except (ValueError,UnicodeDecodeError) as exc: raise AssetError(f'invalid manifest: {exc}') from exc


def compile_manifest(manifest_path, output_prefix=None, *, base_color_only=False, single_sided_materials=False, force=False):
    manifest_path=Path(manifest_path); manifest=read_json(manifest_path)
    require(isinstance(manifest,dict) and manifest.get('schema')==SCHEMA,'invalid export manifest schema')
    def load(path):
        require(isinstance(path,str) and path,'GLB path must be a nonempty string')
        return Scene(*core.parse_glb(core.read_limited(manifest_path.parent/path)),base_color_only=base_color_only,single_sided_materials=single_sided_materials,armature=manifest.get('armature'),rigid_armatures=manifest.get('rigid_armatures',[]))
    rest=load(manifest.get('rest_glb')); names=manifest.get('actors')
    require(isinstance(names,list) and len(names)<=256,'actors must be an array with at most 256 names')
    for warning in rest.warnings+rest.skin.warnings: print(warning,file=sys.stderr)
    vrs,vrm,actors=rest.companions(names); clips=[]; total=0
    rest_rigid=[rest.rigid_signature(a['name']) for a in actors]
    specifications=objects(manifest.get('clips'),'clips'); require(1<=len(specifications)<=128,'need 1..128 clips')
    for spec in specifications:
        name=string(spec.get('name'),'clip name'); require(type(spec.get('loop')) is bool,'clip loop must be boolean')
        scene=load(spec.get('path'))
        require([(b[0],b[1]) for b in scene.skin.bones]==[(b[0],b[1]) for b in rest.skin.bones],'clip skeleton does not match rest skeleton')
        for a,b in zip(scene.skin.bones,rest.skin.bones):
            require(max(abs(x-y) for x,y in zip(a[3],b[3]))<=2e-5,'clip inverse binds differ from authoritative rest export')
        require(scene.skin.output_meshes==rest.skin.output_meshes,'clip changes deform geometry/materials; runtime mesh companions are immutable')
        for actor,expected in zip(actors,rest_rigid):
            actual=scene.rigid_signature(actor['name'])
            require(actual[0]==expected[0],'clip changes rigid geometry/materials; runtime mesh companions are immutable')
            if actual[1] is None or expected[1] is None:
                require(actual[1]==expected[1],'clip changes rigid skin binding')
            else:
                require(actual[1][0]==expected[1][0] and max(abs(x-y) for x,y in zip(actual[1][1],expected[1][1]))<=2e-5,'clip changes rigid joint/inverse bind')
        times=spec.get('times'); require(isinstance(times,list) and 1<=len(times)<=65536,'clip times need 1..65536 samples')
        times=[core.f32(number(t,'sample time')) for t in times]
        require(times[0]==0 and all(b>a for a,b in zip(times,times[1:])),'clip times must start at zero and strictly increase')
        total+=len(times)*(len(rest.joints)+len(actors)); require(total<=MAX_TRANSFORMS,'aggregate transform budget exceeded')
        duration=times[-1]
        for ts,_,_ in scene.channels.values():
            require(abs(ts[0])<=2e-5 and abs(ts[-1]-duration)<=max(2e-5,duration*2e-6), 'baked channels must cover complete normalized clip range')
        require(scene.channels or len(times)==1,'animated clip has no sampled channels')
        visibility=spec.get('visibility',[[1]*len(actors) for _ in times])
        require(isinstance(visibility,list) and len(visibility)==len(times),'visibility frame count mismatch')
        indices=[scene.actor_node(scene.node_named(a['name'])) for a in actors]; frames=[]
        for time,visible in zip(times,visibility):
            require(isinstance(visible,list) and len(visible)==len(actors) and all(type(v) is int and v in (0,1) for v in visible),'invalid visibility samples')
            bones,globals_=scene.sample(time)
            frames.append({'time':time,'bones':bones,'actors':[decompose(globals_[i]) for i in indices],'visible':visible})
        clips.append({'name':name,'loop':spec['loop'],'frames':frames})
    vra=encode_vra(rest.skin.bones,actors,clips,vrs,vrm)
    if output_prefix is not None:
        prefix=Path(output_prefix); outputs=[(prefix.with_suffix(e),d) for e,d in [('.vrs',vrs),('.vrm',vrm),('.vra',vra)]]
        require(all(force or not p.exists() for p,_ in outputs),'output already exists; use --force')
        for p,d in outputs: core.atomic_write(p,d,force)
    return vrs,vrm,vra


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); commands=parser.add_subparsers(dest='command',required=True)
    pack=commands.add_parser('pack'); pack.add_argument('manifest',type=Path); pack.add_argument('output_prefix',type=Path)
    pack.add_argument('--base-color-only',action='store_true'); pack.add_argument('--single-sided-materials',action='store_true'); pack.add_argument('--force',action='store_true')
    inspect=commands.add_parser('inspect'); inspect.add_argument('input',type=Path)
    inspect.add_argument('--skin',type=Path); inspect.add_argument('--mesh',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command=='pack':
            vrs,vrm,vra=compile_manifest(args.manifest,args.output_prefix,base_color_only=args.base_color_only,single_sided_materials=args.single_sided_materials,force=args.force)
            result=decode_vra(vra,vrs=vrs,vrm=vrm)
        else: result=decode_vra(core.read_limited(args.input),vrs=core.read_limited(args.skin) if args.skin else None,vrm=core.read_limited(args.mesh) if args.mesh else None)
        print(json.dumps({'format':MAGIC.decode(),'bones':len(result['bones']),'actors':len(result['actors']),
                          'clips':[{'name':c['name'],'frames':len(c['frames']),'duration':c['frames'][-1]['time'],'loop':c['loop']} for c in result['clips']]},indent=2))
        return 0
    except (AssetError,OSError,OverflowError,RecursionError,struct.error,UnicodeEncodeError) as exc:
        print(f'vrview: {exc}',file=sys.stderr); return 1


if __name__=='__main__': sys.exit(main())
