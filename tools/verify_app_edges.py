#!/usr/bin/env python3
"""Fail-closed app-edge verifier. Read-only; refuses pending native admission.

A CPU synthetic trace exercises this verifier only. Native evidence requires the
independently pinned source/build/admission/receipt/binary chain and terminal
owner process receipts plus real PNG pixels. App-input fixtures do not prove OS
input, combat death, Windows/DX12, mesh parity, performance or artistic approval.
"""
import argparse, hashlib, importlib.util, json, math, re, struct, sys
from pathlib import Path
from app_edge_contract import Recipe, CASES, pressed, input_value, selected_marker
DT=struct.unpack('<f',struct.pack('<f',1/120))[0]
FIELDS=tuple(('simulation_time binding high mantle accepted_at position velocity camera_eye direction '
    'eye_height grounded prone crouched stance_progress dead health ads_requested simulation_ads speed '
    'ammo reserve shots reload_left reload_credit_at reload_ready_at').split())
VISUAL_FIELDS=('visual','high_pose_sampling','camera_forward','camera_up')
# Successful-manifest informational status, derived from the exact source and
# manifest pins. Native verification checks these against the actual candidate;
# no status value can be supplied by the caller or learned from the journal.
REQUIRED_RENDER_STATUS = 'Authored WIP: empty reload, fire, mantle clips unavailable; reload pose crossfades; paired prone runtime remains opt-in WIP'
STATUS_SOURCE_SHA256 = '5088c420374e87437428a864aa2f04afa45377fe3d51943965b448e5929af16e'
STATUS_MANIFEST_SHA256 = 'ecc8bf3e3663276178fa24578f3be57cb3ab96857cfa453be068574914209026'
STATUS_CONTRACT = dict(schema='rust-duty-app-edge-source-status/v1', source_sha256=STATUS_SOURCE_SHA256,
    manifest_sha256=STATUS_MANIFEST_SHA256, required_status=REQUIRED_RENDER_STATUS)
EVENTS={'pause':('pause_before','pause_after'),'reset':('reset_before','reset_after'),
        'debug-death':('debug_death_before','debug_death_after')}
HELPERS={'verify_capture_frame_witness.py':'00011d1904499e1c2c0ea93b4cb74e389d1bf7b78cb0459567b3ae7f65f0f678',
         'verify_render_capture.py':'6bea6d0c9ebabe48bf50c8e45a370652d93bf926bbba3e8326bc754cbff395af'}
class Rejected(ValueError):pass
def need(v,m):
    if not v:raise Rejected(m)
def near(a,b,tol=2e-5):return type(a) in (float,int) and math.isfinite(a) and abs(a-b)<=tol
def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]
def blended_sample_seconds(source,target,weight):
    # Match AnimationSet::blend_poses: each multiply/add/subtract is f32.
    a,b,w=map(f32,(source,target,weight))
    return f32(f32(a*f32(1.-w))+f32(b*w))
def vec(a,b):return type(a) is list and len(a)==len(b) and all(near(x,y) for x,y in zip(a,b))
def finite(v):
    if isinstance(v,dict):return all(finite(x) for x in v.values())
    if isinstance(v,list):return all(finite(x) for x in v)
    return not isinstance(v,float) or math.isfinite(v)
def unique(pairs):
    d={}
    for k,v in pairs:need(k not in d,'duplicate JSON key');d[k]=v
    return d
def loads(b):
    return json.loads(b,object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(Rejected('nonfinite '+x)))
def read(p):
    p=Path(p);need(p.stat().st_size<=16*1024**2,'JSON size bound');return loads(p.read_bytes())
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(p):
    p=Path(p);need(p.is_file() and not p.is_symlink(),'regular file required: '+str(p))
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def valid_sha(s):return isinstance(s,str) and len(s)==64 and s!='0'*64 and all(c in '0123456789abcdef' for c in s)
def path(root,name):
    need(isinstance(name,str) and name and not Path(name).is_absolute() and '\\' not in name,'relative path required')
    need(all(x not in ('','.','..') for x in name.split('/')),'unsafe path')
    p=Path(root)/name
    for q in (p,*p.parents):
        need(not q.is_symlink(),'symlink forbidden')
        if q==Path(root):break
    need(p.resolve().is_relative_to(Path(root).resolve()),'path escapes root');return p
def ref(root,r):
    need(isinstance(r,dict) and valid_sha(r.get('sha256')) and type(r.get('bytes')) is int and r['bytes']>0,'pending file pin')
    p=path(root,r['path']);need(p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'pinned bytes changed: '+r['path']);return p
def state(r):
    need(all(k in r for k in FIELDS),'incomplete actual state: '+r['kind']);return {k:r[k] for k in FIELDS}
def same(a,b,label):need(digest(state(a))==digest(state(b)),label)
def trace(p):
    p=Path(p);need(p.stat().st_size<=5*1024**2,'journal exceeds per-case 5 MiB')
    rows=[]
    with p.open('rb') as stream:
        for line in stream:
            need(len(line)<=32768,'record bytes');rows.append(loads(line));need(len(rows)<=4000,'record count')
    return rows

