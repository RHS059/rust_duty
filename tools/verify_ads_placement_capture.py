#!/usr/bin/env python3
"""Compare native zero-placement and XYZ-offset ADS captures."""
import argparse
import json
from pathlib import Path


def verify(baseline, shifted):
    paths = sorted(baseline.glob('*.gameplay.json'))
    if len(paths) < 530 or [p.name for p in paths] != sorted(p.name for p in shifted.glob('*.gameplay.json')):
        raise ValueError('placement comparison is missing or truncated')
    held = moving = changed_hip = 0
    for path in paths:
        original = json.loads(path.read_text())
        adjusted = json.loads((shifted / path.name).read_text())
        if original != adjusted or original['renderer_failed']:
            raise ValueError('placement changed gameplay/animation telemetry or renderer failed')
        image_name = path.name.removesuffix('.gameplay.json')
        a, b = (baseline / image_name).read_bytes(), (shifted / image_name).read_bytes()
        if any(not image.startswith(b'\x89PNG\r\n\x1a\n') for image in (a, b)):
            raise ValueError('native placement image is invalid')
        if original['route'] == 'ads.hold' and original['run_weight'] == 0:
            if a != b:
                raise ValueError('saved XYZ placement displaced the fully aimed native image')
            held += 1
            moving += original['speed'] > 0.1
        if original['route'] == 'ready' and a != b:
            changed_hip += 1
    if held < 30 or moving < 10 or changed_hip < 20:
        raise ValueError('missing held/moving ADS or effective hip-placement comparison')
    for path in (paths[0], paths[-1]):
        image_name = path.name.removesuffix('.gameplay.json')
        if (baseline / image_name).read_bytes() == (shifted / image_name).read_bytes():
            raise ValueError('hip placement was not present before and after aiming')
    return {'schema': 'rust-duty-ads-placement-capture/v1', 'passed': True,
            'frames': len(paths), 'identical_held_ads_frames': held,
            'identical_moving_ads_frames': moving, 'changed_hip_frames': changed_hip,
            'gameplay_and_animation_telemetry_identical': True,
            'scope': 'Native rendered comparison: saved XYZ has zero effect at full ADS and returns at hip. No new artistic or Windows gameplay claim.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('shifted', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.baseline, args.shifted), indent=2))
