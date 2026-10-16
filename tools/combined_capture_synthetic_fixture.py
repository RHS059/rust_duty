"""Invented observer projections over a source-free CPU route, for rejection tests.

These identities, poses, optics, ammo and raster names are synthetic. This fixture
is NEVER a native capture, loader admission, geometry, performance or art proof.
"""
import copy,json,math,os
from pathlib import Path
from combined_replay_contract import DT
from verify_combined_capture import SCHEMA,UNSUPPORTED,rotate,cross,norm,slerp_identity
BINDINGS={k:dict(asset_sha256='1'*64,receipt_sha256='2'*64,return_seconds=.2) for k in ('high','low')}
BINDINGS['prone']=dict(asset_vra_sha256='3'*64,camera_sidecar_sha256='4'*64,receipt_sha256='5'*64)

def reindex(rows):
    for i,r in enumerate(rows):r.update(schema=SCHEMA,record_index=i)

def frame_ticks(states,hz):
    # Independently mirror the app's target + commit-break loop, not verifier helper.
    result=[0]*7;tick=0;interval=24;old=None
    while tick<len(states)-1:
        until=tick+interval
        while tick<min(until,len(states)-1):
            tick+=1;s=states[tick];p=s['prone_sample'];h=s['high'];l=s['low']
            signature=((s['mantle'] or {}).get('kind'),bool(h and h['outgoing'] and h['outgoing']['completed']),
                bool(l and abs(l['seconds']-63/60)<1e-6),bool(p),bool(p and p['seconds']+1e-6>=68/60),bool(s['prone_return']),s['phase'])
            interval=120//hz if signature[1] or signature[5] or s['visual']['low_return_weight'] is not None or s['phase'] in ('LowAdsTail','RepeatLowAdsTail') else 12 if signature[0] or signature[3] else 24
            changed=old is not None and old!=signature;old=signature
            if changed:break
        result.append(tick)
    return result