def sample(r,binding):
    need(r['binding']==binding,'lost or changed admitted binding')
    h=r['high'];m=r['mantle'];t=r['simulation_time']
    need(0<=t<=8 and r['health']>=0,'invalid bounded state')
    if h:
        sec=h['seconds'];out=h['outgoing']
        need(0<=sec<=95/60 and near(h['source_frame'],1+60*sec) and near(h['reference_frame'],7787+60*sec),'native source clock')
        if out:
            need(m is None and out['completed'] is False,'unexpected native completion in interruption case')
            need(near(out['duration'],.20,1e-8) and near(out['frozen_seconds'],sec)
                and near(out['frozen_source_frame'],h['source_frame']),'return retimed or source unfrozen')
            x=max(0.,min(1.,(t-out['began'])/.20));need(near(out['weight'],x*x*(3-2*x)),'return clock/smoothstep')
        else:
            need(m and m['kind']=='High' and m['from_hang'] is False and near(m['duration'],95/60),'not admitted ordinary high-ONTO')
            need(near(sec,t-r['accepted_at']) and near(m['progress'],sec/(95/60)),'native clock frozen/retimed')
            need(vec(m['start'],[-8.6,0.,-3.]) and near(m['landing'][1],1.8),'wrong shipped high obstacle')
            need(not r['prone'] and not r['crouched'] and near(r['stance_progress'],1),'authored stance descent')
    if r['kind'] not in ('app_step','app_frame'):return
    v=r['visual'];out=h and h['outgoing'];need(v['renderer_failed'] is False and type(v['warning']) is str and v['warning']==REQUIRED_RENDER_STATUS,'missing/changed/appended renderer status or renderer failure')
    need(v['owners']==dict(high=h is not None,low=False,prone=False),'stale renderer ownership')
    need(vec(r['camera_forward'],r['direction']) and vec(r['camera_up'],[0.,1.,0.]),'unexpected authored camera rotation')
    if h:
        times=r['high_pose_sampling']
        need(isinstance(times,dict) and set(times)=={'source_pose_seconds','presented_pose_seconds','mapped_target_pose_seconds'},'missing/distorted distinct source/presentation sampling')
        need(near(times['source_pose_seconds'],h['seconds']) and v['high_generation']==h['generation'],'renderer source sample/generation stale')
        if out:
            target=times['mapped_target_pose_seconds'];need(type(target) in (int,float) and math.isfinite(target) and target>=0,'mapped live target sample missing')
            expected=blended_sample_seconds(times['source_pose_seconds'],target,out['weight'])
            need(near(times['presented_pose_seconds'],expected,2e-6),'presented pose sample does not follow actual live f32 blend')
        else:
            need(times['mapped_target_pose_seconds'] is None and near(times['presented_pose_seconds'],h['seconds']), 'native presentation sample stale or return target leaked')
        need(v['route']==('high_mantle.return' if out else 'high_mantle.native'),'renderer source route mismatch')
        need(near(v['procedural_weight'],out['weight'] if out else 0),'procedural native takeover')
        if out:
            vo=v['outgoing'];need(vo and near(vo['began'],out['began']) and near(vo['duration'],.20,1e-8)
                and near(vo['weight'],out['weight']) and near(vo['frozen_pose_seconds'],h['seconds'])
                and near(v['high_return_weight'],out['weight']),'renderer return not synchronized')
        else:
            need(v['outgoing'] is None and v['high_return_weight'] is None and near(v['visual_ads'],0),'native ADS/return leak')
    else:
        need(r['high_pose_sampling'] is None and v['high_generation'] is None and v['high_return_weight'] is None
            and v['outgoing'] is None and not v['route'].startswith('high_mantle.'),'stale cleared renderer source')
        need(v['presented_pose_crc32']==v['live_target_pose_crc32'],'cleared presentation differs from live target')
    actors=v['presented_actors'];target=v['live_target_actors']
    for group in (actors,target):
        need(group and len({a['name'] for a in group})==len(group) and all(isinstance(a['name'],str) and a['name'] and 0<=a['opacity']<=1 for a in group),'invalid renderer actor inventory')
    if out:
        vo=v['outgoing'];need(len(vo['from_opacity'])==len(actors),'outgoing opacity shape')
        named={a['name']:a['opacity'] for a in target};w=out['weight']
        need(near(v['visual_ads'],w*v['underlying_visual_ads']),'outgoing visual ADS not live blend')
        for a,start in zip(actors,vo['from_opacity']):
            need(0<=start<=1 and near(a['opacity'],start*(1-w)+named.get(a['name'],0)*w),'outgoing actor opacity not live blend')
    if r['kind']=='app_frame':
        need(vec(r['rendered_camera_eye'],r['camera_eye']) and vec(r['rendered_camera_forward'],r['camera_forward'])
            and vec(r['rendered_camera_up'],r['camera_up']),'rendered camera unsynchronized')

