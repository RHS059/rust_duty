#!/usr/bin/env python3
"""Read-only observer checks. Never launch native code or learn approval from capture metadata.

A partial result is not a pass. Source frame 1 is a pre-advance committed event;
frame 96 committed, retained outgoing source and rendered weight-zero endpoint
are three distinct claims. A PNG witness binds invocation/index, not art quality.
"""
import argparse, hashlib, json, math
from pathlib import Path

NATIVE=95/60
SCHEMA='rust-duty-onehand-observer/v1'
HELPERS={'verify_capture_frame_witness.py':'00011d1904499e1c2c0ea93b4cb74e389d1bf7b78cb0459567b3ae7f65f0f678',
         'verify_render_capture.py':'6bea6d0c9ebabe48bf50c8e45a370652d93bf926bbba3e8326bc754cbff395af'}
class EvidenceError(ValueError):pass

def need(ok,message):
    if not ok:raise EvidenceError(message)

def near(a,b,tol=2e-5):
    return type(a) in (int,float) and math.isfinite(a) and abs(a-b)<=tol

def finite(v):
    if isinstance(v,dict):return all(finite(x) for x in v.values())
    if isinstance(v,list):return all(finite(x) for x in v)
    return not isinstance(v,float) or math.isfinite(v)

def read(p):
    def reject(s):raise EvidenceError('non-finite JSON: '+s)
    return json.loads(Path(p).read_text(),parse_constant=reject)

def sha(p):
    p=Path(p);need(p.is_file() and not p.is_symlink(),f'not regular file: {p}')
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def safe_path(root,name):
    p=Path(name);need(not p.is_absolute() and '..' not in p.parts,'unsafe relative path')
    out=root/p;need(out.resolve().is_relative_to(root.resolve()),'symlink path escapes root');return out

def read_trace(path):
    need(Path(path).stat().st_size<=16*1024**2,'observer byte bound exceeded')
    rows=[]
    with Path(path).open() as stream:
        for line in stream:
            need(len(line)<65536,'observer record too large')
            rows.append(json.loads(line,parse_constant=lambda s:(_ for _ in ()).throw(EvidenceError(s))))
            need(len(rows)<=12000,'observer record bound exceeded')
    return rows

