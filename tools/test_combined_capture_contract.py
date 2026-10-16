#!/usr/bin/env python3
"""Synthetic verifier/route tests. These are never native capture evidence."""
import copy,json,math,os,tempfile,unittest
from pathlib import Path
from combined_replay_contract import Route,RouteError,observed,blank
from verify_combined_capture import camera_once,opacity,validate,state_bindings,STATE_KINDS,SCHEMA,UNSUPPORTED,png_extent,STATE_FIELDS,same_state,cross,norm,rotate

def state(t=0.):
    return dict(time=t,position=[-8.6,0.,-3.],speed=0.,grounded=True,standing=True,mantle=None,
        high_completed=False,low_endpoint=False,prone_seconds=None,prone_return=False,
        reload_left=0.,ads=0.,shots=1,dead=False)

def visual_row():
    return dict(simulation_time=1.1,high=None,low=None,prone_sample=None,prone_return=dict(began=1.),
        visual=dict(owners=dict(high=False,low=False,prone=True),renderer_failed=False,warning=None,
            presented_actors=[dict(name='weapon',opacity=.6),dict(name='old_mag',opacity=.5)],
            live_target_actors=[dict(name='weapon',opacity=.2)],
            outgoing=dict(began=1.,duration=.2,weight=.5,from_opacity=[1.,1.]),
            live_target='reload',procedural_weight=.5,visual_ads=0.,underlying_visual_ads=0.,route='prone.return'))

