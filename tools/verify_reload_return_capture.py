#!/usr/bin/env python3
"""Verify a native complete/cancel/restart reload return replay."""
import argparse
import json
import math
from pathlib import Path


def verify(folder):
    paths = sorted(folder.glob('*.gameplay.json'))
    if len(paths) < 360:
        raise ValueError('reload-return capture is missing or truncated')
    rows = [json.loads(path.read_text()) for path in paths]
    if any(row['renderer_failed'] or row['anchor'] is None for row in rows):
        raise ValueError('return renderer failed or omitted its actual anchor')
    for path in paths:
        if not Path(str(path).removesuffix('.gameplay.json')).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('missing native return image')
    returning = [row for row in rows if row['return_weight'] is not None]
    if len(returning) < 20 or any(not 0 < row['return_weight'] < 1 for row in returning):
        raise ValueError('missing smooth outgoing reload poses')
    complete = cancelled = restarted = episodes = 0
    visible_cancel = decreasing_prop = False
    for row in rows:
        duration=row.get('native_reload_duration')
        native=row.get('native_reload_seconds')
        if duration is None or not math.isfinite(duration) or duration<=0:
            raise ValueError('missing native clip duration witness')
        if native is not None and (not math.isfinite(native) or not 0<=native<=duration or row['route'] not in ('reload.tactical','reload.empty')):
            raise ValueError('invalid active native reload witness')
        if row['return_weight'] is not None and (row['route']!='reload.return' or native is not None):
            raise ValueError('return route/native sample disagrees with its weight')
        if any(not math.isfinite(row[key]) or not 0<=row[key]<=1 for key in ('extra_actor_opacity','walk_weight','run_weight')):
            raise ValueError('invalid layer or visibility weight')
    for a,b in zip(rows,rows[1:]):
        dt=b['simulation_time']-a['simulation_time']
        if not math.isfinite(dt) or dt<=0:
            raise ValueError('return replay time did not advance')
        wa,wb=a['return_weight'],b['return_weight']
        if wb is not None and wa is None:
            episodes+=1
            native=a['native_reload_seconds'];duration=a['native_reload_duration']
            if native is None or b['native_reload_seconds'] is not None:
                raise ValueError('return has no preceding active native reload')
            if native>=duration-dt-1/120-1e-6: complete+=1
            elif native<duration-0.05:
                cancelled+=1
                visible_cancel|=a['extra_actor_opacity']>0
            else: raise ValueError('return source endpoint is ambiguous')
        if wa is not None and wb is not None:
            if wb<=wa: raise ValueError('outgoing return weight froze or reversed')
            decreasing_prop|=0<b['extra_actor_opacity']<a['extra_actor_opacity']
        if wa is not None and b['native_reload_seconds'] is not None:
            if b['native_reload_seconds']>dt+1/120+1e-6 or wa>=0.95:
                raise ValueError('new action did not restart during the active return')
            restarted+=1
    if complete<1 or cancelled<2 or restarted<1:
        raise ValueError('complete/cancel/restart native state witnesses are missing')
    if not any(row['run_weight'] > 0 for row in returning) or not any(row['walk_weight'] > 0 for row in returning):
        raise ValueError('return did not overlap live run and walk')
    if not visible_cancel or not decreasing_prop or not any(0 < row['extra_actor_opacity'] < 1 for row in returning):
        raise ValueError('visible reload-only magazine was not faded on interruption')
    return_steps = [math.dist(a['anchor'], b['anchor']) for a,b in zip(rows,rows[1:])
                    if a['return_weight'] is not None or b['return_weight'] is not None]
    if any(not math.isfinite(value) or value > 0.04 for value in return_steps):
        raise ValueError('weapon anchor reset/jumped during return')
    if rows[-1]['route'] != 'ready' or rows[-1]['extra_actor_opacity'] != 0:
        raise ValueError('return did not finish at current ready pose')
    if rows[-1]['ammo'] + rows[-1]['reserve'] + rows[-1]['shots'] != rows[0]['ammo'] + rows[0]['reserve']:
        raise ValueError('presentation changed ammunition conservation')
    report={'schema':'rust-duty-reload-return-capture/v2','passed':True,'frames':len(rows),
            'return_episodes':episodes,'complete_returns':complete,'cancelled_returns':cancelled,'restarts_during_return':restarted,
            'return_frames':len(returning),'max_return_anchor_translation_step_m':max(return_steps),
            'scope':'Native active-reload clock/clip-duration witnesses distinguish completed and cancelled returns and an intervening restart. Anchor metric measures sampled translation only, not angular, joint or skin continuity. No source-motion approval.'}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path)
    print(json.dumps(verify(parser.parse_args().folder),indent=2))
