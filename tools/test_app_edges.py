"""Synthetic/static only. Never builds or executes Rust or opens a window."""
import copy, hashlib, json, re, struct, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
from app_edge_synthetic_fixture import make, BINDING, IDENTITY, CONTRACT
from app_edge_renderer_overlay_v1 import restore_renderer_overlay
from verify_app_edges import validate, Rejected, FIELDS, png_extent, loads, verify_config, verify_run, invocation, sha, digest

def restore_shared_replay_test_binding(source):
    """Undo only the test-only binding injection for the immutable renderer pin."""
    changes = (
        (
            'pub(crate) fn combined_replay_sim(\n'
            '    binding: vector_range::authored_high_mantle::HighMantleBinding,\n'
            ') -> vector_range::sim::Simulation {\n'
            '    tests::combined_replay_sim(binding)\n}',
            'pub(crate) fn combined_replay_sim() -> vector_range::sim::Simulation {\n'
            '    tests::combined_replay_sim()\n}',
        ),
        (
            '    pub(super) fn combined_replay_sim(\n'
            '        binding: vector_range::authored_high_mantle::HighMantleBinding,\n'
            '    ) -> vector_range::sim::Simulation {',
            '    pub(super) fn combined_replay_sim() -> vector_range::sim::Simulation {',
        ),
        (
            '        sim.set_high_mantle_binding(Some(binding));',
            '        sim.set_high_mantle_binding(Some(\n'
            '            vector_range::authored_high_mantle::HighMantleBinding::synthetic(0.20),\n'
            '        ));',
        ),
    )
    for current, previous in changes:
        assert source.count(current) == 1, 'shared replay binding injection changed'
        source = source.replace(current, previous)
    return source


def check_shared_replay_test_scope(renderer, callers):
    assert 'HighMantleBinding::synthetic' not in renderer, 'shared renderer cannot construct a library-only binding'
    restore_shared_replay_test_binding(renderer)
    for source, expected in callers:
        production, tests = source.split('#[cfg(test)]\nmod tests {', 1)
        assert 'HighMantleBinding::synthetic' not in production
        assert tests.count('crate::authored_viewmodel::combined_replay_sim(') == expected
        assert len(re.findall(
            r'crate::authored_viewmodel::combined_replay_sim\(\s*'
            r'crate::authored_high_mantle::HighMantleBinding::synthetic\(0\.20\),\s*\)',
            tests)) == expected, 'library tests must inject the unchanged 0.20-second binding'


