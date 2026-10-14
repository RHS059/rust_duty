#!/usr/bin/env python3
"""Blender 4.3.2 isolated paired prone export; no rendering or source saves.

Use a fresh background Blender process with --factory-startup --disable-autoexec.
Both source Actions stay active during a single global-scene FBX bake. Historical
five-take authoring exporters and their frozen identities are never modified.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prone_camera_pair as pair_contract
import vrpack
from vrpack import require

SCHEMA = 'rust-duty-prone-paired-export/v1'
RECEIPT_SCHEMA = 'rust-duty-prone-paired-fbx/v1'
RIG_ACTION = pair_contract.RIG_ACTION
CAMERA_ACTION = pair_contract.CAMERA_ACTION


def read_json(data):
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=vrpack._no_duplicate_keys,
                          parse_constant=vrpack._bad_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise vrpack.AssetError(f'invalid paired export JSON: {exc}') from exc


def validate_config(config):
    require(isinstance(config, dict), 'paired export config must be an object')
    fixed = {
        'schema': SCHEMA, 'status': 'diagnostic_wip', 'blender_version': '4.3.2',
        'source_fps': 60, 'bake_hz': 480, 'candidate_frames': [1, 69],
        'native_crop': [0, 68], 'candidate_frame_offset': 1, 'imported_frame_offset': 1,
        'source_take': RIG_ACTION, 'runtime_clip': RIG_ACTION,
        'loop': False, 'hold_after_end': True,
        'armature': 'Arms', 'camera': 'RD First Person Review',
        'base_action': 'RD_00_Supplied_Base_Guarded_Recovered',
        'skin_objects': ['Actual arms mesh 0', 'Actual arms mesh 1', 'Actual arms mesh 2'],
        'rigid_actors': ['hk416_weapon', 'hk416_magazine'], 'deform_bone_count': 72,
    }
    for key, value in fixed.items():
        require(type(config.get(key)) is type(value) and
                json.dumps(config[key], sort_keys=True) == json.dumps(value, sort_keys=True),
                f'paired export config mismatch: {key}')
    require(set(config) == set(fixed) | {'source_contract_commit', 'source_sha256',
            'camera_sidecar_sha256', 'action_fingerprints', 'action_count'},
            'unknown or missing paired export config fields')
    commit = config['source_contract_commit']
    require(isinstance(commit, str) and len(commit) == 40 and
            all(c in '0123456789abcdef' for c in commit), 'invalid source contract commit')
    for name in ('source_sha256', 'camera_sidecar_sha256'):
        pair_contract.sha256(config[name], name)
    fingerprints = config['action_fingerprints']
    require(isinstance(fingerprints, dict) and set(fingerprints) == {RIG_ACTION, CAMERA_ACTION},
            'both exact paired Action identities are required')
    for name, value in fingerprints.items():
        pair_contract.sha256(value, name + ' fingerprint')
    require(type(config['action_count']) is int and config['action_count'] >= 114,
            'explicit complete candidate Action count is required')
    return config


def validate_inputs(config, source_sha256, action_fingerprints, sidecar_bytes):
    validate_config(config)
    require(source_sha256 == config['source_sha256'], 'candidate source hash mismatch')
    require(action_fingerprints == config['action_fingerprints'], 'source Action fingerprint mismatch')
    return pair_contract.load_camera_pair(
        sidecar_bytes, expected_sidecar_sha256=config['camera_sidecar_sha256'],
        candidate_sha256=source_sha256, action_fingerprints=action_fingerprints,
        native_start=0, native_end=68, fps=Fraction(60), candidate_frame_offset=1,
        frames=[Fraction(i, 8) for i in range(545)])


@lru_cache(maxsize=2)
def initial_camera(sidecar_bytes):
    return pair_contract.rigid_matrix(read_json(sidecar_bytes)['initial_camera_world'])


def validate_evaluated_sample(pair, candidate_frame, camera_world, rig_world, initial_rig_world):
    frame = Fraction(candidate_frame)
    delta = pair.delta_at(frame - 1)
    initial = initial_camera(pair.sidecar_bytes)
    expected_camera = vrpack.matmul(delta, initial)
    camera = pair_contract.rigid_matrix(camera_world)
    require(max(abs(a-b) for a, b in zip(camera, expected_camera)) <= 1e-5,
            'evaluated camera differs from paired sidecar')
    pair_contract.verify_armature_motion(rig_world, delta, initial_rig_world)
    return pair_contract.remove_common_motion(rig_world, delta)


def preflight_paths(source, output_dir):
    source = Path(source).resolve()
    output = Path(output_dir).resolve()
    require(source.is_file(), 'candidate source must be an existing file')
    require(source.suffix.lower() == '.blend', 'candidate source must be a BLEND')
    require(not output.exists(), 'output directory already exists; refuse overwrite')
    require(output != source and output not in source.parents, 'output collides with source')
    return source, output


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def action_fingerprint(action):
    # Exact source_integrity.py curve-record convention, not an FBX Action hash.
    records = [(curve.data_path, curve.array_index, [
        (list(key.co), list(key.handle_left), list(key.handle_right), key.interpolation)
        for key in curve.keyframe_points]) for curve in action.fcurves]
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def export_settings(config, output_fbx):
    validate_config(config)
    return dict(filepath=str(output_fbx), use_selection=True, object_types={'ARMATURE', 'MESH'},
        axis_forward='-Z', axis_up='Y', global_scale=1.0, apply_unit_scale=True,
        apply_scale_options='FBX_SCALE_UNITS', use_space_transform=True, bake_space_transform=False,
        use_mesh_modifiers=True, mesh_smooth_type='OFF', use_triangles=True,
        add_leaf_bones=False, primary_bone_axis='Y', secondary_bone_axis='X',
        use_armature_deform_only=True, armature_nodetype='NULL', bake_anim=True,
        bake_anim_use_all_bones=True, bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True, bake_anim_step=0.125, bake_anim_simplify_factor=0.,
        path_mode='COPY', embed_textures=True, use_metadata=False)


def flat(matrix):
    return tuple(float(v) for row in matrix for v in row)


def set_frame(bpy, frame):
    frame = float(frame)
    bpy.context.scene.frame_set(math.floor(frame), subframe=frame-math.floor(frame))
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    return deps


@contextmanager
def bound_pair(bpy, config):
    """Temporary bindings only; restore in-memory scene even when export fails."""
    scene = bpy.context.scene
    rig = bpy.data.objects[config['armature']]
    camera = bpy.data.objects[config['camera']]
    props = ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale')
    state = {o.name: {k: list(getattr(o, k)) for k in props} for o in bpy.data.objects}
    poses = {b.name: {k: list(getattr(b, k)) for k in props} for b in rig.pose.bones}
    custom = {b.name: {k: v for k, v in b.items() if isinstance(v, (int, float, str))}
              for b in rig.pose.bones}
    anim = {o.name: None if o.animation_data is None else
            (o.animation_data.action, o.animation_data.use_nla,
             [(t, t.mute, t.is_solo) for t in o.animation_data.nla_tracks]) for o in bpy.data.objects}
    fields = ('name', 'frame_start', 'frame_end', 'camera')
    saved = {k: getattr(scene, k) for k in fields}
    frame, subframe = scene.frame_current, scene.frame_subframe
    fps, fps_base = scene.render.fps, scene.render.fps_base
    selected = [(o, o.select_get(), o.hide_get()) for o in bpy.context.view_layer.objects]
    active = bpy.context.view_layer.objects.active
    images = [(im, im.filepath_raw) for im in bpy.data.images]
    try:
        for obj in bpy.data.objects:
            if obj.animation_data:
                obj.animation_data.use_nla = False
                for track in obj.animation_data.nla_tracks:
                    track.mute = True
                    track.is_solo = False
        rig.animation_data_create()
        rig.animation_data.action = bpy.data.actions[config['base_action']]
        set_frame(bpy, 1)
        rig.animation_data.action = bpy.data.actions[RIG_ACTION]
        camera.animation_data_create()
        camera.animation_data.action = bpy.data.actions[CAMERA_ACTION]
        scene.name = config['source_take']
        require(scene.name == config['source_take'], 'source take scene name collision')
        scene.camera = camera
        scene.frame_start, scene.frame_end = 1, 69
        scene.render.fps, scene.render.fps_base = 60, 1
        set_frame(bpy, 1)
        yield rig, camera
    finally:
        for name, old in anim.items():
            obj = bpy.data.objects[name]
            if old is None:
                obj.animation_data_clear()
            else:
                obj.animation_data.action, obj.animation_data.use_nla = old[:2]
                for track, mute, solo in old[2]:
                    track.mute, track.is_solo = mute, solo
        for bone in rig.pose.bones:
            for key, value in poses[bone.name].items():
                setattr(bone, key, value)
            for key, value in custom[bone.name].items():
                bone[key] = value
        for name, values in state.items():
            for key, value in values.items():
                setattr(bpy.data.objects[name], key, value)
        for key, value in saved.items():
            setattr(scene, key, value)
        scene.render.fps, scene.render.fps_base = fps, fps_base
        for obj, selection, hidden in selected:
            obj.hide_set(hidden)
            obj.select_set(selection)
        bpy.context.view_layer.objects.active = active
        for im, path in images:
            im.filepath_raw = path
        scene.frame_set(frame, subframe=subframe)
        bpy.context.view_layer.update()


def export(args):
    import bpy
    require(bpy.app.version_string == '4.3.2', 'paired export requires Blender 4.3.2')
    require(bpy.app.background and '--factory-startup' in sys.argv and '--disable-autoexec' in sys.argv,
            'use a fresh background process with --factory-startup --disable-autoexec')
    config_bytes = vrpack.read_limited(args.config)
    config = validate_config(read_json(config_bytes))
    source, output = preflight_paths(bpy.data.filepath, args.output_dir)
    source_args = [i for i, value in enumerate(sys.argv)
                   if value.lower().endswith('.blend') and Path(value).resolve() == source]
    require(len(source_args) == 1 and sys.argv.index('--disable-autoexec') < source_args[0]
            and sys.argv.index('--factory-startup') < source_args[0],
            'factory startup and disabled autoexec must precede the candidate BLEND argument')
    source_hash = file_hash(source)
    require(len(bpy.data.actions) == config['action_count'], 'candidate Action count mismatch')
    actions_before = {a.name: action_fingerprint(a) for a in bpy.data.actions}
    require({RIG_ACTION, CAMERA_ACTION, config['base_action']} <= set(actions_before),
            'missing required paired/base Action')
    pair = validate_inputs(config, source_hash,
        {name: actions_before[name] for name in (RIG_ACTION, CAMERA_ACTION)},
        vrpack.read_limited(args.sidecar))
    names = [config['armature']] + config['skin_objects'] + config['rigid_actors']
    require(all(name in bpy.context.scene.objects for name in names + [config['camera']]),
            'required export object missing from active scene')
    require(bpy.data.objects[config['armature']].type == 'ARMATURE' and
            bpy.data.objects[config['camera']].type == 'CAMERA' and
            all(bpy.data.objects[n].type == 'MESH' for n in names[1:]), 'wrong export object types')
    rig = bpy.data.objects[config['armature']]
    require(rig.data.pose_position == 'POSE', 'candidate armature must be in pose mode')
    require(all(any(m.type == 'ARMATURE' and m.object == rig
                    for m in bpy.data.objects[n].modifiers) for n in config['skin_objects']),
            'declared skin must retain its armature binding')
    require(all(not any(m.type == 'ARMATURE' for m in bpy.data.objects[n].modifiers)
                for n in config['rigid_actors']),
            'rigid actor has an Armature modifier; FBX would omit object animation')
    deform = [bone.name for bone in rig.data.bones if bone.use_deform]
    require(len(deform) == config['deform_bone_count'], 'deform bone count mismatch')
    require(bpy.context.mode == 'OBJECT', 'source must open in object mode')
    require(all(not obj.animation_data or not obj.animation_data.use_tweak_mode
                for obj in bpy.data.objects), 'NLA tweak mode is unsupported')
    settings = export_settings(config, output/'prone_pair.fbx')
    # No filesystem output exists until every identity and source-type check passes.
    output.mkdir(parents=True, exist_ok=False)
    oracle_rows = []
    with bound_pair(bpy, config) as (rig, camera):
        deps = set_frame(bpy, 1)
        initial_rig = flat(rig.evaluated_get(deps).matrix_world)
        for index in range(545):
            frame = Fraction(1) + Fraction(index, 8)
            require(rig.animation_data.action.name == RIG_ACTION and
                    camera.animation_data.action.name == CAMERA_ACTION,
                    'paired Actions must remain bound throughout sampling')
            deps = set_frame(bpy, frame)
            evaluated = rig.evaluated_get(deps)
            validate_evaluated_sample(pair, frame, flat(camera.evaluated_get(deps).matrix_world),
                                      flat(evaluated.matrix_world), initial_rig)
            delta = pair.delta_at(frame-1)
            # Local private witness of evaluated source output before basis conversion.
            bones = [pair_contract.remove_common_motion(
                flat(evaluated.matrix_world @ evaluated.pose.bones[n].matrix), delta) for n in deform]
            actors = [pair_contract.remove_common_motion(
                flat(bpy.data.objects[n].evaluated_get(deps).matrix_world), delta)
                for n in config['rigid_actors']]
            oracle_rows.append({'candidate_frame': float(frame), 'bones': bones, 'actors': actors})
            require(all(fc.driver.is_valid for obj in bpy.data.objects if obj.animation_data
                        for fc in obj.animation_data.drivers), 'invalid source driver')
        set_frame(bpy, 1)  # Canonical initial object world for static FBX bind geometry.
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        for name in names:
            obj = bpy.data.objects[name]
            obj.hide_set(False)
            obj.select_set(True)
        bpy.context.view_layer.objects.active = rig
        texture_dir = output/'textures'
        texture_dir.mkdir()
        for index, im in enumerate(bpy.data.images):
            if im.packed_file:
                path = texture_dir/f'packed_{index:03}.png'
                path.write_bytes(bytes(im.packed_file.data))
                im.filepath_raw = str(path)
        require(bpy.ops.export_scene.fbx(**settings) == {'FINISHED'}, 'FBX export did not finish')
    require(actions_before == {a.name: action_fingerprint(a) for a in bpy.data.actions},
            'source Actions changed during export')
    require(file_hash(source) == source_hash, 'source file bytes changed during export')
    (output/'camera_motion_samples.json').write_bytes(pair.sidecar_bytes)
    (output/'export_config.json').write_bytes(config_bytes)
    oracle = {'schema': 'rust-duty-prone-paired-source-oracle/v1',
              'space': 'Blender world; common motion removed once; no axis conversion',
              'deform_bones': deform, 'actors': config['rigid_actors'], 'rows': oracle_rows}
    (output/'source_oracle.json').write_text(json.dumps(oracle, separators=(',', ':'))+'\n')
    receipt = {'schema': RECEIPT_SCHEMA, 'status': 'diagnostic_wip',
        'config': config, 'source_unchanged': True, 'actions_unchanged': True,
        'paired_samples_checked': 545, 'source_take': config['source_take'],
        'fbx_time_policy': 'global scene; absolute source frames 1..69, not zero-based NLA',
        'common_motion_in_fbx': 'intended preserved; actual reimported object track not yet verified',
        'common_motion_removed': False, 'fbx_round_trip_verified': False,
        'measured_source_sha256': source_hash,
        'measured_action_fingerprints': {n: actions_before[n] for n in (RIG_ACTION, CAMERA_ACTION)},
        'export_settings': {k: sorted(v) if isinstance(v, set) else v for k, v in settings.items()},
        'files': {name: file_hash(output/name) for name in ('prone_pair.fbx',
                  'camera_motion_samples.json', 'export_config.json', 'source_oracle.json')},
        'runtime_import_performed': False, 'artistic_approval': False}
    receipt['export_settings']['filepath'] = 'prone_pair.fbx'
    (output/'export_receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--sidecar', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    argv = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    export(parser.parse_args(argv))


if __name__ == '__main__':
    main()
