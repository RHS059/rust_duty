//! Independent elapsed-presentation checks against the public simulation API.
use glam::vec2;
use vector_range::{
    clock::FixedClock,
    reference_motion::{visual_duration, ReloadVisualClock},
    settings::Settings,
    sim::{Input, Simulation, FIXED_DT},
    view_animation::ViewAnimation,
    weapon_animation::{sample_weapon_animation, AnimationInput, WeaponAnimationPose},
};

fn observe(
    state: &mut ViewAnimation,
    sim: &Simulation,
    recoil: f32,
) -> (Option<f32>, WeaponAnimationPose) {
    let p = &sim.player;
    let progress = (p.reload_left > 0. && p.reload_total > 0.)
        .then(|| (1. - p.reload_left / p.reload_total).clamp(0., 1.));
    let completed =
        progress.is_none() && p.reload_ready_at > 0. && sim.time + 1e-6 >= p.reload_ready_at;
    let phase = state.presentation_progress(
        progress,
        p.reload_total,
        p.reload_empty,
        completed,
        sim.time,
    );
    let pose = state.sample_input(
        AnimationInput {
            reload_progress: phase,
            empty_reload: p.reload_empty,
            recoil,
            ads: p.ads,
            ..Default::default()
        },
        completed,
        sim.time,
    );
    (phase, pose)
}

fn begin(ammo: u32) -> (Simulation, Settings) {
    let mut sim = Simulation::new();
    let cfg = Settings::m4_candidate();
    sim.player.ammo = ammo;
    sim.update(
        Input {
            reload: true,
            ..Default::default()
        },
        &cfg,
        FIXED_DT,
    );
    (sim, cfg)
}

#[test]
fn tactical_visual_tail_keeps_accepted_live_recoil_and_trigger_at_all_render_strides() {
    for stride in [1, 2, 4, 8] {
        let (mut sim, cfg) = begin(15);
        let mut firing = ViewAnimation::default();
        let mut residual = ViewAnimation::default();
        observe(&mut firing, &sim, 0.);
        observe(&mut residual, &sim, 0.);
        let mut witnessed_live_tail = false;
        let mut witnessed_settled = false;
        for tick in 1..=300 {
            sim.update(
                Input {
                    fire: true,
                    ..Default::default()
                },
                &cfg,
                FIXED_DT,
            );
            if tick % stride != 0 {
                continue;
            }
            let (phase, pose) = observe(&mut firing, &sim, sim.player.shot_kick);
            let (_, base) = observe(&mut residual, &sim, 0.);
            if sim.stats.shots > 0 && phase.is_some_and(|p| p < 1.) {
                witnessed_live_tail = true;
                assert_eq!(sim.player.reload_left, 0.);
                assert!(sim.time < visual_duration(false) as f64 + 2. * FIXED_DT as f64);
                let live = sample_weapon_animation(AnimationInput {
                    recoil: sim.player.shot_kick,
                    ads: sim.player.ads,
                    ..Default::default()
                });
                assert_eq!(pose.trigger_pull, live.trigger_pull);
                for axis in 0..3 {
                    assert!(
                        (pose.weapon_translation[axis]
                            - base.weapon_translation[axis]
                            - live.weapon_translation[axis])
                            .abs()
                            < 1e-6
                    );
                    assert!(
                        (pose.weapon_euler_yxz[axis]
                            - base.weapon_euler_yxz[axis]
                            - live.weapon_euler_yxz[axis])
                            .abs()
                            < 1e-6
                    );
                }
            }
            if sim.time > 2.24 {
                witnessed_settled = true;
                assert_eq!(phase, None);
            }
        }
        assert!(witnessed_live_tail, "stride {stride} skipped live recovery");
        assert!(witnessed_settled);
        assert!(sim.events[0].time >= cfg.reload_time as f64 - 1e-6);
        assert!(sim.events[0].time < cfg.reload_time as f64 + FIXED_DT as f64 + 1e-6);
    }
}

#[test]
fn empty_visual_is_settled_while_gameplay_still_blocks_held_fire() {
    for stride in [1, 2, 4, 8] {
        let (mut sim, cfg) = begin(0);
        let mut state = ViewAnimation::default();
        observe(&mut state, &sim, 0.);
        let mut witnessed_settled_before_ready = false;
        for tick in 1..=300 {
            sim.update(
                Input {
                    fire: true,
                    ..Default::default()
                },
                &cfg,
                FIXED_DT,
            );
            if tick % stride != 0 {
                continue;
            }
            let (phase, pose) = observe(&mut state, &sim, sim.player.shot_kick);
            if sim.time > 2.23 && sim.player.reload_left > 0. {
                witnessed_settled_before_ready = true;
                assert_eq!(phase, Some(1.));
                assert_eq!(pose, sample_weapon_animation(AnimationInput::default()));
                assert_eq!(sim.stats.shots, 0);
            }
        }
        assert!(witnessed_settled_before_ready, "stride {stride}");
        assert!(sim.events[0].time >= cfg.empty_reload_time as f64 - 1e-6);
        assert!(sim.events[0].time < cfg.empty_reload_time as f64 + FIXED_DT as f64 + 1e-6);
    }
}