def validate(rows,binding,case,identity,contract):
    need(case in CASES,'unknown case');limit=6 if case=='pause' else 3
    need(rows and rows[0]['kind']=='header' and rows[-1]['kind']=='finished','unterminated case')
    h=rows[0]
    expected=dict(diagnostic_schema='rust-duty-app-edge/v3',recipe='high-onto-app-input-edges/v1',case=case,
        input_route='app_input_edge_fixture',ordinary_session_and_hotkey_handlers=True,os_input_verified=False,os_focus_verified=False,focus_policy="existing_platform_signal_or_fallback",
        combat_death_verified=False,capture_mode=False,clock='real_wall_fixed_120hz',contract_sha256=contract,
        frame_witness=identity,max_seconds=60.,max_records=4000,max_jsonl_bytes=5*1024**2,max_pngs=limit,max_extent=[1440,900],
        binding=binding,source_range=[1,96],native_seconds=95/60,return_seconds=.20,
        source_camera_and_rig_basis='static',source_camera_motion_removal='none',authored_stance_descent=False,
        native_capture_verified=False,artistic_approval=False,performance_verified=False)
    for k,v in expected.items():need(type(h.get(k)) is type(v) and h[k]==v,'header mismatch: '+k)
    need(vec(h['immutable_scene_start']['position'],[-8.6,0.,-3.]) and near(h['immutable_scene_start']['yaw'],math.pi),'initial spawn declaration')
    wall=-1.;allowed={'header','initial','fixture_input','app_input','app_clock','accepted','app_step','app_frame','finished',*EVENTS[case]}
    for i,r in enumerate(rows):
        need(r['kind'] in allowed and r['schema']=='rust-duty-onehand-observer/v1' and r['record_index']==i
            and finite(r) and type(r['record_index']) is int and type(r['app_frame']) is int,'journal schema/order/unknown event')
        need(type(r['wall_seconds']) in (int,float) and wall<=r['wall_seconds']<=60,'wall clock reversal/bound');wall=r['wall_seconds']
        if r['kind']!='header':state(r);sample(r,binding)
    need(rows[1]['kind']=='initial' and sum(r['kind']=='initial' for r in rows)==1,'initial state count')
    initial=rows[1];need(initial['simulation_time']==0 and vec(initial['position'],[-8.6,0.,-3.])
        and initial['grounded'] and initial['high'] is None and initial['mantle'] is None and not initial['dead'],'initial state')
    frames=[r for r in rows if r['kind']=='app_frame'];need(frames and len(frames)<1000,'frame count')
    active=True;recipe=Recipe(case);current=initial;remainder=0.;tick=0;jump=False;event_count=0;accepted=[];seen=set();last_visual=None;first_start=None;first_wall=None;last_start=None
    need(rows[0]['app_frame']==0 and initial['app_frame']==0,'header/initial frame ownership')
    cursor=2;native_focus_supported=None
    for index,frame in enumerate(frames):
        end=frame['record_index']+1
        need(cursor<end<=len(rows)-1,'noncontiguous app frame boundary')
        group=rows[cursor:end]
        need(all(r['app_frame']==index for r in group),'orphan/wrong-frame journal record')
        cursor=end
        need(len(group)>=3 and group[0]['kind']=='fixture_input' and group[1]['kind']=='app_input' and group[-1] is frame
            and frame['app_frame']==index,'app-frame boundary/order')
        before,inp=group[:2];same(before,current,'fixture input not preceding actual state');same(inp,before,'app input changed state')
        need(before['session_active_before']==active,'fixture session state')
        try:edges=recipe.next(before,active)
        except AssertionError as e:raise Rejected('input recipe predecessor invalid') from e
        need(before['phase']==recipe.stage and digest(before['edges'])==digest(edges) and digest(inp['edges'])==digest(edges),'fixture never reached actual app input or timeline changed')
        need(inp['blocked'] is False and inp['focus']['unfocused'] is False and inp['focus']['changed'] is False,'actual focus/startup blocked')
        supported=inp['focus']['native_supported'];need(type(supported) is bool,'missing native focus capability')
        if native_focus_supported is None:native_focus_supported=supported
        need(supported is native_focus_supported,'native focus capability changed during case')
        raw=inp['raw_dt'];need(type(raw) in (int,float) and math.isfinite(raw) and raw>=0,'invalid real frame dt')
        started=inp['frame_started'];need(type(started) in (float,int) and math.isfinite(started) and started>=0,'invalid frame start clock')
        if last_start is not None:need(near(started-last_start,raw,1e-7),'raw wall delta retimed/frozen')
        if first_start is None:first_start=started;first_wall=inp['wall_seconds']
        need(abs((started-first_start)-(inp['wall_seconds']-first_wall))<=.10,'app runtime and journal wall clocks diverged')
        last_start=started
        new_active=(not pressed(edges,'Escape')) if active else pressed(edges,'Enter') or pressed(edges,'Escape')
        paused=active and not new_active;resumed=not active and new_active
        transition=dict(active=new_active,paused=paused,resumed=resumed,discard_timing=paused or resumed,hitch=raw>.25)
        need(digest(inp['transition'])==digest(transition),'actual SessionController transition mismatch');active=new_active
        reset=pressed(edges,'F2');death=pressed(edges,'F9');event=paused or reset or death
        pos=2;current=before
        if event:
            event_count+=1;names=EVENTS[case]
            need(tuple(r['kind'] for r in group[pos:pos+2])==names,'missing/wrong app handler events')
            old,new=group[pos:pos+2];same(old,current,'handler before state mismatch');pos+=2
            high=old['high'];need(high and not high['outgoing'] and .45<=high['seconds']<.80,'interrupt outside native window')
            need(new['mantle'] is None,'handler retained traversal')
            if paused:
                need(new['position']==old['position'] and new['simulation_time']==old['simulation_time'] and vec(new['velocity'],[0.,0.,0.]),'pause altered position/time or retained velocity')
                out=new['high']['outgoing'];need(out and out['completed'] is False and out['weight']==0
                    and out['began']==old['simulation_time'] and new['high']['seconds']==high['seconds']
                    and new['high']['generation']==high['generation'],'pause did not retain exact cancelled source')
                for k in FIELDS:
                    if k not in ('high','mantle','velocity','grounded','speed'):need(new[k]==old[k],'pause changed unrelated state: '+k)
            elif reset:
                need(new['simulation_time']==0 and new['high'] is None and not new['dead'] and vec(new['position'],[0.,0.,9.]),'F2 did not use normal range reset')
            else:
                need(new['high'] is None and new['dead'] and new['health']==0 and new['position']==old['position']
                    and new['simulation_time']==old['simulation_time'] and vec(new['velocity'],[0.,0.,0.]),'F9 debug death failed')
            current=new
        clear=paused or resumed or reset
        if clear:remainder=0.;jump=False
        # pause/resume clears FocusInput before gameplay latches. Reset marks
        # just_resumed, so no gameplay edge is accepted on that frame either.
        if active:
            need(pos<len(group) and group[pos]['kind']=='app_clock','ordinary app clock missing')
            clock=group[pos];pos+=1;same(clock,current,'clock started from stale state')
            dt=0. if (paused or resumed) else min(raw,.25)
            remainder+=dt;count=math.floor((remainder+1e-6)/(1/120));remainder-=count*(1/120)
            need(near(clock['simulation_dt'],dt,1e-10) and clock['planned_steps']==count,'ordinary wall FixedClock frozen/retimed')
            if not clear:jump|=pressed(edges,'Space')
            for _ in range(count):
                if pos<len(group) and group[pos]['kind']=='accepted':
                    a=group[pos];pos+=1;accepted.append(a)
                    need(a['simulation_time']==current['simulation_time'] and a['accepted_at']==a['simulation_time']
                        and a['high'] and a['high']['seconds']==0 and a['high']['source_frame']==1
                        and a['high']['reference_frame']==7787 and not a['high']['outgoing']
                        and jump and edges['movement']==[0.,1.],'acceptance not fresh ordinary jump/forward')
                else:a=None
                need(pos<len(group) and group[pos]['kind']=='app_step','committed app tick missing/extra event')
                step=group[pos];pos+=1;tick+=1
                need(step['tick']==tick and near(step['step_started'],current['simulation_time'],1e-8)
                    and near(step['simulation_time']-step['step_started'],DT,1e-8),'committed clock gap/retime')
                need(digest(step['input'])==digest(input_value(edges,jump=jump,cleared=clear)),'ordinary controls/latches bypassed');jump=False
                if a:
                    need(step['high'] and step['high']['generation']==a['high']['generation']
                        and near(step['high']['seconds'],DT) and step['mantle'] and step['mantle']['start']==a['mantle']['start']
                        and step['mantle']['landing']==a['mantle']['landing'],'acceptance detached from first committed sample')
                current=step;last_visual=step
        need(pos==len(group)-1,'unaccounted app actions/ticks')
        same(frame,current,'rendered frame differs from current committed/handler state')
        need(frame['tick']==tick and frame['app_active']==active and frame['phase']==recipe.stage,'render session/tick/phase stale')
        if paused:
            prior=frames[index-1]['visual'];shown=frame['visual'];out=shown['outgoing']
            need(out and out['frozen_pose_crc32']==prior['presented_pose_crc32']==shown['presented_pose_crc32'],
                'pause renderer did not freeze exact preceding native pose')
            need(out['from_opacity']==[a['opacity'] for a in prior['presented_actors']], 'pause renderer froze wrong native opacity')
        if current['kind']=='app_step':
            for key in VISUAL_FIELDS:need(frame[key]==current[key],'render presentation differs from last committed step: '+key)
        elif not event and index:
            for key in VISUAL_FIELDS:need(digest(frame[key])==digest(frames[index-1][key]),'presentation changed without committed tick/event: '+key)
        marker=selected_marker(frame,active,recipe.stage,case,seen)
        if marker:
            need(frame.get('marker')==marker and frame.get('png')==f'{len(seen):04}.png' and frame.get('capture_index')==len(seen),'selected PNG boundary mismatch')
            seen.add(marker)
        else:need('png' not in frame and 'marker' not in frame and 'capture_index' not in frame,'unexpected selected PNG')
        current=frame
    need(cursor==len(rows)-1,'unconsumed journal records before terminal state')
    need(len(accepted)==1 and event_count==1 and recipe.stage=='Done','case acceptance/interrupt/terminal counts')
    expected_markers={'native','paused','tail_early','tail_late','clear','ads'} if case=='pause' else {'native','after','terminal'}
    need(seen==expected_markers,'insufficient native raster boundaries')
    finish=rows[-1];same(finish,frames[-1],'finished actual state differs from final rendered state')
    need(finish['completed'] is True and finish['tick']==tick and finish['pngs']==limit and finish['app_frame']==len(frames)-1,'false terminal success')
    need(sum(r['kind']=='fixture_input' for r in rows)==len(frames),'unaccounted extra input frame')
    if case=='pause':
        tail=[r for r in frames if r.get('marker') in ('tail_early','tail_late')]
        need(len(tail)==2 and len({r['visual']['live_target_pose_crc32'] for r in tail})==2,'frozen outgoing live target')
        need(all(r['ads_requested'] and r['speed']>.1 and r['visual']['visual_ads']>0 for r in tail),'no live outgoing movement/ADS')
        out=[r for r in rows if r['kind'] in ('app_step','app_frame') and r['high'] and r['high']['outgoing']]
        frozen={(r['high']['seconds'],r['high']['generation'],r['high']['outgoing']['began'],r['visual']['outgoing']['frozen_pose_crc32']) for r in out}
        need(len(frozen)==1,'outgoing frozen source/generation restarted')
        clear_step=next(r for r in rows if r['kind']=='app_step' and r['record_index']>out[0]['record_index'] and r['high'] is None)
        began=out[0]['high']['outgoing']['began']
        need(began+.2-1e-7<=clear_step['simulation_time']<=began+.2+DT+1e-7,'outgoing cleared early/late')
    return dict(case=case,journal_contract_validated=True,actual_app_handlers_validated=False,input_route='app_input_edge_fixture',
        os_input_verified=False,os_focus_verified=False,native_focus_supported=native_focus_supported,
        focus_scope="native_platform_signal" if native_focus_supported else "existing_platform_focus_fallback",
        combat_death_verified=False,committed_ticks=tick,pngs=limit,
        native_geometry_parity_verified=False,windows_dx12_verified=False,performance_verified=False,artistic_approval=False)

