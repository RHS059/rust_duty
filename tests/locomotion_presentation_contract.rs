//! CPU-only cosmetic locomotion contracts; also runnable with plain rustc.
#[path = "../src/locomotion_presentation.rs"]
mod locomotion_presentation;
use locomotion_presentation::{
    LocomotionInput, LocomotionPose, LocomotionPresentation, SPRINT_RESPONSE_SECONDS,
};
use std::f64::consts::TAU;

fn walk() -> LocomotionInput {
    LocomotionInput {
        sprint: 0.,
        speed: 4.826,
        ads: 0.,
    }
}
fn run() -> LocomotionInput {
    LocomotionInput {
        sprint: 1.,
        speed: 7.239,
        ads: 0.,
    }
}
fn phase_distance(a: f64, b: f64) -> f64 {
    ((a - b + TAU * 0.5).rem_euclid(TAU) - TAU * 0.5).abs()
}
fn close(a: LocomotionPose, b: LocomotionPose) {
    assert!((a.sprint - b.sprint).abs() < 1e-6, "{a:?} != {b:?}");
    assert!((a.bob - b.bob).abs() < 1e-7, "{a:?} != {b:?}");
    assert!((a.bob_amplitude - b.bob_amplitude).abs() < 1e-7);
    assert!((a.bob_angular_frequency - b.bob_angular_frequency).abs() < 1e-6);
    assert!(phase_distance(a.phase, b.phase) < 1e-8, "{a:?} != {b:?}");
}
fn finite(p: LocomotionPose) {
    assert!(p.sprint.is_finite() && (0. ..=1.).contains(&p.sprint));
    assert!(p.bob.is_finite() && p.bob.abs() <= 0.015_001);
    assert!(p.bob_amplitude.is_finite() && (0. ..=0.015_001).contains(&p.bob_amplitude));
    assert!(p.bob_angular_frequency.is_finite() && (10. ..=14.).contains(&p.bob_angular_frequency));
    assert!(p.phase.is_finite() && (0. ..TAU).contains(&p.phase));
}

#[test]
fn sprint_entry_and_exit_ease_over_about_a_quarter_second() {
    let mut state = LocomotionPresentation::default();
    assert_eq!(state.sample(0., run()), LocomotionPose::default());
    let half = state.sample(SPRINT_RESPONSE_SECONDS * 0.5, run());
    assert!(half.sprint > 0.5 && half.sprint < 0.9);
    let entered = state.sample(SPRINT_RESPONSE_SECONDS, run());
    assert!((entered.sprint - 0.95).abs() < 1e-6);
    let held = state.sample(2., run());
    assert!((held.sprint - 1.).abs() < 1e-6);
    let release = state.sample(2., walk());
    assert_eq!(held, release, "a target change must not jump the pose");
    let exited = state.sample(2. + SPRINT_RESPONSE_SECONDS, walk());
    assert!((exited.sprint - 0.05).abs() < 1e-6);
    assert!(exited.bob_angular_frequency > 10. && exited.bob_angular_frequency < 10.3);
}

fn sample_cadence(hz: u32) -> Vec<LocomotionPose> {
    // Event times are explicit and identical across cadences. Observations
    // between them may differ; they cannot alter analytic held-target motion.
    let events = [
        (0., walk()),
        (0.30, run()),
        (0.49, walk()),
        (0.58, run()),
        (0.91, LocomotionInput { ads: 1., ..walk() }),
        (1.27, LocomotionInput::default()),
        (1.61, run()),
    ];
    let probes = [
        0., 0.30, 0.40, 0.49, 0.58, 0.70, 0.91, 1.05, 1.27, 1.61, 1.85, 2.2,
    ];
    let mut times: Vec<f64> = (0..=(hz as f64 * 2.2) as u32)
        .map(|i| i as f64 / hz as f64)
        .collect();
    times.extend(events.iter().map(|&(t, _)| t));
    times.extend(probes);
    times.sort_by(f64::total_cmp);
    times.dedup();
    let mut state = LocomotionPresentation::default();
    let mut out = Vec::new();
    for time in times {
        let input = events.iter().rev().find(|&&(t, _)| t <= time).unwrap().1;
        let pose = state.sample(time, input);
        if probes.contains(&time) {
            out.push(pose);
        }
    }
    assert_eq!(out.len(), probes.len());
    out
}

#[test]
fn thirty_sixty_and_144_hz_match_with_reversals_and_ads() {
    let reference = sample_cadence(60);
    for hz in [30, 144] {
        for (a, b) in reference.iter().copied().zip(sample_cadence(hz)) {
            close(a, b);
        }
    }
}

