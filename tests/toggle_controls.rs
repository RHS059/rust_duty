//! Pure input contracts plus simulation integration: presentation edges must not
//! repeat when a render frame produces zero, one, or many fixed simulation ticks.
use macroquad::math::{vec2, vec3};
use vector_range::{
    clock::FixedClock,
    control::{
        ButtonInput, ControlIntent, ControlMode, ControlSample, ControlState, DesiredStance,
        IntentLatch,
    },
    settings::Settings,
    sim::{Aabb, Block, Input, Simulation, FIXED_DT},
};

fn press() -> ButtonInput {
    ButtonInput {
        pressed: true,
        down: true,
    }
}
fn held() -> ButtonInput {
    ButtonInput {
        pressed: false,
        down: true,
    }
}
fn ads() -> ControlSample {
    ControlSample {
        ads: press(),
        ..ControlSample::default()
    }
}
fn crouch() -> ControlSample {
    ControlSample {
        crouch: press(),
        ..ControlSample::default()
    }
}
fn prone() -> ControlSample {
    ControlSample {
        prone: press(),
        ..ControlSample::default()
    }
}
fn release(c: &mut ControlState) {
    c.sample(ControlSample::default(), true);
}
fn input(c: &ControlState) -> Input {
    let desired = c.intent();
    Input {
        ads: desired.ads,
        crouch: desired.crouch(),
        prone: desired.prone(),
        ..Input::default()
    }
}
fn ticks(s: &mut Simulation, c: &ControlState, n: usize) {
    for _ in 0..n {
        s.update(input(c), &Settings::default(), FIXED_DT);
    }
}

#[test]
fn defaults_are_toggle_hipfire_and_standing() {
    let c = ControlState::default();
    assert_eq!(c.mode(), ControlMode::Toggle);
    assert_eq!(c.intent(), ControlIntent::default());
}

#[test]
fn each_second_press_toggles_off_after_release() {
    for (sample, expected) in [
        (
            ads(),
            ControlIntent {
                ads: true,
                stance: DesiredStance::Standing,
            },
        ),
        (
            crouch(),
            ControlIntent {
                ads: false,
                stance: DesiredStance::Crouched,
            },
        ),
        (
            prone(),
            ControlIntent {
                ads: false,
                stance: DesiredStance::Prone,
            },
        ),
    ] {
        let mut c = ControlState::default();
        c.sample(sample, true);
        assert_eq!(c.intent(), expected);
        release(&mut c);
        assert_eq!(c.intent(), expected, "release must retain the toggle");
        c.sample(sample, true);
        assert_eq!(c.intent(), ControlIntent::default());
    }
}

#[test]
fn render_frames_and_key_repeat_do_not_toggle_held_buttons_again() {
    for sample in [ads(), crouch(), prone()] {
        let mut c = ControlState::default();
        c.sample(sample, true);
        let expected = c.intent();
        for _ in 0..200 {
            // Includes a spurious/repeated pressed flag while continuously down.
            c.sample(sample, true);
            assert_eq!(c.intent(), expected);
            for _ in 0..30 {
                assert_eq!(c.intent(), expected);
            }
        }
    }
}

#[test]
fn short_taps_survive_frames_with_no_simulation_step() {
    let mut c = ControlState::default();
    let mut clock = FixedClock::default();
    c.sample(
        ControlSample {
            ads: ButtonInput {
                pressed: true,
                down: false,
            },
            crouch: ButtonInput {
                pressed: true,
                down: false,
            },
            ..ControlSample::default()
        },
        true,
    );
    assert_eq!(clock.advance(0.0001).unwrap(), 0);
    release(&mut c);
    let steps = clock.advance(FIXED_DT as f64 * 4.).unwrap();
    assert_eq!(steps, 4);
    let mut s = Simulation::new();
    ticks(&mut s, &c, steps);
    assert!(s.player.crouched);
    assert!(s.player.ads > 0.);
    assert_eq!(c.intent().stance, DesiredStance::Crouched);
    assert!(c.intent().ads);
}

#[test]
fn quick_taps_before_a_fixed_tick_resolve_in_press_order() {
    let mut c = ControlState::default();
    c.sample(crouch(), true);
    release(&mut c);
    c.sample(prone(), true);
    assert_eq!(c.intent().stance, DesiredStance::Prone);
    release(&mut c);
    c.sample(prone(), true);
    assert_eq!(c.intent().stance, DesiredStance::Standing);
}

#[test]
fn switching_stances_is_exclusive_in_both_directions() {
    let mut c = ControlState::default();
    c.sample(crouch(), true);
    assert!(c.intent().crouch());
    c.sample(prone(), true);
    assert!(c.intent().prone());
    assert!(!c.intent().crouch());
    c.sample(crouch(), true);
    assert!(c.intent().crouch());
    assert!(!c.intent().prone());
}

