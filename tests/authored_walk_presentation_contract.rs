use macroquad::math::{Mat4, Vec3};
use vector_range::{
    authored_locomotion_path::{
        AuthoredLocomotionPath, AuthoredLocomotionPathConfig, AuthoredLocomotionPathState as State,
    },
    authored_walk_presentation::{AuthoredWalkPresentation, WALK_ROOT_TRANSITION_SECONDS},
    locomotion_presentation::{LocomotionInput, LocomotionPresentation},
    skinned_asset::Bone,
    viewmodel_animation::{game_model_root, AnimationSet},
};

fn walk() -> LocomotionInput {
    LocomotionInput {
        speed: 4.826,
        ..Default::default()
    }
}

fn moving() -> AuthoredWalkPresentation {
    let mut presentation = AuthoredWalkPresentation::default();
    presentation.sample(0., true, walk());
    presentation.sample(1., true, walk());
    presentation
}

#[test]
fn walking_restores_the_existing_speed_scaled_bob_while_idle_stays_still() {
    let mut walking = AuthoredWalkPresentation::default();
    let mut idle = AuthoredWalkPresentation::default();
    let mut legacy = LocomotionPresentation::default();
    for tick in 0..=240 {
        let time = tick as f64 / 120.;
        walking.sample(time, true, walk());
        idle.sample(time, true, LocomotionInput::default());
        assert_eq!(walking.offset(), legacy.sample(time, walk()).bob);
        assert_eq!(idle.offset(), 0.);
    }
    assert!(walking.offset().abs() > 0.005);
}

#[test]
fn stopping_preserves_the_event_pose_and_smoothly_fades_to_idle() {
    let mut presentation = moving();
    let incoming = presentation.offset();
    presentation.sample(1., true, LocomotionInput::default());
    assert_eq!(presentation.offset(), incoming);
    presentation.sample(1.00001, true, LocomotionInput::default());
    assert!((presentation.offset() - incoming).abs() < 0.000001);
    presentation.sample(2., true, LocomotionInput::default());
    assert!(presentation.offset().abs() < 0.000001);
}

#[test]
fn entry_captures_only_a_bounded_monotonically_decaying_root_residual() {
    let mut presentation = moving();
    let incoming = presentation.offset();
    assert!(incoming.abs() > 0.003);
    presentation.sample(1., false, walk());
    assert_eq!(presentation.offset(), incoming);
    let mut previous = incoming.abs();
    for tick in 1..=100 {
        presentation.sample(1. + tick as f64 / 1000., false, walk());
        let offset = presentation.offset();
        assert!(offset.abs() <= previous);
        assert!(offset.abs() <= incoming.abs());
        assert!(offset == 0. || offset.signum() == incoming.signum());
        previous = offset.abs();
    }
    assert_eq!(presentation.offset(), 0.);
    for time in [1.5, 2., 10., 50.] {
        presentation.sample(time, false, walk());
        assert_eq!(presentation.offset(), 0., "no ongoing sprint bob");
        assert_eq!(presentation.model_root(), game_model_root());
    }
}

#[test]
fn rapid_return_to_ready_is_continuous_even_before_residual_expiry() {
    let mut presentation = moving();
    presentation.sample(1., false, walk());
    presentation.sample(1.02, false, walk());
    let outgoing = presentation.offset();
    presentation.sample(1.02, true, walk());
    assert_eq!(presentation.offset(), outgoing);
    presentation.sample(1.02001, true, walk());
    assert!((presentation.offset() - outgoing).abs() < 0.000001);
    presentation.sample(1.04, false, walk());
    let second = presentation.offset();
    presentation.sample(1.04, true, walk());
    assert_eq!(presentation.offset(), second);
}

#[test]
fn settled_sprint_return_fades_in_instead_of_revealing_hidden_bob() {
    let mut presentation = moving();
    presentation.sample(1., false, walk());
    presentation.sample(3., false, walk());
    assert_eq!(presentation.offset(), 0.);
    presentation.sample(3., true, walk());
    assert_eq!(presentation.offset(), 0.);
    presentation.sample(3.00001, true, walk());
    assert!(presentation.offset().abs() < 0.000001);
    presentation.sample(4., true, walk());
    assert!(presentation.offset().abs() > 0.004);
}

