"""One bounded read-only feasibility probe of an existing anatomy control.

Open the rejected local r6 BLEND with autoexec disabled. No Action is changed,
no guard is relaxed, no file is saved, and nothing is rendered. This script
requires a new coordinator resource window.
"""
import bpy
import hashlib
import json
import math
import sys
from pathlib import Path

OUT = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
assert not OUT.exists(), 'Refuse overwrite of feasibility evidence'
source = Path(bpy.data.filepath)
before = hashlib.sha256(source.read_bytes()).hexdigest()
assert before == 'c072976d9e3846a6b0d9229984994f9e4b21ae1a28cdc6692279ac259e2dc7d9'
rig = bpy.data.objects['Arms']
scene = bpy.context.scene
for obj in bpy.data.objects:
    if obj.animation_data:
        for track in obj.animation_data.nla_tracks:
            track.mute = True
            track.is_solo = False
rig.animation_data.use_nla = False
base = bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered']
rig.animation_data.action = base
scene.frame_set(1)
bpy.context.view_layer.update()
rig.animation_data.action = bpy.data.actions['hip_walk_backward_elara_r6']
control = rig.pose.bones['righthand_prop_lefthand']
saved = float(control['wrist_twist'])
values = [-6.0, -3.0, 0.0, 3.0, 6.0]
rows = []
for k in range(49):
    frame = 26 + k / 4
    floor = math.floor(frame)
    for value in values:
        scene.frame_set(floor, subframe=frame-floor)
        control['wrist_twist'] = value
        rig.update_tag(refresh={'OBJECT'})
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        deps.update()
        er = rig.evaluated_get(deps)
        guard = er.pose.bones['MCH_hand_guarded_l'].matrix
        goal = er.pose.bones['MCH_attach_goal_l'].matrix
        hand = er.pose.bones['hand_l'].matrix
        pos_target = er.pose.bones['righthand_prop_lefthand'].matrix.translation
        rows.append({'frame': frame, 'wrist_twist_degrees': value,
                     'guard_error_degrees': math.degrees(guard.to_quaternion().rotation_difference(goal.to_quaternion()).angle),
                     'hand_goal_matrix_error': max(abs(hand[i][j]-goal[i][j]) for i in range(4) for j in range(4)),
                     'wrist_position_error_m': (hand.translation-pos_target).length,
                     'forearm_roll_degrees': math.degrees(er.pose.bones['MCH_attach_forearm_l'].rotation_euler.y)})
control['wrist_twist'] = saved
assert hashlib.sha256(source.read_bytes()).hexdigest() == before
by_value = {str(v): {'max_guard_error_degrees': max(r['guard_error_degrees'] for r in rows if r['wrist_twist_degrees']==v),
                    'max_hand_goal_matrix_error': max(r['hand_goal_matrix_error'] for r in rows if r['wrist_twist_degrees']==v),
                    'max_wrist_position_error_m': max(r['wrist_position_error_m'] for r in rows if r['wrist_twist_degrees']==v)}
            for v in values}
result = {'status': 'diagnostic feasibility only', 'source_sha256': before,
          'fixed_probe_values_degrees': values, 'frames_inclusive': [26,38], 'sample_step_frames': 0.25,
          'guard_definitions_changed': False, 'actions_changed': False, 'source_saved': False,
          'summary': by_value, 'rows': rows,
          'scope': 'Does not approve a new Action, anatomy, full-cycle contacts or visual match'}
OUT.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(by_value,indent=2),flush=True)
