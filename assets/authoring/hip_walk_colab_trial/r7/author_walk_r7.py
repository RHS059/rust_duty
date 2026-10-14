"""Author isolated root-only copies. No rendering, export, source save or activation.

Usage: blender --background --disable-autoexec SOURCE.blend --python this.py -- OUT
Requires an explicit coordinator resource window before execution.
"""
import bpy
import hashlib
import json
import math
import sys
from pathlib import Path
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / 'inputs')]
from correction_profiles import SOURCE_SHA256, REVIEW_URL, PREFIX, PROFILES, correction, native_map, solve_total_roll_delta
from source_integrity import snapshot, digest
from validate_directional_source import extra_snapshot, atom
from protected_scene import object_defaults, projection_signature

OUT = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
DEST = OUT / 'hip_longitudinal_elara_r7.blend'
assert not DEST.exists(), 'Refuse overwrite of existing candidate'
assert bpy.app.version_string == '4.3.2'
SOURCE = Path(bpy.data.filepath).resolve()
file_sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert file_sha(SOURCE) == SOURCE_SHA256 and SOURCE != DEST
scene = bpy.context.scene
rig = bpy.data.objects['Arms']
root = rig.pose.bones['righthand_prop']
cam = scene.camera
assert cam.name == 'RD First Person Review'
assert cam.data.type == 'PERSP' and cam.data.sensor_fit == 'HORIZONTAL'
assert scene.render.pixel_aspect_x == scene.render.pixel_aspect_y == 1
assert cam.data.shift_x == cam.data.shift_y == 0
assert root.rotation_mode not in ('QUATERNION', 'AXIS_ANGLE')
assert (scene.render.fps, scene.render.fps_base) == (60, 1.0)
assert (scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage) == (1280, 720, 100)
assert len(bpy.data.actions) == 86
original = {'preserved': snapshot(bpy), 'structural': extra_snapshot(), 'object_defaults': object_defaults()}
frame_saved = (scene.frame_current, scene.frame_subframe)
ad_saved = {o.name: (o.animation_data.action, o.animation_data.use_nla,
                   [(t, t.mute, t.is_solo) for t in o.animation_data.nla_tracks])
            for o in bpy.data.objects if o.animation_data}