fn schedule(time: f64) -> (bool, LocomotionInput) {
    let ready = !(0.5..1.5).contains(&time);
    let input = if time < 2. {
        walk()
    } else {
        LocomotionInput::default()
    };
    (ready, input)
}

fn rendered(hz: u32) -> Vec<f32> {
    let mut presentation = AuthoredWalkPresentation::default();
    let mut tick = 0;
    let mut roots = Vec::new();
    for frame in 0..=hz * 3 {
        let render_time = frame as f64 / hz as f64;
        while tick <= 360 && tick as f64 / 120. <= render_time {
            let time = tick as f64 / 120.;
            let (ready, input) = schedule(time);
            presentation.sample(time, ready, input);
            roots.push(presentation.offset());
            tick += 1;
        }
        let root = presentation.model_root();
        for _ in 0..5 {
            assert_eq!(presentation.model_root(), root);
        }
    }
    assert_eq!(roots.len(), 361);
    roots
}

#[test]
fn thirty_sixty_and_144_hz_rendering_produce_identical_fixed_tick_roots() {
    let reference = rendered(60);
    assert_eq!(reference, rendered(30));
    assert_eq!(reference, rendered(144));
}

#[test]
fn same_timestamp_freezes_bob_and_residual_even_if_targets_change() {
    let mut presentation = moving();
    let incoming = presentation.offset();
    for (ready, input) in [
        (true, LocomotionInput::default()),
        (false, walk()),
        (false, LocomotionInput::default()),
        (true, walk()),
    ] {
        presentation.sample(1., ready, input);
        assert_eq!(presentation.offset(), incoming);
    }
}

#[test]
fn explicit_reset_and_clock_rewind_remove_both_bob_and_residual() {
    let mut presentation = moving();
    presentation.sample(1., false, walk());
    presentation.reset(0.);
    assert_eq!(presentation.offset(), 0.);
    assert_eq!(presentation.model_root(), game_model_root());
    let mut fresh = AuthoredWalkPresentation::default();
    for time in [0., 0.2, 0.7, 1.] {
        presentation.sample(time, true, walk());
        fresh.sample(time, true, walk());
        assert_eq!(presentation.offset(), fresh.offset());
    }
    presentation.sample(1., false, walk());
    presentation.sample(0., true, walk());
    assert_eq!(presentation.offset(), 0.);
    presentation.sample(1., true, walk());
    assert_eq!(presentation.offset(), moving().offset());
}

#[test]
fn legacy_ads_attenuation_remains_cosmetic_and_finite_input_guards_survive() {
    let mut presentation = moving();
    let aim = LocomotionInput { ads: 1., ..walk() };
    presentation.sample(1., true, aim);
    presentation.sample(1.3, true, aim);
    assert!(presentation.offset().abs() < 0.000001);
    let before = presentation.model_root();
    presentation.sample(f64::NAN, false, walk());
    assert_eq!(presentation.model_root(), before);
    presentation.sample(
        2.,
        true,
        LocomotionInput {
            speed: f32::INFINITY,
            ads: f32::NAN,
            sprint: f32::NAN,
        },
    );
    presentation.sample(3., true, LocomotionInput::default());
    assert!(presentation.offset().is_finite());
    assert!(presentation.offset().abs() < 0.000001);
}

fn authored() -> AnimationSet {
    AnimationSet::load(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/assets/locomotion/asset.vra"
    ))
    .unwrap()
}

fn path(set: &AnimationSet) -> AuthoredLocomotionPath {
    AuthoredLocomotionPath::new(
        set,
        AuthoredLocomotionPathConfig {
            ready_clip: "normal_ready".into(),
            entry_clip: "normal_entry_connected".into(),
            loop_clip: "normal_loop".into(),
            exit_bridge_clips: (0..35)
                .map(|i| format!("normal_exit_bridge_{i:03}"))
                .collect(),
            exit_clip: "normal_exit".into(),
            settle_clip: "normal_settle".into(),
            rate_response_seconds: 0.05,
            residual_decay_seconds: 0.03,
        },
        0.,
    )
    .unwrap()
}

