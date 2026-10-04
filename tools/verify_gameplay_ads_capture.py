#!/usr/bin/env python3
"""Check real native ADS entry/hold/exit and input-driven interruption evidence."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def verify_walk_episode_clocks(rows):
    """Walk may restart only after a fully inactive interval, never mid-fade."""
    for previous,current in zip(rows,rows[1:]):
        a,b=previous['walk_seconds'],current['walk_seconds']
        if a is None or b is None:
            continue
        elapsed=current['simulation_time']-previous['simulation_time']
        # Explicit runtime policies: native hip, v4 ADS and v9 forward ADS.
        # Keep validating each reported bound rather than accepting arbitrary
        # slow clocks or allowing an invalid row to hide behind the lower one.
        rates=(previous.get('walk_min_rate',1),current.get('walk_min_rate',1))
        if any(rate not in (1,0.85,0.80) for rate in rates):
            raise ValueError('unsupported walk phase rate policy')
        minimum=min(rates)
        if b-a < elapsed*minimum-1e-6 or b-a > elapsed+1e-6:
            raise ValueError('active walk phase did not follow committed time')


def verify_layer_overlap(rows):
    """Require rendered concurrent weights, not just sequential route names."""
    if any('run_weight' not in row or not 0 <= row['run_weight'] <= 1 for row in rows):
        raise ValueError('missing or invalid run-layer telemetry')
    simultaneous = [row for row in rows if row['sprinting'] and row['route'] == 'ads.exit'
                    and row['walk_weight'] > 0 and 0 < row['run_weight'] < 1]
    if len(simultaneous) < 3:
        raise ValueError('run entry did not overlap outgoing ADS and walk layers')
    returning = [row for row in rows if row['segment'] == 'sprint_to_ads'
                 and row['route'] == 'ads.entry' and row['run_weight'] > 0]
    if not returning:
        raise ValueError('ADS entry waited for run fade-out to finish')
    return {'simultaneous_run_ads_walk_frames': len(simultaneous),
            'ads_entry_during_run_return_frames': len(returning)}


def verify(folder: Path):
    paths = sorted(folder.glob('*.gameplay.json'))
    if len(paths) < 530:
        raise ValueError('native ADS capture is missing or truncated')
    rows = [json.loads(path.read_text()) for path in paths]
    if any(row['renderer_failed'] for row in rows):
        raise ValueError('authored ADS renderer failed')
    if any(a['simulation_time'] >= b['simulation_time'] for a, b in zip(rows, rows[1:])):
        raise ValueError('committed ADS simulation time did not advance')
    routes = Counter(row['route'] for row in rows)
    for route in ['ads.entry', 'ads.hold', 'ads.exit', 'ready', 'regular_walk', 'locomotion', 'reload.tactical']:
        if routes[route] == 0:
            raise ValueError(f'expected authored route missing: {route}')
    if rows[0]['route'] != 'ready' or rows[-1]['route'] != 'ready' or rows[-1]['simulation_ads'] != 0:
        raise ValueError('ADS did not start and finish at ready')
    for slot, name in [('entry', 'ads_entry_r1'), ('hold', 'ads_hold_r1'), ('exit', 'ads_exit_r1')]:
        sampled = [row for row in rows if row['route'] == f'ads.{slot}']
        if any(row['clip'] != name or row['native_clip_seconds'] < 0 for row in sampled):
            raise ValueError(f'wrong semantic ADS clip: {slot}')
        if slot != 'hold' and any(row['native_clip_seconds'] > row['clip_duration'] + 1e-6 for row in sampled):
            raise ValueError('ADS transition exceeded source duration')
    reversals = {}
    for slot in ['entry', 'exit']:
        reversed_rows = [row for row in rows if row['route'] == f'ads.{slot}' and row['direction'] == -1]
        if len(reversed_rows) < 2:
            raise ValueError(f'native {slot} reversal was not rendered')
        reversals[slot] = len(reversed_rows)
    first = [row['route'] for row in rows if row['segment'] == 'complete_cycle']
    if not all(route in first for route in ['ready', 'ads.entry', 'ads.hold', 'ads.exit']):
        raise ValueError('complete normal ADS cycle missing')
    if not any(row['route'] == 'ads.hold' and row['speed'] > .1 for row in rows):
        raise ValueError('ADS while actually moving was not rendered')
    aimed_walk = [row for row in rows if row['route'] == 'ads.hold' and row['speed'] > .1]
    if len(aimed_walk) < 10 or any(row['walk_weight'] <= 0 or row['walk_seconds'] is None for row in aimed_walk):
        raise ValueError('ADS suppressed the active walking layer')
    verify_walk_episode_clocks(rows)
    if not any(row['sprinting'] and row['route'] == 'locomotion' for row in rows):
        raise ValueError('committed sprint did not interrupt ADS')
    shot_rows = [row for row in rows if row['segment'] == 'fire_while_aiming']
    if max(row['shots'] for row in shot_rows) < 1 or not any(row['route'] == 'ads.hold' and row['shots'] > 0 for row in shot_rows):
        raise ValueError('firing while aimed failed')
    reload_rows = [row for row in rows if row['route'] == 'reload.tactical']
    reload_end = max(row['simulation_time'] for row in reload_rows)
    if not any(row['route'] == 'ads.hold' and row['simulation_time'] > reload_end for row in rows):
        raise ValueError('ADS did not reacquire after authored reload')
    if rows[-1]['ammo'] != 30 or rows[-1]['ammo'] + rows[-1]['reserve'] + rows[-1]['shots'] != rows[0]['ammo'] + rows[0]['reserve']:
        raise ValueError('ADS replay broke reload ammunition conservation')
    layer_overlap = verify_layer_overlap(rows)
    hashes = {route: set() for route in ['ads.entry', 'ads.hold', 'ads.exit']}
    for path, row in zip(paths, rows):
        image = Path(str(path).removesuffix('.gameplay.json')).read_bytes()
        if not image.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('native frame missing or invalid')
        if row['route'] in hashes:
            hashes[row['route']].add(hashlib.sha256(image).hexdigest())
    if len(hashes['ads.entry']) < 8 or len(hashes['ads.exit']) < 8:
        raise ValueError('ADS transition images lack authored visible motion')
    report = {'schema': 'rust-duty-native-ads-capture/v1', 'passed': True, 'frames': len(rows),
        'routes': dict(routes), 'reversal_frames': reversals,
        'distinct_ads_images': {key: len(values) for key, values in hashes.items()},
        'aimed_walking_frames': len(aimed_walk), **layer_overlap,
        'shots': rows[-1]['shots'], 'final_ammo': rows[-1]['ammo'], 'final_reserve': rows[-1]['reserve'],
        'returned_to_ready': True, 'reacquired_after_reload': True,
        'scope': 'Committed simulation input and native Linux rendered frames. Reload cuts remain documented WIP seams; Windows gameplay and aesthetic approval are separate.'}
    (folder / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    print(json.dumps(verify(parser.parse_args().folder), indent=2))
