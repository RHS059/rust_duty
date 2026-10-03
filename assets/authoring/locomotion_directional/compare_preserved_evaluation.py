#!/usr/bin/env python3
"""Compare fresh baseline/candidate evaluated arrays, with explicit tolerances."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', required=True, type=Path)
    p.add_argument('--candidate', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--position-limit-m', type=float, default=1e-6)
    p.add_argument('--matrix-component-limit', type=float, default=1e-6)
    a = p.parse_args()
    baseline = np.load(a.baseline / 'native_oracle.npz')
    candidate = np.load(a.candidate / 'native_oracle.npz')
    old_meta = json.loads((a.baseline / 'native_oracle.json').read_text())
    new_meta = json.loads((a.candidate / 'native_oracle.json').read_text())
    assert set(baseline.files) == set(candidate.files), 'Evaluated array inventory differs'
    assert old_meta['clip_names'] == new_meta['clip_names'], 'Preserved clip order differs'
    assert old_meta['samples'] == new_meta['samples'], 'Sample schedule differs'
    assert old_meta['deform_bones'] == new_meta['deform_bones'], 'Bone order differs'
    rows = {}
    for key in baseline.files:
        x, y = baseline[key], candidate[key]
        assert x.shape == y.shape and x.dtype == y.dtype, key + ': shape/type differs'
        diff = np.abs(x.astype(np.float64) - y.astype(np.float64))
        max_abs = float(diff.max(initial=0))
        position_error = None
        if key.endswith('__bones') or key.endswith('__actors'):
            position_error = float(np.linalg.norm(x[..., :3, 3].astype(np.float64) - y[..., :3, 3].astype(np.float64), axis=-1).max(initial=0))
            passed = max_abs <= a.matrix_component_limit and position_error <= a.position_limit_m
        else:
            position_error = float(np.linalg.norm(x.astype(np.float64) - y.astype(np.float64), axis=-1).max(initial=0))
            passed = position_error <= a.position_limit_m
        rows[key] = {'shape': list(x.shape), 'byte_identical': x.tobytes() == y.tobytes(), 'max_absolute_difference': max_abs,
                     'max_position_error_m': position_error, 'passed': passed,
                     'baseline_sha256': hashlib.sha256(x.tobytes()).hexdigest(), 'candidate_sha256': hashlib.sha256(y.tobytes()).hexdigest()}
    contacts = [r for clip in new_meta['contact_samples'].values() for r in clip]
    report = {'schema': 'rust-duty-preserved-native-evaluation/v1',
              'baseline_sources_sha256': old_meta['source_files_sha256'], 'candidate_sources_sha256': new_meta['source_files_sha256'],
              'preserved_clip_count': len(old_meta['clip_names']), 'array_count': len(rows),
              'byte_identical_arrays': sum(r['byte_identical'] for r in rows.values()),
              'position_limit_m': a.position_limit_m, 'matrix_component_limit': a.matrix_component_limit,
              'max_position_error_m': max(r['max_position_error_m'] for r in rows.values()),
              'max_matrix_component_error': max(r['max_absolute_difference'] for k,r in rows.items() if k.endswith(('__bones','__actors'))),
              'candidate_max_wrist_solve_error_m': max(v for r in contacts for v in r['wrist_solve_error_m'].values()),
              'candidate_max_guard_error_degrees': max(v for r in contacts for v in r['guard_error_degrees'].values()),
              'arrays': rows, 'passed': all(r['passed'] for r in rows.values()),
              'scope': 'Fresh Blender native evaluated old clips; sampled numerical preservation. Not full visual contact certification or runtime blend acceptance.'}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k!='arrays'}, indent=2))
    if not report['passed']:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
