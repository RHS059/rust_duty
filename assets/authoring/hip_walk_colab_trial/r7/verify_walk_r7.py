"""Reopen preserved source data and sweep source/candidate at 480 Hz. Never saves/renders."""
import bpy
import csv
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
from correction_profiles import SOURCE_SHA256, PREFIX, PROFILES, periodic_cubic
from source_integrity import snapshot, digest
from validate_directional_source import extra_snapshot, props
from protected_scene import object_defaults, projection_signature

OUT = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
manifest = json.loads((OUT / 'authoring_preservation.json').read_text())
original = json.loads((OUT / 'source_baseline_fingerprints.json').read_text())
authored = json.loads((OUT / 'authored_root_keys.json').read_text())
path = Path(bpy.data.filepath)
assert path.is_file(), 'Open the generated candidate BLEND before invoking this verifier'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(path) == manifest['candidate_sha256']
assert bpy.app.version_string == '4.3.2'
current = {'preserved': snapshot(bpy), 'structural': extra_snapshot(), 'object_defaults': object_defaults()}
checks = {}
checks['exact_authoring_script_bytes'] = all(sha(HERE / name) == expected for name, expected in manifest['authoring_script_sha256'].items())
checks['reopened_object_defaults'] = current['object_defaults'] == original['object_defaults']
for section in ('nla', 'packed_images', 'drivers'):
    checks['reopened_' + section] = current['preserved'][section] == original['preserved'][section]
checks['reopened_original_actions'] = all(current['preserved']['actions'].get(n) == v for n, v in original['preserved']['actions'].items())
for section in original['structural']:
    checks['reopened_' + section] = (all(current['structural'][section].get(n) == value
                                         for n, value in original['structural'][section].items())
                                      if section in ('actions_metadata', 'actions_extended')
                                      else current['structural'][section] == original['structural'][section])
checks['exactly_two_new_actions'] = set(current['preserved']['actions']) - set(original['preserved']['actions']) == set(manifest['new_actions'])
scene = bpy.context.scene
rig = bpy.data.objects['Arms']
cam = scene.camera
checks['camera_object_matrix'] = [list(r) for r in cam.matrix_world] == manifest['camera']['matrix']
checks['camera_lens_shift'] = cam.data.lens == manifest['camera']['lens'] and [cam.data.shift_x, cam.data.shift_y] == manifest['camera']['shift']
checks['fixed_resolution_fps'] = [scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage] == [1280,720,100] and (scene.render.fps, scene.render.fps_base) == (60,1.0)
for o in bpy.data.objects:
    if o.animation_data:
        for t in o.animation_data.nla_tracks:
            t.mute, t.is_solo = True, False
rig.animation_data.use_nla = False
base = bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered']
rig.animation_data.action = base
scene.frame_set(1)
bpy.context.view_layer.update()
basis = {p.name: p.matrix_basis.copy() for p in rig.pose.bones}
assert manifest['roll_reference_action'] == 'RD_Locomotion_Normal_Entry_4419_4434_WIP2'
assert manifest['roll_reference_frame'] == 1
rig.animation_data.action = bpy.data.actions[manifest['roll_reference_action']]
scene.frame_set(1)
bpy.context.view_layer.update()
reference_deps = bpy.context.evaluated_depsgraph_get()
reference_deps.update()
reference_rig = rig.evaluated_get(reference_deps)
reference_rebuilt = reference_rig.matrix_world @ reference_rig.pose.bones['righthand_prop'].matrix
checks['reopened_roll_reference_witness'] = max(abs(reference_rebuilt[i][j] - manifest['roll_reference_root_world'][i][j]) for i in range(4) for j in range(4)) <= 1e-6
rig.animation_data.action = None
for p in rig.pose.bones:
    p.matrix_basis = basis[p.name].copy()
rig.animation_data.action = base
scene.frame_set(1)
bpy.context.view_layer.update()
cuff_binding = {'object': 'Actual arms mesh 0', 'vertex_indices': [5681,5679,5666],
                'weights': [0.38801232981670086,0.5282059672418871,0.08378170294141207]}
receiver = Vector((.020,.075,.020))
muzzle = Vector((-.000062,.090545,-.411509))


def max_matrix(a, b):
    return max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4))


def project(p):
    q = world_to_camera_view(scene, cam, p)
    return [q.x * 1280, (1 - q.y) * 720, q.z]


def curve_record(action, excluded):
    return [(f.data_path, f.array_index,
             {'mute': f.mute, 'lock': f.lock, 'extrapolation': f.extrapolation,
              'auto_smoothing': getattr(f, 'auto_smoothing', None),
              'modifiers': [props(m) for m in f.modifiers],
              'group': None if f.group is None else {'name': f.group.name, 'lock': f.group.lock, 'mute': f.group.mute}},
             [(list(k.co), list(k.handle_left), list(k.handle_right), k.interpolation,
               k.handle_left_type, k.handle_right_type, k.easing) for k in f.keyframe_points])
            for f in action.fcurves if f.data_path not in excluded]


