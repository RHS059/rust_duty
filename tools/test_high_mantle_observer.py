"""Synthetic source-only checks. No native executable, geometry or image capture."""
import copy, importlib.util, json, math, sys, unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'tools'))
import verify_high_mantle_observer as v
BINDING={'receipt_sha256':'1'*64,'asset_sha256':'2'*64,'return_seconds':.2}

def state(kind,t=0,high=None,mantle=None):
    return {'kind':kind,'simulation_time':t,'binding':BINDING,'high':high,'mantle':mantle,
            'accepted_at':.25,'position':[-10.,0.,-1.5] if t else [0.,0.,9.],
            'velocity':[0.,0.,0.],'camera_eye':[-10.,1.524,-1.5] if t else [0.,1.524,9.],
            'direction':[0.,0.,-1.],'eye_height':1.524,'grounded':high is None,
            'prone':False,'crouched':False,'stance_progress':1.,'dead':False,'health':100.,
            'ads_requested':False,'simulation_ads':0.,'speed':0.,'ammo':30,'reserve':90,'shots':0,
            'reload_left':0.,'reload_credit_at':0.,'reload_ready_at':0.}

def high(seconds,out=None):
    return {'generation':1,'seconds':seconds,'source_frame':1+60*seconds,'reference_frame':7787+60*seconds,'outgoing':out}

def mantle():return {'kind':'High','from_hang':False,'duration':v.NATIVE,'progress':0.,'start':[-10,0,-1.5],'landing':[-10,1.8,-2.411]}

def visual(r,i):
    h=r['high'];out=h['outgoing'] if h else None;w=out['weight'] if out else 0
    r.update(route=('high_mantle.return' if out else 'high_mantle.native') if h else 'regular_walk',
             renderer_failed=False,procedural_weight=w if h else 1.,render_return_weight=w if out else None,
             visual_ads=w if h else 1.,walk_seconds=i/120,walk_weight=1.,underlying_pose_crc32=i,
             weapon_anchor=[0,0,0],app_active=True,camera_forward=[0,0,-1],camera_up=[0,1,0],prone_camera_active=False)
    return r

def stamp(rows):
    for i,r in enumerate(rows):r.update(record_index=i,wall_seconds=i/240,schema=v.SCHEMA)
    return rows

def complete(rendered_endpoint=True):
    rows=[{'kind':'header','input_route':'platform','scene':'range','source_camera_and_rig_basis':'static',
           'source_camera_motion_removal':'none','authored_stance_descent':False,'source_range':[1,96],
           'reference_range_half_open':[7787,7883],'native_seconds':v.NATIVE},state('initial'),
          state('accepted',.25,high(0),mantle())]
    for i in range(1,245):
        t=.25+i/120;out=None;h=None;m=None
        if i<190:h=high(i/120);m=mantle()
        elif i<214:
            x=(i-190)/24;out={'began':.25+v.NATIVE,'duration':.2,'weight':x*x*(3-2*x),
                             'completed':True,'frozen_seconds':v.NATIVE,'frozen_source_frame':96.}
            h=high(v.NATIVE,out)
        r=visual(state('step',t,h,m),i)
        r.update(step_started=t-1/120,input={'jump':i==1,'movement':[0,1],'ads':True},speed=2. if i>190 else 0.)
        if i>=190:
            r.update(position=[-10.,1.8,-2.411],camera_eye=[-10.,3.324,-2.411],grounded=True)
        rows.append(r)
        frame=copy.deepcopy(r);frame.update(kind='frame')
        if i!=190 or rendered_endpoint:frame.update(png=f'{i:04}.png',capture_index=i)
        rows.append(frame)
    rows.append(state('finished',.25+244/120))
    return stamp(rows)