#[test]
fn simultaneous_stance_presses_have_deterministic_prone_priority() {
    let mut c = ControlState::default();
    c.sample(
        ControlSample {
            crouch: press(),
            prone: press(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(c.intent().prone());
    assert!(!c.intent().crouch());
}

#[test]
fn reset_pause_resume_and_focus_clear_every_intent_and_require_release() {
    for mode in [ControlMode::Toggle, ControlMode::Hold] {
        for sample in [ads(), crouch(), prone()] {
            let mut c = ControlState::new(mode);
            c.sample(sample, true);
            assert_ne!(c.intent(), ControlIntent::default());
            c.clear();
            for _ in 0..10 {
                c.sample(sample, true);
                assert_eq!(c.intent(), ControlIntent::default());
            }
            release(&mut c);
            c.sample(sample, true);
            assert_ne!(c.intent(), ControlIntent::default());
        }
    }
}

#[test]
fn resume_frame_edges_cannot_restore_cleared_desires() {
    let mut c = ControlState::default();
    c.clear();
    c.sample(
        ControlSample {
            ads: press(),
            crouch: press(),
            prone: press(),
            ..ControlSample::default()
        },
        false,
    );
    assert_eq!(c.intent(), ControlIntent::default());
    c.sample(
        ControlSample {
            ads: held(),
            crouch: held(),
            prone: held(),
            ..ControlSample::default()
        },
        true,
    );
    assert_eq!(c.intent(), ControlIntent::default());
    release(&mut c);
    c.sample(ads(), true);
    assert!(c.intent().ads);
}

#[test]
fn ignored_input_clears_desires_even_without_an_explicit_clear() {
    let mut c = ControlState::default();
    c.sample(ads(), true);
    c.sample(crouch(), true);
    c.sample(ControlSample::default(), false);
    assert_eq!(c.intent(), ControlIntent::default());
}

#[test]
fn hold_controls_release_ads_and_stances() {
    let mut c = ControlState::new(ControlMode::Hold);
    c.sample(
        ControlSample {
            ads: press(),
            crouch: press(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(c.intent().ads && c.intent().crouch());
    c.sample(
        ControlSample {
            ads: held(),
            crouch: held(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(c.intent().ads && c.intent().crouch());
    release(&mut c);
    assert_eq!(c.intent(), ControlIntent::default());
    c.sample(
        ControlSample {
            crouch: press(),
            prone: press(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(c.intent().prone());
    assert!(!c.intent().crouch());
    c.sample(
        ControlSample {
            crouch: held(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(c.intent().crouch());
}

#[test]
fn new_sprint_press_cancels_toggle_ads_but_held_shift_does_not_repeatedly_cancel() {
    let mut c = ControlState::default();
    c.sample(ads(), true);
    c.sample(
        ControlSample {
            sprint: press(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(!c.intent().ads);
    c.sample(
        ControlSample {
            ads: press(),
            sprint: held(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(c.intent().ads);
    c.sample(
        ControlSample {
            sprint: held(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(c.intent().ads);
    let mut s = Simulation::new();
    let mut step = input(&c);
    step.sprint = true;
    step.movement = vec2(0., 1.);
    s.update(step, &Settings::default(), FIXED_DT);
    assert!(
        !s.player.sprinting,
        "simulation retains ADS/sprint eligibility"
    );
}

#[test]
fn simultaneous_ads_and_sprint_press_cancels_ads() {
    let mut c = ControlState::default();
    c.sample(
        ControlSample {
            ads: press(),
            sprint: press(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(!c.intent().ads);
}

#[test]
fn hold_mode_retains_prior_ads_priority_over_sprint() {
    let mut c = ControlState::new(ControlMode::Hold);
    c.sample(
        ControlSample {
            ads: press(),
            sprint: press(),
            ..ControlSample::default()
        },
        true,
    );
    assert!(c.intent().ads);
}

#[test]
fn jump_clears_toggle_stance_without_clearing_ads() {
    for stance in [crouch(), prone()] {
        let mut c = ControlState::default();
        c.sample(ads(), true);
        c.sample(stance, true);
        c.request_jump();
        assert_eq!(c.intent().stance, DesiredStance::Standing);
        assert!(c.intent().ads);
        release(&mut c);
        assert_eq!(c.intent().stance, DesiredStance::Standing);
    }
}

#[test]
fn hold_mode_leaves_jump_stand_override_to_simulation() {
    let mut c = ControlState::new(ControlMode::Hold);
    c.sample(crouch(), true);
    c.request_jump();
    assert!(c.intent().crouch());
}

#[test]
fn jump_from_each_lower_stance_stands_then_stays_standing_without_launching() {
    for sample in [crouch(), prone()] {
        let mut c = ControlState::default();
        let mut s = Simulation::new();
        c.sample(sample, true);
        ticks(&mut s, &c, 120);
        assert!(s.player.crouched);
        let height = s.player.eye_height;
        c.request_jump();
        let mut step = input(&c);
        step.jump = true;
        s.update(step, &Settings::default(), FIXED_DT);
        assert!(s.player.grounded);
        assert!(s.player.eye_height < 1.62);
        assert!(
            (s.player.eye_height - height).abs() < 0.02,
            "camera must ease, not teleport"
        );
        ticks(&mut s, &c, 150);
        assert!(!s.player.crouched && !s.player.prone);
        assert!(s.player.grounded);
        s.update(step, &Settings::default(), FIXED_DT);
        assert!(
            !s.player.grounded,
            "a separate jump from standing can launch"
        );
    }
}

#[test]
fn jump_intent_survives_no_tick_frame_and_stand_request_is_consumed_once() {
    let mut c = ControlState::default();
    let mut latch = IntentLatch::default();
    c.sample(prone(), true);
    latch.sample(true, false, false, false, true);
    release(&mut c);
    latch.sample(false, false, false, false, true);
    for i in 0..8 {
        let step = latch.take(false);
        if step.jump {
            c.request_jump();
        }
        assert_eq!(step.jump, i == 0);
        assert_eq!(c.intent().stance, DesiredStance::Standing);
    }
}

#[test]
fn standing_request_waits_for_clearance_without_reactivating_toggle() {
    let mut c = ControlState::default();
    let mut s = Simulation::new();
    c.sample(crouch(), true);
    ticks(&mut s, &c, 100);
    let p = s.player.position;
    s.blocks.push(Block {
        bounds: Aabb {
            min: p + vec3(-2., 1.35, -2.),
            max: p + vec3(2., 2., 2.),
        },
        kind: 0,
    });
    release(&mut c);
    c.sample(crouch(), true);
    ticks(&mut s, &c, 100);
    assert_eq!(c.intent().stance, DesiredStance::Standing);
    assert!(s.player.crouched, "ceiling blocks standing");
    assert!(s.player.eye_height < 1.35);
    s.blocks.pop();
    ticks(&mut s, &c, 100);
    assert!(!s.player.crouched);
    assert_eq!(c.intent().stance, DesiredStance::Standing);
}

#[test]
fn prone_to_standing_uses_two_eased_transitions() {
    let mut c = ControlState::default();
    let mut s = Simulation::new();
    c.sample(prone(), true);
    ticks(&mut s, &c, 120);
    assert!(s.player.prone);
    release(&mut c);
    c.sample(prone(), true);
    let height = s.player.eye_height;
    ticks(&mut s, &c, 1);
    assert!(!s.player.prone && s.player.crouched);
    assert!((s.player.eye_height - height).abs() < 0.02);
    ticks(&mut s, &c, 24);
    assert!(s.player.crouched);
    ticks(&mut s, &c, 100);
    assert!(!s.player.crouched && !s.player.prone);
}

#[test]
fn toggle_ads_respects_reload_and_returns_after_reload_finishes() {
    let mut c = ControlState::default();
    let mut s = Simulation::new();
    c.sample(ads(), true);
    ticks(&mut s, &c, 50);
    assert_eq!(s.player.ads, 1.);
    s.player.ammo = 10;
    let mut step = input(&c);
    step.reload = true;
    s.update(step, &Settings::default(), FIXED_DT);
    ticks(&mut s, &c, 50);
    assert_eq!(s.player.ads, 0.);
    assert!(c.intent().ads);
    ticks(&mut s, &c, 300);
    assert_eq!(s.player.ads, 1.);
}

#[test]
fn existing_fire_latch_keeps_short_and_held_shots_and_blocks_resume_shot() {
    let mut latch = IntentLatch::default();
    latch.sample(false, false, true, false, true);
    assert!(latch.take(false).fire);
    assert!(!latch.take(false).fire);
    latch.sample(false, false, true, true, true);
    for _ in 0..20 {
        assert!(latch.take(true).fire);
    }
    latch.clear();
    latch.sample(true, true, true, true, false);
    for _ in 0..20 {
        let step = latch.take(true);
        assert!(!step.fire && !step.jump && !step.reload);
    }
    latch.sample(false, false, false, false, true);
    latch.sample(false, false, true, true, true);
    assert!(latch.take(true).fire);
}