def png_extent(p,meta):
    with Path(p).open('rb') as f:b=f.read(24)
    need(len(b)==24 and b[:8]==b'\x89PNG\r\n\x1a\n' and b[8:16]==b'\0\0\0\rIHDR','invalid PNG header')
    w=int.from_bytes(b[16:20],'big');h=int.from_bytes(b[20:24],'big')
    need(64<=w<=1440 and 22<=h<=900 and (w,h)==(meta['width'],meta['height']),'actual PNG extent mismatch/bound')

# Exact future wrapper commands; these definitions never launch a process.
RUST_CHECKS=(
    ('fmt',['cargo','fmt','--all','--','--check'],60),
    ('lib_tests',['cargo','test','--offline','--no-default-features','--lib','app_edge_','--','--test-threads=1'],300),
    ('legacy_check',['cargo','check','--offline','--no-default-features','--features','legacy-macroquad','--bin','vector-range'],300),
    ('wgpu_check',['cargo','check','--offline','--no-default-features','--features','wgpu-runtime','--bin','vector-range'],300))
RUST_TESTS=('high_app_edge_input::tests::app_edge_status_requires_exact_source_pinned_information',
    'authored_viewmodel::tests::app_edge_distinguishes_frozen_source_and_live_blend_time',
    'high_app_edge_input::tests::app_edge_guard_is_opt_in_and_rejects_mixed_modes',
    'high_app_edge_input::tests::app_edge_request_only_enters_the_existing_input_bridge')