#[test]
fn actual_authored_entry_loop_and_exit_keep_their_original_poses() {
    let set = authored();
    let mut path = path(&set);
    let mut baseline = path.clone();
    let mut presentation = AuthoredWalkPresentation::default();
    let mut seen = Vec::new();
    for tick in 0..=480 {
        let time = tick as f64 / 120.;
        let sprinting = (1.0..2.0).contains(&time);
        path.update(&set, time, sprinting, true).unwrap();
        baseline.update(&set, time, sprinting, true).unwrap();
        presentation.sample(time, path.state() == State::Ready, walk());
        assert_eq!(path.pose(), baseline.pose());
        if path.state() != State::Ready && time >= 1. + WALK_ROOT_TRANSITION_SECONDS {
            assert_eq!(presentation.offset(), 0.);
        }
        if !seen.contains(&path.state()) {
            seen.push(path.state());
        }
    }
    for state in [
        State::Ready,
        State::Entry,
        State::Loop,
        State::ExitBridge,
        State::Exit,
        State::Settle,
    ] {
        assert!(seen.contains(&state), "missing state {state:?}");
    }
}

fn production_shaped_roots(hz: u32, set: &AnimationSet) -> Vec<f32> {
    let mut path = path(set);
    let mut presentation = AuthoredWalkPresentation::default();
    let mut tick = 0;
    let mut output = Vec::new();
    for frame in 0..=hz * 3 {
        let frame_time = frame as f64 / hz as f64;
        while tick < 360 && (tick + 1) as f64 / 120. <= frame_time {
            if tick == 240 {
                // Production F2 reset clears both paths, including an active
                // walking offset, even when the next clock begins at zero.
                path.reset(set, 0.).unwrap();
                presentation.reset(0.);
                assert_eq!(presentation.offset(), 0.);
            }
            let simulation_tick = if tick >= 240 { tick - 240 } else { tick };
            let start = simulation_tick as f64 / 120.;
            let end = (simulation_tick + 1) as f64 / 120.;
            // One-tick sprint/cancel/restart, a full sprint/exit, walk stop,
            // and a later world reset share the same committed input history.
            let sprinting = tick == 60 || (62..140).contains(&tick);
            let input = if (180..216).contains(&tick) {
                LocomotionInput::default()
            } else {
                walk()
            };
            for time in [start, end] {
                path.update(set, time, sprinting, true).unwrap();
                presentation.sample(time, path.state() == State::Ready, input);
            }
            output.push(presentation.offset());
            tick += 1;
        }
        let cached = presentation.model_root();
        assert_eq!(presentation.model_root(), cached);
    }
    assert_eq!(output.len(), 360);
    output
}

#[test]
fn production_start_end_ticks_with_reversal_and_reset_are_render_independent() {
    let set = authored();
    let reference = production_shaped_roots(60, &set);
    assert_eq!(reference, production_shaped_roots(30, &set));
    assert_eq!(reference, production_shaped_roots(144, &set));
}

#[test]
fn skin_and_rigid_actors_receive_the_same_world_displacement_without_pose_edits() {
    let set = authored();
    let pose = set.sample_clamped("normal_ready", 0.).unwrap();
    let unchanged = pose.clone();
    // Synthetic inverse binds isolate root composition; use every real ordered
    // bone/actor binding without requiring the compressed skin companion here.
    let bones: Vec<_> = set
        .bones()
        .iter()
        .map(|bone| Bone {
            name: bone.name.clone(),
            parent: bone.parent,
            rest_local: Mat4::IDENTITY.to_cols_array(),
            inverse_bind: Mat4::IDENTITY.to_cols_array(),
        })
        .collect();
    let presentation = moving();
    let offset = Vec3::new(0., presentation.offset(), 0.);
    let before = set.skin_palette(&pose, &bones, game_model_root()).unwrap();
    let after = set
        .skin_palette(&pose, &bones, presentation.model_root())
        .unwrap();
    let before_actors = set.actor_matrices(&pose, game_model_root()).unwrap();
    let after_actors = set
        .actor_matrices(&pose, presentation.model_root())
        .unwrap();
    for (a, b) in before
        .iter()
        .chain(&before_actors)
        .zip(after.iter().chain(&after_actors))
    {
        for point in [Vec3::ZERO, Vec3::new(0.15, -0.13, 0.21)] {
            assert!(
                (b.transform_point3(point) - a.transform_point3(point) - offset).length()
                    < 0.000001
            );
        }
        assert!((b.transform_vector3(Vec3::Y) - a.transform_vector3(Vec3::Y)).length() < 0.000001);
    }
    assert_eq!(pose, unchanged);
}
