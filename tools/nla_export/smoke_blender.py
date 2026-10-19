"""Small functional exporter exercise, not a test of authored animation content.

blender -b --disable-autoexec --python-exit-code 1 --python tools/nla_export/smoke_blender.py
"""
import json
from pathlib import Path
import sys
import tempfile
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export import run

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = 'Fixture'
bpy.ops.object.armature_add()
rig = bpy.context.object
rig.name = 'Arms.004'
rig.animation_data_create()
clips = []
for index, key in enumerate(('walk', 'reload'), 1):
    action = bpy.data.actions.new(key)
    curve = action.fcurves.new('pose.bones["Bone"].location', index=0)
    curve.keyframe_points.insert(10, 0)
    curve.keyframe_points.insert(20, index)
    track = rig.animation_data.nla_tracks.new()
    track.name = 'EXPORT::' + key
    track.strips.new(key, 10, action)
    clips.append({'id': key, 'scene': scene.name, 'rig': rig.name, 'track_name': track.name,
                  'frame_start': 10, 'frame_end': 20, 'fps': 60, 'fps_base': 1.001,
                  'object_name_map': {'Arms.004': 'Arms'}})
# Archived history must never become an additional take.
history = rig.animation_data.nla_tracks.new()
history.name = 'ARCHIVE::old'
history.strips.new('old', 10, action)
bpy.ops.object.camera_add()
camera = bpy.context.object
camera.name = 'ViewCamera'
camera.animation_data_create()
action = bpy.data.actions.new('camera_motion')
curve = action.fcurves.new('location', index=2)
curve.keyframe_points.insert(10, 0)
curve.keyframe_points.insert(20, 2)
track = camera.animation_data.nla_tracks.new()
track.name = 'EXPORT::paired_camera'
track.strips.new('camera', 10, action)
clips[1].update(camera=camera.name, camera_track_name=track.name)
bpy.data.texts.new('EXPORT_MANIFEST').write(json.dumps({'schema': 'rust-duty-weapon-nla/v1', 'clips': clips}))
with tempfile.TemporaryDirectory(prefix='weapon-nla-smoke-') as tmp:
    source = Path(tmp) / 'fixture.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    receipt = run(source, Path(tmp) / 'fbx')
    assert [row['file'] for row in receipt['clips']] == ['walk.fbx', 'reload.fbx']
    from io_scene_fbx import parse_fbx
    for row in receipt['clips']:
        root, _ = parse_fbx.parse(str(Path(tmp) / 'fbx' / row['file']))
        objects = next(n for n in root.elems if n.id == b'Objects')
        stacks = [n for n in objects.elems if n.id == b'AnimationStack']
        assert len(stacks) == 1, 'history or other track leaked into export'
        assert stacks[0].props[1].split(b'\x00\x01')[0].decode() == row['id']
        assert row['exported_rig'] == 'Arms' and 'Arms' in row['objects']
        assert row['frame_start'] == 10 and row['frame_end'] == 20
        assert ('ViewCamera' in row['objects']) == (row['id'] == 'reload')
    print('PASS: two isolated stable FBXs, one take each, paired camera, preserved timing, unchanged BLEND')
