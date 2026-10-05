//! Q/E lean and Ctrl+X hip cant: controls, gameplay clamping and permissions.
use glam::{vec2, vec3, Vec3};
use vector_range::{
    control::{ButtonInput, ControlMode, ControlSample, ControlState, CTRL_CHORD_WINDOW},
    settings::Settings,
    sim::{Aabb, Block, Input, Simulation, Target, FIXED_DT, RADIUS},
};

fn down() -> ButtonInput {
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
fn frame(c: &mut ControlState, sample: ControlSample) {
    c.sample(sample, true);
}

// ---------------------------------------------------------------- controls

#[test]
fn ctrl_alone_crouches_on_release_and_ctrl_x_only_cants() {
    let mut c = ControlState::default();
    frame(
        &mut c,
        ControlSample {
            ctrl: down(),
            time: 0.,
            ..Default::default()
        },
    );
    assert!(!c.intent().crouch(), "nothing until Ctrl is released");
    frame(
        &mut c,
        ControlSample {
            ctrl: held(),
            time: 0.5,
            ..Default::default()
        },
    );
    frame(
        &mut c,
        ControlSample {
            time: 0.6,
            ..Default::default()
        },
    );
    assert!(c.intent().crouch() && !c.cant());

    let mut c = ControlState::default();
    frame(
        &mut c,
        ControlSample {
            ctrl: down(),
            time: 0.,
            ..Default::default()
        },
    );
    frame(
        &mut c,
        ControlSample {
            ctrl: held(),
            cant: down(),
            time: 0.05,
            ..Default::default()
        },
    );
    assert!(c.cant());
    frame(
        &mut c,
        ControlSample {
            ctrl: held(),
            time: 0.5,
            ..Default::default()
        },
    );
    frame(
        &mut c,
        ControlSample {
            time: 0.6,
            ..Default::default()
        },
    );
    assert!(c.cant() && !c.intent().crouch(), "chord never crouches");
    // Second chord toggles cant off.
    frame(
        &mut c,
        ControlSample {
            ctrl: down(),
            time: 1.,
            ..Default::default()
        },
    );
    frame(
        &mut c,
        ControlSample {
            ctrl: held(),
            cant: down(),
            time: 1.05,
            ..Default::default()
        },
    );
    frame(
        &mut c,
        ControlSample {
            time: 1.1,
            ..Default::default()
        },
    );
    assert!(!c.cant() && !c.intent().crouch());
}

#[test]
fn x_alone_does_nothing_and_c_stays_an_instant_crouch() {
    let mut c = ControlState::default();
    frame(
        &mut c,
        ControlSample {
            cant: down(),
            ..Default::default()
        },
    );
    assert!(!c.cant());
    frame(&mut c, ControlSample::default());
    frame(
        &mut c,
        ControlSample {
            crouch: down(),
            ..Default::default()
        },
    );
    assert!(c.intent().crouch());
}

#[test]
fn hold_mode_ctrl_crouches_after_the_chord_window_unless_x() {
    let mut c = ControlState::new(ControlMode::Hold);
    frame(
        &mut c,
        ControlSample {
            ctrl: down(),
            time: 0.,
            ..Default::default()
        },
    );
    assert!(!c.intent().crouch());
    frame(
        &mut c,
        ControlSample {
            ctrl: held(),
            time: CTRL_CHORD_WINDOW,
            ..Default::default()
        },
    );
    assert!(c.intent().crouch());
    frame(&mut c, ControlSample::default());
    assert!(!c.intent().crouch());
    frame(
        &mut c,
        ControlSample {
            ctrl: down(),
            time: 1.,
            ..Default::default()
        },
    );
    frame(
        &mut c,
        ControlSample {
            ctrl: held(),
            cant: down(),
            time: 1.05,
            ..Default::default()
        },
    );
    frame(
        &mut c,
        ControlSample {
            ctrl: held(),
            time: 2.,
            ..Default::default()
        },
    );
    assert!(!c.intent().crouch() && c.cant());
}

#[test]
fn lean_toggles_switches_sides_and_clears_on_reset() {
    let mut c = ControlState::default();
    frame(
        &mut c,
        ControlSample {
            lean_left: down(),
            ..Default::default()
        },
    );
    assert_eq!(c.lean(), -1);
    frame(&mut c, ControlSample::default());
    frame(
        &mut c,
        ControlSample {
            lean_right: down(),
            ..Default::default()
        },
    );
    assert_eq!(c.lean(), 1, "other side switches directly");
    frame(&mut c, ControlSample::default());
    frame(
        &mut c,
        ControlSample {
            lean_right: down(),
            ..Default::default()
        },
    );
    assert_eq!(c.lean(), 0, "same side toggles off");
    frame(
        &mut c,
        ControlSample {
            lean_left: down(),
            ..Default::default()
        },
    );
    c.clear();
    assert_eq!(c.lean(), 0);
    frame(
        &mut c,
        ControlSample {
            lean_left: held(),
            ..Default::default()
        },
    );
    assert_eq!(c.lean(), 0, "held key must be released after a clear");
    let mut hold = ControlState::new(ControlMode::Hold);
    frame(
        &mut hold,
        ControlSample {
            lean_right: down(),
            ..Default::default()
        },
    );
    assert_eq!(hold.lean(), 1);
    frame(&mut hold, ControlSample::default());
    assert_eq!(hold.lean(), 0);
}

// ---------------------------------------------------------------- gameplay

fn block(min: Vec3, max: Vec3) -> Block {
    Block {
        bounds: Aabb { min, max },
        kind: 2,
    }
}
fn open_floor() -> Simulation {
    let mut s = Simulation::new();
    s.blocks = vec![block(vec3(-30., -1., -30.), vec3(30., 0., 30.))];
    s.ramps.clear();
    s.targets.clear();
    s.player.position = Vec3::ZERO;
    s.player.yaw = -std::f32::consts::FRAC_PI_2; // facing -Z, right is +X
    s
}
fn run(s: &mut Simulation, input: Input, n: usize) {
    for _ in 0..n {
        s.update(input, &Settings::default(), FIXED_DT);
    }
}
fn lean(side: f32) -> Input {
    Input {
        lean: side,
        ..Input::default()
    }
}

#[test]
fn lean_offsets_only_the_eye_and_rolls_toward_the_side() {
    let t = Settings::default().action;
    let mut s = open_floor();
    let feet = s.player.position;
    run(&mut s, lean(1.), 60);
    assert!((s.player.lean_offset - vec3(t.lean_distance, 0., 0.)).length() < 1e-5);
    assert_eq!(s.player.position, feet, "the body never moves");
    assert!(s.player.lean_roll(t.lean_roll) > 0.);
    run(&mut s, lean(-1.), 60);
    assert!((s.player.lean_offset.x + t.lean_distance).abs() < 1e-5);
    assert!(s.player.lean_roll(t.lean_roll) < 0.);
    run(&mut s, Input::default(), 60);
    assert_eq!(s.player.lean_offset, Vec3::ZERO);
    // Crouched lean is shorter; prone and sprint do not lean.
    run(
        &mut s,
        Input {
            crouch: true,
            lean: 1.,
            ..Input::default()
        },
        80,
    );
    assert!((s.player.lean_offset.x - t.lean_crouch_distance).abs() < 1e-5);
    let mut p = open_floor();
    run(
        &mut p,
        Input {
            prone: true,
            lean: 1.,
            ..Input::default()
        },
        120,
    );
    assert_eq!(p.player.lean_offset, Vec3::ZERO);
    let mut r = open_floor();
    run(
        &mut r,
        Input {
            movement: vec2(0., 1.),
            sprint: true,
            lean: 1.,
            ..Input::default()
        },
        60,
    );
    assert!(r.player.sprinting && r.player.lean_offset == Vec3::ZERO);
}

#[test]
fn lean_into_a_wall_is_clamped_so_the_camera_never_enters_it() {
    let t = Settings::default().action;
    let mut s = open_floor();
    // Wall face 0.25 m right of the body center: only a short lean fits.
    s.blocks
        .push(block(vec3(RADIUS + 0.05, 0., -3.), vec3(2., 3., 3.)));
    run(&mut s, lean(1.), 60);
    let eye = s.player.eye();
    let gap = s.blocks[1].bounds.min.x - eye.x;
    assert!(gap >= t.lean_head_radius - 1e-4, "head stays clear: {gap}");
    assert!(s.player.lean_offset.x < t.lean_distance);
    // Pressed flat against it: no lean at all, and the roll follows the real offset.
    s.player.position.x = s.blocks[1].bounds.min.x - RADIUS;
    run(&mut s, lean(1.), 2);
    assert!(s.player.eye().x <= s.blocks[1].bounds.min.x - t.lean_head_radius + 1e-4);
    // The opposite side is unaffected.
    run(&mut s, lean(-1.), 60);
    assert!((s.player.lean_offset.x + t.lean_distance).abs() < 1e-5);
}

#[test]
fn shots_originate_from_the_leaned_eye() {
    let mut s = open_floor();
    run(&mut s, lean(1.), 60);
    let eye = s.player.eye();
    s.targets = vec![Target {
        bounds: Aabb::from_center(eye + vec3(0., 0., -6.), vec3(0.3, 0.3, 0.2)),
        health: 100.,
        respawn: 0.,
        flash: 0.,
    }];
    let cfg = Settings {
        hip_spread: 0.,
        ..Settings::default()
    };
    s.update(
        Input {
            fire: true,
            lean: 1.,
            ..Input::default()
        },
        &cfg,
        FIXED_DT,
    );
    assert_eq!(s.events[0].start, eye);
    assert_eq!(
        s.stats.hits, 1,
        "a target only visible from the leaned eye is hit"
    );
}

#[test]
fn death_clears_lean_and_cant() {
    let mut s = open_floor();
    run(
        &mut s,
        Input {
            lean: 1.,
            cant: true,
            ..Input::default()
        },
        60,
    );
    assert!(s.player.cant == 1. && s.player.lean_offset != Vec3::ZERO);
    s.kill();
    assert_eq!(s.player.lean_offset, Vec3::ZERO);
    assert_eq!(s.player.cant, 0.);
}

#[test]
fn cant_eases_in_at_the_hip_and_is_suppressed_by_ads() {
    let t = Settings::default().action;
    let mut s = open_floor();
    s.update(
        Input {
            cant: true,
            ..Input::default()
        },
        &Settings::default(),
        FIXED_DT,
    );
    assert!(
        s.player.cant > 0. && s.player.cant < 1.,
        "eased, not snapped"
    );
    let ticks = (t.cant_time / FIXED_DT).ceil() as usize;
    run(
        &mut s,
        Input {
            cant: true,
            ..Input::default()
        },
        ticks,
    );
    assert_eq!(s.player.cant_visual(), 1.);
    run(
        &mut s,
        Input {
            cant: true,
            ads: true,
            ..Input::default()
        },
        60,
    );
    assert_eq!(s.player.cant_visual(), 0., "no cant while aimed");
    assert_eq!(s.player.cant, 1., "the toggle survives ADS");
    run(
        &mut s,
        Input {
            cant: true,
            ..Input::default()
        },
        60,
    );
    assert_eq!(s.player.cant_visual(), 1., "returns after leaving ADS");
}
