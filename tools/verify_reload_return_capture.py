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
    episodes = sum(row['return_weight'] is not None and (i == 0 or rows[i-1]['return_weight'] is None)
                   for i,row in enumerate(rows))
    if episodes < 3:
        raise ValueError('complete/cancel/restart return cases were not all observed')
    if not any(row['run_weight'] > 0 for row in returning) or not any(row['walk_weight'] > 0 for row in returning):
        raise ValueError('return did not overlap live run and walk')
    if not any(0 < row['extra_actor_opacity'] < 1 for row in returning):
        raise ValueError('visible reload-only magazine was not faded on interruption')
    return_steps = [math.dist(a['anchor'], b['anchor']) for a,b in zip(rows,rows[1:])
                    if a['return_weight'] is not None or b['return_weight'] is not None]
    if any(not math.isfinite(value) or value > 0.04 for value in return_steps):
        raise ValueError('weapon anchor reset/jumped during return')
    if rows[-1]['route'] != 'ready' or rows[-1]['extra_actor_opacity'] != 0:
        raise ValueError('return did not finish at current ready pose')
    if rows[-1]['ammo'] + rows[-1]['reserve'] + rows[-1]['shots'] != rows[0]['ammo'] + rows[0]['reserve']:
        raise ValueError('presentation changed ammunition conservation')
    report={'schema':'rust-duty-reload-return-capture/v1','passed':True,'frames':len(rows),
            'return_episodes':episodes,'return_frames':len(returning),'max_return_anchor_step_m':max(return_steps),
            'scope':'Actual native renderer with complete reload, live walk/run overlap, sprint cancellations and restarted handoff. No source-motion approval.'}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path)
    print(json.dumps(verify(parser.parse_args().folder),indent=2))
