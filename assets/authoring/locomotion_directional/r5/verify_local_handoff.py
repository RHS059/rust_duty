#!/usr/bin/env python3
"""Verify the local r5 handoff without opening Blender, editing or publishing."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE_SHA = 'd220162819fb7267aa6b93b209afc8ce5212a0692e6a4e02c5c43602b08907e3'
EXPECTED = {'hip_walk_forward_r5': 38, 'hip_walk_backward_r5': 45,
            'hip_strafe_left_r5': 49, 'hip_strafe_right_r5': 49}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def safe(rel):
    part = Path(rel)
    assert not part.is_absolute() and '..' not in part.parts
    return ROOT / part

def main():
    m = json.loads((ROOT / 'integration_handoff.json').read_text())
    assert m['baseline_source_sha256'] == BASE_SHA
    assert m['status'] == 'local handoff; review and Elara approval pending'
    assert m['approval_and_commit_owner'] == 'Elara'
    assert m['git_writes_performed'] is m['production_activation_performed'] is False
    source = safe(m['source']['file'])
    assert source.stat().st_size == m['source']['bytes'] and sha(source) == m['source']['sha256']
    c = json.loads((ROOT / 'preview_export_config.json').read_text())
    assert c['source_fps'] == 60 and c['bake_hz'] == 480 and c['deform_bone_count'] == 72
    assert c['rigid_actors'] == ['hk416_weapon', 'hk416_magazine'] and len(c['skin_objects']) == 3
    assert {t['name'] for t in c['source_takes']} == set(EXPECTED)
    for t in c['source_takes']:
        assert t['name'] == t['action'] and t['prior_revision_action'] == t['name'].replace('_r5', '_r4')
        assert t['frame_start'] == 1 and t['frame_end'] == EXPECTED[t['name']] + 1
        assert abs(t['duration_seconds'] - EXPECTED[t['name']] / 60) < 1e-9
        assert t['pose_space'] == 'absolute' and t['additive'] is False and t['loop'] is True
        ref = t['reference_anchor']; start, end = ref['frame_range_half_open']
        assert ref['pts_range_half_open'] == [start * 256, end * 256]
        assert ref['time_base'] == '1/15360' and end - start == EXPECTED[t['name']]
    reports = {}
    for rel, row in m['validation_reports'].items():
        file = safe(rel); assert sha(file) == row['sha256'] and file.stat().st_size == row['bytes']
        report = json.loads(file.read_text()); assert report['passed'] is True
        reports[rel] = report
    s = reports['source_preservation.json']
    assert s['source_sha256'] == m['source']['sha256'] and s['baseline_source_sha256'] == BASE_SHA
    assert s['action_count'] == 82 and s['nla_track_count'] == 8 and s['driver_count'] == 185
    old = reports['preserved_evaluation.json']
    assert old['preserved_clip_count'] == 60 and old['byte_identical_arrays'] == old['array_count'] == 302
    assert old['max_position_error_m'] == old['max_matrix_component_error'] == 0
    assert set(reports['preview_export_validation.json']['takes']) == set(EXPECTED)
    assert set(reports['validation/native_validation.json']['actions']) == set(EXPECTED)
    for lane in ('longitudinal', 'lateral'):
        o = reports[f'lane_validation/{lane}/preserved_evaluation.json']
        n = reports[f'lane_validation/{lane}/combined_evaluation_identity.json']
        assert o['byte_identical_arrays'] == 302 and n['byte_identical_arrays'] == 12
        subset = json.loads((ROOT / f'creators/{lane}/creator_subset_manifest.json').read_text())
        for rel, row in subset['files'].items():
            path = safe(f'creators/{lane}/{rel}')
            assert sha(path) == row['sha256'] and path.stat().st_size == row['bytes']
    assert m['earlier_reference_scores_reused_for_r5'] is m['new_reference_fidelity_claim'] is False
    count = 0
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        digest, rel = line.split('  ', 1); assert sha(safe(rel)) == digest, rel; count += 1
    print(json.dumps({'passed': True, 'source_sha256': m['source']['sha256'], 'checked_files': count,
                      'prior_actions': 78, 'prior_clips': 60, 'byte_identical_prior_arrays': 302,
                      'scope': 'Local source/export/preservation handoff; visual and runtime acceptance pending'}, indent=2))

if __name__ == '__main__':
    main()
