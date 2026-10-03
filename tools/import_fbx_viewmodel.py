#!/usr/bin/env python3
"""Blender 4.3.2: FBX-authoritative, explicitly cropped WIP animation conversion.

GLB is a static geometry transport only. Animation comes directly from evaluated
FBX transforms at declared rational sample times. No Actions are selected by name
or inferred as approved from their extent. Source files are never overwritten.
"""
from __future__ import annotations
import argparse
from fractions import Fraction
import hashlib
import inspect
import json
import math
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vrpack
import vrskin
import vrview
from vrpack import require


def sample_grid(start, end, subdivisions=64, switches=()):
    """Explicit rational resampling, not deduplication of FBX key timestamps.

    Each declared switch adds 1/65536-native-frame pre/post witnesses. Float32
    serialization must retain every chosen time; collisions fail conversion.
    The finite transition interval is disclosed and must pass independent parity.
    """
    require(type(start) is int and type(end) is int and 0 <= start <= end, 'invalid crop')
    require(type(subdivisions) is int and 1 <= subdivisions <= 1024, 'invalid subdivisions')
    values = {Fraction(i, subdivisions) for i in range(start*subdivisions, end*subdivisions+1)}
    for value in switches:
        t = Fraction(str(value))
        require(start < t < end, 'switch must be inside crop')
        values.update((t-Fraction(1,65536), t, t+Fraction(1,65536)))
    frames = sorted(values)
    times = [vrpack.f32(float((f-start)*Fraction(1001,60000))) for f in frames]
    require(all(b > a for a,b in zip(times,times[1:])), 'chosen rational samples collide as float32; change format/policy explicitly')
    return frames, times


def rigid_transform(matrix):
    """All-zero scale is the FBX visibility sentinel, never a visible identity."""
    hidden = max(abs(matrix[r*4+c]) for r in range(3) for c in range(3)) < 1e-10
    return vrview.decompose(vrpack.IDENTITY if hidden else matrix), int(not hidden)


def patch_importer():
    import bpy
    import io_scene_fbx.import_fbx as imp
    require(bpy.app.version[:3] == (4,3,2), 'FBX importer patches audited only for Blender 4.3.2')
    originals = {}
    for name, before, after in (
        ('blen_read_animations', 'cnodes, scene.render.fps, anim_offset', 'cnodes, scene.render.fps / scene.render.fps_base, anim_offset'),
        ('blen_store_keyframes_multi', 'blen_fcurve.update()', 'pass # Preserve sorted dense FBX times; update merges neighboring keys'),
    ):
        fn = getattr(imp,name); source = inspect.getsource(fn)
        require(source.count(before) == 1, f'importer patch signature changed: {name}')
        originals[name] = {'sha256':hashlib.sha256(source.encode()).hexdigest(), 'replacement_count':1}
        exec(source.replace(before,after),imp.__dict__)
    return originals


def flat(matrix):
    return tuple(float(v) for row in matrix for v in row)


