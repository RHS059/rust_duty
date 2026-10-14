"""Source-free checks for the actual authoring/verification receipt."""
import math

def validate(summary):
    failures=[]
    if summary.get('action_count') != 114: failures.append('Expected 112 preserved Actions plus the isolated rig/camera pair')
    if set(summary.get('actions',{})) != {'prone_crawl_enter_r6','prone_crawl_enter_camera_r6'}: failures.append('Both paired Action fingerprints are required')
    if summary.get('sample_count') != 545: failures.append('Complete 480 Hz interval required')
    p=summary.get('fresh_reopen_preservation',{})
    if not p or not all(p.values()): failures.append('Source preservation failed or missing')
    if summary.get('protected_f1_to_11_all_bone_max_difference') != 0: failures.append('Protected early poses changed')
    if summary.get('all_bone_matrices_finite') is not True or summary.get('all_drivers_valid') is not True: failures.append('Invalid evaluated data')
    contacts=summary.get('contact_480hz_max_m',{})
    if set(contacts)!={'l','r'} or any(not math.isfinite(v) or v>=.0001 for v in contacts.values()): failures.append('Hand target residual exceeded 0.1 mm or missing')
    guard=summary.get('new_wrist_guard_max_deg',{})
    old=summary.get('old_wrist_guard_max_deg',{})
    if set(guard)!={'l','r'} or set(old)!={'l','r'} or any(not math.isfinite(v) or v>max(.08,max(old.values())+.05) for v in guard.values()): failures.append('Wrist guard changed beyond allowance')
    if any(v>.05 or not math.isfinite(v) for v in summary.get('max_wrist_guard_increase_deg',{'missing':float('inf')}).values()): failures.append('A wrist guard residual became worse than r5 at the same frame')
    if not .299<summary.get('min_camera_height_above_ground_m',-1)<.301: failures.append('Real camera depth not verified')
    if not 0<=summary.get('max_optic_projection_error_px',float('inf'))<.002: failures.append('Camera-relative weapon target not verified')
    if summary.get('no_render') is not True or summary.get('visual_pass') is not None: failures.append('Numerical audit must not claim an artistic pass')
    return failures
