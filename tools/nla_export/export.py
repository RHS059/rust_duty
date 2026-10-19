"""Export one evaluated FBX per explicitly mapped NLA track; never save the BLEND.

blender --background --disable-autoexec --python-exit-code 1 \
  --python tools/nla_export/export.py -- --source path.blend --output directory
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import SOURCE, validate


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def animation_owners(scene):
    """Object and object-data animation, including camera lens animation."""
    seen = set()
    for obj in scene.objects:
        for owner in (obj, obj.data, getattr(obj.data, 'shape_keys', None)):
            if owner is not None and owner.as_pointer() not in seen:
                seen.add(owner.as_pointer())
                if getattr(owner, 'animation_data', None):
                    yield owner


def prepare(bpy, clip):
    scene = bpy.data.scenes[clip['scene']]
    bpy.context.window.scene = scene
    rig = scene.objects[clip['rig']]
    if rig.type != 'ARMATURE':
        raise ValueError('Configured rig is not an armature: ' + rig.name)
    track = rig.animation_data.nla_tracks.get(clip['track_name']) if rig.animation_data else None
    if track is None or not track.strips:
        raise ValueError('Missing/nonanimated rig NLA track: ' + clip['track_name'])
    if clip['frame_start'] < min(s.frame_start for s in track.strips) or clip['frame_end'] > max(s.frame_end for s in track.strips):
        raise ValueError('Declared export range exceeds rig NLA track: ' + clip['id'])
    camera = scene.objects.get(clip.get('camera', ''))
    if clip.get('camera') and (camera is None or camera.type != 'CAMERA'):
        raise ValueError('Missing configured camera: ' + clip['id'])
    camera_track = clip.get('camera_track_name')
    if camera_track and (not camera.animation_data or not camera.animation_data.nla_tracks.get(camera_track)):
        raise ValueError('Missing paired camera NLA track: ' + camera_track)
    for owner in animation_owners(scene):
        data = owner.animation_data
        data.action = None
        data.use_nla = True
        for nla in data.nla_tracks:
            nla.is_solo = False
            nla.mute = not (nla.name == clip['track_name'] or (camera is not None and owner in (camera, camera.data) and nla.name == camera_track))
    scene.render.fps = int(clip['fps'])
    scene.render.fps_base = clip.get('fps_base', 1.0)
    scene.frame_start = int(clip['frame_start'])
    scene.frame_end = int(clip['frame_end'])
    if camera:
        scene.camera = camera
    names = clip.get('objects')
    selected = [scene.objects[name] for name in names] if names else [o for o in scene.objects if o.type in {'MESH', 'EMPTY', 'ARMATURE'}]
    if rig not in selected:
        raise ValueError('Explicit export objects must include the rig')
    if any(o.type == 'ARMATURE' and o != rig for o in selected):
        raise ValueError('Multiple rigs in scene: configure explicit objects for ' + clip['id'])
    if camera and camera not in selected:
        selected.append(camera)
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in selected:
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.select_set(True)
    bpy.context.view_layer.objects.active = rig
    scene.frame_set(int(clip['frame_start']))
    bpy.context.view_layer.update()
    # With strip/all-action enumeration off, FBX bakes exactly the evaluated scene.
    # Its sole take uses the scene name; temporary rename is never saved to source.
    old_name = bpy.data.scenes.get(clip['id'])
    if old_name and old_name != scene:
        old_name.name = '__unused_export_scene__'
    scene.name = clip['id']
    aliases = clip.get('object_name_map', {})
    if len(set(aliases.values())) != len(aliases):
        raise ValueError('Duplicate exported object aliases: ' + clip['id'])
    selected_by_name = {obj.name: obj for obj in selected}
    if set(aliases) - set(selected_by_name):
        raise ValueError('Object alias names an unselected object: ' + clip['id'])
    # Blender names are globally unique, even across preserved source scenes.
    # Temporarily displace collisions; each clip starts from a fresh file load.
    for original, alias in aliases.items():
        obj = selected_by_name[original]
        collision = bpy.data.objects.get(alias)
        if collision is not None and collision != obj:
            collision.name = '__nla_export_displaced__'
        obj.name = alias
    return scene, selected


def run(source, output):
    import bpy
    if bpy.app.version[:3] != (4, 3, 2):
        raise ValueError('Use official pinned Blender 4.3.2')
    source = source.resolve()
    source_hash = digest(source)
    bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
    text = bpy.data.texts.get('EXPORT_MANIFEST')
    if text is None:
        raise ValueError('Canonical BLEND lacks EXPORT_MANIFEST text')
    manifest = validate(json.loads(text.as_string()))
    output.mkdir(parents=True, exist_ok=True)
    # A clean destination prevents stale FBXs surviving after a removed track.
    if any(output.iterdir()):
        raise ValueError('Use an empty output directory')
    results = []
    for clip in manifest['clips']:
        # Reload rather than leak evaluated values or selection between clips.
        bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
        scene, selected = prepare(bpy, clip)
        destination = output / (clip['id'] + '.fbx')
        result = bpy.ops.export_scene.fbx(
            filepath=str(destination), use_selection=True,
            object_types={'ARMATURE', 'MESH', 'EMPTY', 'CAMERA'},
            axis_forward='-Z', axis_up='Y', global_scale=1.0,
            apply_unit_scale=True, apply_scale_options='FBX_SCALE_UNITS',
            use_space_transform=True, bake_space_transform=False,
            use_mesh_modifiers=True, use_triangles=True,
            add_leaf_bones=False, use_armature_deform_only=True,
            primary_bone_axis='Y', secondary_bone_axis='X', armature_nodetype='NULL',
            bake_anim=True, bake_anim_use_all_bones=True,
            bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
            bake_anim_force_startend_keying=True, bake_anim_step=clip.get('bake_step', 0.125),
            bake_anim_simplify_factor=0.0, path_mode='COPY', embed_textures=True,
            use_metadata=False)
        if result != {'FINISHED'} or not destination.is_file():
            raise RuntimeError('FBX export failed: ' + clip['id'])
        results.append({**clip, 'file': destination.name, 'take': scene.name,
                        'objects': sorted(o.name for o in selected),
                        'exported_rig': clip.get('object_name_map', {}).get(clip['rig'], clip['rig']),
                        'exported_camera': clip.get('object_name_map', {}).get(clip.get('camera'), clip.get('camera')),
                        'sha256': digest(destination),
                        'duration_seconds': (clip['frame_end'] - clip['frame_start']) * scene.render.fps_base / scene.render.fps})
        print('EXPORTED', destination.name, flush=True)
    if digest(source) != source_hash:
        raise RuntimeError('Source BLEND unexpectedly changed')
    receipt = {'schema': 'rust-duty-weapon-fbx/v1', 'source': SOURCE,
               'source_sha256': source_hash, 'blender_version': bpy.app.version_string,
               'clips': results}
    (output / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(SOURCE))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    run(args.source, args.output)
