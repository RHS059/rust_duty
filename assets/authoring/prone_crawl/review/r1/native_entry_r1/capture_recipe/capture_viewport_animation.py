"""Equivalent reconstruction of the documented jump-r7 foreground viewport workflow.

This is newly reconstructed capture code, not a recovered byte-identical script.
Run only from the approved graphical launcher. It never saves its input BLEND.
"""
import bpy
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import sys
import traceback
from datetime import datetime, timezone

OUT = Path('/workspace/shared/prone-crawl-20261004/render/r1')
SOURCE = Path('/workspace/shared/prone-crawl-20261004/author/halcyon_prone_crawl_r1.blend')
SOURCE_SHA256 = '7807f7e16f6fabb2833d9e61ae5a942ee9a57f455a6c3e40e15ed4e03fa153b4'
ACTION = 'prone_crawl_enter_r1'
FRAME_START, FRAME_END, FPS = 1, 69, 60
REFERENCE_START, REFERENCE_END = 2241, 2310
ENGINE = 'BLENDER_EEVEE_NEXT'
sys.dont_write_bytecode = True
sys.path.insert(0, str(OUT / 'helpers'))
from source_integrity import snapshot, digest
from validate_source_structure import extra_snapshot

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def utc():
    return datetime.now(timezone.utc).isoformat()

def matrix(value):
    return [list(row) for row in value]

def camera_state(camera):
    return {'name': camera.name, 'matrix_world': matrix(camera.matrix_world),
            **{key: getattr(camera.data, key) for key in (
                'lens', 'sensor_width', 'sensor_height', 'sensor_fit',
                'shift_x', 'shift_y', 'clip_start', 'clip_end')}}

def static_structure(value):
    return {key: value[key] for key in (
        'actions_metadata', 'actions_extended', 'meshes', 'armatures',
        'objects_and_bindings', 'materials', 'cameras')}

def persist():
    (OUT / 'viewport_process_proof.json').write_text(json.dumps(proof, indent=2) + '\n')

assert not bpy.app.background, 'This workflow requires a real graphical Blender window'
assert bpy.app.version_string == '4.3.2'
assert os.environ.get('DISPLAY'), 'No graphical display'
assert Path(bpy.data.filepath).resolve() == SOURCE.resolve()
assert sha(SOURCE) == SOURCE_SHA256
assert FRAME_END - FRAME_START + 1 == REFERENCE_END - REFERENCE_START == 69
assert FPS == 60
assert len(bpy.data.actions) == 108
assert list(bpy.data.actions[ACTION].frame_range) == [1.0, 69.0]
scene = bpy.context.scene
assert scene.camera.name == 'RD First Person Review'
assert scene.render.fps / scene.render.fps_base == FPS
# Set the required engine immediately, before the first scheduled viewport redraw.
scene.render.engine = ENGINE
assert scene.render.engine == 'BLENDER_EEVEE_NEXT'
rig = bpy.data.objects['Arms']
camera_before = camera_state(scene.camera)
rig_world_before = matrix(rig.matrix_world)
before = snapshot(bpy)
structural_before = static_structure(extra_snapshot())
known = json.loads((OUT / 'recovery/current_reopen_preservation.json').read_text())
assert known['source_sha256'] == SOURCE_SHA256 and known['passed']
assert before['actions'] == known['preserved']['actions']
entry_predecessor = json.loads((OUT / 'recovery/entry_reopen_preservation.json').read_text())
assert all(before['actions'][name] == value for name, value in entry_predecessor['preserved']['actions'].items())
assert structural_before == static_structure(known['structural'])
prior = json.loads((OUT / 'recovery/jump_r7_viewport_process_proof.json').read_text())
assert prior['engine'] == ENGINE and prior['operator'] == 'bpy.ops.render.opengl'
assert prior['background'] is False and prior['completed'] is True
assert camera_before == prior['camera'], 'Fixed review camera must remain unchanged'
assert bpy.data.objects['hk416_weapon'].animation_data.action.name == 'hk416_weaponAction.001'
assert bpy.data.objects['hk416_magazine'].animation_data.action.name == 'hk416_magazineAction'
for name in ('hk416_weapon', 'hk416_magazine'):
    assert bpy.data.objects[name].animation_data.use_nla
    assert len(bpy.data.objects[name].animation_data.nla_tracks) == 0