def interruption(mode):
    rows=complete()[:3+60*2]
    before=copy.deepcopy(rows[-1]);before['kind']={'cancel':'pause','reset':'reset','debug-death':'debug_death'}[mode]+'_before'
    platform=copy.deepcopy(before);platform['kind']='platform'
    platform.update(keys={'escape_pressed':mode=='cancel','f2_pressed':mode=='reset','f9_pressed':mode=='debug-death'},transition={'paused':mode=='cancel','resumed':False})
    rows.extend([platform,before]);after=copy.deepcopy(before);after['kind']=before['kind'].replace('_before','_after');after['mantle']=None
    if mode=='cancel':
        out={'began':after['simulation_time'],'duration':.2,'weight':0.,'completed':False,
             'frozen_seconds':after['high']['seconds'],'frozen_source_frame':after['high']['source_frame']}
        after['high']['outgoing']=out;rows.append(after)
        paused=visual(copy.deepcopy(after),61);paused.update(kind='frame',app_active=False,route='high_mantle.native',render_return_weight=None)
        rows.append(paused)
        resume=copy.deepcopy(platform);resume['transition']={'paused':False,'resumed':True};rows.append(resume)
        r=visual(state('step',after['simulation_time']+.3),97)
        r.update(step_started=r['simulation_time']-1/120,input={'jump':False,'movement':[0,0],'ads':False});rows.append(r)
    else:
        after['high']=None
        if mode=='reset':after['simulation_time']=0.
        else:after.update(dead=True,health=0.)
        rows.append(after)
    rows.append(state('finished',rows[-1]['simulation_time']));return stamp(rows)

