"""Narrow observed visibility cues; passing is not a rendered or artistic approval."""
import math

def validate_projection(report):
    rows = {r['native']: r for r in report['samples']}
    def outside(row):
        x0, y0, x1, y1 = row['projected_bbox_pixels']
        return x1 < 0 or x0 > 1280 or y1 < 0 or y0 > 720
    checks = {'hand_mask_present': report['selected_vertex_count'] > 500}
    checks['classification_matches_bounds'] = all(outside(r) == r['bbox_disjoint_from_viewport'] for r in rows.values())
    for n in (7293, 7296, 7331, 7332):
        checks[f'visible_cue_{n}'] = n in rows and not outside(rows[n])
    checks['middle_out_of_view_7315'] = 7315 in rows and outside(rows[7315])
    checks['exact_native_mapping'] = all(r['blender_frame'] == r['native'] - 7283 for r in rows.values())
    checks['finite_projection'] = all(math.isfinite(v) for r in rows.values() for v in r['projected_bbox_pixels'])
    return [name for name, passed in checks.items() if not passed]
