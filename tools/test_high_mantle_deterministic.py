"""Synthetic/source-only deterministic complement checks, never native execution."""
import copy,json,math,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'tools'))
import verify_high_mantle_deterministic as d
import verify_high_mantle_observer as v
from test_high_mantle_observer import complete,state,visual,stamp,BINDING

def fixture(hz):
    original=complete();head=copy.deepcopy(original[0]);head.update(input_route=d.ROUTE,sampling_hz=hz,
        sequence='gameplay-high-onto',immutable_scene_start={'position':list(d.START),'yaw':math.pi,
            'existing_block_center':[-10,.9,-3],'existing_block_size':[2,1.8,2],
            'setup':'existing traversal_replay::start before first update'})
    initial=state('initial');initial.update(position=list(d.START),camera_eye=[-8.6,1.524,-3],direction=[-1,0,0])
    rows=[head,initial];accepted=copy.deepcopy(original[2])
    by_step={i:r for i,r in enumerate([r for r in original if r['kind']=='step'],1)}
    app_frame=0;capture_index=0
    for tick in range(325):
        if tick==31:rows.append(copy.deepcopy(accepted))
        if tick>30 and tick-30 in by_step:r=copy.deepcopy(by_step[tick-30])
        else:r=visual(state('step',tick/120),tick)
        r.update(simulation_time=tick/120,step_started=(tick-1)/120,
                 input=d.expected_input((tick-1)/120+1e-10),direction=[-1,0,0],camera_forward=[-1,0,0],
                 position=list(d.START) if tick<220 else [-9.411,1.8,-3],
                 camera_eye=[-8.6,1.524,-3] if tick<220 else [-9.411,3.324,-3],
                 ads_requested=tick>220,grounded=not(30<tick<220))
        # Avoid artificial decimal boundary ambiguity in these synthetic clocks.
        r['step_started']+=1e-10
        if r['mantle']:r['mantle'].update(start=list(d.START),landing=[-9.411,1.8,-3])
        if tick:rows.append(r)
        if tick%(120//hz)==0:
            f=copy.deepcopy(r);f.update(kind='frame',sampling_hz=hz,app_frame=app_frame);app_frame+=1
            if tick in (0,32,80,128,176,220,228,236,248,324):
                f.update(png=f'{capture_index:04}.png',capture_index=capture_index);capture_index+=1
            rows.append(f)
    accepted_row=next(r for r in rows if r['kind']=='accepted')
    accepted_row.update(position=list(d.START),camera_eye=[-8.6,1.524,-3],direction=[-1,0,0])
    accepted_row['mantle'].update(start=list(d.START),landing=[-9.411,1.8,-3])
    rows.append(state('finished',2.7));return stamp(rows)

class DeterministicTests(unittest.TestCase):
    def test_both_grids_have_rendered_endpoint_and_return(self):
        for hz in (30,60):
            report=d.validate(fixture(hz),BINDING,hz)
            self.assertTrue(report['source96_rendered_at_zero_weight'])
            self.assertTrue(report['rendered_visual_return_passed'])
            self.assertFalse(report['platform_hotkeys_verified'])
    def test_reject_long_return_without_retiming(self):
        with self.assertRaisesRegex(v.EvidenceError,'0.20s'):d.validate(fixture(60),dict(BINDING,return_seconds=.8),60)
    def test_platform_verifier_cannot_accept_replay(self):
        with self.assertRaisesRegex(v.EvidenceError,'route'):v.validate(fixture(60),BINDING,'complete')
    def test_reject_scene_or_input_override(self):
        rows=fixture(60);rows[0]['immutable_scene_start']['position'][0]=0
        with self.assertRaisesRegex(v.EvidenceError,'scene'):d.validate(rows,BINDING,60)
        rows=fixture(60);next(r for r in rows if r['kind']=='step')['input']['sprint']=True
        with self.assertRaisesRegex(v.EvidenceError,'input'):d.validate(rows,BINDING,60)
    def test_reject_cadence_or_missing_ticks(self):
        rows=fixture(60);next(r for r in rows if r['kind']=='frame' and r['simulation_time']>.01)['simulation_time']+=.003
        with self.assertRaisesRegex(v.EvidenceError,'cadence'):d.validate(rows,BINDING,60)
        rows=fixture(60);rows.pop(next(i for i,r in enumerate(rows) if r['kind']=='step'));stamp(rows)
        with self.assertRaisesRegex(v.EvidenceError,'tick count'):d.validate(rows,BINDING,60)
    def test_reject_missing_rendered_return(self):
        rows=fixture(60)
        for r in rows:
            if r['kind']=='frame' and r.get('high') and r['high']['outgoing'] and 0<r['high']['outgoing']['weight']<1:r.pop('png',None)
        with self.assertRaisesRegex(v.EvidenceError,'rendered weights'):d.validate(rows,BINDING,60)
    def test_source_delta_has_no_in_run_state_injection(self):
        replay=(HERE/'src/traversal_replay.rs').read_text()
        input_body=replay.split('pub fn input(',1)[1].split('/// Scripted view',1)[0]
        additions=input_body+(HERE/'src/high_mantle_capture.rs').read_text()
        for forbidden in ('sim.player.position =','sim.player.yaw =','sim.player.velocity =','sim.time =','set_high_mantle_binding(', 'APPROVED_RUNTIME_PINS', 'sim.update('):self.assertNotIn(forbidden,additions)
        self.assertIn('vec3(-8.6, 0., -3.)',replay.split('pub fn duration(',1)[0])
        app=(HERE/'src/app.rs').read_text()
        self.assertIn('Capture::step(input, start, &sim',app)
        self.assertIn('!bounded_onehand && crate::capture::write_frame',app)
    def test_only_supported_rate_and_bounded_native_window_command(self):
        import run_high_mantle_deterministic as runner
        command=runner.invocation('/app','/manifest','/output','0'*64,60)
        self.assertIn('--capture-native-window',command);self.assertIn('--capture-hz=60',command)
        self.assertNotIn('--reference-viewport',command)
        self.assertEqual(runner.WALL_SECONDS,600);self.assertEqual(runner.RETURN_SECONDS,.2)
    def test_integrated_capture_keeps_platform_and_replay_routes_distinct(self):
        capture=(HERE/'src/high_mantle_capture.rs').read_text()
        self.assertIn('deterministic_ordinary_input',capture)
        self.assertIn('else {"platform"}',capture)
        self.assertIn('--onehand-deterministic',capture)
        self.assertIn("const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = None;",
                      (HERE/'src/authored_high_mantle.rs').read_text())

if __name__=='__main__':unittest.main()