CANDIDATE_FIELDS=('source_root','source_files','source_fingerprint','overlay_allowlist','package_identity',
    'independent_review','high_receipt','high_asset','high_companions','binding','payload_files','manifest',
    'settings','runtime','renderer','build_version','build_number','rust_target_dir','native_focus_supported')
def candidate_identity(c):return {key:c[key] for key in CANDIDATE_FIELDS}
def rust_environment(c):
    target=c['rust_target_dir'];need(isinstance(target,str) and Path(target).is_absolute(),'missing owner-recorded Rust target directory')
    return dict(CARGO_BUILD_JOBS='1',CARGO_INCREMENTAL='0',CARGO_TARGET_DIR=target)
def bounded_command(root,c,e,command,seconds):
    need(e['command']==command and e['cwd']==str(path(root,c['source_root']).resolve()),'wrong exact Rust command/cwd')
    need(e['environment']==rust_environment(c),'Rust environment differs from bounded plan')
    need(e['completed'] is True and type(e['exit_code']) is int and e['exit_code']==0
        and e['timed_out'] is False and e['process_group_terminal'] is True,'Rust command failed/nonterminal')
    need(type(e['wall_seconds']) in (int,float) and math.isfinite(e['wall_seconds']) and 0<e['wall_seconds']<=seconds,'Rust command wall bound')
    need(e['source_before_fingerprint']==c['source_fingerprint']==e['source_after_fingerprint'],'Rust source changed across command')
    g=e['resource_observation']
    need(set(g)=={'live_guard_active','guard_triggered','minimum_free_bytes','minimum_memory_available_bytes','maximum_new_target_bytes'},'incomplete resource observation')
    need(g['live_guard_active'] is True and g['guard_triggered'] is False,'Rust resource guard missing/triggered')
    need(all(type(g[k]) is int for k in ('minimum_free_bytes','minimum_memory_available_bytes','maximum_new_target_bytes'))
        and g['minimum_free_bytes']>=1288490189 and g['minimum_memory_available_bytes']>=2147483648
        and 0<=g['maximum_new_target_bytes']<=402653184,'Rust reserve/resource bound')
    need(e['log']['bytes']<=2*1024**2,'Rust log bound');return ref(root,e['log'])