def convert(args):
    import bpy
    import numpy as np
    from mathutils import Matrix
    import export_viewmodel
    fbx = args.fbx.resolve()
    digest = hashlib.sha256(fbx.read_bytes()).hexdigest()
    require(digest == args.fbx_sha256, 'FBX hash differs from explicit input contract')
    require(not args.output.exists(), 'output directory already exists; use a new diagnostic destination')
    skeleton = vrview.decode_vra(args.skeleton_vra.read_bytes())['bones']
    keep = {name for name,_ in skeleton}
    frames,times = sample_grid(args.native_start,args.native_end,args.subdivisions,args.switch)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    patches = patch_importer()
    bpy.ops.import_scene.fbx(filepath=str(fbx),use_anim=True,anim_offset=0.,ignore_leaf_bones=False,
                            automatic_bone_orientation=False,use_prepost_rot=True)
    scene = bpy.context.scene; arm = bpy.data.objects[args.armature]
    require(abs(scene.render.fps/scene.render.fps_base-60000/1001)<1e-4, 'unexpected native FBX rate')
    require(keep <= set(arm.data.bones.keys()), 'canonical skeleton bones missing from FBX')
    for name,parent in skeleton:
        bone = arm.data.bones[name]
        actual = bone.parent.name if bone.parent else None
        require(actual == (skeleton[parent][0] if parent>=0 else None), f'canonical parent differs for {name}; never drop a deform parent')
    skins = [o for o in scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==arm for m in o.modifiers)]
    actors = [bpy.data.objects[n] for n in args.actor]
    require(skins and actors, 'need skin meshes and explicit rigid actors')
    action_ranges=[{'name':a.name,'frame_range':list(a.frame_range)} for a in bpy.data.actions]
    weights = {}
    for obj in skins:
        rows = [[(obj.vertex_groups[g.group].name,g.weight) for g in v.groups if g.weight>0] for v in obj.data.vertices]
        require(all(n in keep for row in rows for n,w in row), f'weighted noncanonical bone in {obj.name}')
        maximum = max(map(len,rows)); require(maximum<=8, 'runtime cannot preserve more than eight influences')
        weights[obj.name] = {'vertices':len(rows),'maximum_influences':maximum,'vertices_over_four':sum(len(r)>4 for r in rows)}
    # Blender Z-up to glTF Y-up once. Joint local basis remains Blender
    # (matching glTF inverse binds); rigid mesh coordinates are converted too.
    basis = Matrix(((1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))
    inv_basis = basis.inverted()
    bone_names = [b[0] for b in skeleton]
    raw_bones = np.empty((len(frames),len(skeleton),4,4),dtype=np.float64)
    raw_actors = np.empty((len(frames),len(actors),4,4),dtype=np.float64)
    for i,native in enumerate(frames):
        f=float(native)+1; scene.frame_set(math.floor(f),subframe=f-math.floor(f)); arm.update_tag();bpy.context.view_layer.update()
        dg=bpy.context.evaluated_depsgraph_get(); ae=arm.evaluated_get(dg)
        raw_bones[i]=[basis @ ae.matrix_world @ ae.pose.bones[n].matrix for n in bone_names]
        raw_actors[i]=[basis @ o.evaluated_get(dg).matrix_world @ inv_basis for o in actors]
        if i%512==0: print('FBX_SAMPLE',i,len(frames),flush=True)
    # Freeze geometry independently. Prune only unweighted helpers outside the
    # explicitly verified canonical parent closure; no deform rest is altered.
    rest = {n:flat(arm.matrix_world@arm.data.bones[n].matrix_local) for n in bone_names}
    actor_rest = {o.name:Matrix.Identity(4) for o in actors}
    for obj in scene.objects:
        obj.animation_data_clear()
    arm.data.pose_position='REST'
    for obj in actors:
        obj.parent=None; obj.matrix_world=actor_rest[obj.name]
    bpy.context.view_layer.objects.active=arm
    bpy.ops.object.select_all(action='DESELECT');arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for bone in list(arm.data.edit_bones):
        if bone.name not in keep: arm.data.edit_bones.remove(bone)
    bpy.ops.object.mode_set(mode='OBJECT')
    require(all(max(abs(a-b) for a,b in zip(rest[n],flat(arm.matrix_world@arm.data.bones[n].matrix_local)))<1e-6 for n in keep), 'rest changed during helper pruning')
    for obj in skins+actors+[arm]: obj.hide_set(False);obj.select_set(True)
    args.output.mkdir(parents=True)
    if args.material_source:
        require(hashlib.sha256(args.material_source.read_bytes()).hexdigest()==args.source_sha256, 'material source hash mismatch')
        slots={o.name:[m.name if m else None for m in o.data.materials] for o in skins+actors}
        wanted=sorted({n for names in slots.values() for n in names if n})
        with bpy.data.libraries.load(str(args.material_source.resolve()),link=False) as (available,loaded):
            require(set(wanted)<=set(available.materials),'FBX material missing in canonical source')
            loaded.materials=list(wanted)
        restored=dict(zip(wanted,loaded.materials))
        for obj in skins+actors:
            for i,name in enumerate(slots[obj.name]):
                if name:obj.data.materials[i]=restored[name]
    geometry_path=args.output/'geometry-only.glb'
    export_viewmodel.export_glb(bpy,geometry_path,animation=False)
    doc,blob=vrpack.parse_glb(geometry_path.read_bytes())
    require(not doc.get('animations'), 'geometry intermediate unexpectedly contains animation')
    geometry=vrview.Scene(doc,blob,armature=arm.name,base_color_only=True,single_sided_materials=True)
    vrs,vrm,actor_defs=geometry.companions(args.actor)
    output_bones=geometry.skin.bones
    require({b[0] for b in output_bones}==keep, 'geometry bone selection changed')
    for name in keep:
        expected=basis @ arm.matrix_world @ arm.data.bones[name].matrix_local
        actual=geometry.rest_globals[geometry.node_named(name)]
        require(max(abs(a-b) for a,b in zip(flat(expected),actual))<1e-5, f'joint basis/rest mismatch: {name}')
    # Reindex by names. Animation locals are derived from evaluated global
    # transforms rather than FK channels or omitted mechanism parents.
    order=[bone_names.index(b[0]) for b in output_bones]
    encoded=[]
    for i,t in enumerate(times):
        globals_=[tuple(raw_bones[i,j].flat) for j in order]
        locals_=[vrpack.matmul(vrview.inverse(globals_[b[1]]),g) if b[1]>=0 else g for b,g in zip(output_bones,globals_)]
        actor_values=[]; visible=[]
        for m in raw_actors[i]:
            value, mask=rigid_transform(tuple(m.flat))
            visible.append(mask); actor_values.append(value)
        encoded.append({'time':t,'bones':[vrview.decompose(m) for m in locals_],
                        'actors':actor_values,'visible':visible})
    vra=vrview.encode_vra(output_bones,actor_defs,[{'name':args.name,'loop':False,'frames':encoded}],vrs,vrm)
    for suffix,data in [('vrs',vrs),('vrm',vrm),('vra',vra)]: (args.output/f'asset.{suffix}').write_bytes(data)
    manifest={'schema':'rust-duty-fbx-segment-diagnostic/v1','status':'diagnostic',
      'source_fbx_sha256':digest,'authoring_master_sha256':args.source_sha256,
      'native_crop':[args.native_start,args.native_end],'native_fps':[60000,1001],
      'timing_policy':{'kind':'explicit-rational-resampling','subdivisions':args.subdivisions,'switches':args.switch,
                       'switch_neighbor_offset_native':[1,65536],'float32_collision_policy':'reject','samples':len(frames)},
      'bones':len(output_bones),'actors':args.actor,'weights':weights,'importer_patches':patches,
      'source_action_ranges':action_ranges, 'visibility_policy':'all-zero rigid scale maps to invisible STEP with identity placeholder; partial singular scale rejected', 'geometry_transport':'static GLB only; no sampled GLB animation', 'material_source_sha256':args.source_sha256 if args.material_source else None,
      'files':{f'asset.{s}':{'sha256':hashlib.sha256(d).hexdigest(),'bytes':len(d)} for s,d in [('vrs',vrs),('vrm',vrm),('vra',vra)]},
      'scope':'Explicitly selected source range converted as WIP. Review scope is recorded in the source-selection manifest. No runtime parity or gameplay visual approval is implied.'}
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('fbx','output','skeleton-vra'):p.add_argument('--'+flag,type=Path,required=True)
    for flag in ('fbx-sha256','source-sha256','name'):p.add_argument('--'+flag,required=True)
    p.add_argument('--material-source',type=Path);p.add_argument('--armature',default='Arms');p.add_argument('--actor',action='append',required=True)
    p.add_argument('--native-start',type=int,required=True);p.add_argument('--native-end',type=int,required=True)
    p.add_argument('--subdivisions',type=int,default=64);p.add_argument('--switch',action='append',default=[])
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    convert(p.parse_args(argv))

if __name__=='__main__':main()
