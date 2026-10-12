#!/usr/bin/env python3
"""Compare native zero-placement and XYZ-offset ADS captures."""
import argparse
import json
from pathlib import Path

from PIL import Image
import verify_capture_frame_witness as witness
from verify_capture_telemetry import read_record


def comparison_bytes(image):
    """Ignore only a valid validation marker; ordinary PNG comparison is unchanged.

    Current aggregate callers independently bind each identity to invocation.
    This local validator additionally rejects malformed/mismatched marker pixels.
    """
    metadata = read_record(Path(str(image) + '.json')) if Path(str(image) + '.json').is_file() else {}
    if 'frame_witness' not in metadata:
        return image.read_bytes(), False
    if not image.stem.isdecimal():
        raise ValueError('witnessed placement frame needs a numeric filename')
    binding = metadata['frame_witness']
    identity = binding.get('capture_identity') if isinstance(binding, dict) else None
    witness.verify(image, metadata, int(image.stem), identity)
    with Image.open(image) as source:
        pixels = source.convert('RGBA')
        width, height = pixels.size
        # The witness is an actual-render diagnostic, not a sight/world pixel.
        return (pixels.crop((64, 0, width, 22)).tobytes() +
                pixels.crop((0, 22, width, height)).tobytes()), True


def same_capture(left, right):
    a, marked_a = comparison_bytes(left)
    b, marked_b = comparison_bytes(right)
    if marked_a != marked_b:
        raise ValueError('placement comparison mixes witnessed and ordinary captures')
    return a == b


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
            if not same_capture(baseline / image_name, shifted / image_name):
                raise ValueError('saved XYZ placement displaced the fully aimed native image')
            held += 1
            moving += original['speed'] > 0.1
        if original['route'] == 'ready' and not same_capture(baseline / image_name, shifted / image_name):
            changed_hip += 1
    if held < 30 or moving < 10 or changed_hip < 20:
        raise ValueError('missing held/moving ADS or effective hip-placement comparison')
    for path in (paths[0], paths[-1]):
        image_name = path.name.removesuffix('.gameplay.json')
        if same_capture(baseline / image_name, shifted / image_name):
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