frame_dir = OUT / 'frames' / ACTION
frame_dir.mkdir(parents=True, exist_ok=True)
assert not list(frame_dir.glob('*.png')), 'Refuse to overwrite any existing native captures'
proof = {
    'schema': 'rust-duty-prone-foreground-viewport/v1',
    'reconstruction': 'Equivalent-from-immutable-r7-proof; original capture code unavailable',
    'workflow_provenance_commit': 'e9317f90ea171976306e2f17c111325d948ea357',
    'source_path': str(SOURCE), 'source_sha256': SOURCE_SHA256,
    'source_commit': '99a804349c3a5ca7d7a9fa64f0c4f213d01e9b35',
    'entry_predecessor_sha256': '793546897db5634fca6ba6da7cefd5240e3712932c239bbabea7dfaa0f03419e',
    'entry_action_fingerprint': before['actions'][ACTION],
    'blender': bpy.app.version_string, 'pid': os.getpid(), 'hostname': socket.gethostname(),
    'display': os.environ['DISPLAY'], 'background': bpy.app.background,
    'camera': camera_before, 'resolution': [1280, 720], 'source_fps': FPS,
    'engine': ENGINE, 'operator': 'bpy.ops.render.opengl',
    'operator_arguments': {'animation': True, 'view_context': True,
                           'render_keyed_only': False, 'sequencer': False},
    'source_reference_frames_half_open': [REFERENCE_START, REFERENCE_END],
    'frame_mapping': 'Blender frame = source frame - 2241 + 1',
    'source_saved': False, 'regular_offline_render_operator_used': False,
    'no_scoring': True, 'completed': False, 'actions': [],
    'action_curve_digest_before': digest(before['actions']),
    'source_mesh_digest_before': digest(structural_before['meshes']),
    'material_digest_before': digest(structural_before['materials']),
    'started_utc': utc(),
}
persist()

