"""INVENTED CPU-only journal data. Does not run or certify Rust/game/native assets.

The simplified physics and poses below deliberately are not the game engine.
This generator exists solely to test verifier rejection/acceptance semantics.
"""
from copy import deepcopy as cp
from app_edge_contract import Recipe, pressed, input_value, selected_marker
from verify_app_edges import DT, f32, blended_sample_seconds, REQUIRED_RENDER_STATUS
import math
BINDING=dict(receipt_sha256='a'*64,asset_sha256='b'*64,return_seconds=.2)
IDENTITY='1'*64
CONTRACT='2'*64

def initial():
    return dict(simulation_time=0.,binding=BINDING,high=None,mantle=None,accepted_at=-10.,position=[-8.6,0.,-3.],
        velocity=[0.,0.,0.],camera_eye=[-8.6,1.524,-3.],direction=[-1.,0.,0.],eye_height=1.524,grounded=True,
        prone=False,crouched=False,stance_progress=1.,dead=False,health=100.,ads_requested=False,simulation_ads=0.,
        speed=0.,ammo=30,reserve=90,shots=0,reload_left=0.,reload_credit_at=0.,reload_ready_at=0.)

def visual(s):
    h=s['high'];out=h and h['outgoing'];w=out['weight'] if out else 0.;live=100000+round(s['simulation_time']*120)
    source=round(h['seconds']*6000) if h else live
    return dict(route=('high_mantle.return' if out else 'high_mantle.native') if h else 'locomotion',
        owners=dict(high=h is not None,low=False,prone=False),high_generation=h['generation'] if h else None,
        low_generation=None,live_target='base',live_target_pose_crc32=live,presented_pose_crc32=source,
        live_target_actors=[dict(name='test_actor',opacity=1.)],presented_actors=[dict(name='test_actor',opacity=1.)],
        outgoing=dict(began=out['began'],duration=.2,weight=w,from_opacity=[1.],
            frozen_pose_seconds=h['seconds'],frozen_pose_crc32=source) if out else None,
        visual_ads=w*s['simulation_ads'] if out else 0. if h else s['simulation_ads'],
        underlying_visual_ads=s['simulation_ads'],walk_seconds=s['simulation_time'] if s['speed'] else None,
        walk_weight=1. if s['speed'] else 0.,procedural_weight=w if h else 1.,prone_procedural_weight=1.,
        high_return_weight=w if out else None,low_return_weight=None,warning=REQUIRED_RENDER_STATUS,renderer_failed=False)

def decorate(row):
    row['visual']=visual(row)
    h=row['high'];out=h and h['outgoing']
    source=f32(h['seconds']) if h else None
    target=f32(0.10+(row['simulation_time']%0.30)) if out else None
    # Invented live target sample ages, deliberately distinct from the native
    # frozen source. Presentation uses the renderer's documented f32 arithmetic.
    row['high_pose_sampling']=dict(source_pose_seconds=source,
        presented_pose_seconds=blended_sample_seconds(source,target,out['weight']) if out else source,
        mapped_target_pose_seconds=target) if h else None
    row['camera_forward']=row['direction'];row['camera_up']=[0.,1.,0.]

