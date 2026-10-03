"""Fresh on-disk BLEND fingerprints and non-mutating directional handoff checks.

Run with Blender 4.3.2 --background --factory-startup --disable-autoexec.
This inspects RNA/data, never executes embedded source text and never saves.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import bpy

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_integrity import snapshot, digest

EXPECTED = {'hip_walk_forward_r1', 'hip_walk_backward_r1', 'hip_strafe_left_r1', 'hip_strafe_right_r1'}

def atom(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, bpy.types.ID):
        return {'id_type': type(v).__name__, 'name': v.name}
    try:
        return [atom(x) for x in v]
    except TypeError:
        return str(v)

def props(obj):
    out = {}
    for p in obj.bl_rna.properties:
        k = p.identifier
        if k == 'rna_type' or p.type == 'COLLECTION' or p.is_readonly:
            continue
        try:
            out[k] = atom(getattr(obj, k))
        except (AttributeError, TypeError, ValueError):
            pass
    return out

def matrix(m):
    return [list(r) for r in m]

def extra_snapshot():
    meshes = {}
    for m in bpy.data.meshes:
        value = {
            'vertices': [list(v.co) for v in m.vertices],
            'edges': [list(e.vertices) for e in m.edges],
            'polygons': [{'vertices': list(p.vertices), 'material_index': p.material_index, 'use_smooth': p.use_smooth} for p in m.polygons],
            'uv': {l.name: [list(v.uv) for v in l.data] for l in m.uv_layers},
            'materials': [x.name if x else None for x in m.materials],
        }
        meshes[m.name] = {'sha256': digest(value), 'vertices': len(m.vertices), 'polygons': len(m.polygons)}
    armatures = {}
    for a in bpy.data.armatures:
        val = [{'name': b.name, 'parent': b.parent.name if b.parent else None, 'rest_matrix': matrix(b.matrix_local),
                'use_deform': b.use_deform, 'use_connect': b.use_connect, 'inherit_scale': b.inherit_scale,
                'head': list(b.head_local), 'tail': list(b.tail_local)} for b in a.bones]
        armatures[a.name] = {'sha256': digest(val), 'bones': len(val), 'deform_order': [b.name for b in a.bones if b.use_deform]}
    objects = {}
    for o in bpy.data.objects:
        v = {'type': o.type, 'data': o.data.name if o.data else None,
             'parent': o.parent.name if o.parent else None, 'parent_type': o.parent_type, 'parent_bone': o.parent_bone,
             'matrix_parent_inverse': matrix(o.matrix_parent_inverse),
             'modifiers': [{'type': m.type, 'props': props(m)} for m in o.modifiers],
             'constraints': [{'type': c.type, 'props': props(c)} for c in o.constraints],
             'vertex_groups': [g.name for g in o.vertex_groups]}
        if o.type == 'MESH':
            v['weights'] = [[(g.group, g.weight) for g in vert.groups] for vert in o.data.vertices]
        if o.pose:
            v['pose_constraints'] = {b.name: [{'type': c.type, 'props': props(c)} for c in b.constraints] for b in o.pose.bones}
        objects[o.name] = {'sha256': digest(v), 'type': o.type, 'data': v['data']}
    materials = {}
    for m in bpy.data.materials:
        val = {'diffuse_color': list(m.diffuse_color), 'use_nodes': m.use_nodes}
        if m.node_tree:
            val['nodes'] = [{'name': n.name, 'type': n.bl_idname, 'image': n.image.name if hasattr(n, 'image') and n.image else None,
                             'inputs': [(x.name, atom(x.default_value)) for x in n.inputs if hasattr(x, 'default_value')]} for n in m.node_tree.nodes]
            val['links'] = [(l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name) for l in m.node_tree.links]
        materials[m.name] = digest(val)
    actions_extended = {a.name: digest([{'data_path': f.data_path, 'index': f.array_index, 'extrapolation': f.extrapolation, 'mute': f.mute, 'modifiers': [props(m) for m in f.modifiers], 'key_handle_types': [(k.handle_left_type, k.handle_right_type, k.easing) for k in f.keyframe_points]} for f in a.fcurves]) for a in bpy.data.actions}
    pose_channels = {o.name: {b.name: {'rotation_mode': b.rotation_mode, 'location': list(b.location), 'rotation_euler': list(b.rotation_euler), 'rotation_quaternion': list(b.rotation_quaternion), 'rotation_axis_angle': list(b.rotation_axis_angle), 'scale': list(b.scale), 'custom_properties': {k: atom(b[k]) for k in b.keys() if k != '_RNA_UI'}} for b in o.pose.bones} for o in bpy.data.objects if o.pose}
    return {'pose_channel_defaults': pose_channels, 'actions_extended': actions_extended, 'meshes': meshes, 'armatures': armatures, 'objects_and_bindings': objects, 'materials': materials,
            'cameras': {c.name: digest(props(c)) for c in bpy.data.cameras}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--config', type=Path)
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    assert bpy.app.version_string == '4.3.2'
    before = hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()
    fresh = snapshot(bpy)
    extra = extra_snapshot()
    scene = bpy.context.scene
    scene.frame_set(scene.frame_current)
    bpy.context.view_layer.update()
    drivers = [d for o in bpy.data.objects if o.animation_data for d in o.animation_data.drivers]
    result = {'schema': 'rust-duty-directional-source-preservation/v1', 'blender': bpy.app.version_string,
              'source_bytes': Path(bpy.data.filepath).stat().st_size, 'source_sha256': before,
              'preserved': fresh, 'structural': extra,
              'driver_count': len(drivers), 'invalid_drivers': [d.data_path for d in drivers if not d.driver.is_valid],
              'action_count': len(bpy.data.actions), 'nla_track_count': sum(len(o.animation_data.nla_tracks) for o in bpy.data.objects if o.animation_data),
              'embedded_source_text_executed': False, 'source_saved': False}
    checks = {}
    if args.baseline:
        base = json.loads(args.baseline.read_text())
        checks['all_original_action_fingerprints_unchanged'] = all(fresh['actions'].get(k) == v for k, v in base['preserved']['actions'].items())
        checks['exactly_four_expected_new_actions'] = set(fresh['actions']) - set(base['preserved']['actions']) == EXPECTED
        checks['original_nla_tracks_and_active_state_unchanged'] = fresh['nla'] == base['preserved']['nla']
        checks['all_driver_definitions_unchanged'] = fresh['drivers'] == base['preserved']['drivers']
        checks['all_packed_images_unchanged'] = fresh['packed_images'] == base['preserved']['packed_images']
        for k in extra:
            checks[k + '_unchanged'] = (all(extra[k].get(n) == v for n, v in base['structural'][k].items()) if k == 'actions_extended' else extra[k] == base['structural'][k])
        checks['all_native_drivers_valid'] = not result['invalid_drivers']
        result['baseline_source_sha256'] = base['source_sha256']
    if args.config:
        c = json.loads(args.config.read_text())
        rig = bpy.data.objects[c['armature']]
        checks['deform_bone_count_72'] = len([b for b in rig.data.bones if b.use_deform]) == c['deform_bone_count'] == 72
        checks['three_skin_objects_exist'] = len(c['skin_objects']) == 3 and all(n in bpy.data.objects for n in c['skin_objects'])
        checks['two_bound_rigid_actors_exist'] = c['rigid_actors'] == ['hk416_weapon', 'hk416_magazine'] and all(n in bpy.data.objects for n in c['rigid_actors'])
        checks['source_rate_60_bake_480'] = c['source_fps'] == 60 and c['bake_hz'] == 480
        checks['four_actions_absolute_loop_pose'] = all(t['action'] in EXPECTED and t['pose_space'] == 'absolute' and t['additive'] is False and t['loop'] for t in c['source_takes'])
        result['clip_ranges'] = {}
        for t in c['source_takes']:
            a = bpy.data.actions[t['action']]
            row = {'range': list(a.frame_range), 'duration_seconds': (t['frame_end'] - t['frame_start']) / 60,
                   'fcurves': len(a.fcurves), 'keyed_bones': sorted({f.data_path.split('"')[1] for f in a.fcurves if f.data_path.startswith('pose.bones["')}),
                   'varying_bones': sorted({f.data_path.split('"')[1] for f in a.fcurves if f.data_path.startswith('pose.bones["') and len({round(k.co.y, 9) for k in f.keyframe_points}) > 1})}
            checks[t['name'] + '_source_range_matches'] = list(a.frame_range) == [t['frame_start'], t['frame_end']]
            checks[t['name'] + '_duration_matches'] = abs(row['duration_seconds'] - t['duration_seconds']) < 1e-9
            result['clip_ranges'][t['name']] = row
    checks['source_bytes_unchanged_by_validation'] = hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest() == before
    result['checks'] = checks
    result['passed'] = all(checks.values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'checks': checks, 'source_sha256': before, 'output': str(args.output)}, indent=2))
    if not result['passed']:
        raise RuntimeError('Directional source contract failed')

if __name__ == '__main__':
    main()
