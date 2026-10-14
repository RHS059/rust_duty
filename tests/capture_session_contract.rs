//! Scripted capture commits must not inherit presentation-frame input resets.
use vector_range::{
    authored_ads::gameplay_ads_replay_input,
    clock::capture_tick_target,
    session::{SessionController, SessionInput, SessionTransition},
    settings::Settings,
    sim::{Simulation, FIXED_DT},
};

fn has_only_policy_guarded_firing_reset(app: &str) -> bool {
    // Git may materialize Windows sources with CRLF. Normalize only line
    // endings; retain the exact reset count and guarded call-site assertion.
    let app = app.replace("\r\n", "\n");
    app.matches("sim.player.firing_sequence = false;").count() == 1
        && app.contains(concat!(
            "if transition.interrupts_firing_sequence(gameplay_capture, focus_state.changed) {\n",
            "            sim.player.firing_sequence = false;"
        ))
}

#[test]
fn app_has_only_the_policy_guarded_firing_reset() {
    // Static wiring guard; the Windows replay comparison is the runtime proof.
    assert!(has_only_policy_guarded_firing_reset(include_str!(
        "../src/app.rs"
    )));
}

#[test]
fn static_wiring_guard_accepts_crlf_but_rejects_broken_control_flow() {
    let lf = include_str!("../src/app.rs").replace("\r\n", "\n");
    for app in [lf.clone(), lf.replace('\n', "\r\n")] {
        assert!(has_only_policy_guarded_firing_reset(&app));
        let duplicate = format!("{app}\nsim.player.firing_sequence = false;\n");
        assert!(!has_only_policy_guarded_firing_reset(&duplicate));
        let unguarded = app.replace(
            "transition.interrupts_firing_sequence(gameplay_capture, focus_state.changed)",
            "transition.discard_timing",
        );
        assert!(!has_only_policy_guarded_firing_reset(&unguarded));
    }
}

#[test]
fn live_input_boundaries_still_interrupt_firing_but_capture_does_not() {
    // Exercise all combinations, including real pause/resume and focus edges.
    for bits in 0..16 {
        let transition = SessionTransition {
            active: true,
            paused: bits & 1 != 0,
            resumed: bits & 2 != 0,
            discard_timing: bits & 4 != 0,
        };
        let focus_changed = bits & 8 != 0;
        assert_eq!(
            transition.interrupts_firing_sequence(false, focus_changed),
            bits != 0,
        );
        assert!(!transition.interrupts_firing_sequence(true, focus_changed));
    }
}

#[test]
fn an_actual_live_render_hitch_still_interrupts_the_committed_burst() {
    let cfg = Settings::m4_candidate();
    let mut sim = Simulation::new();
    sim.update(
        vector_range::sim::Input {
            fire: true,
            ..vector_range::sim::Input::default()
        },
        &cfg,
        FIXED_DT,
    );
    assert!(sim.player.firing_sequence);
    let mut session = SessionController::default();
    session.set_active(true);
    let transition = session.step(SessionInput {
        dt: 2.4,
        ..SessionInput::default()
    });
    assert!(transition.active && transition.discard_timing);
    assert!(!transition.paused && !transition.resumed);
    if transition.interrupts_firing_sequence(false, false) {
        sim.player.firing_sequence = false;
    }
    assert!(!sim.player.firing_sequence);
}

#[derive(Debug, PartialEq)]
struct Snapshot {
    frame: u64,
    time: f64,
    ammo: u32,
    reserve: u32,
    shots: u32,
    next_shot_at: f64,
    last_shot_at: f64,
    firing_sequence: bool,
    cooldown: f32,
    reload_left: f32,
    reload_credit_at: f64,
    reload_ready_at: f64,
    ads: f32,
    ads_requested: bool,
    position: [f32; 3],
    velocity: [f32; 3],
}

fn replay(hz: Option<u32>, dt: f64, focus_changes: bool) -> Vec<Snapshot> {
    let cfg = Settings::m4_candidate();
    let mut sim = Simulation::new();
    sim.player.ammo = 12;
    let mut session = SessionController::default();
    session.set_active(true);
    let rate = hz.map_or(60000_f32 / 1001., |hz| hz as f32);
    let mut committed_ticks = 0;
    let mut snapshots = Vec::new();
    for frame in 0..=(9. * rate).ceil() as u64 {
        // A capture has no live pause buttons; physical focus is independently
        // ignored by the existing FocusState::apply_to_session_input policy.
        let transition = session.step(SessionInput {
            dt,
            ..SessionInput::default()
        });
        assert!(transition.active);
        if transition.interrupts_firing_sequence(true, focus_changes && frame % 2 == 0) {
            sim.player.firing_sequence = false;
        }
        let elapsed = frame as f32 / rate;
        let target = hz.and_then(|hz| capture_tick_target(frame, hz));
        while target.map_or(
            sim.time + f64::from(FIXED_DT) <= f64::from(elapsed) + 1e-7,
            |target| committed_ticks < target,
        ) {
            sim.update(gameplay_ads_replay_input(sim.time), &cfg, FIXED_DT);
            committed_ticks += 1;
        }
        let player = &sim.player;
        snapshots.push(Snapshot {
            frame,
            time: sim.time,
            ammo: player.ammo,
            reserve: player.reserve,
            shots: sim.stats.shots,
            next_shot_at: player.next_shot_at,
            last_shot_at: player.last_shot_at,
            firing_sequence: player.firing_sequence,
            cooldown: player.cooldown,
            reload_left: player.reload_left,
            reload_credit_at: player.reload_credit_at,
            reload_ready_at: player.reload_ready_at,
            ads: player.ads,
            ads_requested: player.ads_requested,
            position: player.position.to_array(),
            velocity: player.velocity.to_array(),
        });
    }
    snapshots
}

#[test]
fn authored_ads_capture_is_identical_across_render_hitches_and_focus_changes() {
    for hz in [None, Some(30), Some(60)] {
        let baseline = replay(hz, 1. / 60., false);
        if hz.is_none() {
            // Native GL/DX12 failure: a render hitch formerly postponed the
            // third shot from frame 0297 to 0298 (ammo 9 versus 10).
            assert_eq!(baseline[297].ammo, 9);
            assert_eq!(baseline[297].shots, 3);
        }
        assert_eq!(baseline.last().unwrap().ammo, 30);
        assert_eq!(baseline.last().unwrap().shots, 3);
        for dt in [0., 0.25, 0.251, 2.4, f64::NAN, f64::INFINITY, -0.01] {
            for focus_changes in [false, true] {
                let candidate = replay(hz, dt, focus_changes);
                assert_eq!(candidate.len(), baseline.len());
                for (expected, actual) in baseline.iter().zip(&candidate) {
                    assert_eq!(
                        actual, expected,
                        "hz={hz:?} dt={dt} focus_changes={focus_changes}"
                    );
                }
            }
        }
    }
}
