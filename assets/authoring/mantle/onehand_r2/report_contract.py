"""Technical gates only. Passing these never certifies appearance or contact surfaces."""
def validate(summary):
    failures = []
    checks = {
        'finite_skin_and_bones': summary['all_finite'],
        'driver_validity': summary['all_drivers_valid'],
        'unchanged_weapon': summary['weapon_matrix_max_component_delta'] == 0,
        'wrist_position': summary['max_wrist_target_mm'] < 0.1,
        'attached_wrist_guard': summary['max_attached_guard_delta_deg'] < 0.1,
        'free_wrist_guard': summary['min_free_guard_margin_deg'] > 0,
        'source_switch_position': all(v['position_mm'] < 0.05 for v in summary['switches'].values()),
        'source_switch_rotation': all(v['rotation_deg'] < 0.1 for v in summary['switches'].values()),
        'full_skin_coverage': summary['finite_skin_vertex_samples'] > 3800000,
        'dense_time_coverage': summary['samples'] >= 1533,
    }
    return [name for name, passed in checks.items() if not passed]