numeric = {}
tracks = {}
dense = {}
Ci = cam.matrix_world.inverted()
C = cam.matrix_world.copy()
rig_world = rig.matrix_world.copy()
projection_saved = projection_signature(scene)
for direction, spec in PROFILES.items():
    allowed = {PREFIX + p for p in spec['allowed']}
    checks[direction + '_copied_other_curves'] = curve_record(bpy.data.actions[spec['baseline']], allowed) == curve_record(bpy.data.actions[spec['candidate']], allowed)
    if spec['preserved_keys']:
        def protected_keys(action):
            return [(f.data_path, f.array_index, [(list(k.co), list(k.handle_left), list(k.handle_right),
                                                  k.interpolation, k.handle_left_type, k.handle_right_type, k.easing)
                                                 for k in f.keyframe_points if int(k.co.x) in spec['preserved_keys']])
                    for f in action.fcurves if f.data_path in allowed]
        checks[direction + '_protected_key_records'] = protected_keys(bpy.data.actions[spec['baseline']]) == protected_keys(bpy.data.actions[spec['candidate']])
    for name in (spec['baseline'], spec['candidate']):
        action = bpy.data.actions[name]
        checks[name + '_timing'] = list(action.frame_range) == [1.0, float(spec['period'] + 1)] and int(action['loop_period_frames']) == spec['period']
        rig.animation_data.action = None
        for p in rig.pose.bones:
            p.matrix_basis = basis[p.name].copy()
        rig.animation_data.action = base
        scene.frame_set(1)
        bpy.context.view_layer.update()
        rig.animation_data.action = action
        first = None
        wrist_max = [0.0, 0.0]
        guard_max = [0.0, 0.0]
        contact_max = [0.0, 0.0]
        root_steps = []
        previous_root = None
        points = []
        samples = []
        endpoint = {}
        for k in range(spec['period'] * 8 + 1):
            frame = 1 + k / 8
            floor = math.floor(frame)
            scene.frame_set(floor, subframe=frame-floor)
            bpy.context.view_layer.update()
            deps = bpy.context.evaluated_depsgraph_get()
            deps.update()
            er = rig.evaluated_get(deps)
            ew = bpy.data.objects['hk416_weapon'].evaluated_get(deps)
            root = er.matrix_world @ er.pose.bones['righthand_prop'].matrix
            assert max_matrix(cam.matrix_world, C) == 0, 'Camera moved during dense sweep'
            assert projection_signature(scene) == projection_saved, 'Camera projection changed during dense sweep'
            assert max_matrix(er.matrix_world, rig_world) == 0, 'Rig object moved during dense sweep'
            hands = [er.matrix_world @ er.pose.bones['hand_' + side].matrix for side in ('l','r')]
            relative = [root.inverted() @ m for m in hands]
            samples.append({'frame': frame, 'receiver': project(ew.matrix_world @ receiver),
                            'root': [list(row) for row in root],
                            'actor_relative': [list(row) for row in root.inverted() @ ew.matrix_world],
                            'hands_relative': [[list(row) for row in m] for m in relative]})
            if first is None:
                first = {'root': root.copy(), 'actor': ew.matrix_world.copy(),
                         'hands': [m.copy() for m in hands], 'relative': [m.copy() for m in relative]}
            for i, side in enumerate(('l','r')):
                target = er.pose.bones['righthand_prop_' + ('left' if side == 'l' else 'right') + 'hand'].matrix.translation
                wrist_max[i] = max(wrist_max[i], (er.pose.bones['hand_' + side].matrix.translation - target).length)
                guard = er.pose.bones['MCH_hand_guarded_' + side].matrix.to_quaternion()
                goal = er.pose.bones['MCH_attach_goal_' + side].matrix.to_quaternion()
                guard_max[i] = max(guard_max[i], math.degrees(guard.rotation_difference(goal).angle))
                contact_max[i] = max(contact_max[i], max_matrix(relative[i], first['relative'][i]))
            for control in ('righthand_prop_lefthand','righthand_prop_righthand','lefthand_prop'):
                assert abs(float(rig.pose.bones[control]['weapon_follow']) - 1) < 1e-7
            if previous_root is not None:
                root_steps.append((root.translation - previous_root).length)
            previous_root = root.translation.copy()
            if k % 8 == 0:
                p = {'frame': int(frame), 'receiver': project(ew.matrix_world @ receiver),
                     'muzzle': project(ew.matrix_world @ muzzle),
                     'support_wrist': project(hands[0].translation),
                     'firing_wrist': project(hands[1].translation)}
                mesh_obj = bpy.data.objects[cuff_binding['object']].evaluated_get(deps)
                mesh = mesh_obj.to_mesh()
                cuff = sum((mesh.vertices[idx].co * w for idx, w in zip(cuff_binding['vertex_indices'], cuff_binding['weights'])), Vector((0,0,0)))
                p['support_cuff_surface'] = project(mesh_obj.matrix_world @ cuff)
                mesh_obj.to_mesh_clear()
                points.append(p)
            if k == spec['period'] * 8:
                endpoint = {'root': max_matrix(root, first['root']),
                            'actor': max_matrix(ew.matrix_world, first['actor']),
                            'hands': max(max_matrix(hands[i], first['hands'][i]) for i in (0,1))}
        invalid = [o.name + ':' + f.data_path for o in bpy.data.objects if o.animation_data
                   for f in o.animation_data.drivers if not f.driver.is_valid]
        seam = math.dist(points[0]['receiver'][:2], points[-2]['receiver'][:2])
        numeric[name] = {'samples_480hz': spec['period'] * 8 + 1,
                         'max_wrist_error_m': wrist_max, 'max_guard_error_degrees': guard_max,
                         'max_hand_relative_root_matrix_drift': contact_max,
                         'loop_endpoint_errors': endpoint, 'receiver_last_unique_to_first_px': seam,
                         'max_root_translation_step_480hz_m': max(root_steps), 'invalid_drivers': invalid,
                         'first_hand_relative_root_matrices': [[list(r) for r in m] for m in first['relative']]}
        tracks[name] = points
        dense[name] = samples
        checks[name + '_wrist'] = max(wrist_max) <= 1e-5
        checks[name + '_guard'] = max(guard_max) <= 1e-4
        checks[name + '_relative_contact'] = max(contact_max) <= 1e-5
        checks[name + '_exact_loop'] = all(x == 0 for x in endpoint.values())
        checks[name + '_drivers'] = not invalid
        print(name, json.dumps(numeric[name]), flush=True)
    baseline = tracks[spec['baseline']]
    candidate = tracks[spec['candidate']]
    old_grasps = numeric[spec['baseline']]['first_hand_relative_root_matrices']
    new_grasps = numeric[spec['candidate']]['first_hand_relative_root_matrices']
    checks[direction + '_same_source_grasp_matrices'] = max(max_matrix(a, b) for a, b in zip(old_grasps, new_grasps)) <= 1e-5
    dense_deltas = []
    intended_roll_keys = [r['screen_roll_delta_degrees'] for r in authored[direction]['rows'][:-1]]
    total_roll_keys = [r['requested_total_screen_roll_degrees'] for r in authored[direction]['rows'][:-1]]
    for old, new in zip(dense[spec['baseline']], dense[spec['candidate']]):
        assert old['frame'] == new['frame']
        T = Ci @ Matrix(new['root']) @ Matrix(old['root']).inverted() @ C
        R = T.to_quaternion().to_matrix()
        roll = -math.degrees(math.atan2(R[1][0], R[0][0]))
        off_axis = math.degrees(math.atan2(math.hypot(R[0][2], R[1][2]), R[2][2]))
        delta = [new['receiver'][i] - old['receiver'][i] for i in range(3)]
        total_roll_error = 0.0
        total_roll = None
        if direction == 'backward':
            Rt = (Ci @ Matrix(new['root']) @ Matrix(manifest['roll_reference_root_world']).inverted() @ C).to_3x3()
            total_roll = math.degrees(math.atan2(Rt[0][1], Rt[0][0]))
            total_roll_error = abs(total_roll - periodic_cubic(total_roll_keys, old['frame']))
        dense_deltas.append({'frame': old['frame'], 'receiver_delta_xy_px_depth_m': delta,
                             'screen_roll_delta_degrees': roll, 'unintended_off_axis_degrees': off_axis,
                             'intended_roll_degrees': periodic_cubic(intended_roll_keys, old['frame']),
                             'roll_error_degrees': abs(roll - periodic_cubic(intended_roll_keys, old['frame'])),
                             'total_authoring_roll_degrees': total_roll,
                             'total_authoring_roll_error_degrees': total_roll_error,
                             'root_scale_delta': max(abs(v - 1) for v in T.to_scale()),
                             'root_displacement_m': (Matrix(new['root']).translation - Matrix(old['root']).translation).length,
                             'actor_relative_error': max_matrix(new['actor_relative'], old['actor_relative']),
                             'hand_relative_errors': [max_matrix(a,b) for a,b in zip(new['hands_relative'],old['hands_relative'])]})
    # Fractional root curves are cubic interpolants of fixed integer source keys.
    # Bound their actual evaluated output; a profile-only unit test cannot do so.
    tol_px = 0.1
    seam = authored[direction]['seam_repair_last_unique_delta_px']
    def seam_support(frame):
        return 42 < frame < 46 or 1 < frame < 2
    checks[direction + '_dense_x_bound'] = all(abs(r['receiver_delta_xy_px_depth_m'][0]) <= spec['bounds']['x_px'] + (abs(seam[0]) if seam_support(r['frame']) else 0) + tol_px for r in dense_deltas)
    checks[direction + '_dense_y_bound'] = all(abs(r['receiver_delta_xy_px_depth_m'][1]) <= spec['bounds']['y_px'] + (abs(seam[1]) if seam_support(r['frame']) else 0) + tol_px for r in dense_deltas)
    checks[direction + '_dense_roll_bound'] = max(abs(r['screen_roll_delta_degrees']) for r in dense_deltas) <= spec['bounds']['incremental_roll_degrees'] + 0.02
    checks[direction + '_dense_signed_roll_profile'] = max(r['roll_error_degrees'] for r in dense_deltas) <= 0.02
    checks[direction + '_dense_total_authoring_roll_profile'] = max(r['total_authoring_roll_error_degrees'] for r in dense_deltas) <= 0.05
    checks[direction + '_dense_depth_preserved'] = max(abs(r['receiver_delta_xy_px_depth_m'][2]) for r in dense_deltas) <= 1e-5
    checks[direction + '_dense_no_off_axis_rotation'] = max(r['unintended_off_axis_degrees'] for r in dense_deltas) <= 0.02
    checks[direction + '_dense_no_scale_change'] = max(r['root_scale_delta'] for r in dense_deltas) <= 1e-5
    checks[direction + '_dense_root_step_bounded'] = numeric[spec['candidate']]['max_root_translation_step_480hz_m'] <= 0.01
    checks[direction + '_dense_final_root_displacement_bounded'] = max(r['root_displacement_m'] for r in dense_deltas) <= 0.05001
    checks[direction + '_dense_same_source_grasp'] = max(max(r['hand_relative_errors']) for r in dense_deltas) <= 1e-5
    checks[direction + '_dense_same_source_actor_attachment'] = max(r['actor_relative_error'] for r in dense_deltas) <= 1e-5
    numeric[spec['candidate']]['dense_delta_limits'] = {'xy_interpolation_tolerance_px': tol_px,
                                                       'roll_off_axis_tolerance_degrees': 0.02,
                                                       'depth_tolerance_m': 1e-5,
                                                       'root_translation_step_480hz_m': 0.01}
    numeric[spec['candidate']]['dense_deltas'] = dense_deltas
    displacement = []
    for old, new, requested in zip(baseline, candidate, authored[direction]['rows']):
        measured = [new['receiver'][i] - old['receiver'][i] for i in (0,1)]
        target = [requested['requested_witness_delta_px'][i] + requested.get('seam_delta_px',[0,0])[i] for i in (0,1)]
        displacement.append({'frame': old['frame'], 'requested_px': target, 'measured_px': measured,
                             'error_px': math.dist(target, measured)})
    numeric[spec['candidate']]['displacement'] = displacement
    # Translation-only projection is exact except for float32 matrix precision.
    checks[direction + '_requested_receiver_displacement'] = max(r['error_px'] for r in displacement) < 0.02
    if direction == 'forward':
        checks['forward_preserved_last_unique_seam'] = abs(numeric[spec['candidate']]['receiver_last_unique_to_first_px'] - numeric[spec['baseline']]['receiver_last_unique_to_first_px']) < 0.001
    else:
        checks['backward_receiver_seam_under_3px'] = numeric[spec['candidate']]['receiver_last_unique_to_first_px'] <= 3
checks['source_bytes_unchanged'] = sha(Path(manifest['source'])) == SOURCE_SHA256
checks['candidate_bytes_unchanged'] = sha(path) == manifest['candidate_sha256']
summary = {'status': 'diagnostic', 'passed': all(checks.values()), 'checks': checks,
           'verifier_sha256': sha(Path(__file__).resolve()),
           'candidate_sha256': manifest['candidate_sha256'], 'actions': numeric,
           'scope': 'Reopened source preservation and 480 Hz matrix-contact checks only; no native render or runtime acceptance',
           'required_visual_witnesses': ['forward two dips and raised peak, lateral maximum near f8, clean seam',
                                         'backward two dips f14-17 and f34-37, rise f24-26, roll and <=3px rendered seam',
                                         'both hands, fingers and full skin through complete loops']}
(OUT / 'reopened_numeric_validation.json').write_text(json.dumps(summary, indent=2) + '\n')
(OUT / 'evaluated_tracks_60fps.json').write_text(json.dumps(tracks, indent=2) + '\n')
print(json.dumps({'passed': summary['passed'], 'failed_checks': [k for k,v in checks.items() if not v]}), flush=True)
assert summary['passed'], 'See reopened_numeric_validation.json; do not promote failed numerical candidate'
