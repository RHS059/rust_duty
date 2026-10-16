#!/usr/bin/env python3
"""Fail-closed nonuniform combined native capture verifier. Never launches code.

Bindings must be independently pinned, never copied from capture output. Native
PNG witness checks are separate from CPU state/pose checks and do not prove art,
performance, OS input, Windows/DX12, or source-to-runtime geometry parity.
"""
import argparse, hashlib, json, math
from pathlib import Path
from combined_replay_contract import Route, observed, DT, PHASES
from verify_high_mantle_observer import need, near, finite, read, sha, safe_path, HELPERS
SCHEMA='rust-duty-combined-observer/v1'
UNSUPPORTED=['platform_pause','platform_cancel','platform_reset','platform_debug_death',
             'direct_high_low_outgoing_overlap','traversal_tail_active_prone_overlap']

STATE_KINDS=frozenset(('initial','accepted','step','frame','finished'))

# Complete common projection emitted by combined_observer::state and its
# high_mantle_observer base. Record-specific labels/input/visual are excluded.
STATE_FIELDS=tuple(('simulation_time bindings high mantle accepted_at position velocity '
    'camera_eye direction eye_height grounded prone crouched stance_progress dead health '
    'ads_requested simulation_ads speed ammo reserve shots reload_left reload_credit_at '
    'reload_ready_at look prone_entry_started low low_generation prone_sample prone_return '
    'prone_camera lean_offset landing_kick').split())
FRAME_STEP_FIELDS=('phase','camera_base_forward','camera_base_up','camera_forward','camera_up','visual')

def state_projection(row):
    need(all(k in row for k in STATE_FIELDS),'incomplete actual state projection: '+row['kind'])
    return {k:row[k] for k in STATE_FIELDS}

def same_state(actual,committed,label):
    a=state_projection(actual);b=state_projection(committed)
    for k in STATE_FIELDS:need(a[k]==b[k],label+': '+k)

def state_bindings(row,expected):
    """Current admitted identities are mandatory on each state projection."""
    if row['kind'] in STATE_KINDS:
        need('bindings' in row,'missing current loaded bindings on '+row['kind'])
        need(row['bindings']==expected,'loaded binding changed or admission lost on '+row['kind'])

def read_trace(path):
    need(Path(path).stat().st_size<=64*1024**2,'journal byte bound')
    rows=[]
    for line in Path(path).open():
        need(len(line.encode())<=65536,'journal record byte bound')
        value=json.loads(line,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
        need(finite(value),'nonfinite journal');rows.append(value)
        need(len(rows)<=12000,'journal record bound')
    return rows

def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def norm(a):
    n=math.sqrt(sum(v*v for v in a));need(n>1e-12,'zero camera vector');return [v/n for v in a]
def rotate(q,v):
    # Quaternion-vector multiplication; source quaternion is XYZW.
    a=cross(q[:3],v);b=cross(q[:3],a)
    return [v[i]+2*(q[3]*a[i]+b[i]) for i in range(3)]
def vec_near(a,b,tol=2e-5):return len(a)==len(b) and all(near(x,y,tol) for x,y in zip(a,b))
def slerp_identity(q,w):
    q=list(q)
    if q[3]<0:q=[-x for x in q]
    dot=max(-1.,min(1.,q[3]))
    if dot>.9995:return norm([q[i]*(1-w)+(w if i==3 else 0) for i in range(4)])
    angle=math.acos(dot);a=math.sin((1-w)*angle)/math.sin(angle);b=math.sin(w*angle)/math.sin(angle)
    return norm([a*q[i]+(b if i==3 else 0) for i in range(4)])

def expected_render_ticks(steps,hz):
    """Independent reconstruction of the committed-boundary presentation loop."""
    ticks=[0]*7 # app counter is incremented before target_tick; frames 1..7 warm up
    at=0;stride=24;signature=None
    while at<len(steps):
        target=at+stride
        while at<min(target,len(steps)):
            r=steps[at];s=observed(r)
            sig=(s['mantle'],s['high_completed'],s['low_endpoint'],s['prone_seconds'] is not None,
                 s['prone_seconds'] is not None and s['prone_seconds']+1e-6>=68/60,s['prone_return'],r['phase'])
            boundary=signature is not None and sig!=signature;signature=sig
            stride=120//hz if (s['high_completed'] or s['prone_return'] or r['visual']['low_return_weight'] is not None
                or r['phase'] in ('LowAdsTail','RepeatLowAdsTail')) else 12 if (s['mantle'] or s['prone_seconds'] is not None) else 24
            at+=1
            if boundary:break
        ticks.append(at)
    return ticks