def make(case,hz=60):
    rows=[];s=initial();active=True;recipe=Recipe(case);wall=0.;app_frame=0;tick=0;remainder=0.;jump=False;seen=set()
    def record(kind,value=None,**extra):
        r=cp(s if value is None else value);r.update(extra)
        r.update(kind=kind,schema='rust-duty-onehand-observer/v1',record_index=len(rows),wall_seconds=wall,app_frame=app_frame)
        rows.append(r);return r
    record('header',dict(diagnostic_schema='rust-duty-app-edge/v3',recipe='high-onto-app-input-edges/v1',case=case,
        input_route='app_input_edge_fixture',ordinary_session_and_hotkey_handlers=True,os_input_verified=False,os_focus_verified=False,focus_policy="existing_platform_signal_or_fallback",
        combat_death_verified=False,capture_mode=False,clock='real_wall_fixed_120hz',contract_sha256=CONTRACT,
        frame_witness=IDENTITY,max_seconds=60.,max_records=4000,max_jsonl_bytes=5*1024**2,max_pngs=6 if case=='pause' else 3,max_extent=[1440,900],
        binding=BINDING,source_range=[1,96],native_seconds=95/60,return_seconds=.20,build_version='SYNTHETIC',build_number=0,
        source_camera_and_rig_basis='static',source_camera_motion_removal='none',authored_stance_descent=False,
        native_capture_verified=False,artistic_approval=False,performance_verified=False,
        immutable_scene_start=dict(position=[-8.6,0.,-3.],yaw=math.pi)))
    record('initial')
    for app_frame in range(500):
        raw=1/hz;wall+=raw
        edges=recipe.next(s,active)
        record('fixture_input',phase=recipe.stage,session_active_before=active,edges=edges)
        new_active=(not pressed(edges,'Escape')) if active else pressed(edges,'Enter') or pressed(edges,'Escape')
        paused=active and not new_active;resumed=not active and new_active;active=new_active
        tr=dict(active=active,paused=paused,resumed=resumed,discard_timing=paused or resumed,hitch=raw>.25)
        record('app_input',edges=edges,frame_started=100.+wall,raw_dt=raw,blocked=False,transition=tr,focus=dict(unfocused=False,changed=False,native_supported=False))
        reset=pressed(edges,'F2');death=pressed(edges,'F9')
        if paused:
            record('pause_before');h=s['high'];h['outgoing']=dict(began=s['simulation_time'],duration=.2,weight=0.,completed=False,
                frozen_seconds=h['seconds'],frozen_source_frame=h['source_frame'])
            s.update(mantle=None,velocity=[0.,0.,0.],speed=0.,grounded=False);record('pause_after')
        elif reset:
            record('reset_before');s=initial();s['position']=[0.,0.,9.];s['camera_eye']=[0.,1.524,9.];record('reset_after')
        elif death:
            record('debug_death_before');s.update(high=None,mantle=None,dead=True,health=0.,velocity=[0.,0.,0.],speed=0.)
            record('debug_death_after')
        clear=paused or resumed or reset
        if clear:remainder=0.;jump=False
        if active:
            dt=0. if paused or resumed else min(raw,.25);remainder+=dt
            count=math.floor((remainder+1e-6)/(1/120));remainder-=count*(1/120)
            record('app_clock',simulation_dt=dt,planned_steps=count)
            if not clear:jump|=pressed(edges,'Space')
            for _ in range(count):
                inp=input_value(edges,jump=jump,cleared=clear);jump=False;t=s['simulation_time']
                if inp['jump']:
                    s['accepted_at']=t;s['high']=dict(generation=1,seconds=0.,source_frame=1.,reference_frame=7787.,outgoing=None)
                    s['mantle']=dict(kind='High',from_hang=False,duration=95/60,progress=0.,start=[-8.6,0.,-3.],landing=[-9.6,1.8,-3.])
                    s['grounded']=False;record('accepted')
                s['simulation_time']+=DT;h=s['high']
                if h and not h['outgoing']:
                    sec=s['simulation_time']-s['accepted_at'];h.update(seconds=sec,source_frame=1+60*sec,reference_frame=7787+60*sec)
                    s['mantle']['progress']=sec/(95/60)
                    s['position']=[-8.6,sec*.5,-3.]
                elif h:
                    out=h['outgoing'];x=max(0.,min(1.,(s['simulation_time']-out['began'])/.2));out['weight']=x*x*(3-2*x)
                    if x>=1:s['high']=None
                if inp['ads']:
                    s['simulation_ads']=min(1.,s['simulation_ads']+.08);s['ads_requested']=True
                    s['velocity']=[0.,0.,1.];s['speed']=1.;s['position'][2]+=DT
                s['camera_eye']=[s['position'][0],s['position'][1]+s['eye_height'],s['position'][2]]
                tick+=1;r=record('app_step',tick=tick,step_started=t,input=inp);decorate(r)
        r=record('app_frame',tick=tick,phase=recipe.stage,app_active=active);decorate(r)
        r.update(rendered_camera_eye=r['camera_eye'],rendered_camera_forward=r['camera_forward'],rendered_camera_up=r['camera_up'])
        marker=selected_marker(r,active,recipe.stage,case,seen)
        if marker:r.update(marker=marker,png=f'{len(seen):04}.png',capture_index=len(seen));seen.add(marker)
        if recipe.stage=='Done':break
    record('finished',completed=True,tick=tick,pngs=len(seen))
    return rows