def verify_rust_checks(root,c,build):
    receipt=read(ref(root,build['rust_checks_receipt']))
    need(set(receipt)=={'schema','candidate','completed','exit_code','rust_format_passed','rust_tests_passed','runtime_checks_passed','checks'},'Rust checks receipt schema fields')
    need(receipt['schema']=='rust-duty-app-edge-rust-checks/v1' and receipt['completed'] is True
        and type(receipt['exit_code']) is int and receipt['exit_code']==0,'Rust checks receipt failed/nonterminal')
    expected=candidate_identity(c)
    need(receipt['candidate']==expected and build['candidate']==expected,'Rust checks/build candidate identity mismatch')
    for flag in ('rust_format_passed','rust_tests_passed','runtime_checks_passed'):
        need(receipt[flag] is True and build[flag] is True,'Rust success flags absent/contradictory: '+flag)
    checks=receipt['checks'];need([e['name'] for e in checks]==[r[0] for r in RUST_CHECKS],'missing/duplicate/reordered Rust check')
    need(len({e['log']['path'] for e in checks})==4 and build['log']['path'] not in {e['log']['path'] for e in checks},'Rust command logs reused')
    for e,(name,command,seconds) in zip(checks,RUST_CHECKS):
        need(set(e)=={'name','command','cwd','environment','completed','exit_code','timed_out','process_group_terminal',
            'wall_seconds','source_before_fingerprint','source_after_fingerprint','resource_observation','log'},'Rust check result fields')
        log=bounded_command(root,c,e,command,seconds)
        if name=='lib_tests':
            text=log.read_text()
            observed=re.findall(r'^test (\S+) \.\.\. (.+)$',text,re.M)
            need(sorted(observed)==sorted((name,'ok') for name in RUST_TESTS),'Rust test results missing/extra/failed/contradictory')
            summaries=re.findall(r'^test result:.*$',text,re.M)
            need(len(summaries)==1 and re.fullmatch(r'test result: ok\. '+str(len(RUST_TESTS))+r' passed; 0 failed; 0 ignored; 0 measured; \d+ filtered out; finished in [0-9.]+s',summaries[0]),'Rust lib summary missing/extra/failed/contradictory')
            need(re.findall(r'^running \d+ tests?$',text,re.M)==['running '+str(len(RUST_TESTS))+' tests'],'Rust test execution count missing/contradictory')
            need(not re.search(r'(?im)^\s*(?:failures:|error:|thread .*panicked|test result: FAILED)',text),'Rust log reports failure despite success receipt')
    return receipt

def check_source_status_identity(c,review):
    source=next((r for r in c['source_files'] if r['path']==c['source_root']+'/src/authored_viewmodel.rs'),None)
    need(source and source['sha256']==STATUS_SOURCE_SHA256,'informational status source differs from exact derivation')
    need(c['manifest']['sha256']==STATUS_MANIFEST_SHA256,'informational status manifest differs from exact derivation')
    need(review.get('renderer_status_contract')==STATUS_CONTRACT,'independent exact source-status review missing/changed')