pose_saved = {p.name: {'rotation_mode': p.rotation_mode,
                     **{k: list(getattr(p, k)) for k in ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale')},
                     'properties': {k: atom(p[k]) for k in p.keys()}}
              for p in rig.pose.bones}
camera_saved = {'name': cam.name, 'matrix': [list(x) for x in cam.matrix_world],
                'lens': cam.data.lens, 'shift': [cam.data.shift_x, cam.data.shift_y],
                'resolution': [1280, 720, 100], 'fps': [60, 1.0]}
for o in bpy.data.objects:
    if o.animation_data:
        for track in o.animation_data.nla_tracks:
            track.mute = True
            track.is_solo = False
rig.animation_data.use_nla = False
base = bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered']
rig.animation_data.action = base
scene.frame_set(1)
bpy.context.view_layer.update()
basis = {p.name: p.matrix_basis.copy() for p in rig.pose.bones}
rig.animation_data.action = bpy.data.actions['RD_Locomotion_Normal_Entry_4419_4434_WIP2']
scene.frame_set(1)
bpy.context.view_layer.update()
roll_reference_root_world = rig.matrix_world @ root.matrix.copy()
C = cam.matrix_world.copy()
Ci = C.inverted()
Ri = rig.matrix_world.inverted()
rig_world = rig.matrix_world.copy()
projection_saved = projection_signature(scene)
fx = 640 / math.tan(cam.data.angle_x / 2)
RECEIVER = Vector((0.020, 0.075, 0.020))


def set_action(action):
    rig.animation_data.action = None
    for p in rig.pose.bones:
        p.matrix_basis = basis[p.name].copy()
    rig.animation_data.action = base
    scene.frame_set(1)
    bpy.context.view_layer.update()
    rig.animation_data.action = action


def project(p):
    q = world_to_camera_view(scene, cam, p)
    assert q.z > 0
    return Vector((q.x * 1280, (1 - q.y) * 720))


def key_record(k):
    return {'co': list(k.co), 'left': list(k.handle_left), 'right': list(k.handle_right),
            'left_type': k.handle_left_type, 'right_type': k.handle_right_type,
            'interpolation': k.interpolation, 'easing': k.easing}


def restore_key(k, old):
    k.co = old['co']
    k.interpolation = old['interpolation']
    k.easing = old['easing']
    k.handle_left_type = old['left_type']
    k.handle_right_type = old['right_type']
    k.handle_left = old['left']
    k.handle_right = old['right']


created = []
records = {}
for direction, spec in PROFILES.items():
    original_action = bpy.data.actions[spec['baseline']]
    assert spec['candidate'] not in bpy.data.actions
    assert list(original_action.frame_range) == [1.0, float(spec['period'] + 1)]
    set_action(original_action)
    rows = []
    for frame in range(1, spec['period'] + 2):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        deps.update()
        er = rig.evaluated_get(deps)
        assert [list(r) for r in cam.matrix_world] == [list(r) for r in C], 'Animated camera is outside scope'
        assert projection_signature(scene) == projection_saved, 'Animated projection is outside scope'
        assert [list(r) for r in er.matrix_world] == [list(r) for r in rig_world], 'Animated rig object is outside scope'
        ew = bpy.data.objects['hk416_weapon'].evaluated_get(deps)
        world_root = er.matrix_world @ er.pose.bones['righthand_prop'].matrix
        witness = ew.matrix_world @ RECEIVER
        pivot = er.matrix_world @ er.pose.bones['hand_l'].matrix.translation
        x_px, y_px, image_roll = correction(direction, frame)
        requested_total_roll = None
        baseline_screen_roll = None
        if direction == 'backward':
            requested_total_roll = image_roll
            R0 = (Ci @ world_root @ roll_reference_root_world.inverted() @ C).to_3x3()
            # Original r5 authoring is Rx(pitch) @ Ry(yaw) @ Rz(roll).
            # Screen-sign roll is the negative camera Z component of that product.
            baseline_screen_roll = math.degrees(math.atan2(R0[0][1], R0[0][0]))
            image_roll = solve_total_roll_delta(R0, requested_total_roll)
            assert abs(image_roll) <= spec['bounds']['incremental_roll_degrees']
        pivot_c = Ci @ pivot
        # Clockwise screen rotation is negative camera-space Z rotation.
        R = Matrix.Translation(pivot_c) @ Matrix.Rotation(-math.radians(image_roll), 4, 'Z') @ Matrix.Translation(-pivot_c)
        wc = Ci @ witness
        rc = R @ wc
        target_xy = Vector((wc.x * fx / -wc.z + x_px,
                            wc.y * fx / -wc.z - y_px))
        shift = Vector((target_xy.x * -rc.z / fx - rc.x,
                        target_xy.y * -rc.z / fx - rc.y, 0.0))
        assert shift.length < 0.05, 'Bounded diagnostic translation exceeded 5 cm'
        transform = C @ Matrix.Translation(shift) @ R @ Ci
        transformed_root = transform @ world_root
        assert (transformed_root.translation - world_root.translation).length <= 0.05, 'Final root displacement exceeded 5 cm'
        local_matrix = Ri @ transformed_root
        old_loc, old_rot, old_scale = root.location.copy(), root.rotation_euler.copy(), root.scale.copy()
        root.matrix = local_matrix
        euler = root.rotation_euler.copy()
        euler.make_compatible(old_rot if not rows else rows[-1]['euler_object'])
        rows.append({'frame': frame, 'location': list(root.location), 'rotation_euler': list(euler),
                     'euler_object': euler, 'root_world': transformed_root,
                     'witness_world': transform @ witness,
                     'witness_root_local': world_root.inverted() @ witness,
                     'baseline_witness_px': list(project(witness)),
                     'requested_witness_delta_px': [x_px, y_px],
                     'screen_roll_delta_degrees': image_roll,
                     'requested_total_screen_roll_degrees': requested_total_roll,
                     'baseline_screen_roll_degrees': baseline_screen_roll,
                     'translation_camera_m': list(shift)})
        root.location, root.rotation_euler, root.scale = old_loc, old_rot, old_scale
    # An explicitly bounded, last-three-key translation adjustment addresses the
    # backward last-unique-to-first seam without changing frame timing or beats.
    seam_adjust = [0.0, 0.0]
    if direction == 'backward':
        first = project(rows[0]['witness_world'])
        last = project(rows[-2]['witness_world'])
        gap = last - first
        if gap.length > 2.0:
            delta = -gap * (1 - 2.0 / gap.length)
            assert delta.length <= 15.0, 'Seam repair exceeds bounded 15 px correction'
            seam_adjust = list(delta)
            for frame, weight in ((43, 0.0), (44, 0.5), (45, 1.0)):
                row = rows[frame - 1]
                depth = -(Ci @ row['witness_world']).z
                shift = Vector((delta.x * weight * depth / fx, -delta.y * weight * depth / fx, 0))
                T = C @ Matrix.Translation(shift) @ Ci
                row['root_world'] = T @ row['root_world']
                row['witness_world'] = T @ row['witness_world']
                scene.frame_set(frame)
                bpy.context.view_layer.update()
                assert [list(r) for r in rig.matrix_world] == [list(r) for r in rig_world]
                baseline_root = rig.matrix_world @ root.matrix
                assert (row['root_world'].translation - baseline_root.translation).length <= 0.05, 'Seam-inclusive root displacement exceeded 5 cm'
                root.matrix = Ri @ row['root_world']
                row['location'] = list(root.location)
                row['seam_delta_px'] = list(delta * weight)
    rows[-1]['location'] = rows[0]['location'][:]
    rows[-1]['rotation_euler'] = rows[0]['rotation_euler'][:]
    candidate = original_action.copy()
    candidate.name = spec['candidate']
    candidate.use_fake_user = True
    allowed = {PREFIX + p for p in spec['allowed']}
    untouched = digest([(f.data_path, f.array_index, [key_record(k) for k in f.keyframe_points])
                        for f in original_action.fcurves if f.data_path not in allowed])
    for fc in candidate.fcurves:
        if fc.data_path not in allowed:
            continue
        prop = fc.data_path.removeprefix(PREFIX)
        baseline_fc = next(f for f in original_action.fcurves
                           if f.data_path == fc.data_path and f.array_index == fc.array_index)
        assert [float(k.co.x) for k in baseline_fc.keyframe_points] == list(range(1, spec['period'] + 2)), 'Unexpected source root key times'
        saved_keys = {int(k.co.x): key_record(k) for k in baseline_fc.keyframe_points}
        fc.keyframe_points.clear()
        for modifier in list(fc.modifiers):
            fc.modifiers.remove(modifier)
        fc.lock = False
        vals = [row[prop][fc.array_index] for row in rows]
        N = spec['period']
        tangents = [(vals[(i + 1) % N] - vals[(i - 1) % N]) / 2 for i in range(N)]
        tangents.append(tangents[0])
        for i, value in enumerate(vals):
            frame = i + 1
            point = fc.keyframe_points.insert(frame, value)
            point.interpolation = 'BEZIER'
            point.handle_left_type = point.handle_right_type = 'FREE'
            point.handle_left = (frame - 1/3, value - tangents[i]/3)
            point.handle_right = (frame + 1/3, value + tangents[i]/3)
            if frame in spec['preserved_keys']:
                restore_key(point, saved_keys[frame])
        fc.modifiers.new('CYCLES')
    assert untouched == digest([(f.data_path, f.array_index, [key_record(k) for k in f.keyframe_points])
                                 for f in candidate.fcurves if f.data_path not in allowed])
    candidate['revision_of'] = spec['baseline']
    candidate['reference_id'] = '5KM0XSKxTWw'
    candidate['reference_frame_start'] = spec['reference_start']
    candidate['reference_frame_end_exclusive'] = spec['reference_start'] + spec['period']
    candidate['authoring_fps'] = 60
    candidate['loop_period_frames'] = spec['period']
    candidate['acceptance_status'] = 'diagnostic; numeric and native Eevee review pending'
    candidate['review_source'] = REVIEW_URL
    candidate['revision_notes'] = 'Elara r7 root-only spatial correction on r5; fixed camera/timing; isolated Action'
    created.append(candidate.name)
    records[direction] = {'spec': spec, 'seam_repair_last_unique_delta_px': seam_adjust,
                          'rows': [{k: v for k, v in row.items()
                                    if k not in ('euler_object', 'root_world', 'witness_world', 'witness_root_local')}
                                   for row in rows]}
    print('AUTHORED', candidate.name, flush=True)

# Restore all source defaults and active/NLA state before snapshots and save.
for p in rig.pose.bones:
    saved = pose_saved[p.name]
    p.rotation_mode = saved['rotation_mode']
    for key in ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale'):
        setattr(p, key, saved[key])
    for key, value in saved['properties'].items():
        current = p[key]
        if hasattr(current, 'to_list'):
            for i, v in enumerate(value):
                current[i] = v
        elif isinstance(value, (str, int, float, bool)):
            p[key] = value
        else:
            assert atom(current) == value
for name, (action, use_nla, tracks) in ad_saved.items():
    ad = bpy.data.objects[name].animation_data
    ad.action, ad.use_nla = action, use_nla
    for track, mute, solo in tracks:
        track.mute, track.is_solo = mute, solo
scene.frame_set(frame_saved[0], subframe=frame_saved[1])
bpy.context.view_layer.update()
after = {'preserved': snapshot(bpy), 'structural': extra_snapshot(), 'object_defaults': object_defaults()}
checks = {}
checks['object_transform_defaults'] = after['object_defaults'] == original['object_defaults']
for section in ('nla', 'packed_images', 'drivers'):
    checks[section] = after['preserved'][section] == original['preserved'][section]
for section in ('actions',):
    checks[section] = all(after['preserved'][section][n] == value
                          for n, value in original['preserved'][section].items())
for section in original['structural']:
    checks[section] = (all(after['structural'][section][n] == value
                          for n, value in original['structural'][section].items())
                       if section in ('actions_extended', 'actions_metadata')
                       else after['structural'][section] == original['structural'][section])
checks['exactly_two_new_actions'] = set(after['preserved']['actions']) - set(original['preserved']['actions']) == set(created)
checks['camera_object_transform'] = [list(x) for x in cam.matrix_world] == camera_saved['matrix']
checks['source_bytes'] = file_sha(SOURCE) == SOURCE_SHA256
assert all(checks.values()), checks
(OUT / 'source_baseline_fingerprints.json').write_text(json.dumps(original, indent=2) + '\n')
(OUT / 'authored_root_keys.json').write_text(json.dumps(records, indent=2) + '\n')
(OUT / 'native_frame_maps.json').write_text(json.dumps({d: native_map(d) for d in PROFILES}, indent=2) + '\n')
bpy.ops.wm.save_as_mainfile(filepath=str(DEST), compress=True)
assert file_sha(SOURCE) == SOURCE_SHA256
manifest = {'status': 'diagnostic', 'source': str(SOURCE), 'source_sha256': SOURCE_SHA256,
            'source_commit': '6a1c145ca63143e99bbf694a76f9d19bd31becf5',
            'source_repository_path': 'assets/authoring/hip_walk_colab_trial/v1/hip_four_walks_colab_visual_v1.blend',
            'candidate': str(DEST), 'candidate_sha256': file_sha(DEST),
            'candidate_action_count': len(bpy.data.actions),
            'roll_reference_root_world': [list(r) for r in roll_reference_root_world],
            'roll_reference_action': 'RD_Locomotion_Normal_Entry_4419_4434_WIP2',
            'roll_reference_frame': 1,
            'authoring_script_sha256': {p: file_sha(HERE / p) for p in ('author_walk_r7.py', 'correction_profiles.py', 'protected_scene.py', 'inputs/source_integrity.py', 'inputs/validate_directional_source.py')},
            'original_actions_preserved': 86, 'new_actions': created, 'checks': checks,
            'camera': camera_saved, 'rendered': False, 'runtime_activated': False,
            'review_url': REVIEW_URL,
            'witness': {'object': 'hk416_weapon', 'local': list(RECEIVER),
                        'purpose': 'Internal displacement calibration, not a homologous cross-weapon visual landmark'},
            'limits': 'A numeric pass cannot approve anatomy, surface grasp, visual match, centroid seam or runtime parity.'}
(OUT / 'authoring_preservation.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest), flush=True)