class TraceTests(unittest.TestCase):
    def rows(self,case='pause',hz=60):return make(case,hz)
    def check(self,rows,case='pause'):return validate(rows,BINDING,case,IDENTITY,CONTRACT)
    def reject(self,fn,case='pause',hz=60):
        rows=self.rows(case,hz);fn(rows)
        with self.assertRaises((Rejected,KeyError,TypeError,ValueError,StopIteration)):self.check(rows,case)
    def test_positive_synthetic_only_all_three_cases_and_real_time_cadences(self):
        for hz in (30,60,144):
            for case in ('pause','reset','debug-death'):
                with self.subTest(hz=hz,case=case):
                    r=self.check(self.rows(case,hz),case)
                    self.assertTrue(r['journal_contract_validated'])
                    self.assertFalse(r['actual_app_handlers_validated'])
                    self.assertFalse(r['os_input_verified']);self.assertFalse(r['combat_death_verified'])
    def test_absent_wrong_or_duplicate_input_events(self):
        for case,kind in [('pause','pause_before'),('reset','reset_before'),('debug-death','debug_death_before')]:
            for mutation in ('omit','rename','duplicate'):
                def change(rows):
                    i=next(i for i,r in enumerate(rows) if r['kind']==kind)
                    if mutation=='omit':rows.pop(i)
                    elif mutation=='rename':rows[i]['kind']='reset_before' if case!='reset' else 'debug_death_before'
                    else:rows.insert(i,copy.deepcopy(rows[i]))
                    for j,r in enumerate(rows):r['record_index']=j
                with self.subTest(case=case,mutation=mutation):self.reject(change,case)
    def test_every_state_field_is_required_and_cross_record_bound(self):
        for field in FIELDS:
            for mode in ('missing','stale'):
                def change(rows):
                    r=next(r for r in rows if r['kind']=='app_frame' and r['high'] and r['high']['outgoing'] is None)
                    if mode=='missing':r.pop(field)
                    else:
                        old=r[field]
                        if isinstance(old,bool):r[field]=not old
                        elif isinstance(old,(int,float)):r[field]=old+.123
                        elif isinstance(old,list):r[field]=[99.]*len(old)
                        else:r[field]=None if old is not None else {'unexpected':True}
                with self.subTest(field=field,mode=mode):self.reject(change)
    def test_input_recipe_session_clock_and_renderer_mutations(self):
        def one(rows,kind,predicate=lambda r:True):return next(r for r in rows if r['kind']==kind and predicate(r))
        probes={
            'synthetic_route_claim':lambda r:r[0].update(input_route='platform'),
            'contract_changed':lambda r:r[0].update(contract_sha256='f'*64),
            'witness_changed':lambda r:r[0].update(frame_witness='f'*64),
            'source_stretched':lambda r:r[0].update(native_seconds=2.),
            'return_stretched':lambda r:r[0].update(return_seconds=.3),
            'no_input_bridge':lambda r:one(r,'app_input')['edges']['keys'][0].update(pressed=True),
            'fixture_input_tampered':lambda r:one(r,'fixture_input')['edges'].update(movement=[0.,1.]),
            'wrong_recipe_phase':lambda r:one(r,'fixture_input').update(phase='Injected'),
            'wrong_session_transition':lambda r:one(r,'app_input')['transition'].update(paused=True),
            'clock_count_frozen':lambda r:one(r,'app_clock').update(planned_steps=0),
            'clock_dt_retimed':lambda r:one(r,'app_clock').update(simulation_dt=.025),
            'raw_dt_retimed':lambda r:one(r,'app_input',lambda x:x['app_frame']>2).update(raw_dt=.025),
            'runtime_wall_frozen':lambda r:one(r,'app_input',lambda x:x['app_frame']>2).update(frame_started=0.),
            'committed_tick_retimed':lambda r:one(r,'app_step').update(step_started=.03),
            'movement_bypassed':lambda r:one(r,'app_step')['input'].update(movement=[1.,1.]),
            'absent_fresh_jump':lambda r:one(r,'app_step',lambda x:x['input']['jump'])['input'].update(jump=False),
            'unrelated_input':lambda r:one(r,'app_step')['input'].update(fire=True),
            'acceptance_source_not_zero':lambda r:one(r,'accepted')['high'].update(seconds=.01),
            'acceptance_generation_stale':lambda r:one(r,'accepted')['high'].update(generation=9),
            'renderer_pose_stale':lambda r:one(r,'app_frame',lambda x:x['high'] is not None)['high_pose_sampling'].update(source_pose_seconds=0.),
            'renderer_generation_stale':lambda r:one(r,'app_frame',lambda x:x['high'] is not None)['visual'].update(high_generation=8),
            'renderer_owner_stale':lambda r:one(r,'app_frame')['visual']['owners'].update(high=True),
            'renderer_failed':lambda r:one(r,'app_frame')['visual'].update(renderer_failed=True),
            'renderer_warning':lambda r:one(r,'app_frame')['visual'].update(warning='bad asset'),
            'wrong_camera_eye':lambda r:one(r,'app_frame').update(rendered_camera_eye=[9.,9.,9.]),
            'wrong_camera_forward':lambda r:one(r,'app_frame').update(rendered_camera_forward=[0.,1.,0.]),
            'wrong_camera_up':lambda r:one(r,'app_frame').update(rendered_camera_up=[0.,0.,1.]),
            'terminal_false':lambda r:r[-1].update(completed=False),
            'terminal_stale':lambda r:r[-1].update(health=3.),
            'terminal_tick':lambda r:r[-1].update(tick=1),
            'missing_png':lambda r:one(r,'app_frame',lambda x:'png' in x).pop('png'),
            'missing_clear_ownership':lambda r:one(r,'app_frame',lambda x:x.get('marker')=='clear')['visual']['owners'].update(high=True),
            'frozen_source_crc':lambda r:one(r,'app_frame',lambda x:x.get('marker')=='paused')['visual']['outgoing'].update(frozen_pose_crc32=0),
            'frozen_named_opacity':lambda r:one(r,'app_frame',lambda x:x.get('marker')=='paused')['visual']['outgoing'].update(from_opacity=[.2]),
            'return_clock':lambda r:one(r,'app_frame',lambda x:x.get('marker')=='tail_late')['visual']['outgoing'].update(began=9.),
            'frozen_live_target':lambda r:one(r,'app_frame',lambda x:x.get('marker')=='tail_late')['visual'].update(live_target_pose_crc32=one(r,'app_frame',lambda x:x.get('marker')=='tail_early')['visual']['live_target_pose_crc32']),
        }
        for label,fn in probes.items():
            with self.subTest(label=label):self.reject(fn)
    def test_all_admitted_binding_projections_required(self):
        for kind in ('initial','accepted','app_input','fixture_input','app_clock','app_step','app_frame','finished','pause_after'):
            def change(rows):next(r for r in rows if r['kind']==kind)['binding']=None
            with self.subTest(kind=kind):self.reject(change)
    def test_missing_native_intermediate_frames_is_failure_not_retiming(self):
        for hz in (1,2,4,5,6,10):
            with self.subTest(hz=hz):
                with self.assertRaises((Rejected,AssertionError,KeyError)):self.check(self.rows('pause',hz))
    def test_original_orphan_accepted_reproducer_is_rejected_for_all_cases(self):
        for case in ('pause','reset','debug-death'):
            def change(rows):
                extra=copy.deepcopy(next(r for r in rows if r['kind']=='accepted'))
                extra['app_frame']=999999;extra['wall_seconds']=rows[-1]['wall_seconds'];rows.insert(-1,extra)
                for i,r in enumerate(rows):r['record_index']=i
            with self.subTest(case=case):self.reject(change,case)
    def test_every_record_has_exact_order_and_frame_ownership(self):
        for kind in ('fixture_input','app_input','app_clock','accepted','app_step','app_frame','pause_before','pause_after'):
            for owner in (-1,999999,0):
                def change(rows):
                    extra=copy.deepcopy(next(r for r in rows if r['kind']==kind))
                    extra['app_frame']=owner;extra['wall_seconds']=rows[-1]['wall_seconds'];rows.insert(-1,extra)
                    for i,r in enumerate(rows):r['record_index']=i
                with self.subTest(kind=kind,owner=owner):self.reject(change)
        for kind in ('fixture_input','app_input','app_clock','accepted','app_step','app_frame'):
            def change(rows):
                row=next(r for r in rows if r['kind']==kind);row['app_frame']+=1
            with self.subTest(kind=kind):self.reject(change)
    def test_live_displayed_sample_is_not_frozen_source_time(self):
        rows=self.rows();out=[r for r in rows if r['kind'] in ('app_step','app_frame') and r['high'] and r['high']['outgoing'] and r['high']['outgoing']['weight']>0]
        self.assertTrue(all(r['high_pose_sampling']['source_pose_seconds']!=r['high_pose_sampling']['presented_pose_seconds'] for r in out))
        self.check(rows)
        for mode in ('presented_frozen','source_blended','target_missing','target_wrong'):
            def change(rows):
                for r in rows:
                    if r['kind'] not in ('app_step','app_frame') or not r['high'] or not r['high']['outgoing']:continue
                    t=r['high_pose_sampling']
                    if mode=='presented_frozen':t['presented_pose_seconds']=t['source_pose_seconds']
                    elif mode=='source_blended':t['source_pose_seconds']=t['presented_pose_seconds']
                    elif mode=='target_missing':t['mapped_target_pose_seconds']=None
                    else:t['mapped_target_pose_seconds']=3.
            with self.subTest(mode=mode):self.reject(change)
    def test_native_focus_capability_is_retained_without_claiming_os_focus(self):
        for supported in (False,True):
            rows=self.rows()
            for r in rows:
                if r['kind']=='app_input':r['focus']['native_supported']=supported
            result=self.check(rows);self.assertIs(result['native_focus_supported'],supported)
            self.assertFalse(result['os_focus_verified'])
            self.assertEqual(result['focus_scope'],'native_platform_signal' if supported else 'existing_platform_focus_fallback')
        self.reject(lambda rows:next(r for r in rows if r['kind']=='app_input')['focus'].update(native_supported=True))

    def test_death_and_reset_do_not_accept_combat_or_stale_source(self):
        for case,field,value in [('reset','simulation_time',1.),('reset','dead',True),('debug-death','dead',False),('debug-death','health',1.)]:
            def change(rows):next(r for r in rows if r['kind']==('reset_after' if case=='reset' else 'debug_death_after'))[field]=value
            with self.subTest(case=case,field=field):self.reject(change,case)
    def test_json_duplicate_and_nonfinite_rejected(self):
        for data in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}'):
            with self.assertRaises(Rejected):loads(data)
    def test_png_extent_is_checked_from_bytes_before_decoder(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.png';p.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+struct.pack('>II',128,64))
            png_extent(p,{'width':128,'height':64})
            with self.assertRaises(Rejected):png_extent(p,{'width':64,'height':64})
            p.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+struct.pack('>II',2000,900))
            with self.assertRaises(Rejected):png_extent(p,{'width':2000,'height':900})
    def test_failed_or_nonterminal_native_process_receipts_are_rejected(self):
        helpers=Path(__file__).absolute().parent
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);binary=root/'not_executed';manifest=root/'not_loaded';settings=root/'not_loaded_settings'
            c=dict(source_fingerprint='a'*64,binary=dict(sha256='b'*64),runtime='legacy',renderer='gl',run_id='synthetic-only',recipe='high-onto-app-input-edges/v1')
            entries=[dict(case=case,command=invocation(c,binary,manifest,settings,root/case,case,CONTRACT),
                exit_code=0,completed=True,timed_out=False,process_group_terminal=True,
                binary_before_sha256='b'*64,binary_after_sha256='b'*64,wall_seconds=1.) for case in ('pause','reset','debug-death')]
            run=dict(schema='rust-duty-app-edge-native-run/v1',contract_sha256=CONTRACT,completed=True,inputs_unchanged=True,
                source_fingerprint='a'*64,binary_sha256='b'*64,scope='native_app_input_fixture',os_input_verified=False,
                combat_death_verified=False,cases=entries)
            for field,bad in [('exit_code',1),('completed',False),('timed_out',True),('process_group_terminal',False),
                ('command',['wrong']),('binary_before_sha256','c'*64),('binary_after_sha256','c'*64),('wall_seconds',61.)]:
                changed=copy.deepcopy(run);changed['cases'][0][field]=bad
                (root/'run.json').write_text(json.dumps(changed))
                with self.subTest(field=field),patch('verify_app_edges.verify_config',return_value=(c,root,binary,manifest,settings)):
                    with self.assertRaises(Rejected):verify_run(root,root/'unused',CONTRACT,helpers)
    def test_pending_native_contract_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'pending.json';p.write_text(json.dumps({'schema':'rust-duty-app-edge-run-contract/v1','admitted':False}))
            with self.assertRaises(Rejected):verify_config(p,sha(p))