def lifecycle(steps,initial):
    """Link each frozen source and reload milestone to preceding committed state."""
    previous=initial;clock=None;low_tail=None;reload=None;reloads=[]
    for r in steps:
        v=r['visual'];out=v['outgoing'];t=r['simulation_time'];old=previous.get('visual');oldout=old['outgoing'] if old else None
        if previous.get('low') and not r['low']:
            need(near(previous['low']['seconds'],63/60),'low return did not follow native endpoint');low_tail=t
        low_expected=bool(r['low']) or (low_tail is not None and t<low_tail+.2-1e-8)
        need(v['owners']==dict(high=bool(r['high']),low=low_expected,prone=bool(r['prone_sample'] or r['prone_return'])),'stale/missing presentation owner')
        if r['high']:
            need(v['high_generation']==r['high']['generation'],'high renderer generation mismatch')
            if previous.get('high'):need(r['high']['generation']==previous['high']['generation'],'high generation changed mid-action')
        else:need(v['high_generation'] is None,'stale high generation')
        if low_expected:
            need(v['low_generation']==r['low_generation'],'low renderer generation mismatch')
            if previous.get('low') or (old and old['owners']['low']):need(r['low_generation']==previous['low_generation'],'low generation changed mid-action')
        else:need(v['low_generation'] is None,'stale low generation')
        if r['low']:need(r['low']['generation']==r['low_generation'],'low sample generation mismatch')
        p=r['prone_sample'];pr=r['prone_return'];prior=previous.get('prone_sample')
        if p:
            began=r['prone_entry_started'];need(began is not None and near(p['seconds'],min(68/60,t-began)),'prone entry identity/clock mismatch')
            if prior:need(began==previous['prone_entry_started'],'prone entry identity changed')
        if pr:
            need(p is None and r['prone_entry_started'] is None,'interrupted prone source still active')
            need(near(pr['duration'],.2,1e-8),'prone outgoing duration')
            if prior:
                need(near(pr['began'],previous['simulation_time']) and near(pr['frozen_seconds'],prior['seconds'])
                     and near(pr['frozen_source_frame'],prior['source_frame']) and vec_near(pr['orientation_xyzw'],prior['orientation_xyzw']),
                     'prone return not frozen at preceding committed interruption')
            else:
                before=previous.get('prone_return');need(before is not None,'prone return lacks committed source')
                for k in ('began','duration','frozen_seconds','frozen_source_frame','orientation_xyzw'):need(pr[k]==before[k],'prone frozen source changed: '+k)
            need(near(pr['weight'],out['weight']) and near(pr['began'],out['began']),'prone simulation/renderer outgoing clock')
        if out:
            identity=(v['route'],out['began'])
            names=[a['name'] for a in v['presented_actors']]
            frozen=(names,out['from_opacity'],out['frozen_pose_seconds'],out['frozen_pose_crc32'])
            if clock and clock[0]==identity:need(frozen==clock[1],'outgoing frozen pose/opacity identity changed')
            else:
                if r['high']:
                    need(near(out['began'],t) and near(out['weight'],0) and near(out['frozen_pose_seconds'],95/60),'high return lacks native endpoint')
                    need(out['frozen_pose_crc32']==v['presented_pose_crc32'],'high frozen pose differs from actual endpoint')
                    actual=v['presented_actors']
                else:
                    need(old is not None and oldout is None,'return lacks preceding native snapshot')
                    need(out['frozen_pose_crc32']==old['presented_pose_crc32'],'return frozen pose differs from preceding committed snapshot')
                    actual=old['presented_actors']
                    expected_seconds=previous['low']['seconds'] if low_expected else prior['seconds']
                    need(near(out['frozen_pose_seconds'],expected_seconds),'return frozen native clock mismatch')
                    need(near(out['began'],t if low_expected else previous['simulation_time']),'return start boundary mismatch')
                need(names==[a['name'] for a in actual] and vec_near(out['from_opacity'],[a['opacity'] for a in actual]),'return frozen named opacity differs from source snapshot')
                clock=(identity,frozen,out['began']+.2)
        elif oldout:
            need(t+1e-7>=oldout['began']+.2 and previous['simulation_time']<oldout['began']+.2,'outgoing lifecycle cleared early/late')
            clock=None
        if oldout and not out:need(not any(v['owners'].values()),'cleared outgoing kept owner')
        if oldout and out:need((v['route'],out['began'])==(old['route'],oldout['began']),'outgoing clock restarted before completion')
        # Two actual tactical reloads: stable credit/ready clocks, conserved reserve,
        # exactly one credit at its first ordinary eligible simulation tick.
        if r['reload_left']>0 and previous['reload_left']<=0:
            need(r['input']['reload'] and previous['ammo']<30,'reload has no ordinary nonfull-magazine request')
            need(r['step_started']<r['reload_credit_at']<=r['reload_ready_at'],'invalid reload credit/ready clocks')
            reload=dict(credit=r['reload_credit_at'],ready=r['reload_ready_at'],credited=False,complete=False);reloads.append(reload)
        shot_delta=r['shots']-previous['shots'];need(shot_delta in (0,1),'shot count discontinuity')
        credit=r['ammo']-previous['ammo']+shot_delta
        expected_credit=0
        if previous['reload_left']>0:
            need(reload is not None and near(r['reload_credit_at'],reload['credit']) and near(r['reload_ready_at'],reload['ready']),'reload clock changed')
            if not reload['credited'] and r['step_started']+1e-7>=reload['credit']:
                expected_credit=min(30-previous['ammo'],previous['reserve']);need(expected_credit>0,'reload credited no ammunition');reload['credited']=True
            need(near(r['reload_left'],max(0,reload['ready']-r['step_started']),2e-6),'reload ready countdown mismatch')
            if r['reload_left']==0:reload['complete']=True
        need(credit==expected_credit and previous['reserve']-r['reserve']==expected_credit,'ordinary reload credit/reserve milestone missing or changed')
        previous=r
    need(len(reloads)==2 and all(x['credited'] and x['complete'] for x in reloads),'two completed credited reloads required')

