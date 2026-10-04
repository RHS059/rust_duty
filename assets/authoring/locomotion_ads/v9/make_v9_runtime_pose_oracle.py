"""Native forward v9 complete-pose oracle. Numeric evaluation only; no render.

Run with Blender 4.3.2 and ADS_V9_HIP_SOURCE pointing to the pinned r5 source.
The original source and the PR23 comparison bake are read without modification.
"""
import bpy
import hashlib
import json
import math
from pathlib import Path
from mathutils import Matrix, Quaternion, Vector

P = Path(__file__).resolve().parent
probe = P / 'probe_v9_articulation.py'
exec(compile(probe.read_text().split('connected=[]', 1)[0], str(probe), 'exec'), globals())
R = Matrix.Diagonal((-1., 1., -1., 1.))
F = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
def matrix_rows(m):
    return [list(row) for row in m]
def matrix_error(a, b):
    return max(abs(x-y) for ar, br in zip(a, b) for x, y in zip(ar, br))
camera_basis_residue = matrix_error(F @ C, R)
assert camera_basis_residue < 1e-6, camera_basis_residue
bone_names = [bone.name for bone in A.data.bones if bone.use_deform]
assert len(bone_names) == 72
actor_names = ['hk416_weapon', 'hk416_magazine']
select('ads_hold_r1')
held_actor_globals = {name: bpy.data.objects[name].matrix_world.copy() for name in actor_names}
held_actor_relative = {name: baseW.inverted() @ m for name, m in held_actor_globals.items()}
frames = [0, 3, 7, 8, 12, 18, 24, 28, 31, 32, 39, 40, 41.5, 41.75, 42, 47, 55, 58, 64, 72, 78, 79, 95, 103, 113, 125]
cases = []
def receiver_target(d):
    m = Quaternion().slerp(d.to_quaternion(), .4).to_matrix().to_4x4()
    m.translation = d.translation * .4
    return m @ p0
for j in frames:
    primary = 1 + ((j + 5.75) * .8) % 38
    secondary = 1 + ((j + 5.75) * .8 + 19) % 38
    select('hip_walk_forward_r5', primary)
    primary_weapon = W.matrix_world.copy()
    primary_bones = globals_now()
    primary_actors = {name: bpy.data.objects[name].matrix_world.copy() for name in actor_names}
    delta0 = (C.inverted() @ primary_weapon) @ ready.inverted()
    select('hip_walk_forward_r5', secondary)
    delta1 = (C.inverted() @ W.matrix_world) @ ready.inverted()
    primary_target = receiver_target(delta0)
    secondary_target = receiver_target(delta1)
    u = u0 + (primary_target.x / -primary_target.z - u0) * .25
    v = secondary_target.y / -secondary_target.z
    angle = math.atan2(v, u) - math.atan2(p0.y, p0.x)
    angle = math.atan2(math.sin(angle), math.cos(angle))
    depth = -math.hypot(p0.x, p0.y) / math.hypot(u, v) - p0.z
    offset = Matrix.Rotation(angle, 4, 'Z')
    offset.translation = Vector((0, 0, depth))
    anchor = C @ offset @ C.inverted() @ baseW
    expected_bones = {
        name: anchor @ blend(baseRel[name], primary_weapon.inverted() @ primary_bones[name], .15)
        for name in bone_names
    }
    # Exact preview semantics carry held rigid actors under the one weapon anchor.
    expected_actors = {name: anchor @ held_actor_relative[name] for name in actor_names}
    actor_relative_residue = max(
        matrix_error(primary_weapon.inverted() @ primary_actors[name], held_actor_relative[name])
        for name in actor_names
    )
    cases.append({
        'output_frame': j,
        'primary_native_frame': primary,
        'secondary_native_frame': secondary,
        'primary_weapon_asset': matrix_rows(F @ primary_weapon),
        'primary_bone_globals_asset': [matrix_rows(F @ primary_bones[name]) for name in bone_names],
        'primary_actor_globals_asset': [matrix_rows(F @ primary_actors[name]) for name in actor_names],
        'primary_delta_asset': matrix_rows(R @ delta0 @ R),
        'secondary_delta_asset': matrix_rows(R @ delta1 @ R),
        'expected_offset_asset': matrix_rows(R @ offset @ R),
        'expected_weapon_asset': matrix_rows(F @ anchor),
        'expected_bone_globals_asset': [matrix_rows(F @ expected_bones[name]) for name in bone_names],
        'expected_actor_globals_asset': [matrix_rows(F @ expected_actors[name]) for name in actor_names],
        'input_actor_relative_max_component_residue': actor_relative_residue,
    })