def fixture(hz=30):
    source=json.loads(Path(os.environ['COMBINED_SOURCE_FREE_TEST_TRACE']).read_text())['rows']
    states=[];accepted=[];accepted_at=0.;low_gen=0;low_end=None;prone_start=None;frozen=None
    ammo=30;reserve=90;credit_at=ready_at=0.;credited=False
    for idx,item in enumerate(source):
        s=copy.deepcopy(item);t=s['simulation_time'];prev=states[-1] if states else None
        for sample in (s['prone_sample'],s['prone_return']):
            if sample:sample['orientation_xyzw']=[math.sin(.1),0.,0.,math.cos(.1)]
        shot_delta=s['shots']-(prev['shots'] if prev else 0)
        if prev and prev['reload_left']>0 and not credited and prev['simulation_time']+1e-7>=credit_at:
            n=min(30-ammo,reserve);ammo+=n;reserve-=n;credited=True
        ammo-=shot_delta
        if s['reload_left']>0 and (not prev or prev['reload_left']<=0):
            credit_at=prev['simulation_time']+1.35;ready_at=prev['simulation_time']+s['reload_left'];credited=False
        if s.get('input',{}).get('jump'):
            accepted_at=prev['simulation_time']
            if s['mantle']['kind']=='Low':low_gen=s['low']['generation']
            a=copy.deepcopy(prev);a['kind']='accepted';a['mantle']=copy.deepcopy(s['mantle']);a['mantle']['progress']=0.;a['low_generation']=low_gen
            a.update(accepted_at=accepted_at,grounded=False,velocity=[0.,0.,0.],speed=0.,reload_left=0.,reload_credit_at=0.,reload_ready_at=0.)
            if s['high']:
                a['high']=copy.deepcopy(s['high']);a['high'].update(seconds=0.,source_frame=1.,reference_frame=7787.)
            a['accepted_source_clock']=dict(kind=s['mantle']['kind'],seconds=0.,source_frame=1.,rendered=False,from_hang=False)
            accepted.append((idx,a))
        if prev and prev.get('low') and not s.get('low'):low_end=t
        low_out=low_end is not None and t<low_end+.2-1e-8
        out=s['high']['outgoing'] if s['high'] else s['prone_return']
        if low_out:out=dict(began=low_end,duration=.2)
        high=bool(s['high']);low=bool(s['low'] or low_out);prone=bool(s['prone_sample'] or s['prone_return'])
        route=('high_mantle.return' if out else 'high_mantle.native') if high else ('low_vault.return' if out else 'low_vault.low_mantle_native_wip') if low else ('prone.return' if out else 'prone.entry_hold') if prone else 'ready'
        if s['prone_sample']:
            if not prev or not prev['prone_sample']:prone_start=t
        else:prone_start=None
        if out:
            out=copy.deepcopy(out);x=max(0,min(1,(t-out['began'])/.2));out['weight']=x*x*(3-2*x);out['from_opacity']=[1.]
            if not prev or not prev['visual']['outgoing']:
                clock=s['high']['seconds'] if high else prev['low']['seconds'] if low else prev['prone_sample']['seconds']
                frozen=(clock,idx if high else prev['visual']['presented_pose_crc32'])
            out.update(frozen_pose_seconds=frozen[0],frozen_pose_crc32=frozen[1])
        eye=s['prone_sample']['eye_height'] if s['prone_sample'] else 1.524
        camera=copy.deepcopy(s['prone_sample'])
        if s['prone_return']:
            pr=s['prone_return'];camera=dict(seconds=pr['frozen_seconds'],source_frame=pr['frozen_source_frame'],eye_height=eye,orientation_xyzw=slerp_identity(pr['orientation_xyzw'],pr['weight']))
        f=[-1.,0.,0.];u=[0.,1.,0.];forward=f;up=u
        if camera:
            right=norm(cross(f,u));basis_up=norm(cross(right,f));q=camera['orientation_xyzw']
            def world(v):return norm([right[k]*v[0]+basis_up[k]*v[1]-f[k]*v[2] for k in range(3)])
            forward=world(rotate(q,[0,0,-1]));up=world(rotate(q,[0,1,0]))
        s.update(kind='initial' if idx==0 else 'step',phase=s.get('phase','PrimeShot'),tick=idx-1,step_started=max(0,idx-1)*DT,accepted_at=accepted_at,low_generation=low_gen,
                 velocity=[0.,0.,0.],health=100.,ammo=ammo,reserve=reserve,reload_credit_at=credit_at,reload_ready_at=ready_at,ads_requested=s.get('input',{}).get('ads',False),
                 eye_height=eye,landing_kick=0.,lean_offset=[0.,0.,0.],bindings=copy.deepcopy(BINDINGS),look=dict(yaw=math.pi,pitch=0.),prone_entry_started=prone_start,
                 direction=f,camera_base_forward=f,camera_base_up=u,camera_forward=forward,camera_up=up,prone_camera=camera)
        s['camera_eye']=[s['position'][0],s['position'][1]+eye,s['position'][2]]
        weight=out['weight'] if out else 0. if high or low or prone else 1.
        s['visual']=dict(owners=dict(high=high,low=low,prone=prone),renderer_failed=False,warning=None,route=route,
                        high_generation=s['high']['generation'] if high else None,low_generation=low_gen if low else None,
                        presented_actors=[dict(name='weapon',opacity=1.)],live_target_actors=[dict(name='weapon',opacity=1.)],
                        outgoing=out,live_target='reload' if s['reload_left']>0 else 'base',live_target_pose_crc32=idx,
                        presented_pose_crc32=idx,procedural_weight=weight,
                        high_return_weight=out['weight'] if out and high else None,low_return_weight=out['weight'] if out and low else None,
                        visual_ads=s['simulation_ads']*weight,underlying_visual_ads=s['simulation_ads'],walk_weight=1.,walk_seconds=t,prone_procedural_weight=out['weight'] if prone and out else 0. if prone else 1.)
        states.append(s)
    header=dict(kind='header',input_route='deterministic_committed_input_replay',sequence='gameplay-combined',sampling_hz=hz,fixed_hz=120,
                render_cadence=dict(policy='nonuniform_committed_boundaries_v1',source_hz=10,travel_hz=5,dense_return_hz=hz,render_on_committed_boundaries=True),
                bindings=BINDINGS,unsupported_scenarios=UNSUPPORTED,platform_hotkeys_verified=False,performance_verified=False,artistic_approval=False,
                immutable_scene_start=dict(position=[-8.6,0.,-3.],yaw=math.pi,setup='combined_replay::start before first update'),frame_witness='0'*64)
    ticks=frame_ticks(states,hz);rows=[header,states[0]];pngs=0;frame=0;last_tick=0;groups={};last_endpoint=None
    for tick in ticks:
        for idx in range(last_tick+1,tick+1):
            rows.extend(a for at,a in accepted if at==idx);rows.append(states[idx])
        s=states[tick];f=copy.deepcopy(s);f.update(kind='frame',simulation_tick=tick,app_frame=frame,rendered_camera_eye=s['camera_eye'],rendered_camera_forward=s['camera_forward'],rendered_camera_up=s['camera_up'])
        endpoint=bool((s['high'] and s['high']['outgoing'] and s['high']['outgoing']['weight']==0) or (s['low'] and s['low']['source_frame']==64) or (s['prone_sample'] and s['prone_sample']['source_frame']==69 and last_endpoint!='prone'))
        out=s['visual']['outgoing'];chosen=False
        if out and 0<out['weight']<1:
            key=(s['visual']['route'],out['began']);groups[key]=groups.get(key,0)+1;chosen=groups[key] in (1,3)
        if endpoint or chosen:
            f.update(png=f'{pngs:04}.png',capture_index=pngs);pngs+=1
            if s['prone_sample']:last_endpoint='prone'
        rows.append(f);frame+=1;last_tick=tick
    terminal=copy.deepcopy(states[-1]);terminal.update(kind='finished',completed=True,accepted_counts_high_low_prone=[2,2,2],pngs=pngs);rows.append(terminal)
    reindex(rows);return rows
