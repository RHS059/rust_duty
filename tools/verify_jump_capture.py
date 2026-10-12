#!/usr/bin/env python3
"""Validate real native Jump replay output; does not assign an artistic score."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def verify(folder):
    paths = sorted(folder.glob('*.gameplay.json'))
    rows = [json.loads(p.read_text()) for p in paths]
    if len(rows) < 390 or any(r['sampling_hz'] != 60 for r in rows):
        raise ValueError('missing/truncated 60 Hz Jump native capture')
    if any(r['renderer_failed'] or r['pose_crc32'] is None for r in rows):
        raise ValueError('Jump native loader or renderer failed')
    ticks = [round(r['simulation_time'] * 120) for r in rows]
    if any(b - a != 2 for a, b in zip(ticks, ticks[1:])):
        raise ValueError('Jump capture did not follow committed time')
    phases = {'none', 'takeoff', 'air', 'land'}
    for row in rows:
        if row['phase'] not in phases or any(not isinstance(row.get(key), (int, float))
                or not math.isfinite(row[key]) for key in ('native_seconds', 'accepted_jump_at')):
            raise ValueError('missing or invalid Jump clock telemetry')
        seconds = row['native_seconds']
        age = row['simulation_time'] - row['accepted_jump_at']
        if row['phase'] == 'takeoff':
            if not 0 <= seconds <= 11/60 + 1e-6 or abs(seconds - age) > 1e-5:
                raise ValueError('takeoff clock did not follow accepted input')
        elif row['phase'] == 'air':
            expected = min(max(age - 11/60, 0), 23/60)
            if abs(seconds - expected) > 1e-5:
                raise ValueError('air clock retimed or repeated the transition')
            if row['holding_air_endpoint'] and abs(seconds - 23/60) > 1e-5:
                raise ValueError('air endpoint hold used the wrong native time')
        elif row['phase'] == 'land' and not 0 <= seconds <= 28/60 + 1e-6:
            raise ValueError('landing native time is out of bounds')
    third = [r for r in rows if 3.25 <= r['simulation_time'] < 3.4 and r['phase'] == 'takeoff']
    if len(third) < 3 or any(not 3.25 <= r['accepted_jump_at'] < 3.28 for r in third):
        raise ValueError('reload interruption has no preceding accepted third Jump')
    for start in [0.25, 1.75]:
        jump = [r for r in rows if start <= r['simulation_time'] < start + 1.2]
        if not {'takeoff', 'air', 'land'}.issubset({r['phase'] for r in jump}):
            raise ValueError('accepted Jump is missing native phases')
        active = [r for r in jump if r['phase'] != 'none']
        if any(not start <= r['accepted_jump_at'] < start + .03 for r in active):
            raise ValueError('Jump phase was not bound to its accepted input')
        contacts = [r['simulation_time'] - r['native_seconds'] for r in jump if r['phase'] == 'land']
        if max(contacts) - min(contacts) > 1e-5:
            raise ValueError('landing native clock changed after contact')
        if not any(r['holding_air_endpoint'] for r in jump):
            raise ValueError('extended flight did not hold the authored air endpoint')
        if any(r['phase'] == 'land' and not r['grounded'] for r in jump):
            raise ValueError('landing started before ground contact')
        if start == 1.75 and any(r['visual_ads'] < .98 for r in jump):
            raise ValueError('common Jump displaced the active ADS clock')
    interruption = [r for r in rows if 3.5 <= r['simulation_time'] < 3.7]
    if not interruption or any(r['phase'] != 'none' or r['reload_left'] <= 0 for r in interruption):
        raise ValueError('reload failed to take ownership during Jump')
    if rows[-1]['phase'] != 'none':
        raise ValueError('Jump did not return to the live base pose')
    images = []
    for path in paths:
        data = Path(str(path).removesuffix('.gameplay.json')).read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('native image missing')
        images.append(hashlib.sha256(data).hexdigest())
    if len(set(images)) < 20:
        raise ValueError('native capture lacks changing frames')
    report = dict(schema='rust-duty-jump-native-capture/v1', passed=True,
                  frames=len(rows), sampling_hz=60, distinct_images=len(set(images)),
                  scope='Actual loader/rendered frames and committed-input phase/ADS/reload checks. Elara review and Windows gameplay remain separate.')
    (folder / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    print(json.dumps(verify(parser.parse_args().folder), indent=2))