def png_extent(path,meta):
    # Read only the fixed PNG header before a decoder can allocate the raster.
    with Path(path).open('rb') as f:header=f.read(24)
    need(len(header)==24 and header[:8]==b'\x89PNG\r\n\x1a\n' and header[8:16]==b'\0\0\0\rIHDR','invalid PNG header')
    width=int.from_bytes(header[16:20],'big');height=int.from_bytes(header[20:24],'big')
    need(0<width<=1440 and 0<height<=900,'actual PNG extent exceeds bound')
    need((width,height)==(meta['width'],meta['height']),'PNG extent differs from metadata')
    return width,height

def camera_once(row):
    f=row['camera_base_forward'];u=row['camera_base_up'];sample=row.get('prone_camera')
    need(vec_near(f,row['direction']) and vec_near(u,[0.,1.,0.]),'camera base differs from committed direction/unleaned input route')
    prone=row.get('prone_sample');fade=row.get('prone_return')
    need(bool(sample)==bool(prone or fade),'paired camera missing or stale')
    if prone:
        need(sample==prone,'active paired camera differs from accepted weapon sample')
    elif fade:
        need(near(sample['seconds'],fade['frozen_seconds']) and near(sample['source_frame'],fade['frozen_source_frame'])
             and near(sample['eye_height'],row['eye_height']) and vec_near(sample['orientation_xyzw'],slerp_identity(fade['orientation_xyzw'],fade['weight'])),'prone outgoing camera does not match frozen pair')
    if sample:
        right=norm(cross(f,u));up=norm(cross(right,f));q=sample['orientation_xyzw']
        need(near(sum(v*v for v in q),1,2e-4),'camera quaternion not unit')
        def into_world(v):return norm([right[k]*v[0]+up[k]*v[1]-f[k]*v[2] for k in range(3)])
        ef=into_world(rotate(q,[0,0,-1]));eu=into_world(rotate(q,[0,1,0]))
    else:ef,eu=f,u
    need(vec_near(row['camera_forward'],ef) and vec_near(row['camera_up'],eu),'paired camera applied other than once')
    expected=list(row['position']);expected[1]+=row['eye_height']-row['landing_kick']
    expected=[a+b for a,b in zip(expected,row['lean_offset'])]
    need(vec_near(row['camera_eye'],expected),'stance height added twice')
    prone=row.get('prone_sample')
    if prone:need(near(row['eye_height'],prone['eye_height']),'paired height did not replace stance height')
    if row['kind']=='frame':
        need(vec_near(row['rendered_camera_eye'],row['camera_eye']) and vec_near(row['rendered_camera_forward'],ef)
             and vec_near(row['rendered_camera_up'],eu),'actual world camera differs from once-applied pair')