def validate(rows,expected_binding,scenario,*,input_route="platform",start_position=(0,0,9)):
    need(rows and rows[0].get('kind')=='header' and rows[-1].get('kind')=='finished','unterminated observer')
    head=rows[0]
    need(input_route in ('platform','deterministic_ordinary_input'),'unknown verifier input route')
    need(head['input_route']==input_route and head['scene']=='range','scene/input route mismatch')
    need(input_route=='platform' or scenario=='complete','deterministic inputs cannot prove platform interruptions')
    need(head['source_camera_and_rig_basis']=='static' and head['source_camera_motion_removal']=='none'
         and head['authored_stance_descent'] is False,'wrong static rig/camera declaration')
    need(head['source_range']==[1,96] and head['reference_range_half_open']==[7787,7883]
         and near(head['native_seconds'],NATIVE),'native/source range mismatch')
    last_wall=-1
    for i,r in enumerate(rows):
        need(r['schema']==SCHEMA and r['record_index']==i and finite(r),'record order/schema/nonfinite')
        need(r['wall_seconds']>=last_wall,'wall time reversal');last_wall=r['wall_seconds']
        if 'simulation_time' not in r:continue
        need(r['binding']==expected_binding,'loaded binding mismatch or inactive production pins')
        h=r['high'];m=r['mantle']
        if h:
            need(near(h['source_frame'],1+60*h['seconds']) and near(h['reference_frame'],7787+60*h['seconds']), 'native frame/seconds mismatch')
            need(-1e-7<=h['seconds']<=NATIVE+1e-7 and 1<=h['source_frame']<=96,'native clock range')
            out=h['outgoing']
            if out:
                need(near(out['duration'],expected_binding['return_seconds']),'return duration mismatch')
                x=max(0,min(1,(r['simulation_time']-out['began'])/out['duration']));w=x*x*(3-2*x)
                need(near(out['weight'],w),'return smoothstep mismatch')
                need(near(out['frozen_seconds'],h['seconds']) and near(out['frozen_source_frame'],h['source_frame']),'outgoing source not frozen')
                if out['completed']:need(near(h['seconds'],NATIVE) and h['source_frame']==96,'completion did not retain96')
            else:
                need(m and m['kind']=='High' and not m['from_hang'],'wrong high-ONTO route')
                need(near(m['duration'],NATIVE) and near(h['seconds'],r['simulation_time']-r['accepted_at']),'stretched native clock')
                need(1.2 < m['landing'][1]-m['start'][1] <= 1.85+1e-5,'not high-ONTO height')
                need(not r['prone'] and not r['crouched'] and near(r['stance_progress'],1),'stance descent during high-ONTO')
                # Accepted is before this update resolves ADS eligibility.
                # Ordinary simulation ADS may decay from an already aimed state;
                # the authored visual must still be exclusively native.
                need(0<=r['simulation_ads']<=1,'invalid simulation ADS')
                if r['kind'] in ('step','frame'):
                    need(r['ads_requested'] is False and near(r['visual_ads'],0),'ADS target/visual leaked during traversal')
            if r['kind'] in ('step','frame'):
                need(r['renderer_failed'] is False,'renderer failed')
                paused_frozen=(r['kind']=='frame' and not r['app_active'] and out and near(out['weight'],0)
                               and r['route']=='high_mantle.native' and r['render_return_weight'] is None)
                need(paused_frozen or r['route']==('high_mantle.return' if out else 'high_mantle.native'),'renderer route mismatch')
                need(near(r['procedural_weight'],out['weight'] if out else 0),'procedural/high weight mismatch')
                need(paused_frozen or (out is None and r['render_return_weight'] is None) or (out and near(r['render_return_weight'],out['weight'])), 'render/simulation return weight mismatch')
        if r['kind']=='step':
            need(near(r['simulation_time']-r['step_started'],1/120,1e-7),'non-native committed tick')
            need('input' in r,'missing committed input')
        if r['kind']=='frame' and h and not r['dead']:
            need(not r['prone_camera_active'],'unexpected authored prone camera')
            need(all(near(a,b) for a,b in zip(r['camera_eye'],[r['position'][0],r['position'][1]+r['eye_height'],r['position'][2]])), 'eye/physics mismatch')
            need(all(near(a,b) for a,b in zip(r['camera_forward'],r['direction'])),'unexpected cosmetic camera rotation')
    initial=next(r for r in rows if r['kind']=='initial')
    need(all(near(a,b) for a,b in zip(initial['position'],start_position)) and initial['grounded'],'not independently expected range spawn')
    accepted=[r for r in rows if r['kind']=='accepted' and r['high']]
    need(accepted,'no actual accepted high')
    for a in accepted:
        need(a['high']['seconds']==0 and a['high']['source_frame']==1 and a['high']['outgoing'] is None,'missing pre-advance frame1')
        later=next((r for r in rows[a['record_index']+1:] if r['kind']=='step'),None)
        need(later and later['input']['jump'] and later['input']['movement'][1]>.1
             and near(later['step_started'],a['simulation_time']),'acceptance lacks actual fresh jump/forward input')
    # Per-episode eye-height comparison avoids confusing death camera/physics with source-camera motion.
    for a in accepted:
        previous_ads=a['simulation_ads']
        for r in rows[a['record_index']+1:]:
            if not r.get('high') or r['high']['generation']!=a['high']['generation']:break
            need(near(r['eye_height'],a['eye_height']),'authored stance descent appeared')
            if r['high']['outgoing'] is None:
                need(r['simulation_ads']<=previous_ads+1e-6,'simulation ADS grew during traversal')
                previous_ads=r['simulation_ads']
    need(any(r['kind']=='frame' and 'png' in r and r['high'] and r['high']['outgoing'] is None for r in rows), 'no rendered native action frame')
    complete=[r for r in rows if r['kind']=='step' and r['high'] and r['high']['outgoing'] and r['high']['outgoing']['completed']]
    endpoints=[r for r in complete if near(r['high']['outgoing']['weight'],0,1e-7)]
    rendered_endpoint=[r for r in rows if r['kind']=='frame' and 'png' in r and r['high']
                       and r['high']['outgoing'] and r['high']['outgoing']['completed']
                       and near(r['high']['outgoing']['weight'],0,1e-7)]
    rendered_return=[r for r in rows if r['kind']=='frame' and 'png' in r and r.get('high')
                     and r['high']['outgoing'] and r['high']['outgoing']['completed']
                     and 0<r['high']['outgoing']['weight']<1]
    weights=[r['high']['outgoing']['weight'] for r in rendered_return]
    rendered_return_pass=(len(set(weights))>=2 and len({r['underlying_pose_crc32'] for r in rendered_return})>=2)
    report={'scenario':scenario,'source1_committed_before_advance':True,'source1_rendered':False,
            'source96_committed_at_zero_weight':bool(endpoints), 'source96_rendered_at_zero_weight':bool(rendered_endpoint),
            'high_acceptances':len(accepted),'pngs':sum('png' in r for r in rows),
            'rendered_return_intermediate_weights':weights,'rendered_visual_return_passed':rendered_return_pass,
            'windows_dx12_verified':False,'artistic_approval':False}
    if scenario=='complete':
        need(endpoints,'exact committed frame96 endpoint missing')
        for r in endpoints:
            need(near(r['high']['outgoing']['began']-r['accepted_at'],NATIVE),'completion not95/60')
            accepted_state=next(a for a in reversed(accepted) if a['record_index']<r['record_index'])
            need(r['grounded'] and all(near(x,y) for x,y in zip(r['position'],accepted_state['mantle']['landing'])), 'not landed ONTO accepted top')
        outgoing=[r for r in complete if 0<r['high']['outgoing']['weight']<1]
        need(outgoing,'outgoing return not observed')
        need(any(r['input']['ads'] and r['input']['movement'][1]>.1 and r['speed']>.1 and r['visual_ads']>0 for r in outgoing),'no live walk/ADS during return')
        need(len({r['underlying_pose_crc32'] for r in outgoing})>1,'underlying pose did not keep moving')
        need(any(r['kind']=='frame' and r['high'] is None and r['visual_ads']>.95 for r in rows),'ADS never restored')
        report['live_walk_ads_return']=True
        report['rendered_endpoint_gap']=not bool(rendered_endpoint)
        report['rendered_visual_return_gap']=not rendered_return_pass
    elif scenario=='cancel':
        before=next((r for r in rows if r['kind']=='pause_before' and r['high'] and r['high']['outgoing'] is None),None)
        need(before is not None,'no native pause during high')
        after=rows[before['record_index']+1]
        need(after['kind']=='pause_after' and after['high'] and after['high']['outgoing'] and not after['high']['outgoing']['completed'],'not legitimate incomplete pause cancel')
        need(after['position']==before['position'] and after['high']['source_frame']==before['high']['source_frame'],'cancel moved physics or source')
        previous=next((r for r in reversed(rows[:before['record_index']]) if r['kind']=='platform'),None)
        need(previous and previous['keys']['escape_pressed'] and previous['transition']['paused'],'cancel lacks real Escape event')
        resumed=next((r for r in rows[after['record_index']+1:] if r['kind']=='platform' and r['transition']['resumed']),None)
        need(resumed,'pause never resumed')
        paused=[r for r in rows[after['record_index']+1:resumed['record_index']] if r['kind']=='frame']
        need(paused and all(r['simulation_time']==after['simulation_time'] and r['high']==after['high'] for r in paused),'pause clock did not freeze')
        need(any(r['kind']=='step' and r['high'] is None for r in rows[resumed['record_index']+1:]),'cancel never returned')
        report['escape_pause_cancel_and_resume']=True
    elif scenario in ('reset','debug-death'):
        event='reset' if scenario=='reset' else 'debug_death'
        before=next((r for r in rows if r['kind']==event+'_before' and r['high'] and r['high']['outgoing'] is None),None)
        need(before is not None,'no requested native hotkey during high')
        after=rows[before['record_index']+1]
        need(after['kind']==event+'_after' and after['high'] is None and after['mantle'] is None,'stale source/traversal after hotkey')
        key='f2_pressed' if scenario=='reset' else 'f9_pressed'
        previous=next((r for r in reversed(rows[:before['record_index']]) if r['kind']=='platform'),None)
        need(previous and previous['keys'][key],'missing native hotkey edge')
        if scenario=='debug-death':need(after['dead'] and after['health']==0,'debug death did not happen')
        else:need(after['simulation_time']==0 and not after['dead'],'reset failed')
        report['hotkey_cleared_source']=True
        report['combat_death_verified']=False
    else:raise EvidenceError('unknown scenario')
    return report

