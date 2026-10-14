"""Small original helpers for an unretimed, bounded one-hand mantle correction.

No Blender imports or asset data. These checks report technical facts only.
"""
import math

SOURCE_START = 7787
SOURCE_END_EXCLUSIVE = 7883
ACTION_START = 1
ACTION_END = 96
PROTECTED_INTERVALS = ((1.0, 8.0), (89.0, 96.0))
WEAPON_PROTECTED_INTERVALS = ((1.0, 8.0), (85.0, 96.0))


def source_frame(action_frame):
    if not ACTION_START <= action_frame <= ACTION_END:
        raise ValueError('Action frame outside native reviewed range')
    return SOURCE_START + action_frame - ACTION_START


def smooth5(t):
    t = max(0.0, min(1.0, t))
    return t * t * t * (10.0 + t * (-15.0 + 6.0 * t))


def interpolate(rows, frame):
    """Bounded quintic key interpolation, without overshoot or retiming."""
    if frame <= rows[0][0]:
        return tuple(rows[0][1:])
    if frame >= rows[-1][0]:
        return tuple(rows[-1][1:])
    for left, right in zip(rows, rows[1:]):
        if left[0] <= frame <= right[0]:
            alpha = smooth5((frame-left[0]) / (right[0]-left[0]))
            return tuple(a+(b-a)*alpha for a,b in zip(left[1:],right[1:]))
    raise ValueError('Invalid key rows')


def protected(frame):
    return any(start <= frame <= end for start,end in PROTECTED_INTERVALS)


def weapon_protected(frame):
    return any(start <= frame <= end for start,end in WEAPON_PROTECTED_INTERVALS)


def evaluation_times(divisions=16, switches=(44.0,65.0)):
    """Include 960 Hz baseline plus dense ownership switch neighborhoods."""
    if not isinstance(divisions,int) or divisions < 4:
        raise ValueError('At least quarter-frame evaluation is required')
    times = {1+i/divisions for i in range(95*divisions+1)}
    for switch in switches:
        for delta in (-.01,-.001,-.0001,0.,.0001,.001,.01):
            if 1 <= switch+delta <= 96:
                times.add(switch+delta)
    return sorted(times)


def validate_report(report):
    """A numerical pass does not certify a render, contact or runtime motion."""
    tests = {
        'source_identity': report.get('input_sha256') ==
            'f289c6d404a6c9c276baac3089887f77a15ac2d18029e1aa39f66d6e335081df',
        'native_mapping': report.get('source_window') == [SOURCE_START,SOURCE_END_EXCLUSIVE]
            and report.get('fps') == [60,1] and report.get('frames') == 96,
        'prior_actions_preserved': report.get('prior_actions_preserved') is True,
        'structure_preserved': report.get('structure_preserved') is True,
        'protected_pose': report.get('protected_pose_max_delta',math.inf) <= 1e-6,
        'protected_weapon': report.get('protected_weapon_max_delta',math.inf) <= 1e-6,
        'finite_skin': report.get('all_skin_finite') is True,
        'finite_bones': report.get('all_bones_finite') is True,
        'valid_drivers': report.get('all_drivers_valid') is True,
        'dense_coverage': report.get('samples',0) >= 1521,
        'support_reattached': report.get('support_follow_at_65',0) >= .999,
        'support_target': report.get('max_wrist_target_mm',math.inf) < .1,
        'guard_not_clipped': report.get('max_attached_guard_delta_deg',math.inf) < .1,
        'right_guard_not_clipped': report.get('max_right_guard_delta_deg',math.inf) < .1,
        'free_guard': report.get('min_free_guard_margin_deg',-math.inf) > 0,
        'switch_position': report.get('max_switch_position_mm',math.inf) < .05,
        'switch_rotation': report.get('max_switch_rotation_deg',math.inf) < .1,
    }
    return [name for name,ok in tests.items() if not ok]