class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay=Path(__file__).absolute().parents[1]
        cls.contracts=json.loads((cls.overlay/'tools/combined_source_contracts.json').read_text(encoding='utf-8'))
    def test_driver_has_no_simulation_writes_or_direct_action_calls(self):
        source=(self.overlay/'src/high_app_edge_input.rs').read_text(encoding='utf-8').split('#[cfg(test)]')[0]
        for forbidden in ('&mut Simulation','sim.update(','sim.reset(','sim.cancel_mantle(','sim.damage_player(','.set_binding(','.set_high_mantle_binding(','std::process','Command::'):
            self.assertNotIn(forbidden,source)
        self.assertIn('self.input.key_event(',source);self.assertIn('self.input.mouse_button_event(',source)
    def test_actual_handlers_and_simulation_clock_are_unchanged(self):
        app=(self.overlay/'src/app.rs').read_text(encoding='utf-8')
        for block in self.contracts['application_blocks']:
            text=app[app.index(block['begin']):app.index(block['end'])]
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),block['sha256'])
        self.assertIn('focus_input.install_app_edge_frame(frame)?;',app)
        self.assertIn('observer.session(&sim,&focus_input.frame(),transition,now,raw_dt,', ''.join(app.split()))
        self.assertIn('input_frame.sample_intents(&mut intents, !just_resumed && !transition.discard_timing);',app)
        self.assertIn('let steps = clock.advance(simulation_dt).unwrap_or(0);',app)
        self.assertNotIn('set_active(false)',app)
    def test_focus_input_initializers_cover_all_declared_fields(self):
        import re
        source=(self.overlay/'src/platform/session_focus.rs').read_text(encoding='utf-8')
        def complete(text):
            declaration=text.split('pub struct FocusInput {',1)[1].split('\n}',1)[0]
            fields=set(re.findall(r'^    (\w+):',declaration,re.M))
            self.assertEqual(fields,{'subscriber','state','focus','app_edge_frame'})
            constructor=text.split('pub fn new() -> Self {',1)[1].split('    /// Call once',1)[0]
            bodies=re.findall(r'Self \{\n(.*?)\n\s*\}',constructor,re.S)
            bodies+=re.findall(r'let (?:mut )?\w+ = FocusInput \{\n(.*?)\n\s*\};',text,re.S)
            self.assertEqual(len(bodies),3)
            for body in bodies:
                self.assertEqual(set(re.findall(r'^\s+(\w+):',body,re.M)),fields)
                self.assertRegex(body,r'app_edge_frame:\s*None,')
        complete(source)
        # Reverse the exact one-line repair: the original E0063 must fail here.
        repaired='let mut input = FocusInput {\n            subscriber: None,\n            app_edge_frame: None,'
        original=source.replace(repaired,'let mut input = FocusInput {\n            subscriber: None,',1)
        self.assertNotEqual(original,source)
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),self.contracts['unrepaired_focus_sha256'])
        with self.assertRaises(AssertionError):complete(original)
    def test_capture_flags_remain_rejected_and_motion_source_is_untouched(self):
        opts=(self.overlay/'src/high_app_edge_input.rs').read_text(encoding='utf-8')
        for flag in ('--capture','--combined','--onehand','--viewmodel-','--demo','--reference-viewport','--procedural-weapon'):
            self.assertIn('"'+flag+'"',opts)
        for name, expected in self.contracts['unchanged_files'].items():
            self.assertEqual(hashlib.sha256((self.overlay/name).read_bytes()).hexdigest(),expected,name)
        high=(self.overlay/'src/authored_high_mantle.rs').read_text(encoding='utf-8')
        sim=(self.overlay/'src/sim.rs').read_text(encoding='utf-8')
        begin=sim.index('    /// The admitted pair identity, never raw unvalidated manifest fields.')
        end=sim.index('    pub fn prone_sample(',begin)
        sim=(sim[:begin]+sim[end:]).replace('        crate::combined_observer::accepted(self);\n','')
        self.assertEqual(hashlib.sha256(sim.encode()).hexdigest(),self.contracts['simulation_before_observers_sha256'])
        self.assertIn('APPROVED_RUNTIME_PINS: Option<RuntimePins<\'static>> = None;',high)
        self.assertIn('pub const NATIVE_SECONDS: f64 = 95. / 60.;',high)
    def test_renderer_delta_only_observes_existing_samples_and_adds_unrun_test(self):
        # Reverse the exact versioned successor before the unchanged historical delta.
        current=(self.overlay/'src/authored_viewmodel.rs').read_bytes()
        provenance=(self.overlay/'tools/combined_source_contracts.json').read_bytes()
        new=restore_renderer_overlay(current,provenance).decode('utf-8')
        new=restore_shared_replay_test_binding(new)
        begin=new.index('    /// Distinct source and presented sample times. An outgoing pose is a live')
        end=new.index('    /// Set the hip cant applied at the next draw.',begin)
        new=new[:begin]+new[end:]
        begin=new.index('    #[test]\n    fn app_edge_distinguishes_frozen_source_and_live_blend_time()')
        end=new.index('    #[test]\n    fn high_mantle_return_tracks_live_pose_opacity_ads_and_resets()',begin)
        new=new[:begin]+new[end:]
        new=new.replace('    // Diagnostic observation of the actual mapped target, never an input to motion.\n    mapped_target_pose_seconds: Option<f32>,\n','')
        new=new.replace('            mapped_target_pose_seconds: None,\n','')
        new=new.replace('        self.mapped_target_pose_seconds = None;\n','')
        new=new.replace('            visual.mapped_target_pose_seconds = None;\n','')
        new=new.replace('        // Observe the existing mapped result; do not substitute or resample it.\n        visual.mapped_target_pose_seconds = Some(target.sample_time);\n','')
        new=new.replace('#[cfg(test)]\n#[allow(dead_code)]\npub(crate) fn combined_replay_sim()', '#[cfg(test)]\npub(crate) fn combined_replay_sim()')
        new=new.replace('// The library-only admitted fixture calls this helper. The binary also\n// compiles this module for tests, but cannot construct that library test binding.\n#[cfg(test)]\n#[allow(dead_code)]\npub(crate) fn assert_combined_admitted_sync(', '#[cfg(test)]\npub(crate) fn assert_combined_admitted_sync(')
        self.assertEqual(hashlib.sha256(new.encode()).hexdigest(),self.contracts['renderer_before_app_edge_sha256'])
    def test_shared_renderer_replay_binding_is_constructed_only_in_library_tests(self):
        renderer=(self.overlay/'src/authored_viewmodel.rs').read_text(encoding='utf-8')
        callers=[((self.overlay/path).read_text(encoding='utf-8'),count) for path,count in
            (('src/combined_replay.rs',2),('src/combined_observer.rs',1))]
        check_shared_replay_test_scope(renderer,callers)
        library=(self.overlay/'src/lib.rs').read_text(encoding='utf-8')
        self.assertIn('#[cfg(test)]\nextern crate self as vector_range;',library)
        self.assertIn('#[cfg(test)]\n#[allow(dead_code)]\nmod authored_viewmodel;',library)
        # This module is also compiled against a non-test library by these targets.
        main=(self.overlay/'src/main.rs').read_text(encoding='utf-8')
        self.assertIn('#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]\nmod authored_viewmodel;',main)
        for path in ('tests/source_triangle_completeness.rs',
                     'tests/authored_high_mantle_contract.rs',
                     'tests/authored_low_vault_contract.rs',
                     'tests/authored_low_vault_presentation.rs',
                     'tests/combined_animation_contract.rs',
                     'examples/source_visibility_certificate.rs',
                     'examples/source_visibility_geometry_probe.rs'):
            included=(self.overlay/path).read_text(encoding='utf-8')
            self.assertIn('#[path = "../src/authored_viewmodel.rs"]\nmod authored_viewmodel;',included)
    def test_shared_renderer_test_scope_rejects_original_failure_and_duration_mutation(self):
        renderer=(self.overlay/'src/authored_viewmodel.rs').read_text(encoding='utf-8')
        callers=[((self.overlay/path).read_text(encoding='utf-8'),count) for path,count in
            (('src/combined_replay.rs',2),('src/combined_observer.rs',1))]
        with self.assertRaises(AssertionError):
            check_shared_replay_test_scope(restore_shared_replay_test_binding(renderer),callers)
        broken=renderer.replace('sim.set_high_mantle_binding(Some(binding));',
            'sim.set_high_mantle_binding(Some(vector_range::authored_high_mantle::HighMantleBinding::synthetic(0.20)));')
        with self.assertRaises(AssertionError):check_shared_replay_test_scope(broken,callers)
        for at in range(len(callers)):
            changed=callers.copy();source,count=changed[at]
            changed[at]=(source.replace('HighMantleBinding::synthetic(0.20)',
                'HighMantleBinding::synthetic(0.21)',1),count)
            with self.assertRaises(AssertionError):check_shared_replay_test_scope(renderer,changed)
    def test_python_has_no_launch_or_os_input_route(self):
        for name in ('app_edge_contract.py','verify_app_edges.py','app_edge_synthetic_fixture.py'):
            text=(self.overlay/'tools'/name).read_text(encoding='utf-8')
            for forbidden in ('subprocess','os.system','ctypes','xdotool','Xvfb','pyautogui'):
                self.assertNotIn(forbidden,text)

if __name__=='__main__':unittest.main(verbosity=2)