#[test]
fn render_sampling_and_pause_do_not_advance_elapsed_phase() {
    let mut expected: Option<f32> = None;
    for stride in [1, 2, 4, 8, 12] {
        let (mut sim, cfg) = begin(15);
        let mut state = ViewAnimation::default();
        // Intentionally begin rendering at different elapsed simulation times.
        for tick in 1..=120 {
            sim.update(Input::default(), &cfg, FIXED_DT);
            if tick % stride == 0 {
                observe(&mut state, &sim, 0.);
            }
        }
        let (phase, pose) = observe(&mut state, &sim, 0.);
        let phase = phase.unwrap();
        if let Some(expected) = expected {
            assert!((phase - expected).abs() < 1e-6);
        } else {
            expected = Some(phase);
        }
        for _ in 0..60 {
            assert_eq!(observe(&mut state, &sim, 0.), (Some(phase), pose));
        }
    }
}

#[test]
fn actual_fixed_simulation_never_false_restarts_at_30_60_or_144_render_hz() {
    for fps in [30_f64, 60000. / 1001., 60., 144., 240.] {
        for ammo in [0, 15] {
            for session_start in [0., 3600., 86400.] {
                let cfg = Settings::m4_candidate();
                let mut sim = Simulation::new();
                sim.time = session_start;
                sim.player.ammo = ammo;
                let mut clock = FixedClock::default();
                let mut state = ViewAnimation::default();
                let mut started = false;
                let mut previous_phase = 0.;
                for _ in 0..(fps * 3.).ceil() as usize {
                    for _ in 0..clock.advance(1. / fps).unwrap() {
                        sim.update(
                            Input {
                                reload: !started,
                                ..Default::default()
                            },
                            &cfg,
                            FIXED_DT,
                        );
                        started = true;
                    }
                    let (phase, _) = observe(&mut state, &sim, 0.);
                    if !started {
                        assert_eq!(phase, None);
                        continue;
                    }
                    // Player deadlines/reload_left describe the last update's
                    // start; the renderer observes its post-update timestamp.
                    let expected = ((sim.time - session_start - FIXED_DT as f64)
                        / visual_duration(ammo == 0) as f64)
                        as f32;
                    if let Some(phase) = phase {
                        assert!(
                            (phase - expected.clamp(0., 1.)).abs() < 1e-5,
                            "false restart at {fps} Hz, ammo {ammo}, start {session_start}: \
                             phase {phase}, expected {expected}"
                        );
                        assert!(phase + 1e-6 >= previous_phase);
                        previous_phase = phase;
                    } else {
                        assert!(expected >= 1. && sim.player.reload_left == 0.);
                    }
                }
            }
        }
    }
}

#[test]
fn a_new_reload_after_an_observed_ready_frame_replaces_the_tail() {
    let mut state = ReloadVisualClock::default();
    state.phase(Some(0.), 2.029, false, false, 0.);
    let tail = state.phase(None, 2.029, false, true, 2.04).unwrap();
    assert!(tail > 0.9 && tail < 1.);
    assert_eq!(state.phase(Some(0.), 2.359, true, false, 2.06), Some(0.));
    assert!(
        (state
            .phase(Some(0.1 / 2.359), 2.359, true, false, 2.16)
            .unwrap()
            - 0.1 / 2.2)
            .abs()
            < 1e-6
    );
}

#[test]
fn cancellation_after_ready_discards_an_existing_visual_tail() {
    let mut state = ReloadVisualClock::default();
    state.phase(Some(0.), 2.029, false, false, 0.);
    assert!(state.phase(None, 2.029, false, true, 2.04).is_some());
    // Mantle/supply cancellation clears the simulation ready deadline after the
    // previous render already observed ready. The presentation must clear too.
    assert_eq!(state.phase(None, 0., false, false, 2.08), None);
    assert_eq!(state.phase(None, 0., false, false, 2.12), None);
}

#[test]
fn cancellation_and_restart_without_an_intermediate_render_start_a_fresh_clock() {
    let (mut sim, cfg) = begin(15);
    let mut state = ViewAnimation::default();
    observe(&mut state, &sim, 0.);
    for _ in 0..60 {
        sim.update(Input::default(), &cfg, FIXED_DT);
    }
    assert!(observe(&mut state, &sim, 0.).0.unwrap() > 0.2);
    // A single accepted simulation update can cancel tactical reload for a
    // sprint request and then process a fresh reload press. No None is rendered.
    sim.update(
        Input {
            movement: vec2(0., 1.),
            sprint: true,
            reload: true,
            ..Default::default()
        },
        &cfg,
        FIXED_DT,
    );
    assert_eq!(sim.player.reload_left, cfg.reload_time);
    assert_eq!(observe(&mut state, &sim, 0.).0, Some(0.));
}

#[test]
fn explicit_animation_reset_discards_a_tail_and_any_cancel_blend() {
    let (mut sim, cfg) = begin(15);
    let mut state = ViewAnimation::default();
    observe(&mut state, &sim, 0.);
    for _ in 0..245 {
        sim.update(Input::default(), &cfg, FIXED_DT);
    }
    assert!(observe(&mut state, &sim, 0.).0.is_some());
    sim.reset();
    state = ViewAnimation::default();
    assert_eq!(
        observe(&mut state, &sim, 0.),
        (None, sample_weapon_animation(AnimationInput::default()))
    );
}