def verify_config(config,config_sha):
    need(valid_sha(config_sha) and sha(config)==config_sha,'independently supplied contract pin changed/pending')
    c=read(config);need(c.get('schema')=='rust-duty-app-edge-run-contract/v1' and c.get('admitted') is True,'native admission pending')
    root=Path(c['root']).resolve();need(root.is_dir(),'contract root missing')
    need(c['recipe']=='high-onto-app-input-edges/v1' and c['cases']==list(CASES),'recipe/case set changed')
    review=read(ref(root,c['independent_review']))
    need(review.get('passed') is True and review.get('app_edge_overlay_sha256')==c['overlay_allowlist']['sha256']
        and review.get('source_fingerprint')==c['source_fingerprint'] and review.get('package_identity')==c['package_identity'],
        'separate app-edge review/admission absent or stale')
    allow=read(ref(root,c['overlay_allowlist']))
    need(allow['schema']=='rust-duty-app-edge-overlay/v1' and allow['unapplied'] is True,'wrong preparation identity')
    source_root=path(root,c['source_root']);inventory=c['source_files']
    need(inventory and len({r['path'] for r in inventory})==len(inventory),'source inventory empty/duplicate')
    for r in inventory:ref(root,r)
    entries=list(source_root.rglob('*'))
    need(all(not p.is_symlink() and (p.is_file() or p.is_dir()) for p in entries),'source tree contains symlink or special unlisted input')
    actual=sorted(str(p.relative_to(root)) for p in entries if p.is_file()
        and not any(part in ('target','.git','__pycache__') for part in p.relative_to(source_root).parts))
    need(sorted(r['path'] for r in inventory)==actual,'source inventory omits/adds actual files')
    need(digest(sorted(inventory,key=lambda r:r['path']))==c['source_fingerprint'],'source fingerprint mismatch')
    for r in allow['files']:
        name=c['source_root']+'/'+r['path']
        entry=next((x for x in inventory if x['path']==name),None)
        need(entry and entry['sha256']==r['sha256'],'candidate does not contain exact app-edge overlay')
    binary=ref(root,c['binary']);build=read(ref(root,c['build_receipt']))
    need(build['schema']=='rust-duty-app-edge-build-receipt/v1' and build['completed'] is True and build['exit_code']==0
        and build['source_fingerprint']==c['source_fingerprint'] and build['binary']==c['binary']
        and build['overlay_allowlist_sha256']==c['overlay_allowlist']['sha256'],'binary not bound to reviewed source/build')
    need(build['build_version']==c['build_version'] and build['build_number']==c['build_number'],'build release identity changed')
    verify_rust_checks(root,c,build)
    feature='legacy-macroquad' if c['runtime']=='legacy' else 'wgpu-runtime'
    need(build['command']==['cargo','build','--offline','--no-default-features','--features',feature,'--bin','vector-range'], 'unexpected native build command')
    bounded_command(root,c,build,build['command'],600)
    receipt=ref(root,c['high_receipt']);asset=ref(root,c['high_asset'])
    need(c['binding']['receipt_sha256']==sha(receipt) and c['binding']['asset_sha256']==sha(asset)
        and near(c['binding']['return_seconds'],.20,1e-8),'binding not exact admitted asset/receipt')
    need(review['high_receipt_sha256']==sha(receipt) and review['high_asset_sha256']==sha(asset),'receipt admission mismatch')
    payload=c['payload_files']
    need(payload and len({r['path'] for r in payload})==len(payload),'payload inventory empty/duplicate')
    for r in payload:ref(root,r)
    need(digest(sorted(payload,key=lambda r:r['path']))==review['payload_fingerprint'],'payload not bound to independent admission review')
    for r in (c['high_receipt'],c['high_asset'],c['manifest'],c['settings']):need(r in payload,'required input omitted from admitted payload inventory')
    companions=c['high_companions'];need(set(companions)=={'vrs','vrm'},'high companion inventory missing')
    for suffix,r in companions.items():
        need(r in payload and ref(root,r)==asset.with_suffix('.'+suffix),'high companion changed/omitted')
    manifest=ref(root,c['manifest']);settings=ref(root,c['settings'])
    need(c['runtime'] in ('legacy','wgpu') and c['renderer'] in ('gl','dx12','vulkan'),'unsupported declared runtime/backend')
    need((c['runtime']=='legacy')==(c['renderer']=='gl'),'runtime/renderer mismatch')
    need(type(c['run_id']) is str and c['run_id'],'run identity missing')
    need(type(c['native_focus_supported']) is bool,'native focus capability admission pending')
    check_source_status_identity(c,review)
    return c,root,binary,manifest,settings

def witness_identity(c,case,contract_sha):
    return digest(dict(contract_sha256=contract_sha,source_fingerprint=c['source_fingerprint'],
        binary_sha256=c['binary']['sha256'],run_id=c['run_id'],case=case,recipe=c['recipe']))

def invocation(c,binary,manifest,settings,folder,case,contract_sha):
    return [str(binary),'--no-update','--hold-controls','--level=range','--profile=m4a1',
        '--renderer='+c['renderer'],'--animation-manifest='+str(manifest),
        '--settings='+str(settings),'--app-edge-case='+case,'--app-edge-output='+str(folder),
        '--app-edge-witness='+witness_identity(c,case,contract_sha),'--app-edge-contract='+contract_sha]

def native_guard(e):
    g=e['resource_observation']
    need(isinstance(g,dict) and g.get('live_guard_active') is True and g.get('guard_triggered') is False
        and type(g.get('minimum_free_bytes')) is int and g['minimum_free_bytes']>=1288490189
        and type(g.get('minimum_memory_available_bytes')) is int and g['minimum_memory_available_bytes']>=2147483648,
        'native resource guard absent/failed or reserve below bound')
def native_output_inventory(folder,case_limits,receipt_name,max_bytes):
    need(folder.is_dir() and not folder.is_symlink(),'native output root must be a real directory')
    entries=list(folder.rglob('*'))
    need(all(not p.is_symlink() and (p.is_file() or p.is_dir()) for p in entries),'native output symlink/special file')
    expected={receipt_name}
    for case,limit in case_limits.items():
        expected.update(case+'/'+name for name in ('observer.jsonl','stdout.log','stderr.log'))
        expected.update(case+'/'+f'{i:04}.png'+suffix for i in range(limit) for suffix in ('','.json'))
    actual={str(p.relative_to(folder)) for p in entries if p.is_file()}
    need(actual==expected and {str(p.relative_to(folder)) for p in entries if p.is_dir()}==set(case_limits),
        'native output inventory missing/extra/unaccounted file or directory')
    total=sum(p.stat().st_size for p in entries if p.is_file())
    need(total<=max_bytes,'complete native output exceeds reservation')
    return total
