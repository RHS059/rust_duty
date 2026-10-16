#!/usr/bin/env python3
"""Separate 60/30 ordinary-Input evidence; never substitutes for real hotkeys."""
import argparse,json,math
from pathlib import Path
import verify_high_mantle_observer as v

ROUTE='deterministic_ordinary_input'
START=(-8.6,0.,-3.)
RETURN_SECONDS=.2
DURATION=2.7

def expected_input(t):
    return {'movement':[0,1 if .15<=t<2.15 else 0],
            'jump':.25<=t<.25+1/120,'ads':.15<=t<2.7,
            'fire':False,'reload':False,'sprint':False,'tactical_sprint':False,'crouch':False,'prone':False,
            'sidearm':False,'mount':False,'cant':False,'lean':0.}

def validate(rows,binding,hz):
    v.need(hz in (30,60),'expected sampling rate must be30 or60')
    v.need(v.near(binding['return_seconds'],RETURN_SECONDS,1e-8),'fixture only covers the independently pinned0.20s return')
    result=v.validate(rows,binding,'complete',input_route=ROUTE,start_position=START)
    head=rows[0]
    v.need(head['sampling_hz']==hz and head['sequence']=='gameplay-high-onto','deterministic header mismatch')
    scene=head['immutable_scene_start']
    v.need(scene['position']==list(START) and v.near(scene['yaw'],math.pi)
           and scene['existing_block_center']==[-10.,.9,-3.]
           and scene['existing_block_size']==[2.,1.8,2.]
           and scene['setup']=='existing traversal_replay::start before first update','immutable scene declaration mismatch')
    initial=next(r for r in rows if r['kind']=='initial')
    v.need(all(v.near(a,b) for a,b in zip(initial['direction'],[-1,0,0])),'immutable start yaw changed')
    v.need(not any(r['kind'] in ('reset_before','pause_before','debug_death_before') for r in rows),'platform interruption contaminated deterministic pass')
    steps=[r for r in rows if r['kind']=='step']
    v.need(len(steps)==324,'deterministic fixed tick count mismatch')
    for i,r in enumerate(steps):
        v.need(v.near(r['step_started'],i/120,2e-6),'deterministic tick start discontinuity')
        v.need(r['input']==expected_input(r['step_started']),'ordinary replay input changed')
    accepted=[r for r in rows if r['kind']=='accepted']
    v.need(len(accepted)==1 and v.near(accepted[0]['simulation_time'],.25,2e-6),'acceptance must occur on tick30')
    frames=[r for r in rows if r['kind']=='frame']
    v.need(frames and all(r['sampling_hz']==hz for r in frames),'per-frame capture rate mismatch')
    v.need([r['app_frame'] for r in frames]==list(range(len(frames))),'app-frame sequence gap')
    advanced=[r for r in frames if r['simulation_time']>1e-6]
    v.need(len(advanced)==round(DURATION*hz),'deterministic rendered frame count mismatch')
    for i,r in enumerate(advanced,1):
        v.need(v.near(r['simulation_time'],i/hz,2e-6),'rendered cadence differs from deterministic120Hz tick grid')
    v.need(result['source96_rendered_at_zero_weight'],'deterministic endpoint raster missing')
    v.need(result['rendered_visual_return_passed'],'deterministic intermediate rendered weights missing')
    captured=[r for r in frames if 'png' in r and r.get('high') and r['high']['outgoing']
              and 0<r['high']['outgoing']['weight']<1]
    v.need(all(r['ads_requested'] and r['speed']>.1 and r['visual_ads']>0 for r in captured),'rendered return lacks live walk/ADS target')
    result.update(input_route=ROUTE,sampling_hz=hz,immutable_scene_start_verified=True,
                  ordinary_input_ticks_verified=len(steps),rendered_nominal_seconds=DURATION,
                  real_time_performance_verified=False,platform_hotkeys_verified=False)
    return result

def verify(folder,binding,hz,identity):
    folder=Path(folder);rows=v.read_trace(folder/'observer.jsonl')
    result=validate(rows,binding,hz)
    native=v.verify(folder,binding,'complete',identity,input_route=ROUTE,start_position=START)
    result.update({k:value for k,value in native.items() if k not in result})
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,required=True);p.add_argument('--binding',type=Path,required=True)
    p.add_argument('--binding-sha256',required=True);p.add_argument('--identity',required=True)
    p.add_argument('--hz',type=int,choices=[30,60],required=True);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();v.need(v.sha(a.binding)==a.binding_sha256,'independent binding changed')
    v.need(not a.report.exists(),'report must be new')
    report=verify(a.capture,v.read(a.binding),a.hz,a.identity)
    a.report.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'sampling_hz':a.hz,'rendered_visual_return_passed':report['rendered_visual_return_passed'],'platform_hotkeys_verified':False}))
if __name__=='__main__':main()