frozen_source = P / 'ads_v9_depthphase_public47_hipr5_diagnostic.blend'
source_sha = hashlib.sha256(frozen_source.read_bytes()).hexdigest()
assert source_sha == '094c54c25815126479ca30051a15b8e8dd8f0b4f7bab0767ba96599534652c62'
held_bones_asset = [matrix_rows(F @ base[name]) for name in bone_names]
held_actors_asset = [matrix_rows(F @ held_actor_globals[name]) for name in actor_names]
bpy.ops.wm.open_mainfile(filepath=str(frozen_source))
scene = bpy.data.scenes['ADS V9 Depth Phase Diagnostic']
if bpy.context.window:
    bpy.context.window.scene = scene
diagnostic_rig = bpy.data.objects['DIAG_V9_Arms']
maximum_bone = 0.
maximum_actor = 0.
for case in cases:
    frame = case['output_frame'] + 1
    scene.frame_set(math.floor(frame), subframe=frame % 1)
    bpy.context.view_layer.update()
    actual_bones = [F @ diagnostic_rig.matrix_world @ diagnostic_rig.pose.bones[name].matrix for name in bone_names]
    actual_actors = [F @ bpy.data.objects['DIAG_V9_' + name].matrix_world for name in actor_names]
    bone_residue = max(matrix_error(a, Matrix(b)) for a, b in zip(actual_bones, case['expected_bone_globals_asset']))
    actor_residue = max(matrix_error(a, Matrix(b)) for a, b in zip(actual_actors, case['expected_actor_globals_asset']))
    case['saved_bone_globals_asset'] = [matrix_rows(m) for m in actual_bones]
    case['saved_actor_globals_asset'] = [matrix_rows(m) for m in actual_actors]
    case['saved_bone_max_component_residue'] = bone_residue
    case['saved_actor_max_component_residue'] = actor_residue
    maximum_bone = max(maximum_bone, bone_residue)
    maximum_actor = max(maximum_actor, actor_residue)
report = {
    'schema': 'rust-duty-v9-complete-pose-oracle/v1',
    'candidate_id': 'ads-v9-depthphase-forward-public47-r5',
    'source_commit': 'f6c0d0f9efc3c8b78f63c6b3e292326e476f30b1',
    'source_blend_sha256': source_sha,
    'source_hip_sha256': '36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d',
    'source_ads_sha256': '3acdf3e2d04757d719ba59ede08decdf8bad48e2e87d9448046fe8edcbba4f58',
    'matrix_convention': 'Row-major arrays, column vectors, metres. Asset=F*BlenderWorld; apply game_model_root Ry(pi) once for display. Expected globals are ideal evaluated composition before runtime local-TRS reconstruction.',
    'world_to_asset': matrix_rows(F),
    'camera_to_asset_basis': matrix_rows(R),
    'camera_basis_residue': camera_basis_residue,
    'bone_names': bone_names,
    'actor_names': actor_names,
    'receiver_point_camera': list(p0),
    'held_weapon_asset': matrix_rows(F @ baseW),
    'ready_weapon_asset': matrix_rows(R @ ready),
    'held_bone_globals_asset': held_bones_asset,
    'held_actor_globals_asset': held_actors_asset,
    'articulation_weight': .15,
    'cases': cases,
    'saved_bone_max_component_residue': maximum_bone,
    'saved_actor_max_component_residue': maximum_actor,
    'strict_bake_tolerance': 1e-5,
    'strict_bake_pass': maximum_bone <= 1e-5 and maximum_actor <= 1e-5,
    'scope': '26 pure-forward full-ADS native samples. Partial ADS, direction mixtures and transitions need runtime tests. No visual acceptance or score.',
    'rendered': False,
}
(P / 'v9_complete_pose_runtime_oracle.json').write_text(json.dumps(report, separators=(',', ':')) + '\n')
print(json.dumps({key: report[key] for key in ['camera_basis_residue', 'saved_bone_max_component_residue', 'saved_actor_max_component_residue', 'strict_bake_pass']}), flush=True)
