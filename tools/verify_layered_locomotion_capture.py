#!/usr/bin/env python3
"""Check native four-direction layering and 30/60 sample-clock determinism.

This gate is separate from source-reference similarity, anatomy, visual review,
and achieved wall-clock rendering performance.
"""
import argparse
import hashlib
import json
from pathlib import Path


def verify(folder: Path, allow_legacy_walk=False):
    paths=sorted(folder.glob('*.gameplay.json'))
    rows=[json.loads(path.read_text()) for path in paths]
    if not rows or len(rows) < rows[0]['sampling_hz'] * 11:
        raise ValueError('missing or truncated layered native capture')
    hz=rows[0]['sampling_hz']
    if hz not in (30,60) or any(row['sampling_hz'] != hz for row in rows):
        raise ValueError('expected one declared 30 or 60 Hz capture')
    if any(row['renderer_failed'] or row['pose_crc32'] is None for row in rows):
        raise ValueError('native layered renderer failed or pose telemetry missing')
    if any(a['simulation_time'] >= b['simulation_time'] for a,b in zip(rows,rows[1:])):
        raise ValueError('committed replay clock did not advance')
    ticks=[round(row['simulation_time']*120) for row in rows]
    stride=120//hz
    if any(b-a != stride for a,b in zip(ticks,ticks[1:])):
        raise ValueError('capture cadence does not use the exact fixed-step stride')
    segments={name:[row for row in rows if row['segment']==name]
              for name in {row['segment'] for row in rows}}
    for index,direction in enumerate(('forward','backward','left','right')):
        for kind in ('hip','ads'):
            segment=segments.get(f'{direction}_{kind}',[])
            if len(segment)<hz*.8:
                raise ValueError(f'{direction}_{kind} segment is missing')
            settled=segment[-max(3,int(hz*.25)):]
            if any(row['walk_weight']<.99 for row in settled):
                raise ValueError(f'{direction}_{kind} never reaches walking')
            if kind=='ads' and any(row['route']!='ads.hold' for row in settled):
                raise ValueError(f'{direction} ADS is not active over walking')
            if not allow_legacy_walk and any(row['directional_weights'] is None or row['directional_weights'][index]<.98 for row in settled):
                raise ValueError(f'{direction}_{kind} does not use the declared direction')
    rapid=segments.get('rapid_run_interruptions',[])
    overlap=[row for row in rapid if row['sprinting'] and row['route'].startswith('ads.')
             and 0 < row['run_weight'] < 1 and row['walk_weight']>0]
    returns=[row for row in rapid if row['ads_requested'] and 0 < row['run_weight'] < 1 and row['route'].startswith('ads.')]
    if len(overlap)<2 or len(returns)<2:
        raise ValueError('rapid interruptions lack concurrent outgoing/incoming layers')
    if rows[-1]['run_weight'] or rows[-1]['walk_weight'] or rows[-1]['route']!='ready':
        raise ValueError('layered replay did not settle to ready')
    hashes={}
    for path,row in zip(paths,rows):
        png=Path(str(path).removesuffix('.gameplay.json')).read_bytes()
        if not png.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('native image missing')
        hashes.setdefault(row['segment'],set()).add(hashlib.sha256(png).hexdigest())
    if any(len(hashes.get(f'{direction}_hip',set()))<4 for direction in ('forward','backward','left','right')):
        raise ValueError('HIP images lack visible authored animation')
    report={'schema':'rust-duty-layered-native-capture/v1','passed':True,
            'sampling_hz':hz,'frames':len(rows),'fixed_steps_per_frame':stride,'directional_source_required':not allow_legacy_walk,
            'partial_run_ads_walk_overlap_frames':len(overlap),'interrupted_run_return_frames':len(returns),
            'scope':'Native rendered frame and committed-state checks only; reference motion score, visual contact, and actual Windows gameplay remain separate.'}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    return report,rows


def compare_rates(first,second):
    left={round(row['simulation_time']*120):row for row in first}
    right={round(row['simulation_time']*120):row for row in second}
    common=left.keys()&right.keys()
    if len(common)<min(len(left),len(right))*.95:
        raise ValueError('insufficient common committed ticks for rate comparison')
    fields=('pose_crc32','walk_weight','walk_seconds','run_weight','directional_weights',
            'ads_requested','sprinting','simulation_ads','position','velocity','ammo','shots')
    for tick in common:
        if any(left[tick][field]!=right[tick][field] for field in fields):
            raise ValueError(f'render sampling changed committed output at tick {tick}')
    return {'common_ticks':len(common),'compared_fields':list(fields),
            'pose_crc_scope':'Deterministic noncryptographic pose-only checksum; frame images retained for visual inspection.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folders',type=Path,nargs='+')
    parser.add_argument('--allow-legacy-walk',action='store_true',help='diagnostic only; not a four-direction source gate')
    args=parser.parse_args()
    outputs=[verify(folder,args.allow_legacy_walk) for folder in args.folders]
    report={'captures':[output[0] for output in outputs]}
    if len(outputs)==2:
        if {output[0]['sampling_hz'] for output in outputs}!={30,60}: raise ValueError('comparison needs one 30 and one 60 Hz capture')
        report['rate_comparison']=compare_rates(outputs[0][1],outputs[1][1])
    print(json.dumps(report,indent=2))
