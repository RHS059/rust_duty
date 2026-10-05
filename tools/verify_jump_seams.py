#!/usr/bin/env python3
"""Check stable jump phase endpoints with the actual Rust runtime sampler.

This is numerical endpoint/air-hold evidence, not continuous visual approval.
Ground-contact interruption blending belongs to the committed controller tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np


def sample(sampler, asset, clip, time):
    output = subprocess.check_output([str(sampler.resolve()), str(asset.resolve()),
                                     clip, str(time), '--clamp'], text=True)
    return json.loads(output)


def positions(row):
    return np.asarray([p for mesh in row['skin_meshes'] + row['rigid_meshes']
                       for p in mesh['positions']])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('asset', type=Path)
    parser.add_argument('--sampler', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    pairs = [
        ('ready_takeoff', ('normal_ready', 0), ('jump_takeoff', 0)),
        ('takeoff_air', ('jump_takeoff', 11 / 60), ('jump_air', 0)),
        ('air_land', ('jump_air', 23 / 60), ('jump_land', 0)),
        ('land_ready', ('jump_land', 28 / 60), ('normal_ready', 0)),
        ('air_endpoint_hold', ('jump_air', 23 / 60), ('jump_air', 23 / 60 + 3)),
    ]
    checks = []
    for name, left, right in pairs:
        a = sample(args.sampler, args.asset, *left)
        b = sample(args.sampler, args.asset, *right)
        pa, pb = positions(a), positions(b)
        if pa.shape != pb.shape:
            raise ValueError('seam sample geometry dimensions changed')
        error = float(np.linalg.norm(pa - pb, axis=1).max())
        visible = [x['visible'] for x in a['actors']] == [x['visible'] for x in b['actors']]
        checks.append(dict(name=name, left=left, right=right,
                           max_vertex_error_m=error, visibility_matches=visible,
                           passed=error <= 0.001 and visible))
    report = dict(schema='rust-duty-jump-runtime-seams/v1', backend='Rust CPU sampler',
                  asset_sha256=hashlib.sha256(args.asset.read_bytes()).hexdigest(),
                  declared_position_limit_m=0.001, checks=checks,
                  passed=all(x['passed'] for x in checks),
                  scope='Exact endpoint positions and clamped air hold only. Velocity, visual approval, and native gameplay are separate evidence.')
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    if not report['passed']:
        raise SystemExit('jump runtime endpoint mismatch')


if __name__ == '__main__':
    main()
