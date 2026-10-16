"""Bounded r6 hypotheses from Elara PR41 comment 6158919419.

Positive X is image-right; positive Y is image-down. Roll is clockwise in
the image. Pixel requests are calibrated at a fixed native receiver witness,
not treated as a cross-weapon landmark match or a measured render result.
"""
import math

SOURCE_SHA256 = 'f7d6e76d387a07508f61b2ade708fa930b93bd73b167110469a43c88ecf8eaf4'
REVIEW_URL = 'https://github.com/RHS059/rust_duty/pull/41#issuecomment-6158919419'
PREFIX = 'pose.bones["righthand_prop"].'
PROFILES = {
    'forward': {
        'baseline': 'hip_walk_forward_r5',
        'candidate': 'hip_walk_forward_elara_r6',
        'period': 38,
        'reference_start': 48,
        'x': [(1, 0), (2, 0), (5, 8), (8, 28), (12, 23), (16, 8),
              (20, 0), (24, -11), (28, -18), (32, -18), (36, -11),
              (37, -4), (38, 0), (39, 0)],
        'y': [(1, 0), (2, 0), (6, 11), (10, 20), (13, 17), (15, 0),
              (17, -19), (21, -25), (25, -19), (27, 0), (29, 6),
              (31, 9), (33, 6), (36, 0), (38, 0), (39, 0)],
        'roll': [(1, 0), (39, 0)],
        'allowed': ['location'],
        'preserved_keys': [1, 2, 38, 39],
        'bounds': {'x_px': 28, 'y_px': 25, 'roll_degrees': 0},
    },
    'backward': {
        'baseline': 'hip_walk_backward_r5',
        'candidate': 'hip_walk_backward_elara_r6',
        'period': 45,
        'reference_start': 211,
        'x': [(1, 13), (4, 15), (8, 13), (12, 10), (18, 0),
              (24, -15), (28, -27), (31, -25), (33, -15), (36, 0),
              (39, 11), (41, 17), (43, 14), (46, 13)],
        'y': [(1, 0), (7, 0), (12, 7), (15, 15), (17, 13), (19, 0),
              (21, -12), (25, -21), (29, -12), (32, 0), (35, 15),
              (37, 17), (40, 15), (42, 11), (46, 0)],
        'roll': [(1, -6), (7, -6), (14, 0), (24, 1), (30, 6),
                 (34, 6), (40, 0), (46, -6)],
        'allowed': ['location', 'rotation_euler'],
        'preserved_keys': [],
        'bounds': {'x_px': 27, 'y_px': 21, 'roll_degrees': 6},
    },
}


def smoothstep5(t):
    t = min(1.0, max(0.0, t))
    return t * t * t * (10 + t * (-15 + 6 * t))


def evaluate_knots(knots, frame):
    if frame <= knots[0][0]:
        return float(knots[0][1])
    if frame >= knots[-1][0]:
        return float(knots[-1][1])
    for (a, va), (b, vb) in zip(knots, knots[1:]):
        if a <= frame <= b:
            return va + (vb - va) * smoothstep5((frame - a) / (b - a))
    raise ValueError(frame)


def correction(direction, frame):
    p = PROFILES[direction]
    return tuple(evaluate_knots(p[k], frame) for k in ('x', 'y', 'roll'))


def periodic_cubic(values, frame):
    """Evaluate central-difference cubic through unique integer values, periodic."""
    count = len(values)
    t = (frame - 1) % count
    index = math.floor(t)
    u = t - index
    a, b = values[index], values[(index + 1) % count]
    ma = (values[(index + 1) % count] - values[(index - 1) % count]) / 2
    mb = (values[(index + 2) % count] - values[index]) / 2
    return (2*u**3 - 3*u**2 + 1)*a + (u**3 - 2*u**2 + u)*ma + (-2*u**3 + 3*u**2)*b + (u**3 - u**2)*mb


def native_map(direction):
    p = PROFILES[direction]
    return [dict(action=p['candidate'], action_frame=f,
                 reference_id='5KM0XSKxTWw', source_frame=p['reference_start'] + f - 1,
                 source_pts_ticks=(p['reference_start'] + f - 1) * 256,
                 output_pts_ticks=(f - 1) * 256, time_base='1/15360',
                 closure_witness=f == p['period'] + 1,
                 include_in_unique_playback=f <= p['period'])
            for f in range(1, p['period'] + 2)]