def opacity(row):
    v=row['visual'];owners=v['owners'];need(sum(bool(x) for x in owners.values())<=1,'sequential route retained multiple presentation owners')
    need(v['renderer_failed'] is False and v['warning'] is None,'renderer warning/failure invalidates combined evidence')
    source=v['presented_actors'];target=v['live_target_actors'];out=v['outgoing']
    need(source and target,'empty source/target actor inventory')
    need(set(owners)=={'high','low','prone'},'owner inventory')
    for actors in (source,target):
        need(all(isinstance(a['name'],str) and a['name'] for a in actors),'missing actor name')
        need(len({a['name'] for a in actors})==len(actors),'duplicate actor name')
        need(all(0<=a['opacity']<=1 for a in actors),'invalid actor opacity')
    if out:
        need(0<=out['weight']<1,'completed outgoing owner was not cleared')
        need(near(out['duration'],.2,1e-8),'outgoing blend was stretched')
        t=max(0,min(1,(row['simulation_time']-out['began'])/out['duration']));w=t*t*(3-2*t)
        need(near(out['weight'],w),'outgoing clock mismatch')
        need(len(out['from_opacity'])==len(source) and all(0<=x<=1 for x in out['from_opacity']),'outgoing opacity shape changed')
        need(near(v['visual_ads'],w*v['underlying_visual_ads']),'outgoing visual ADS mismatch')
        named={a['name']:a['opacity'] for a in target}
        for a,start in zip(source,out['from_opacity']):
            need(near(a['opacity'],start*(1-w)+named.get(a['name'],0)*w),'outgoing actor opacity does not target live named actor')
        need(v['live_target'] in ('base','reload'),'unreachable paired-prone/traversal overlap reported')
        need(near(v['procedural_weight'],w),'outgoing procedural layer weight mismatch')
    high=row.get('high');low=row.get('low');prone=row.get('prone_sample');pr=row.get('prone_return')
    expected_route='high_mantle.return' if high and high['outgoing'] else 'high_mantle.native' if high else 'low_vault.low_mantle_native_wip' if low else 'prone.entry_hold' if prone else 'prone.return' if pr else 'low_vault.return' if owners['low'] else None
    if expected_route:need(v['route']==expected_route,'owner/source/route mismatch')
    else:need(not any(owners.values()) and out is None and not v['route'].startswith(('high_mantle.','low_vault.','prone.')),'stale presentation route/owner')
    need(bool(out)==bool((high and high['outgoing']) or pr or (owners['low'] and not low)),'outgoing source ownership mismatch')
    if (high and not high['outgoing']) or low or prone:
        need(near(v['visual_ads'],0) and near(v['procedural_weight'],0),'active authored source leaked ADS/procedural layers')
    if high:
        need(owners['high'] and not owners['low'],'high ownership mismatch')
        need(near(high['source_frame'],1+60*high['seconds']) and near(high['reference_frame'],7787+60*high['seconds']),'high source clock')
        if high['outgoing']:need(near(v['high_return_weight'],high['outgoing']['weight']) and near(out['began'],high['outgoing']['began']),'high renderer/committed return clock mismatch')
        else:
            need(near(v['procedural_weight'],0),'active high leaked procedural pose')
            need(near(high['seconds'],row['simulation_time']-row['accepted_at']), 'active high committed clock was retimed')
        need(0<=high['seconds']<=95/60+1e-6,'high native clock range')
        if high['outgoing']:
            out_high=high['outgoing']
            need(near(out_high['frozen_seconds'],high['seconds']) and near(out_high['frozen_source_frame'],high['source_frame']), 'high outgoing source was not frozen')
            need(out_high['completed'] and near(high['seconds'],95/60),'unexpected high cancellation or incomplete source')
    if low:
        need(owners['low'] and not owners['high'],'low ownership mismatch')
        need(near(low['source_frame'],1+60*low['seconds']) and near(low['reference_frame'],7284+60*low['seconds']),'low source clock')
        need(near(v['procedural_weight'],0),'active low leaked procedural pose')
        need(0<=low['seconds']<=63/60+1e-6 and near(low['seconds'],row['simulation_time']-row['accepted_at']), 'active low committed clock was retimed')
    if row.get('prone_sample'):
        p=row['prone_sample'];need(owners['prone'],'paired prone owner missing')
        need(near(p['source_frame'],1+60*p['seconds']) and 0<=p['seconds']<=68/60+1e-6,'prone source clock')
    if v['route'].startswith('low_vault.return'):need(near(v['low_return_weight'],out['weight']),'low renderer return weight')

