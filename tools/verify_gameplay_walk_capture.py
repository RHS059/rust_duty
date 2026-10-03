#!/usr/bin/env python3
"""Verify real native renderer walking loops and return to ready from movement input."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def verify(folder: Path):
    paths = sorted(folder.glob('*.gameplay.json'))
    if len(paths) < 180:
        raise ValueError('native walking capture is missing or truncated')
    rows = [json.loads(path.read_text()) for path in paths]
    walking = [(i, row) for i, row in enumerate(rows) if row['route'] == 'regular_walk']
    if len(walking) <= 100 or any(row['sprinting'] or row['renderer_failed'] for row in rows):
        raise ValueError('authored grounded walking route did not render cleanly')
    if not all(row['grounded'] and row['speed'] > 0.1 for _, row in walking):
        raise ValueError('walk route was not driven by actual grounded movement')
    times = [row['native_clip_seconds'] for _, row in walking]
    duration = walking[0][1]['clip_duration']
    if not duration > 0 or max(times) <= 2 * duration or not all(a < b for a, b in zip(times, times[1:])):
        raise ValueError('native walking failed to advance across two complete loops')
    if rows[0]['route'] != 'locomotion' or rows[-1]['route'] != 'locomotion' or rows[-1]['speed'] > 0.1:
        raise ValueError('walking did not start and stop in authored ready')
    displacement = math.dist(rows[0]['position'], rows[-1]['position'])
    if displacement <= 0.5:
        raise ValueError('capture lacks actual simulated forward displacement')
    hashes = []
    for index, _ in walking:
        image = Path(str(paths[index]).removesuffix('.gameplay.json')).read_bytes()
        if not image.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('native screenshot is missing or invalid')
        hashes.append(hashlib.sha256(image).hexdigest())
    if len(set(hashes)) < 30:
        raise ValueError('walking images do not show authored motion')
    report = {'schema': 'rust-duty-native-walk-capture/v1', 'passed': True,
              'frames': len(rows), 'walking_frames': len(walking), 'loop_duration': duration,
              'max_native_clip_seconds': max(times), 'distinct_walking_images': len(set(hashes)),
              'displacement_m': displacement, 'returned_to_ready': True,
              'scope': 'Real input, simulation and native renderer. Whole-model start/stop cuts remain WIP; no artistic approval.'}
    (folder / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    print(json.dumps(verify(parser.parse_args().folder), indent=2))