#[test]
fn rapid_reversals_keep_pose_frequency_and_sprint_velocity_continuous() {
    let mut state = LocomotionPresentation::default();
    state.sample(0., run());
    let epsilon = 0.00001;
    for i in 1..=20 {
        let time = i as f64 * 0.037;
        let old = if i % 2 == 1 { run() } else { walk() };
        let next = if i % 2 == 1 { walk() } else { run() };
        let before = state.sample(time - epsilon, old);
        let edge = state.sample(time, old);
        assert_eq!(edge, state.sample(time, next));
        let after = state.sample(time + epsilon, next);
        finite(after);
        let velocity_before = (edge.sprint as f64 - before.sprint as f64) / epsilon;
        let velocity_after = (after.sprint as f64 - edge.sprint as f64) / epsilon;
        assert!((velocity_before - velocity_after).abs() < 0.015);
        assert!(phase_distance(after.phase, edge.phase) < 0.00015);
        assert!((after.bob - edge.bob).abs() < 0.00001);
    }
}

#[test]
fn pause_and_zero_delta_do_not_advance_visuals_or_phase() {
    let mut state = LocomotionPresentation::default();
    state.sample(10., run());
    let held = state.sample(10.12, run());
    for input in [walk(), LocomotionInput::default(), run()] {
        assert_eq!(held, state.sample(10.12, input));
    }
    let mut clone = state.clone();
    close(state.sample(10.22, run()), clone.sample(10.22, run()));
}

#[test]
fn explicit_reset_and_rewound_simulation_start_from_rest() {
    let mut state = LocomotionPresentation::default();
    state.sample(10., run());
    state.sample(11., run());
    state.reset(20.);
    assert_eq!(state.sample(20., run()), LocomotionPose::default());
    let after = state.sample(20.12, run());
    assert!(after.sprint > 0.);
    assert_eq!(state.sample(0., run()), LocomotionPose::default());
    let mut fresh = LocomotionPresentation::default();
    fresh.sample(0., run());
    close(state.sample(0.12, run()), fresh.sample(0.12, run()));
}

#[test]
fn hitches_integrate_frequency_instead_of_restarting_bob() {
    let mut sparse = LocomotionPresentation::default();
    sparse.sample(0., run());
    let mut dense = sparse.clone();
    for i in 1..=600 {
        dense.sample(i as f64 / 60., run());
    }
    close(sparse.sample(10., run()), dense.sample(10., run()));
    let event = sparse.sample(10., walk());
    dense.sample(10., walk());
    assert_eq!(event, sparse.sample(10., walk()));
    for i in 1..=120 {
        dense.sample(10. + i as f64 / 60., walk());
    }
    close(sparse.sample(12., walk()), dense.sample(12., walk()));
}

#[test]
fn ads_and_stopping_fade_amplitude_without_resetting_the_oscillator() {
    let mut state = LocomotionPresentation::default();
    state.sample(0., walk());
    let moving = state.sample(1., walk());
    assert!(moving.bob_amplitude > 0.006);
    let aim = LocomotionInput { ads: 1., ..walk() };
    assert_eq!(moving, state.sample(1., aim));
    let aimed = state.sample(1.3, aim);
    assert!(aimed.bob_amplitude < 0.000001);
    assert!(phase_distance(aimed.phase, moving.phase) > 1.);
    let stopped = LocomotionInput::default();
    state.sample(1.3, stopped);
    let rest = state.sample(2.3, stopped);
    assert!(rest.bob_amplitude < 0.000001);
    finite(rest);
}

#[test]
fn invalid_targets_clocks_and_extreme_finite_hitches_remain_safe() {
    let mut state = LocomotionPresentation::default();
    state.sample(0., run());
    let held = state.sample(0.1, run());
    for time in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert_eq!(held, state.sample(time, LocomotionInput::default()));
    }
    for (i, value) in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY, -1., f32::MAX]
        .into_iter()
        .enumerate()
    {
        finite(state.sample(
            1. + i as f64,
            LocomotionInput {
                sprint: value,
                speed: value,
                ads: value,
            },
        ));
    }
    finite(state.sample(f64::MAX, run()));
    state.reset(f64::NAN);
    assert_eq!(state.sample(-2., run()), LocomotionPose::default());
    finite(state.sample(f64::MAX, run()));
}

#[test]
fn low_carry_frequency_matches_measured_reference_cycle() {
    let mut state = LocomotionPresentation::default();
    state.sample(0., run());
    let held = state.sample(2., run());
    let hz = held.bob_angular_frequency as f64 / TAU;
    assert!((hz - 1.71).abs() < 0.04);
    assert!(
        (TAU / held.bob_angular_frequency as f64
            - locomotion_presentation::LOW_CARRY_CYCLE_SECONDS)
            .abs()
            < 1e-6
    );
    assert_eq!(held, state.sample(2., walk()));
    let returned = state.sample(4., walk());
    assert!((returned.bob_angular_frequency - 10.).abs() < 1e-6);
}