def native_logs(folder,e,case):
    logs=e['process_logs'];need(set(logs)=={'stdout','stderr'},'native process log inventory')
    for stream,pin in logs.items():
        need(pin['path']==case+'/'+stream+'.log' and valid_sha(pin['sha256']) and type(pin['bytes']) is int
            and 0<=pin['bytes']<=2*1024**2,'native process log path/pin/bound')
        p=path(folder,pin['path']);need(p.stat().st_size==pin['bytes'] and sha(p)==pin['sha256'],'native process log changed')

def verify_run(folder,config,config_sha,helper_dir):
    c,root,binary,manifest,settings=verify_config(config,config_sha)
    folder=Path(folder).resolve();run=read(folder/'run.json')
    need(run['schema']=='rust-duty-app-edge-native-run/v1' and run['contract_sha256']==config_sha
        and run['completed'] is True and run['inputs_unchanged'] is True,'native run incomplete/stale')
    need(run['source_fingerprint']==c['source_fingerprint'] and run['binary_sha256']==c['binary']['sha256'],'run source/binary mismatch')
    need(run['scope']=='native_app_input_fixture' and run['os_input_verified'] is False and run['combat_death_verified'] is False,'false evidence scope')
    entries=run['cases'];need([e['case'] for e in entries]==list(CASES),'missing/duplicate/reordered native cases')
    total_output_bytes=native_output_inventory(folder,dict(pause=6,reset=3,**{'debug-death':3}),'run.json',96*1024**2)
    helpers=Path(helper_dir).resolve()
    for name,pin in HELPERS.items():need(sha(helpers/name)==pin,'PNG verifier helper changed')
    sys.path.insert(0,str(helpers))
    from verify_capture_frame_witness import verify as witness
    results=[];total_bytes=0;total_wall=0;total_png=0
    for e in entries:
        case=e['case'];out=folder/case
        command=invocation(c,binary,manifest,settings,out,case,config_sha)
        need(e['command']==command and type(e['exit_code']) is int and e['exit_code']==0 and e['completed'] is True
            and e['timed_out'] is False and e['process_group_terminal'] is True,'native process failed/nonterminal or wrong actual command')
        need(e['binary_before_sha256']==c['binary']['sha256']==e['binary_after_sha256'],'executed binary changed')
        need(type(e['wall_seconds']) in (float,int) and 0<e['wall_seconds']<=60,'case wall bound')
        native_guard(e);native_logs(folder,e,case)
        total_wall+=e['wall_seconds'];journal=out/'observer.jsonl'
        need(sha(journal)==e['observer_sha256'],'recorded input/event timeline changed')
        rows=trace(journal);total_bytes+=journal.stat().st_size
        need(rows[-1]['wall_seconds']<=e['wall_seconds']+0.1,'journal beyond process lifetime')
        need(rows[0]['build_version']==c['build_version'] and rows[0]['build_number']==c['build_number'],'native build header mismatch')
        identity=witness_identity(c,case,config_sha);result=validate(rows,c['binding'],case,identity,config_sha)
        need(result['native_focus_supported'] is c['native_focus_supported'],'native focus capability differs from admitted backend')
        selected=[r for r in rows if 'png' in r]
        need({p.name for p in out.glob('*.png')}=={r['png'] for r in selected},'missing/extra raster files')
        need({p.name for p in out.glob('*.png.json')}=={r['png']+'.json' for r in selected},'missing/extra raster metadata')
        files={}
        for r in selected:
            p=path(out,r['png']);meta=read(str(p)+'.json')
            need(meta['capture']=='native window','not actual native window readback')
            need(meta['requested']==c['renderer'] and meta['backend']=={'gl':'OpenGl','dx12':'Dx12','vulkan':'Vulkan'}[c['renderer']]
                and isinstance(meta['adapter'],str) and meta['adapter'],'native backend/request mismatch')
            png_extent(p,meta);witness(p,meta,r['capture_index'],identity)
            files[p.name]=sha(p);files[p.name+'.json']=sha(str(p)+'.json')
        need(files==e['capture_files_sha256'],'PNG or metadata bytes changed')
        total_png+=len(selected);result['native_png_witnesses_verified']=len(selected);result['actual_app_handlers_validated']=True
        result['observer_sha256']=sha(journal);results.append(result)
    need(total_wall<=180 and total_bytes<=15*1024**2 and total_png==12,'suite budget exceeded')
    verify_config(config,config_sha)
    return dict(schema='rust-duty-app-edge-native-verification/v1',cases=results,
        contract_sha256=config_sha,run_sha256=sha(folder/'run.json'),total_pngs=12,total_journal_bytes=total_bytes,total_output_bytes=total_output_bytes,
        actual_app_handlers_validated=True,native_png_witnesses_verified=12,os_input_verified=False,os_focus_verified=False,
        native_focus_supported=c["native_focus_supported"],focus_scope="native_platform_signal" if c["native_focus_supported"] else "existing_platform_focus_fallback",
        combat_death_verified=False,windows_dx12_verified=False,performance_verified=False,artistic_approval=False)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--contract',type=Path,required=True);p.add_argument('--contract-sha256',required=True)
    p.add_argument('--helper-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();need(not a.report.exists(),'report must be new')
    result=verify_run(a.run,a.contract,a.contract_sha256,a.helper_dir)
    a.report.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
