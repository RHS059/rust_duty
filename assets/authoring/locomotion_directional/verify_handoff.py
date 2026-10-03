#!/usr/bin/env python3
"""Validate the portable directional source handoff without modifying files."""
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED = {'hip_walk_forward_r1', 'hip_walk_backward_r1', 'hip_strafe_left_r1', 'hip_strafe_right_r1'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent)
    a = p.parse_args(); root = a.directory.resolve()
    m = json.loads((root / 'handoff.json').read_text())
    source = root / m['source']['file']
    assert source.is_file() and source.parent == root
    assert hashlib.sha256(source.read_bytes()).hexdigest() == m['source']['sha256']
    assert source.stat().st_size == m['source']['bytes']
    assert m['source']['blender_version'] == '4.3.2'
    assert m['source']['source_fps'] == 60 and m['source']['bake_hz'] == 480
    assert set(x['name'] for x in m['clips']) == EXPECTED
    assert m['rig']['deform_bone_count'] == len(m['rig']['deform_bones']) == 72
    assert len(m['rig']['skin_objects']) == 3
    assert m['rig']['rigid_actors'] == ['hk416_weapon', 'hk416_magazine']
    assert m['rig']['excluded_rigid_actor'] == 'hk416_magazine_outgoing'
    for c in m['clips']:
        assert c['action'] == c['name']
        assert c['pose_space'] == 'absolute' and c['additive'] is False and c['loop'] is True
        assert c['frame_start'] == 1 and c['frame_end'] == c['unique_frames'] + 1
        assert abs(c['duration_seconds'] - c['unique_frames'] / 60) < 1e-9
        r = c['reference_periodic_core']
        assert r['time_base'] == '1/15360' and r['fps'] == '60/1'
        assert r['start_pts'] == r['start_frame'] * 256
        assert r['end_pts_exclusive'] == r['end_frame_exclusive'] * 256
        assert r['end_frame_exclusive'] - r['start_frame'] == c['unique_frames']
    for name, record in m['validation_reports'].items():
        rel = Path(record['file']); path = root / rel
        assert not rel.is_absolute() and '..' not in rel.parts and path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'], name
        content = json.loads(path.read_text())
        assert content['passed'] is True, name
    preservation = json.loads((root / m['validation_reports']['source_preservation']['file']).read_text())
    assert preservation['source_sha256'] == m['source']['sha256']
    assert preservation['action_count'] == 66 and preservation['nla_track_count'] == 8 and preservation['driver_count'] == 185
    numerical = json.loads((root / m['validation_reports']['preserved_evaluation']['file']).read_text())
    assert numerical['byte_identical_arrays'] == numerical['array_count'] == 222
    assert numerical['preserved_clip_count'] == 44
    assert numerical['max_position_error_m'] == numerical['max_matrix_component_error'] == 0
    review_record = m['acceptance']['reference_motion_review']
    review_path = root / review_record['file']
    assert hashlib.sha256(review_path.read_bytes()).hexdigest() == review_record['sha256']
    review = json.loads(review_path.read_text())
    assert review['source_blend_sha256'] == m['source']['sha256']
    assert review['hard_gate_status']['candidate_contact'] == 'pass'
    assert review['hard_gate_status']['candidate_local_loop_continuity'] == 'pass'
    assert review['actions']['hip_walk_backward_r1']['all_categories_at_least60percent'] is False
    for row in json.loads((root / 'review' / 'FILE_INVENTORY.json').read_text()):
        path = root / 'review' / row['file']
        assert path.stat().st_size == row['bytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
    assert m['acceptance']['runtime_integration_accepted'] is False
    assert m['acceptance']['whole_reference_fidelity_claim'] is False
    assert m['acceptance']['publication_status'] == 'draft WIP'
    approved_media = {}
    preview_manifest = root / 'previews' / 'preview_manifest.json'
    if preview_manifest.exists():
        for row in json.loads(preview_manifest.read_text()):
            rel = Path(row['path'])
            assert len(rel.parts) == 1 and row['scope'].startswith('Native')
            path = preview_manifest.parent / rel
            assert path.stat().st_size == row['bytes']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
            approved_media[path.resolve()] = row
    for path in root.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix.lower() in ('.mp4', '.webm', '.mov', '.jpg', '.jpeg', '.png'):
            assert path.resolve() in approved_media, 'Unmanifested media is excluded from this handoff: ' + path.name
    print(json.dumps({'passed': True, 'source_sha256': m['source']['sha256'], 'clips': sorted(EXPECTED),
                      'scope': 'Portable source/PTS/pose flags and validation-report integrity; reviewer outcome remains separately stated.'}, indent=2))

if __name__ == '__main__':
    main()
