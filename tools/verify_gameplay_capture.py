#!/usr/bin/env python3
"""Verify native game captures came through accepted reload and returned to play."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(folder: Path):
    paths = sorted(folder.glob('*.gameplay.json'))
    if len(paths) < 60:
        raise ValueError('native gameplay capture is missing or truncated')
    records = [json.loads(path.read_text()) for path in paths]
    hashes = []
    for path in paths:
        png = Path(str(path).removesuffix('.gameplay.json')).read_bytes()
        if not png.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('native screenshot is not a PNG')
        hashes.append(hashlib.sha256(png).hexdigest())
    tactical = [(i, record) for i, record in enumerate(records) if record['route'] == 'reload.tactical']
    if len(tactical) < 60 or not all(record['accepted_r_issued'] for _, record in tactical):
        raise ValueError('accepted R did not produce sustained authored reload playback')
    times = [record['native_clip_seconds'] for _, record in tactical]
    if not all(a < b for a, b in zip(times, times[1:])) or max(times) < 2.5:
        raise ValueError('native authored reload time did not advance through full WIP')
    first, last = tactical[0][0], tactical[-1][0]
    if not any(r['route'] == 'locomotion' for r in records[:first]) or not any(r['route'] == 'locomotion' for r in records[last + 1:]):
        raise ValueError('capture lacks initial gameplay or return to locomotion')
    if len({hashes[i] for i, _ in tactical}) < 10:
        raise ValueError('native reload screenshots do not show changing frames')
    if len({r['ammo'] + r['reserve'] for r in records}) != 1:
        raise ValueError('reload capture changed total ammunition')
    increases = [(prev, curr) for prev, curr in zip(records, records[1:]) if curr['ammo'] > prev['ammo']]
    if len(increases) != 1:
        raise ValueError('expected exactly one magazine credit')
    previous, credited = increases[0]
    credit_at = credited['reload_credit_at'] or previous['reload_credit_at']
    if credit_at <= 0 or credited['simulation_time'] + 1e-6 < credit_at:
        raise ValueError('magazine credited before gameplay credit boundary')
    result = {'schema': 'rust-duty-native-gameplay-capture/v1', 'passed': True,
              'frames': len(records), 'reload_frames': len(tactical),
              'max_native_clip_seconds': max(times), 'distinct_reload_images': len({hashes[i] for i, _ in tactical}),
              'returned_to_locomotion': True, 'ammo_credit_count': len(increases),
              'scope': 'Actual native game renderer and committed R simulation; visual review still required.'}
    (folder / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    print(json.dumps(verify(parser.parse_args().folder), indent=2))