def capture():
    try:
        import gpu
        for obj in bpy.data.objects:
            if obj.animation_data:
                for track in obj.animation_data.nla_tracks:
                    track.mute = True
                    track.is_solo = False
        rig.animation_data.use_nla = False
        rig.animation_data.action = bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered']
        scene.frame_set(1)
        bpy.context.view_layer.update()
        rig.animation_data.action = bpy.data.actions[ACTION]
        scene.frame_set(FRAME_START)
        bpy.context.view_layer.update()
        assert camera_state(scene.camera) == camera_before
        assert matrix(rig.matrix_world) == rig_world_before
        scene.render.resolution_x, scene.render.resolution_y = 1280, 720
        scene.render.resolution_percentage = 100
        scene.render.fps, scene.render.fps_base = FPS, 1.0
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '8'
        scene.render.image_settings.compression = 15
        scene.render.use_file_extension = True
        scene.render.use_border = False
        scene.render.filepath = str(frame_dir / 'f')
        scene.frame_start, scene.frame_end, scene.frame_step = FRAME_START, FRAME_END, 1
        for key in ('taa_samples', 'taa_render_samples', 'volumetric_samples',
                    'volumetric_sample_distribution', 'volumetric_shadow_samples'):
            if hasattr(scene.eevee, key):
                setattr(scene.eevee, key, prior['eevee_sample_settings'][key])
        candidates = [(window, area) for window in bpy.context.window_manager.windows
                      for area in window.screen.areas if area.type == 'VIEW_3D']
        assert candidates, 'No real VIEW_3D area in any foreground Blender window'
        window, area = max(candidates, key=lambda pair: pair[1].width * pair[1].height)
        region = next(region for region in area.regions if region.type == 'WINDOW')
        space = area.spaces.active
        assert space.type == 'VIEW_3D'
        space.shading.type = 'RENDERED'
        space.shading.use_scene_world_render = True
        space.shading.use_scene_lights_render = True
        space.overlay.show_overlays = False
        space.show_gizmo = False
        space.use_local_camera = False
        space.region_3d.view_perspective = 'CAMERA'
        proof.update({
            'window_pointer': window.as_pointer(), 'area_type': area.type,
            'region_type': region.type, 'viewport_shading': space.shading.type,
            'scene_world': space.shading.use_scene_world_render,
            'scene_lights': space.shading.use_scene_lights_render,
            'camera_view': space.region_3d.view_perspective,
            'gpu': {'vendor': gpu.platform.vendor_get(), 'renderer': gpu.platform.renderer_get(),
                    'version': gpu.platform.version_get(), 'backend': gpu.platform.backend_type_get()},
            'object_action_bindings': {obj.name: obj.animation_data.action.name
                                      if obj.animation_data and obj.animation_data.action else None
                                      for obj in bpy.data.objects},
            'eevee_sample_settings': {key: getattr(scene.eevee, key) for key in
                prior['eevee_sample_settings'] if hasattr(scene.eevee, key)},
        })
        row = {'action': ACTION, 'frame_start': FRAME_START, 'frame_end_inclusive': FRAME_END,
               'native_frames': 69, 'duration_intervals': 68, 'output_directory': str(frame_dir),
               'started_utc': utc(), 'engine_at_call': scene.render.engine,
               'viewport_shading_at_call': space.shading.type}
        proof['actions'].append(row)
        persist()
        assert scene.render.engine == 'BLENDER_EEVEE_NEXT'
        assert space.shading.type == 'RENDERED' and space.region_3d.view_perspective == 'CAMERA'
        with bpy.context.temp_override(window=window, area=area, region=region):
            result = bpy.ops.render.opengl('EXEC_DEFAULT', animation=True, view_context=True,
                                          render_keyed_only=False, sequencer=False)
        row['operator_result'] = sorted(result)
        assert result == {'FINISHED'}
        files = sorted(frame_dir.glob('*.png'))
        assert [path.name for path in files] == [f'f{frame:04d}.png' for frame in range(1, 70)]
        for path in files:
            header = path.read_bytes()[:24]
            assert header[:8] == b'\x89PNG\r\n\x1a\n'
            assert struct.unpack('>II', header[16:24]) == (1280, 720)
        after = snapshot(bpy)
        structure_after = static_structure(extra_snapshot())
        checks = {'source_bytes_unchanged': sha(SOURCE) == SOURCE_SHA256,
                  'camera_unchanged': camera_state(scene.camera) == camera_before,
                  'world_root_unchanged': matrix(rig.matrix_world) == rig_world_before,
                  'action_curves_unchanged': before['actions'] == after['actions'],
                  'source_structure_unchanged': structural_before == structure_after,
                  'drivers_unchanged': before['drivers'] == after['drivers'],
                  'packed_images_unchanged': before['packed_images'] == after['packed_images'],
                  'companions_unchanged': all(before['nla'][name] == after['nla'][name]
                      for name in ('hk416_weapon', 'hk416_magazine'))}
        assert all(checks.values()), checks
        row.update(checks)
        row.update({'output_files': [{'path': str(path), 'sha256': sha(path)} for path in files],
                    'ended_utc': utc()})
        proof.update(checks)
        proof.update({'completed': True, 'ended_utc': utc()})
        persist()
        print('VIEWPORT_CAPTURE_COMPLETE', str(OUT), flush=True)
        bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=1.0)
    except BaseException:
        proof.update({'completed': False, 'error': traceback.format_exc(), 'failed_utc': utc()})
        persist()
        traceback.print_exc()
        raise
    return None

bpy.app.timers.register(capture, first_interval=1.0)