class Tests(unittest.TestCase):
    def test_complete_synthetic_contract(self):
        r=v.validate(complete(),BINDING,'complete');self.assertTrue(r['live_walk_ads_return']);self.assertTrue(r['source96_rendered_at_zero_weight'])
    def test_rendered_endpoint_gap_is_honest(self):
        r=v.validate(complete(False),BINDING,'complete');self.assertTrue(r['source96_committed_at_zero_weight']);self.assertFalse(r['source96_rendered_at_zero_weight']);self.assertTrue(r['rendered_endpoint_gap'])
    def test_skipped_rendered_return_is_not_a_visual_pass(self):
        rows=complete()
        for r in rows:
            if r['kind']=='frame' and r['high'] and r['high']['outgoing'] and 0<r['high']['outgoing']['weight']<1:
                r.pop('png',None)
        result=v.validate(rows,BINDING,'complete')
        self.assertTrue(result['live_walk_ads_return']);self.assertFalse(result['rendered_visual_return_passed'])
        self.assertTrue(result['rendered_visual_return_gap'])
    def test_platform_interruptions(self):
        for mode in ('cancel','reset','debug-death'):v.validate(interruption(mode),BINDING,mode)
    def reject(self,rows,match,scenario='complete'):
        with self.assertRaisesRegex(v.EvidenceError,match):v.validate(rows,BINDING,scenario)
    def test_reject_inactive_binding(self):
        r=complete();r[1]['binding']=None;self.reject(r,'binding')
    def test_reject_low_and_pullup(self):
        for field,value in [('kind','Low'),('from_hang',True)]:
            r=complete();r[2]['mantle'][field]=value;self.reject(r,'high-ONTO')
    def test_reject_legacy_clock(self):
        r=complete();r[2]['mantle']['duration']=.85;self.reject(r,'stretched')
    def test_reject_stretched_sample(self):
        r=complete();r[3]['high'].update(seconds=.05,source_frame=4,reference_frame=7790);self.reject(r,'stretched')
    def test_reject_not_landed_onto(self):
        r=complete();next(x for x in r if x.get('high') and x['high']['outgoing'] and x['kind']=='step')['position'][1]=0;self.reject(r,'landed ONTO')
    def test_recording_bounds_and_secure_runner(self):
        import run_high_mantle_inputs as runner
        self.assertEqual(runner.FLOOR,1024**3)
        self.assertEqual(runner.WALL_SECONDS,600);self.assertEqual(runner.SIMULATED_SECONDS,30)
        self.assertGreaterEqual(runner.PER_SCENARIO,12*1440*900*4+32*1024**2)
        cmd=runner.invocation(Path('/exe'),Path('/manifest'),Path('/out'),'1'*64)
        self.assertFalse(any(x.startswith('--capture') for x in cmd));self.assertIn('--hold-controls',cmd)
        self.assertIn('--no-update',cmd)
        recorder=(HERE/'src/high_mantle_observer.rs').read_text()
        self.assertIn('const MAX_RECORDS: u64 = 12_000',recorder);self.assertIn('const MAX_BYTES: usize = 16 * 1024 * 1024',recorder)
        capture=(HERE/'src/high_mantle_capture.rs').read_text();self.assertIn('self.index>=12',capture)
    def test_reject_fake_final_source(self):
        r=complete();r[381]['high']['source_frame']=95;self.reject(r,'frame/seconds')
    def test_reject_no_source1(self):
        r=complete();r[2]['high']=high(.001);self.reject(r,'stretched|frame1')
    def test_reject_stance_descent(self):
        r=complete();r[3]['eye_height']=1.4;self.reject(r,'stance descent')
    def test_preexisting_simulation_ads_decays_without_visual_leak(self):
        rows=complete();rows[2]['simulation_ads']=.5;rows[2]['ads_requested']=True
        for r in rows[3:]:
            if r.get('high') and r['high']['outgoing'] is None:
                r['simulation_ads']=max(0,.5-4*r['high']['seconds'])
        v.validate(rows,BINDING,'complete')
        rows[3]['visual_ads']=.01;self.reject(rows,'ADS target/visual')
    def test_reject_simulation_ads_growth_during_native(self):
        rows=complete();rows[3]['simulation_ads']=.2;self.reject(rows,'ADS grew')
    def test_reject_stale_live_pose(self):
        r=complete()
        for row in r:
            if 'underlying_pose_crc32' in row:row['underlying_pose_crc32']=123
        self.reject(r,'underlying pose')
    def test_reject_return_mismatch(self):
        r=complete();row=next(x for x in r if x.get('high') and x['high']['outgoing'] and x['kind']=='step');row['render_return_weight']=.5;self.reject(r,'return weight')
    def test_reject_fake_hotkey(self):
        r=interruption('debug-death');next(x for x in r if x['kind']=='platform')['keys']['f9_pressed']=False;self.reject(r,'native hotkey','debug-death')
    def test_reject_pause_advancement(self):
        r=interruption('cancel');next(x for x in r if x['kind']=='frame' and not x['app_active'])['simulation_time']+=.01;self.reject(r,'smoothstep|freeze','cancel')
    def test_reject_nonfinite_and_unterminated(self):
        r=complete();r[3]['speed']=math.nan;self.reject(r,'nonfinite');self.reject(complete()[:-1],'unterminated')
    def test_helper_hashes(self):
        for name,digest in v.HELPERS.items():self.assertEqual(v.sha(HERE/'tools'/name),digest)
    def test_observer_is_read_only_and_production_admission_stays_closed(self):
        observer=(HERE/'src/high_mantle_observer.rs').read_text()
        additions=observer+(HERE/'src/high_mantle_capture.rs').read_text()
        for forbidden in ['sim.player.position =','sim.time =','sim.player.velocity =','set_high_mantle_binding(', 'APPROVED_RUNTIME_PINS', 'sim.kill(', 'sim.update(']:
            self.assertNotIn(forbidden,additions)
        self.assertIn('event("accepted", self)',(HERE/'src/sim.rs').read_text())
        self.assertIn('sim: &Simulation',observer)
        self.assertNotIn('&mut Simulation',observer)
        self.assertIn("const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = None;",
                      (HERE/'src/authored_high_mantle.rs').read_text())
    def test_observer_rejects_replay_flags_and_uses_native_capture(self):
        text=(HERE/'src/high_mantle_capture.rs').read_text()
        for marker in ['a.starts_with("--capture")','a == "--demo"','a == "--reference-viewport"','capture_png_with_frame_witness(None,']:
            self.assertIn(marker,text)
if __name__=='__main__':unittest.main()
