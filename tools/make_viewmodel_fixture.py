#!/usr/bin/env python3
"""Build an original two-armature Blender/NLA fixture and independent pose oracle.
Run: blender -b --factory-startup --python tools/make_viewmodel_fixture.py -- --out /tmp/viewmodel
No private assets, runtime-authored animation, or source reconstruction is used.
"""
import argparse
import json
import math
import sys
from pathlib import Path


def main():
    import bpy
    from mathutils import Matrix, Vector
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--rigid-skin-weapon', action='store_true', help='Export gun through a one-bone rigid skin, matching the clean private master')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 60; scene.render.fps_base = 1.0
    scene.frame_start = 1; scene.frame_end = 13
    scene.unit_settings.system = 'METRIC'; scene.unit_settings.scale_length = 1.0
    data = bpy.data.armatures.new('Original fixture skeleton')
    rig = bpy.data.objects.new('Fixture Master', data)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig; rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, head, tail, parent=None, deform=True):
        b = data.edit_bones.new(name); b.head = head; b.tail = tail
        b.use_deform = deform
        if parent: b.parent = data.edit_bones[parent]
        return b
    bone('arms_root', (0, 0, 0), (0, 0, .2))
    for side, sign in [('l', 1), ('r', -1)]:
        shoulder = (.45*sign, 0, 1.3)
        elbow = (.52*sign, -.35, 1.14)
        wrist = (.22*sign, -.66, 1.04)
        bone('upperarm_'+side, shoulder, elbow, 'arms_root')
        bone('lowerarm_'+side, elbow, wrist, 'upperarm_'+side)
        bone('hand_'+side, wrist, (.22*sign, -.80, 1.04), 'lowerarm_'+side)
    bpy.ops.object.mode_set(mode='OBJECT')
    weapondata = bpy.data.armatures.new('Original weapon controls')
    weaponrig = bpy.data.objects.new('Fixture Weapon Rig', weapondata)
    scene.collection.objects.link(weaponrig); weaponrig.parent = rig
    rig.select_set(False); weaponrig.select_set(True); bpy.context.view_layer.objects.active = weaponrig
    bpy.ops.object.mode_set(mode='EDIT')
    weaponbone = weapondata.edit_bones.new('weapon'); weaponbone.head=(0,-.66,1.04); weaponbone.tail=(0,-.46,1.04)
    for side in ['l', 'r']:
        source = data.bones['hand_'+side]
        target = weapondata.edit_bones.new(side+'_hand_weapon_ik')
        target.matrix = source.matrix_local.copy(); target.length=source.length
        target.parent=weaponbone; target.use_deform=False
    bpy.ops.object.mode_set(mode='OBJECT')
    for side in ['l', 'r']:
        key = side+'_hand_weapon_ik_influence'; rig[key] = 1.0
        lower = rig.pose.bones['lowerarm_'+side]
        ik = lower.constraints.new('IK'); ik.name = 'Original independent '+side+' IK'
        ik.target = weaponrig; ik.subtarget = side+'_hand_weapon_ik'; ik.chain_count = 2
        ik.use_stretch = False
        lower.ik_stretch = 0.0; rig.pose.bones['upperarm_'+side].ik_stretch = 0.0
        orient = rig.pose.bones['hand_'+side].constraints.new('COPY_ROTATION')
        orient.target = weaponrig; orient.subtarget = side+'_hand_weapon_ik'
        orient.owner_space = 'WORLD'; orient.target_space = 'WORLD'
        for c in (ik, orient):
            driver = c.driver_add('influence').driver
            driver.type = 'SCRIPTED'; variable = driver.variables.new(); variable.name = 'amount'
            variable.targets[0].id = rig; variable.targets[0].data_path = '["'+key+'"]'
            driver.expression = 'min(1,max(0,amount))'
    # Independent triangles with weighted deformation and no shared vertices:
    # every evaluated source vertex can be checked against the runtime mesh.
    points = []; faces = []; weights = []
    for side, sign in [('l', 1), ('r', -1)]:
        for segment, names in enumerate([
            [('upperarm_'+side, 1.0)],
            [('upperarm_'+side, .35), ('lowerarm_'+side, .65)],
            [('lowerarm_'+side, .25), ('hand_'+side, .75)],
        ]):
            b = data.bones[['upperarm_', 'lowerarm_', 'hand_'][segment]+side]
            center = b.head_local.lerp(b.tail_local, .5)
            start = len(points)
            for delta in [Vector((-.035, 0, -.015)), Vector((.035, 0, -.015)), Vector((0, 0, .04))]:
                points.append(tuple(center+delta)); weights.append(names)
            faces.append((start, start+1, start+2))
    mesh = bpy.data.meshes.new('Original weighted triangles')
    mesh.from_pydata(points, [], faces); mesh.update()
    skin = bpy.data.objects.new('Fixture Skin', mesh); scene.collection.objects.link(skin)
    skin.parent = rig
    groups = {b.name: skin.vertex_groups.new(name=b.name) for b in data.bones if b.use_deform}
    for i, entries in enumerate(weights):
        for name, weight in entries: groups[name].add([i], weight, 'REPLACE')
    mod = skin.modifiers.new('Original skin', 'ARMATURE'); mod.object = rig
    material = bpy.data.materials.new('Original neutral matte'); material.use_nodes = True
    material.use_backface_culling = True
    material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.35, .5, .7, 1)
    material.node_tree.nodes['Principled BSDF'].inputs['Metallic'].default_value = 0
    material.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = .8
    mesh.materials.append(material)
    # Gun geometry is deliberately longitudinal along Blender -Y.
    gunmesh = bpy.data.meshes.new('Original rigid gun triangles')
    gunmesh.from_pydata([(-.05, 0, 0), (.05, 0, 0), (0, -.7, .025)], [], [(0, 1, 2)]); gunmesh.update()
    gunmesh.materials.append(material)
    gun = bpy.data.objects.new('Fixture Gun', gunmesh); scene.collection.objects.link(gun)
    if args.rigid_skin_weapon:
        for vertex in gunmesh.vertices: vertex.co += Vector((0,-.66,1.04))
        gun.parent=weaponrig
        gun.vertex_groups.new(name='weapon').add(list(range(len(gunmesh.vertices))),1.,'REPLACE')
        gunmod=gun.modifiers.new('Original rigid weapon skin','ARMATURE'); gunmod.object=weaponrig
    else:
        gun.parent=rig
        follow=gun.constraints.new('COPY_TRANSFORMS'); follow.target=weaponrig; follow.subtarget='weapon'
        follow.owner_space='WORLD'; follow.target_space='WORLD'
    for owner in (rig,weaponrig):
        for b in owner.pose.bones: b.rotation_mode='QUATERNION'
        owner.animation_data_create()
    tracks = {}
    def reset():
        rig.location = (0, 0, 0); rig.rotation_euler = (0, 0, 0); rig.scale = (1, 1, 1)
        for owner in (rig,weaponrig):
            for b in owner.pose.bones:
                b.location=(0,0,0); b.rotation_quaternion=(1,0,0,0); b.scale=(1,1,1)
            for t in owner.animation_data.nla_tracks: t.mute=True
            owner.animation_data.action=None
        rig['l_hand_weapon_ik_influence'] = 1.0; rig['r_hand_weapon_ik_influence'] = 1.0
        for t in rig.animation_data.nla_tracks: t.mute = True
        rig.animation_data.action = None
    for clip, side, sign in [('left_release', 'l', 1), ('right_release', 'r', -1)]:
        reset(); action = bpy.data.actions.new(clip+'_authored_in_Blender')
        rig.animation_data.action = action
        weaponaction=bpy.data.actions.new(clip+'_weapon_authored_in_Blender')
        weaponrig.animation_data.action=weaponaction
        for frame, influence in [(1, 1), (4, .5), (7, 0), (10, .5), (13, 1)]:
            phase = (frame-1)/12
            rig['l_hand_weapon_ik_influence'] = float(influence if side == 'l' else 1)
            rig['r_hand_weapon_ik_influence'] = float(influence if side == 'r' else 1)
            for s in ['l', 'r']: rig.keyframe_insert(data_path='["'+s+'_hand_weapon_ik_influence"]', frame=frame)
            rig.location = (.025*sign*phase, .012*phase, .015*phase)
            rig.keyframe_insert(data_path='location', frame=frame)
            weapon = weaponrig.pose.bones['weapon']
            weapon.location = (.045*sign*phase, -.025*phase, .028*phase)
            weapon.rotation_quaternion = __import__('mathutils').Quaternion((0, 0, 1), sign*.18*phase)
            weapon.keyframe_insert(data_path='location', frame=frame)
            weapon.keyframe_insert(data_path='rotation_quaternion', frame=frame)
            for s in ['l', 'r']:
                for part, angle in [('upperarm_', .45), ('lowerarm_', -.3), ('hand_', .35)]:
                    pb = rig.pose.bones[part+s]
                    amount = math.sin(math.pi*phase) if s == side else 0
                    pb.rotation_quaternion = __import__('mathutils').Quaternion((0, 0, 1), angle*sign*amount)
                    pb.keyframe_insert(data_path='rotation_quaternion', frame=frame)
        for act in (action,weaponaction):
            for curve in act.fcurves:
                for keyframe in curve.keyframe_points: keyframe.interpolation='LINEAR'
        rig.animation_data.action = None
        track = rig.animation_data.nla_tracks.new(); track.name = clip
        strip = track.strips.new(clip, 1, action); strip.blend_type = 'REPLACE'; strip.extrapolation = 'NOTHING'
        track.mute=True
        weaponrig.animation_data.action=None
        weapontrack=weaponrig.animation_data.nla_tracks.new(); weapontrack.name=clip
        weaponstrip=weapontrack.strips.new(clip,1,weaponaction); weaponstrip.blend_type='REPLACE'; weaponstrip.extrapolation='NOTHING'
        weapontrack.mute=True; tracks[clip]=(track,weapontrack)
    reset(); scene.frame_set(1); bpy.context.view_layer.update()
    registry = {'schema':'rust-duty-viewmodel-export/v1','armature':rig.name,
                'export_objects':[rig.name,weaponrig.name,skin.name,gun.name],
                'clips':[{'name':'neutral','frame_start':1,'frame_end':1,'loop':False,'tracks':{}},
                         *[{'name':name,'frame_start':1,'frame_end':13,'loop':False,'tracks':{rig.name:[name],weaponrig.name:[name]}} for name in tracks]]}
    if args.rigid_skin_weapon: registry['rigid_armatures']=[weaponrig.name]
    (out/'fixture-registry.json').write_text(json.dumps(registry, indent=2)+'\n')
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'fixture.blend'))
    basis = Matrix(((1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))
    def cols(m): return [m[r][c] for c in range(4) for r in range(4)]
    def positions(obj, graph):
        evaluated = obj.evaluated_get(graph); evaluated_mesh = evaluated.to_mesh()
        result = [list(basis @ (evaluated.matrix_world @ v.co)) for v in evaluated_mesh.vertices]
        evaluated.to_mesh_clear(); return result
    oracle = {'schema':'original-blender-viewmodel-oracle/v1','basis':'gltf-y-up',
              'axis':{'blender_forward':[0,-1,0],'game_forward':[0,0,-1],'blender_up':[0,0,1],'game_up':[0,1,0]},
              'samples':[]}
    for clip in registry['clips']:
        reset()
        for name in clip['tracks'].get(rig.name, []):
            for t in tracks[name]: t.mute=False
        frames = [1.] if clip['name']=='neutral' else sorted(set([float(i) for i in range(1,14)]+[1.5,3.5,6.5,9.5,12.5]))
        for frame in frames:
            scene.frame_set(math.floor(frame), subframe=frame%1); bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get(); evaluated_rig = rig.evaluated_get(graph); evaluated_weapon=weaponrig.evaluated_get(graph)
            bones = [{'name':b.name,'global':cols(basis @ evaluated_rig.matrix_world @ b.matrix)} for b in evaluated_rig.pose.bones]
            errors={}
            for s in ['l','r']:
                hand = evaluated_rig.pose.bones['hand_'+s].matrix
                target = evaluated_rig.matrix_world.inverted() @ evaluated_weapon.matrix_world @ evaluated_weapon.pose.bones[s+'_hand_weapon_ik'].matrix
                errors[s]={'influence':float(rig[s+'_hand_weapon_ik_influence']),
                           'target_distance':(hand.translation-target.translation).length}
            oracle['samples'].append({'clip':clip['name'],'time':(frame-1)/60,'frame':frame,
                                      'bones':bones,'skin_positions':positions(skin,graph),
                                      'rigid_positions':positions(gun,graph),'constraints':errors})
    (out/'blender-oracle.json').write_text(json.dumps(oracle, indent=2)+'\n')
    print('ORIGINAL_VIEWMODEL_FIXTURE_READY',out)

if __name__=='__main__': main()