def validate(rows,bindings,hz):
    need(hz in (30,60),'dense return rate must be30 or60')
    need(rows and rows[0]['kind']=='header' and rows[-1]['kind']=='finished','unterminated combined trace')
    h=rows[0];need(h['input_route']=='deterministic_committed_input_replay' and h['sequence']=='gameplay-combined','input route mismatch')
    need(h['sampling_hz']==hz and h['fixed_hz']==120,'clock declaration mismatch')
    need(h['render_cadence']==dict(policy='nonuniform_committed_boundaries_v1',source_hz=10,travel_hz=5,dense_return_hz=hz,render_on_committed_boundaries=True),'nonuniform cadence mismatch')
    need(h['bindings']==bindings and all(bindings.get(k) for k in ('high','low','prone')),'independent admitted identities mismatch')
    for key in ('high','low'):
        for field in ('asset_sha256','receipt_sha256'):
            val=bindings[key][field];need(len(val)==64 and all(c in '0123456789abcdef' for c in val),'invalid independent digest')
        need(near(bindings[key]['return_seconds'],.2,1e-8),'independent return duration mismatch')
    for field in ('asset_vra_sha256','camera_sidecar_sha256','receipt_sha256'):
        val=bindings['prone'][field];need(len(val)==64 and all(c in '0123456789abcdef' for c in val),'invalid independent prone digest')
    need(h['unsupported_scenarios']==UNSUPPORTED,'unsupported scenario declaration changed')
    need(not h['platform_hotkeys_verified'] and not h['performance_verified'] and not h['artistic_approval'],'unsupported claims')
    scene=h['immutable_scene_start'];need(scene['position']==[-8.6,0.,-3.] and near(scene['yaw'],math.pi),'initial fixture changed')
    need(scene['setup']=='combined_replay::start before first update','fixture ownership mismatch')
    initial=[r for r in rows if r['kind']=='initial'];need(len(initial)==1 and near(initial[0]['simulation_time'],0),'initial state missing/duplicated')
    need(vec_near(initial[0]['position'],scene['position']) and not initial[0]['high'] and not initial[0]['low'],'initial state injected action')
    for n,r in enumerate(rows):
        need(r['schema']==SCHEMA and r['record_index']==n and finite(r),'record schema/order/nonfinite')
        need(r['kind'] in ('header','initial','accepted','phase','step','frame','finished'),'failure/unexpected event')
        state_bindings(r,bindings)
        if r['kind'] in STATE_KINDS:need(near(r['look']['yaw'],math.pi) and near(r['look']['pitch'],0),'unjournaled platform look changed fixed replay aim')
        if r['kind'] in ('step','frame'):camera_once(r);opacity(r)
    for r in rows:
        if r['kind'] in STATE_KINDS:state_projection(r)
    steps=[r for r in rows if r['kind']=='step'];need(0<len(steps)<=7201,'fixed tick bound')
    route=Route();previous=initial[0]
    for tick,r in enumerate(steps):
        need(r['tick']==tick and near(r['step_started'],tick*DT,2e-6) and near(r['simulation_time'],(tick+1)*DT,2e-6),'120Hz committed step discontinuity')
        need(r['input']==route.input(observed(previous)) and r['phase']==route.phase,'committed input differs from independent route')
        need(not r['dead'],'death is unsupported here')
        ps=r.get('prone_sample');old=previous.get('prone_sample')
        if ps:
            expected=min(68/60,old['seconds']+DT) if old else 0.
            need(near(ps['seconds'],expected),'paired prone committed clock discontinuity')
        if r['ammo']>previous['ammo']:
            need(previous['reload_left']>0 and r['step_started']+1e-6>=previous['reload_credit_at'],'ammo credited without ordinary reload milestone')
        previous=r
    lifecycle(steps,initial[0])
    need(route.phase=='Done' and route.counts==[2,2,2],'route did not complete repeated accepted actions')
    need(rows[-1]['completed'] is True and rows[-1]['accepted_counts_high_low_prone']==[2,2,2],'terminal state mismatch')
    same_state(rows[-1],steps[-1],'terminal actual state differs from final committed state')
    accepted=[r for r in rows if r['kind']=='accepted']
    need([r['mantle']['kind'] for r in accepted]==['High','Low','Low','High'],'ordinary traversal acceptance sequence mismatch')
    endpoints=[];high_generations=[];low_generations=[]
    for a in accepted:
        m=a['mantle'];high=m['kind']=='High';span=95/60 if high else 63/60
        need(not m['from_hang'] and near(m['duration'],span),'hang/legacy/retimed acceptance')
        need(a['accepted_source_clock']==dict(kind=m['kind'],seconds=0.,source_frame=1.,rendered=False,from_hang=False),'accepted source1 conflated with render')
        tick=round(a['simulation_time']/DT)
        need(tick<len(steps) and steps[tick]['input']['jump'] and steps[tick]['input']['movement']==[0.,1.],'acceptance lacks ordinary committed request')
        first=steps[tick]
        before=steps[tick-1] if tick else initial[0]
        need(before['record_index']<a['record_index']<first['record_index'],'accepted event is outside its committed tick')
        need(near(a['simulation_time'],first['step_started']) and near(a['accepted_at'],first['step_started'])
             and near(first['accepted_at'],a['accepted_at']),'accepted event timestamp/episode mismatch')
        need(m['progress']==0 and a['grounded'] is False and vec_near(a['position'],m['start'])
             and vec_near(a['velocity'],[0.,0.,0.]) and near(a['speed'],0.),'accepted state is not pre-advance ordinary traversal')
        need(first['mantle'] is not None,'accepted traversal missing first committed mantle')
        for key in ('kind','from_hang','duration','start','landing'):
            need(m[key]==first['mantle'][key],'accepted mantle differs from first committed episode: '+key)
        need(a['low'] is None and a['low_generation']==first['low_generation']
             and all(a[k] is None for k in ('prone_sample','prone_return','prone_camera','prone_entry_started')),
             'accepted traversal retained another source or stale generation')
        first_source=first['high'] if high else first['low']
        need(first_source is not None and near(first_source['seconds'],DT)
             and near(first_source['source_frame'],1+60*DT),'accepted source lacks first ordinary native advance')
        if high:
            actual=a['high']
            need(actual is not None and actual['outgoing'] is None and actual['seconds']==0.
                 and actual['source_frame']==1. and actual['reference_frame']==7787.,'actual accepted high source is not frame1')
            need(actual['generation']==first_source['generation'] and first_source['outgoing'] is None,'accepted high generation differs from first committed episode')
        else:
            need(a['high'] is None and a['low'] is None and a['low_generation']==first_source['generation'],
                 'accepted low event/sample generation mismatch')
        need(near(m['landing'][1],1.8 if high else .6),'wrong shipped traversal support')
        end=next((r for r in steps if r['simulation_time']+1e-6>=a['simulation_time']+span),None)
        need(end is not None and vec_near(end['position'],m['landing']) and end['mantle'] is None,'native landing endpoint missing')
        sample=end['high'] if high else end['low'];need(sample and near(sample['seconds'],span),'native endpoint clock missing')
        need(near(sample['source_frame'],96 if high else 64),'native final frame missing')
        if high:
            high_generations.append(sample['generation'])
            need(a['high'] and a['high']['generation']==sample['generation'],'high generation changed during accepted action')
        else:
            low_generations.append(sample['generation'])
            need(a['low_generation']==sample['generation'],'low generation changed during accepted action')
        endpoints.append(end['simulation_time'])
    need(len(set(high_generations))==2 and len(set(low_generations))==2,'repeated traversal reused stale ownership generation')
    frames=[r for r in rows if r['kind']=='frame'];need(frames,'native frame records missing')
    need([r['simulation_tick'] for r in frames]==expected_render_ticks(steps,hz),'native render cadence/boundary sequence mismatch')
    last_tick=0;last=None
    for index,r in enumerate(frames):
        tick=r['simulation_tick'];need(r['app_frame']==index and tick>=last_tick and tick-last_tick<=24,'nonuniform frame tick gap/order')
        need(near(r['simulation_time'],tick*DT,2e-6),'render time does not equal committed tick')
        committed=steps[tick-1] if tick else initial[0]
        need(committed['record_index']<r['record_index'] and (tick==len(steps) or r['record_index']<steps[tick]['record_index']),
             'render record is outside its committed tick')
        same_state(r,committed,'render observer changed committed state')
        if tick:
            for key in FRAME_STEP_FIELDS:
                need(r[key]==committed[key],'render observer changed committed presentation: '+key)
        if last and last['visual']['outgoing'] and r['visual']['outgoing'] and last['visual']['route']==r['visual']['route']:
            need(tick-last_tick<=120//hz,'requested dense outgoing render cadence missing')
        last_tick=tick;last=r
    same_state(rows[-1],frames[-1],'terminal actual state differs from final rendered state')
    for t in endpoints:need(any(near(r['simulation_time'],t) and 'png' in r for r in frames),'native endpoint raster witness missing')
    # Six independent outgoing source clocks, each with actual rendered live targets.
    groups={}
    for r in frames:
        out=r['visual']['outgoing']
        if out and 0<out['weight']<1:
            groups.setdefault((r['visual']['route'],out['began']),[]).append(r)
    need(len(groups)==6,'expected high2+low2+prone2 outgoing clocks')
    for key,group in groups.items():
        need(len({round(r['visual']['outgoing']['weight'],6) for r in group})>=2,'insufficient distinct rendered outgoing weights')
        need(len({r['visual']['live_target_pose_crc32'] for r in group})>=2,'outgoing target did not update live')
        selected=[r for r in group if 'png' in r]
        need(len({round(r['visual']['outgoing']['weight'],6) for r in selected})>=2,'insufficient selected intermediate outgoing PNGs')
    need(any(r['phase']=='HighReloadTail' and r['reload_left']>0 and r['visual']['live_target']=='reload' for r in frames),'high tail lacks genuine reload target')
    need(any(r['phase']=='ProneReload' and r['reload_left']>0 and r['visual']['live_target']=='reload' for r in frames),'prone tail lacks genuine reload target')
    for phase in ('LowAdsTail','RepeatLowAdsTail','HighAdsTail'):
        walking=[r for r in frames if r['phase']==phase and r['visual']['outgoing'] and r['ads_requested'] and r['speed']>.1 and r['visual']['visual_ads']>0 and r['visual']['walk_weight']>0 and r['visual']['walk_seconds'] is not None]
        need(len({r['visual']['walk_seconds'] for r in walking})>=2,'live ADS/walk tail missing: '+phase)
    need(sum(1 for r in steps if r.get('prone_sample') and near(r['prone_sample']['seconds'],0))==2,'paired prone entries missing')
    need(any(r.get('prone_sample') and near(r['prone_sample']['seconds'],68/60) and 'png' in r for r in frames),'paired prone native endpoint raster missing')
    need(steps[-1]['shots']==2 and steps[-1]['ammo']+steps[-1]['reserve']==initial[0]['ammo']+initial[0]['reserve']-2,'reload/ammo accounting changed')
    return dict(schema='rust-duty-combined-capture-verification/v1',input_route=h['input_route'],render_cadence=h['render_cadence'],
        committed_ticks=len(steps),native_frame_records=len(frames),accepted_high_low_prone=[2,2,2],native_endpoints=4,
        outgoing_clocks_verified=len(groups),unsupported_scenarios=UNSUPPORTED,platform_hotkeys_verified=False,
        real_time_performance_verified=False,windows_dx12_verified=False,runtime_geometry_parity_verified=False,artistic_approval=False)

def verify(folder,bindings,hz,identity):
    folder=Path(folder);rows=read_trace(folder/'observer.jsonl');result=validate(rows,bindings,hz)
    need(rows[0]['frame_witness']==identity,'invocation witness mismatch')
    for name,digest in HELPERS.items():need(sha(Path(__file__).parent/name)==digest,'witness helper changed')
    from verify_capture_frame_witness import verify as witness
    captures=[r for r in rows if 'png' in r];need(1<=len(captures)<=32,'PNG bound')
    need([r['capture_index'] for r in captures]==list(range(len(captures))),'PNG index gap')
    need(rows[-1]['pngs']==len(captures),'PNG terminal count')
    need({p.name for p in folder.glob('*.png')}=={r['png'] for r in captures},'missing/extra PNG')
    hashes={}
    for r in captures:
        path=safe_path(folder,r['png']);meta=read(str(path)+'.json')
        need(meta['capture']=='native window' and 0<meta['width']<=1440 and 0<meta['height']<=900,'native capture extent')
        png_extent(path,meta)
        witness(path,meta,r['capture_index'],identity)
        for p in (path,Path(str(path)+'.json')):hashes[p.name]=sha(p)
    result.update(rendered_witnesses_verified=len(captures),files_sha256=hashes,observer_sha256=sha(folder/'observer.jsonl'))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',type=Path,required=True)
    p.add_argument('--bindings',type=Path,required=True);p.add_argument('--bindings-sha256',required=True)
    p.add_argument('--hz',type=int,choices=[30,60],required=True);p.add_argument('--identity',required=True);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();need(sha(a.bindings)==a.bindings_sha256,'independent bindings changed');need(not a.report.exists(),'report must be new')
    result=verify(a.capture,read(a.bindings),a.hz,a.identity)
    a.report.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