def verify(folder,binding,scenario,identity,*,input_route="platform",start_position=(0,0,9)):
    folder=Path(folder);rows=read_trace(folder/'observer.jsonl')
    need(rows[0]['frame_witness']==identity,'wrong invocation witness')
    result=validate(rows,binding,scenario,input_route=input_route,start_position=start_position)
    for name,digest in HELPERS.items():need(sha(Path(__file__).parent/name)==digest,'witness helper changed')
    from verify_capture_frame_witness import verify as witness
    captures=[r for r in rows if 'png' in r]
    need(1<=len(captures)<=12,'PNG selection bound exceeded or empty')
    need([r['capture_index'] for r in captures]==list(range(len(captures))),'capture index gap')
    need(rows[-1]['pngs']==len(captures),'terminal PNG count mismatch')
    need({p.name for p in folder.glob('*.png')}=={r['png'] for r in captures},'missing/extra PNGs')
    hashes={}
    for r in captures:
        path=safe_path(folder,r['png']);meta=read(str(path)+'.json')
        need(meta['capture']=='native window','offscreen frame is not ordinary gameplay')
        witness(path,meta,r['capture_index'],identity)
        for p in (path,Path(str(path)+'.json')):hashes[p.name]=sha(p)
    result.update(telemetry_contract_passed=True,rendered_witnesses_verified=len(captures),files_sha256=hashes,
                  observer_sha256=sha(folder/'observer.jsonl'))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',type=Path,required=True)
    p.add_argument('--binding',type=Path,required=True,help='Independent approved binding JSON, never capture-derived.')
    p.add_argument('--binding-sha256',required=True);p.add_argument('--identity',required=True)
    p.add_argument('--scenario',choices=['complete','cancel','reset','debug-death'],required=True)
    p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    try:
        need(sha(a.binding)==a.binding_sha256,'independent binding changed')
        need(not a.report.exists(),'refuse overwrite')
        result=verify(a.capture,read(a.binding),a.scenario,a.identity)
        a.report.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='files_sha256'},indent=2))
        return 0
    except (EvidenceError,KeyError,TypeError,ValueError,OSError) as e:print('Verification failed:',e);return 1
if __name__=='__main__':raise SystemExit(main())