class ContractTests(unittest.TestCase):
    def test_each_state_requires_current_complete_bindings(self):
        expected={key:dict(receipt_sha256=key) for key in ('low','prone','high')}
        for kind in STATE_KINDS:
            state_bindings(dict(kind=kind,bindings=copy.deepcopy(expected)),expected)
            with self.assertRaisesRegex(ValueError,'missing current loaded bindings'):
                state_bindings(dict(kind=kind),expected)
            for key in expected:
                for changed in (None,dict(receipt_sha256='changed')):
                    actual=copy.deepcopy(expected);actual[key]=changed
                    with self.assertRaisesRegex(ValueError,'loaded binding changed or admission lost'):
                        state_bindings(dict(kind=kind,bindings=actual),expected)
                actual=copy.deepcopy(expected);del actual[key]
                with self.assertRaisesRegex(ValueError,'loaded binding changed or admission lost'):
                    state_bindings(dict(kind=kind,bindings=actual),expected)
    def test_full_validator_rejects_missing_state_binding_before_motion_claims(self):
        expected={key:dict(asset_sha256='1'*64,receipt_sha256='2'*64,return_seconds=.2) for key in ('low','high')}
        expected['prone']=dict(asset_vra_sha256='3'*64,camera_sidecar_sha256='4'*64,receipt_sha256='5'*64)
        header=dict(kind='header',schema=SCHEMA,record_index=0,input_route='deterministic_committed_input_replay',sequence='gameplay-combined',sampling_hz=30,fixed_hz=120,
            render_cadence=dict(policy='nonuniform_committed_boundaries_v1',source_hz=10,travel_hz=5,dense_return_hz=30,render_on_committed_boundaries=True),
            bindings=expected,unsupported_scenarios=UNSUPPORTED,platform_hotkeys_verified=False,performance_verified=False,artistic_approval=False,
            immutable_scene_start=dict(position=[-8.6,0.,-3.],yaw=math.pi,setup='combined_replay::start before first update'))
        initial=dict(kind='initial',schema=SCHEMA,record_index=1,simulation_time=0.,position=[-8.6,0.,-3.],high=None,low=None,bindings=expected,look=dict(yaw=math.pi,pitch=0.))
        for kind in STATE_KINDS:
            rows=[copy.deepcopy(header),copy.deepcopy(initial)]
            if kind=='initial':del rows[1]['bindings']
            elif kind!='finished':rows.append(dict(kind=kind,schema=SCHEMA,record_index=2))
            finish=dict(kind='finished',schema=SCHEMA,record_index=len(rows),bindings=expected,look=dict(yaw=math.pi,pitch=0.))
            if kind=='finished':del finish['bindings']
            rows.append(finish)
            with self.assertRaisesRegex(ValueError,'missing current loaded bindings on '+kind):validate(rows,expected,30)
    def test_request_rejection_cannot_advance_route(self):
        r=Route();self.assertTrue(r.input(state())['fire']);self.assertFalse(r.input(state(.3))['jump'])
        self.assertTrue(r.input(state(38/120))['jump'])
        with self.assertRaises(RouteError):r.input(state(39/120))
    def test_wrong_native_endpoint_cannot_advance_route(self):
        r=Route();r.phase='LowRide'
        with self.assertRaises(RouteError):r.input(state(1.))
    def test_unsafe_east_lane_is_failure(self):
        r=Route();r.phase='SouthLane'
        with self.assertRaises(RouteError):r.input(state())
    def test_named_live_opacity_must_follow_committed_weight(self):
        row=visual_row();opacity(row)
        row['visual']['presented_actors'][1]['opacity']=1.
        with self.assertRaises(ValueError):opacity(row)
    def test_two_presentation_owners_are_rejected(self):
        row=visual_row();row['visual']['owners']['high']=True
        with self.assertRaises(ValueError):opacity(row)
    def test_stretched_blend_is_rejected(self):
        row=visual_row();row['visual']['outgoing']['duration']=.8
        with self.assertRaises(ValueError):opacity(row)
    def test_camera_applies_pair_once_and_replaces_height(self):
        q=[math.sin(.1),0,0,math.cos(.1)]
        row=dict(kind='step',direction=[0,0,-1],camera_base_forward=[0,0,-1],camera_base_up=[0,1,0],prone_camera=dict(seconds=.2,source_frame=13.,eye_height=.4,orientation_xyzw=q),
            camera_forward=[0,math.sin(.2),-math.cos(.2)],camera_up=[0,math.cos(.2),math.sin(.2)],
            position=[0,0,0],eye_height=.4,landing_kick=0,lean_offset=[0,0,0],camera_eye=[0,.4,0],prone_sample=dict(seconds=.2,source_frame=13.,eye_height=.4,orientation_xyzw=q))
        camera_once(row);row['camera_forward']=[0,math.sin(.4),-math.cos(.4)]
        with self.assertRaises(ValueError):camera_once(row)
        row['camera_forward']=[0,math.sin(.2),-math.cos(.2)];row['camera_eye'][1]=.8
        with self.assertRaises(ValueError):camera_once(row)
    def test_partial_trace_never_passes(self):
        with self.assertRaises(ValueError):validate([dict(kind='header')],{},30)
    def test_rust_source_free_committed_inputs_match_independent_python_route(self):
        path=os.environ.get('COMBINED_SOURCE_FREE_TEST_TRACE')
        if not path:self.skipTest('explicit source-free Rust trace not supplied')
        fixture=json.loads(Path(path).read_text());self.assertEqual(fixture['schema'],'source-free-combined-route-test/v1');self.assertFalse(fixture['native_capture'])
        r=Route();rows=fixture['rows']
        for before,after in zip(rows,rows[1:]):
            self.assertEqual(r.input(observed(before)),after['input'])
            self.assertEqual(r.phase,after['phase'])
        self.assertEqual(r.counts,[2,2,2]);self.assertEqual(r.phase,'Done')
        self.assertGreater(len(rows),2000)
        # Flipping a committed request must disagree with the independent route.
        broken=copy.deepcopy(rows);at=next(i for i,x in enumerate(broken) if x.get('input',{}).get('jump'))
        broken[at]['input']['jump']=False;r=Route();mismatch=False
        for before,after in zip(broken,broken[1:]):
            mismatch |= r.input(observed(before)) != after['input']
        self.assertTrue(mismatch)
class FullSyntheticRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('COMBINED_SOURCE_FREE_TEST_TRACE'):raise unittest.SkipTest('source-free Rust route required')
        from combined_capture_synthetic_fixture import fixture,BINDINGS
        cls.bindings=BINDINGS;cls.rows=fixture();cls.fixture=staticmethod(fixture)
    def test_complete_synthetic_projections_pass_both_cadences(self):
        for hz,count in ((30,200),(60,236)):
            result=validate(self.fixture(hz),self.bindings,hz)
            self.assertEqual(result['native_frame_records'],count)
            self.assertFalse(result['artistic_approval'])
    def test_review_mutations_fail_complete_validation(self):
        from combined_capture_synthetic_fixture import reindex
        def each(rows,fn):
            for r in rows:
                if r['kind'] in ('step','frame'):fn(r)
        def rewrite_opacity(r):
            o=r['visual']['outgoing']
            if o:
                a=.8+.1*math.sin(r['simulation_time']);o['from_opacity']=[a]
                r['visual']['presented_actors'][0]['opacity']=a*(1-o['weight'])+o['weight']
        def missing_credits(rows):
            for r in rows:
                if r['kind'] in STATE_KINDS:r.update(ammo=30-r['shots'],reserve=90,reload_credit_at=0.,reload_ready_at=0.)
        mutations={
            'missing state binding':lambda rows:next(r for r in rows if r['kind']=='step').pop('bindings'),
            'changed frame binding':lambda rows:next(r for r in rows if r['kind']=='frame')['bindings']['high'].update(asset_sha256='9'*64),
            'lost admission':lambda rows:next(r for r in rows if r['kind']=='step')['bindings'].update(prone=None),
            'empty actor inventories':lambda rows:each(rows,lambda r:(r['visual'].update(presented_actors=[],live_target_actors=[]),r['visual']['outgoing'].update(from_opacity=[]) if r['visual']['outgoing'] else None)),
            'wrong active route':lambda rows:each(rows,lambda r:r['visual'].update(route='bogus.route') if r['high'] and not r['high']['outgoing'] else None),
            'walk evidence erased':lambda rows:each(rows,lambda r:r['visual'].update(walk_seconds=None,walk_weight=0.)),
            'active high ADS contamination':lambda rows:each(rows,lambda r:r['visual'].update(visual_ads=.9) if r['high'] and not r['high']['outgoing'] else None),
            'active prone procedural contamination':lambda rows:each(rows,lambda r:r['visual'].update(procedural_weight=.2) if r['prone_sample'] else None),
            'prone frozen clock changed':lambda rows:each(rows,lambda r:r['prone_return'].update(frozen_seconds=.7,frozen_source_frame=43.) if r['prone_return'] else None),
            'prone entry identity changed':lambda rows:each(rows,lambda r:r.update(prone_entry_started=9.) if r['prone_sample'] else None),
            'low generation changed before endpoint':lambda rows:each(rows,lambda r:r['low'].update(generation=999) if r['low'] and r['low']['source_frame']<64 else None),
            'high generation changed before endpoint':lambda rows:each(rows,lambda r:r['high'].update(generation=999) if r['high'] and not r['high']['outgoing'] else None),
            'renderer low generation changed':lambda rows:each(rows,lambda r:r['visual'].update(low_generation=999) if r['visual']['owners']['low'] else None),
            'stale cleared owner':lambda rows:each(rows,lambda r:r['visual']['owners'].update(high=True) if not any(r['visual']['owners'].values()) else None),
            'frozen opacity rewritten each tick':lambda rows:each(rows,rewrite_opacity),
            'frozen pose changed':lambda rows:each(rows,lambda r:r['visual']['outgoing'].update(frozen_pose_crc32=999) if r['visual']['outgoing'] else None),
            'missing paired camera':lambda rows:each(rows,lambda r:r.update(prone_camera=None)),
            'outgoing camera clock changed':lambda rows:each(rows,lambda r:r['prone_camera'].update(seconds=.7) if r['prone_return'] else None),
            'outgoing camera orientation changed':lambda rows:each(rows,lambda r:r['prone_camera'].update(orientation_xyzw=[0.,0.,0.,1.]) if r['prone_return'] else None),
            'no actual reload credit':missing_credits,
            'reload credit deadline changed':lambda rows:each(rows,lambda r:r.update(reload_credit_at=0.) if r['reload_left']>0 else None),
            'platform look drift':lambda rows:each(rows,lambda r:r['look'].update(yaw=3.)),
            'native source renders reduced to 5Hz':lambda rows:rows.__setitem__(slice(None),[r for r in rows if not (r['kind']=='frame' and r['mantle'] and r['simulation_tick']%24)]),
            'omitted phase/owner boundary':lambda rows:rows.remove(next(r for r in rows if r['kind']=='frame' and r['phase']=='HighReloadTail')),
            'omitted native endpoint PNG':lambda rows:[r.pop('png',None) for r in rows if r['kind']=='frame' and r['high'] and r['high']['outgoing'] and r['high']['outgoing']['weight']==0],
            'missing committed input':lambda rows:next(r for r in rows if r['kind']=='step').pop('input'),
        }
        for name,mutate in mutations.items():
            with self.subTest(mutation=name):
                rows=copy.deepcopy(self.rows);mutate(rows);reindex(rows)
                with self.assertRaises((ValueError,KeyError,TypeError)):validate(rows,self.bindings,30)
    def test_complete_state_projection_rejects_every_missing_or_changed_field(self):
        original=next(r for r in self.rows if r['kind']=='step')
        for field in STATE_FIELDS:
            with self.subTest(field=field):
                changed=copy.deepcopy(original);changed[field]={'different':True}
                with self.assertRaises(ValueError):same_state(changed,original,'projection')
                del changed[field]
                with self.assertRaises(ValueError):same_state(changed,original,'projection')
    def test_v2_cross_record_mutations_rejected_at_both_rates(self):
        from combined_capture_synthetic_fixture import reindex
        def accepted_clock(rows):
            for r in rows:
                if r['kind']=='accepted' and r['high']:r['high'].update(seconds=.9,source_frame=55.,reference_frame=7841.)
        def frame_camera(rows,zero=False):
            for r in rows:
                if r['kind']!='frame' or (bool(r['simulation_tick'])==zero):continue
                f=[0.,0.,-1.];u=[0.,1.,0.];forward=f;up=u;sample=r['prone_camera']
                if sample:
                    right=norm(cross(f,u));basis_up=norm(cross(right,f));q=sample['orientation_xyzw']
                    def world(a):return norm([right[k]*a[0]+basis_up[k]*a[1]-f[k]*a[2] for k in range(3)])
                    forward=world(rotate(q,[0,0,-1]));up=world(rotate(q,[0,1,0]))
                r.update(direction=f,camera_base_forward=f,camera_base_up=u,camera_forward=forward,camera_up=up,rendered_camera_forward=forward,rendered_camera_up=up)
        def late_acceptance(rows):
            event=next(r for r in rows if r['kind']=='accepted');rows.remove(event);rows.insert(len(rows)-1,event)
        def early_frame(rows):
            frame=next(r for r in rows if r['kind']=='frame' and r['simulation_tick']);rows.remove(frame);rows.insert(2,frame)
        mutations={
            'accepted event outside its committed tick':late_acceptance,
            'render record outside its committed tick':early_frame,
            'actual high frame55 labelled frame1':accepted_clock,
            'rendered camera diverges from committed step':frame_camera,
            'tick-zero camera diverges from initial state':lambda rows:frame_camera(rows,True),
            'terminal stale high source':lambda rows:rows[-1].update(high=copy.deepcopy(next(r['high'] for r in rows if r.get('high')))),
            'accepted high outgoing source':lambda rows:next(r for r in rows if r['kind']=='accepted' and r['high'])['high'].update(outgoing={'began':0.}),
            'accepted mantle belongs to another landing':lambda rows:next(r for r in rows if r['kind']=='accepted')['mantle'].update(landing=[-15.,1.8,-3.]),
            'accepted low generation differs from first step':lambda rows:next(r for r in rows if r['kind']=='accepted' and not r['high']).update(low_generation=999),
            'frame ammo differs from committed step':lambda rows:next(r for r in rows if r['kind']=='frame' and r['simulation_tick']).update(ammo=999),
            'frame velocity differs from committed step':lambda rows:next(r for r in rows if r['kind']=='frame' and r['simulation_tick']).update(velocity=[0.,9.,0.]),
            'terminal stance differs from final committed state':lambda rows:rows[-1].update(prone=True),
            'terminal reload milestone differs from final committed state':lambda rows:rows[-1].update(reload_credit_at=999.),
        }
        for hz in (30,60):
            baseline=self.fixture(hz)
            for name,mutate in mutations.items():
                with self.subTest(hz=hz,mutation=name):
                    rows=copy.deepcopy(baseline);mutate(rows);reindex(rows)
                    with self.assertRaises((ValueError,KeyError,TypeError)):validate(rows,self.bindings,hz)
    def test_actual_png_extent_precedes_decode(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'synthetic-header.png'
            def write(w,h):p.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+w.to_bytes(4,'big')+h.to_bytes(4,'big'))
            write(64,22);self.assertEqual(png_extent(p,dict(width=64,height=22)),(64,22))
            for w,h,mw,mh in ((1450,22,64,22),(64,901,64,22),(64,22,65,22),(0,22,0,22)):
                write(w,h)
                with self.assertRaises(ValueError):png_extent(p,dict(width=mw,height=mh))

if __name__=='__main__':unittest.main()

