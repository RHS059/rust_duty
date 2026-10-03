//! Synthetic connected-path contracts; no private rigs or baked motion.
pub use vector_range::viewmodel_animation;
#[path = "../src/authored_locomotion_path.rs"]
mod authored_locomotion_path;
use authored_locomotion_path::{
    AuthoredLocomotionPath, AuthoredLocomotionPathConfig, AuthoredLocomotionPathState as State,
};
use macroquad::math::{Mat4, Quat, Vec3};
use vector_range::{
    skinned_asset::crc32,
    viewmodel_animation::{AnimationSet, Transform, ViewmodelPose},
};
#[derive(Clone)]
struct Clip {
    name: &'static str,
    looping: bool,
    frames: Vec<(f32, Transform, bool)>,
}
fn transform(x: f32) -> Transform {
    Transform {
        translation: Vec3::new(x * 0.001, x * 0.0003, 0.),
        rotation: Quat::from_rotation_y(x * 0.01),
        scale: Vec3::new(1. + x * 0.0001, 1., 1.),
    }
}
fn clip(name: &'static str, looping: bool, values: &[(f32, f32)]) -> Clip {
    Clip {
        name,
        looping,
        frames: values
            .iter()
            .map(|&(t, x)| (t, transform(x), true))
            .collect(),
    }
}
fn fixture() -> Vec<Clip> {
    vec![
        clip("ready", false, &[(0., 0.)]),
        clip("entry", false, &[(0., 0.), (0.25, 2.)]),
        clip(
            "loop",
            true,
            &[
                (0., 2.),
                (0.125, 3.25),
                (0.25, 4.),
                (0.5, 2.),
                (0.75, 0.),
                (1., 2.),
            ],
        ),
        clip("bridge0", false, &[(0., 2.), (0.125, 6.)]),
        clip("bridge1", false, &[(0., 4.), (0.125, 6.)]),
        clip("bridge2", false, &[(0., 2.), (0.125, 6.)]),
        clip("bridge3", false, &[(0., 0.), (0.125, 6.)]),
        clip("exit", false, &[(0., 6.), (0.25, 8.)]),
        clip("settle", false, &[(0., 8.), (0.125, 0.)]),
    ]
}
fn number(bytes: &mut Vec<u8>, value: u32) {
    bytes.extend(value.to_le_bytes());
}
fn name(bytes: &mut Vec<u8>, text: &str) {
    bytes.extend((text.len() as u16).to_le_bytes());
    bytes.extend(text.as_bytes());
}
fn floats(bytes: &mut Vec<u8>, values: &[f32]) {
    for value in values {
        bytes.extend(value.to_le_bytes());
    }
}
fn trs(bytes: &mut Vec<u8>, value: Transform) {
    floats(bytes, &value.translation.to_array());
    floats(bytes, &value.rotation.to_array());
    floats(bytes, &value.scale.to_array());
}
fn decode(clips: &[Clip]) -> AnimationSet {
    let mut payload = Vec::new();
    number(&mut payload, 0); // Synthetic companion checksums.
    number(&mut payload, 0);
    number(&mut payload, 1);
    name(&mut payload, "arbitrary-joint");
    number(&mut payload, u32::MAX);
    number(&mut payload, 1);
    name(&mut payload, "arbitrary-socket");
    number(&mut payload, 0);
    floats(&mut payload, &Mat4::IDENTITY.to_cols_array());
    number(&mut payload, clips.len() as u32);
    for clip in clips {
        name(&mut payload, clip.name);
        number(&mut payload, u32::from(clip.looping));
        number(&mut payload, clip.frames.len() as u32);
        for &(time, value, visible) in &clip.frames {
            floats(&mut payload, &[time]);
            trs(&mut payload, value);
            trs(&mut payload, value);
            payload.push(u8::from(visible));
        }
    }
    let mut bytes = b"VRANIM01".to_vec();
    number(&mut bytes, 1);
    number(&mut bytes, payload.len() as u32);
    number(&mut bytes, crc32(&payload));
    number(&mut bytes, 0);
    bytes.extend(payload);
    AnimationSet::decode(&bytes).unwrap()
}
fn config() -> AuthoredLocomotionPathConfig {
    AuthoredLocomotionPathConfig {
        ready_clip: "ready".into(),
        entry_clip: "entry".into(),
        loop_clip: "loop".into(),
        exit_bridge_clips: (0..4).map(|n| format!("bridge{n}")).collect(),
        exit_clip: "exit".into(),
        settle_clip: "settle".into(),
        rate_response_seconds: 0.0625,
        residual_decay_seconds: 0.03,
    }
}
fn controller(set: &AnimationSet) -> AuthoredLocomotionPath {
    AuthoredLocomotionPath::new(set, config(), 0.).unwrap()
}
fn close(a: &ViewmodelPose, b: &ViewmodelPose) {
    for (a, b) in a
        .bone_locals
        .iter()
        .chain(&a.actor_globals)
        .zip(b.bone_locals.iter().chain(&b.actor_globals))
    {
        assert!(
            (a.translation - b.translation).length() < 1e-7,
            "{a:?} != {b:?}"
        );
        assert!(a.rotation.dot(b.rotation).abs() > 1. - 1e-6);
        assert!((a.scale - b.scale).abs().max_element() < 1e-6);
    }
    assert_eq!(a.actor_visible, b.actor_visible);
}
#[test]
fn forward_path_uses_decoded_durations_and_exact_native_joins() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    c.update(&set, 0., true, true).unwrap();
    assert_eq!(c.state(), State::Entry);
    for time in [0., 0.125, 0.25] {
        c.update(&set, time, true, true).unwrap();
        close(c.pose(), &set.sample_clamped("entry", time as f32).unwrap());
    }
    assert_eq!(c.state(), State::Loop);
    c.update(&set, 0.5, false, true).unwrap();
    assert_eq!(c.state(), State::ExitBridge);
    close(c.pose(), &set.sample("loop", 0.25).unwrap());
    c.update(&set, 0.625, false, true).unwrap();
    assert_eq!(c.state(), State::Exit);
    close(c.pose(), &set.sample("exit", 0.).unwrap());
    c.update(&set, 0.875, false, true).unwrap();
    assert_eq!(c.state(), State::Settle);
    close(c.pose(), &set.sample("settle", 0.).unwrap());
    c.update(&set, 1., false, true).unwrap();
    assert_eq!(c.state(), State::Ready);
    close(c.pose(), &set.sample("ready", 0.).unwrap());
}
#[test]
fn stopping_entry_reverses_the_same_path_with_continuous_rate() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    c.update(&set, 0., true, true).unwrap();
    c.update(&set, 0.125, true, true).unwrap();
    let before = c.pose().clone();
    let rate = c.playback_rate();
    c.update(&set, 0.125, false, true).unwrap();
    assert_eq!(c.pose(), &before);
    assert_eq!(c.playback_rate(), rate);
    c.update(&set, 0.15, false, true).unwrap();
    assert!(c.playback_rate() > 0. && c.playback_rate() < 1.);
    c.update(&set, 0.2, false, true).unwrap();
    assert!(c.playback_rate() < 0. && c.playback_rate() > -1.);
    assert_eq!(c.state(), State::Entry);
    c.update(&set, 1., false, true).unwrap();
    assert_eq!(c.state(), State::Ready);
}
#[test]
fn restarting_exit_retraces_bridge_and_preserves_negative_loop_rate() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    c.update(&set, 0., true, true).unwrap();
    c.update(&set, 0.5, false, true).unwrap();
    c.update(&set, 0.5625, true, true).unwrap();
    assert_eq!(c.playback_rate(), 1.);
    let mut observed = false;
    for tick in 1..100 {
        let t = 0.5625 + tick as f64 / 1000.;
        c.update(&set, t, true, true).unwrap();
        if c.state() == State::Loop {
            assert!(
                c.playback_rate() < 0.,
                "reverse bridge must not snap loop rate to +1"
            );
            observed = true;
            break;
        }
    }
    // The decelerating path initially continues forward; enough time must be
    // allowed to travel back through its captured bridge.
    if !observed {
        for tick in 100..300 {
            let t = 0.5625 + tick as f64 / 1000.;
            c.update(&set, t, true, true).unwrap();
            if c.state() == State::Loop {
                assert!(c.playback_rate() < 0.);
                observed = true;
                break;
            }
        }
    }
    assert!(observed);
}
#[test]
fn stop_during_backward_loop_decelerates_then_starts_bridge_within_49ms() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    c.update(&set, 0., true, true).unwrap();
    c.update(&set, 0.5, false, true).unwrap();
    c.update(&set, 0.5625, true, true).unwrap();
    let mut stopped_at = None;
    for tick in 1..300 {
        let t = 0.5625 + tick as f64 / 1000.;
        c.update(&set, t, true, true).unwrap();
        if c.state() == State::Loop && c.playback_rate() < 0. {
            let before = c.pose().clone();
            let rate = c.playback_rate();
            c.update(&set, t, false, true).unwrap();
            assert_eq!(c.pose(), &before);
            assert_eq!(c.playback_rate(), rate);
            assert_eq!(c.state(), State::Loop);
            stopped_at = Some(t);
            break;
        }
    }
    let t = stopped_at.expect("reverse loop reached");
    c.update(&set, t + 0.049, false, true).unwrap();
    assert_eq!(c.state(), State::ExitBridge);
    assert!(c.playback_rate() >= 0.);
}
fn partitioned(hz: u32) -> Vec<(State, f64, ViewmodelPose)> {
    let set = decode(&fixture());
    let mut c = controller(&set);
    let events = [
        (0., true),
        (0.1, false),
        (0.125, true),
        (0.6, false),
        (0.66, true),
        (0.86, false),
        (0.875, true),
        (1.4, false),
        (1.78, true),
        (1.82, false),
        (2.2, true),
    ];
    let probes = [
        0., 0.1, 0.125, 0.25, 0.4, 0.6, 0.66, 0.7, 0.8, 0.86, 0.875, 0.9, 1.1, 1.4, 1.6, 1.78,
        1.82, 2., 2.2, 3.,
    ];
    let mut times: Vec<f64> = (0..=3 * hz).map(|i| i as f64 / hz as f64).collect();
    times.extend(events.iter().map(|e| e.0));
    times.extend(probes);
    times.sort_by(f64::total_cmp);
    times.dedup();
    let mut results = Vec::new();
    for time in times {
        let sprint = events.iter().rev().find(|e| e.0 <= time).unwrap().1;
        c.update(&set, time, sprint, true).unwrap();
        if probes.contains(&time) {
            results.push((c.state(), c.playback_rate(), c.pose().clone()));
        }
    }
    results
}
#[test]
fn input_and_boundary_anchoring_make_tick_partitions_identical() {
    let expected = partitioned(120);
    for hz in [1, 30, 60, 144, 240] {
        for (a, b) in expected.iter().zip(partitioned(hz)) {
            assert_eq!(a.0, b.0, "{hz} Hz state");
            assert_eq!(a.1, b.1, "{hz} Hz rate");
            assert_eq!(&a.2, &b.2, "{hz} Hz pose");
        }
    }
}
#[test]
fn bridge_join_reports_native_discrepancy_and_corrects_only_the_small_seam() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    c.update(&set, 0., true, true).unwrap();
    c.update(&set, 0.375, true, true).unwrap();
    let exact = c.pose().clone();
    c.update(&set, 0.375, false, true).unwrap();
    let error = c.last_bridge_join_error().unwrap();
    assert!(error.max_bone_local_translation_m > 0.0002);
    assert!(error.max_actor_global_translation_m > 0.0002);
    assert_eq!(
        c.pose(),
        &exact,
        "zero bridge progress preserves the exact cached source"
    );
}
#[test]
fn reset_pause_invalid_input_and_render_reads_do_not_invent_history() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    c.update(&set, 0., true, true).unwrap();
    c.update(&set, 0.1, true, true).unwrap();
    let before = c.pose().clone();
    for wanted in [false, true, false, true] {
        c.update(&set, 0.1, wanted, true).unwrap();
        assert_eq!(c.pose(), &before);
    }
    for _ in 0..50 {
        assert_eq!(c.pose(), &before);
    }
    for bad in [f64::NAN, f64::INFINITY, -0.1] {
        assert!(c.update(&set, bad, false, true).is_err());
        assert_eq!(c.pose(), &before);
    }
    assert_eq!(c.simulation_time(), 0.1);
    c.update(&set, 0., false, true).unwrap();
    assert_eq!(c.state(), State::Ready);
    c.update(&set, 0., true, true).unwrap();
    c.reset(&set, 0.).unwrap();
    assert_eq!(c.state(), State::Ready);
}
#[test]
fn invalid_paths_are_rejected_at_construction() {
    let set = decode(&fixture());
    for tau in [0., -0.1, 0.071, f64::NAN, f64::INFINITY] {
        let mut cfg = config();
        cfg.rate_response_seconds = tau;
        assert!(AuthoredLocomotionPath::new(&set, cfg, 0.).is_err());
    }
    for index in [1, 2, 3, 4, 5, 6, 7, 8] {
        let mut clips = fixture();
        clips[index].frames.last_mut().unwrap().1.translation.x += 0.01;
        assert!(AuthoredLocomotionPath::new(&decode(&clips), config(), 0.).is_err());
    }
}

#[test]
fn residual_caps_reject_before_changing_state_pose_or_intent() {
    for component in 0..4 {
        let mut clips = fixture();
        let mid = &mut clips[2].frames[1];
        match component {
            0 => mid.1.translation.x += 0.003,
            1 => mid.1.rotation = Quat::from_rotation_y(0.5),
            2 => mid.1.scale.x += 0.001,
            _ => mid.2 = false,
        }
        let set = decode(&clips);
        let mut c = controller(&set);
        c.update(&set, 0., true, true).unwrap();
        c.update(&set, 0.375, true, true).unwrap();
        let before = c.clone();
        let error = c.update(&set, 0.375, false, true).unwrap_err().to_string();
        assert!(error.contains("residual exceeds"), "{error}");
        assert_eq!(c.pose(), before.pose());
        assert_eq!(c.state(), before.state());
        assert_eq!(c.playback_rate(), before.playback_rate());
        assert_eq!(c.simulation_time(), before.simulation_time());
        assert_eq!(c.last_bridge_join_error(), before.last_bridge_join_error());
        let mut expected = before;
        expected.update(&set, 0.5, true, true).unwrap();
        c.update(&set, 0.5, true, true).unwrap();
        assert_eq!(
            c.pose(),
            expected.pose(),
            "failed stop must not change intent"
        );
    }
}

#[test]
fn residual_expires_by_progress_and_retraces_the_identical_corrected_curve() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    c.update(&set, 0., true, true).unwrap();
    c.update(&set, 0.375, false, true).unwrap();
    let mut forward = c.clone();
    forward.update(&set, 0.40625, false, true).unwrap();
    let native = set
        .blend_poses(
            &set.sample("bridge0", 0.03125).unwrap(),
            &set.sample("bridge1", 0.03125).unwrap(),
            0.5,
        )
        .unwrap();
    assert_eq!(
        forward.pose(),
        &native,
        "after 0.03 progress only native bridge remains"
    );
    c.update(&set, 0.390625, false, true).unwrap();
    let reference = c.pose().clone();
    c.update(&set, 0.390625, true, true).unwrap();
    assert_eq!(c.pose(), &reference);
    // At restart the rate is +1 and the target is -1. Find the later time
    // where -dt + 2*tau*(1-exp(-dt/tau)) returns to the same path position.
    let tau = config().rate_response_seconds;
    let mut low: f64 = 0.02;
    let mut high: f64 = 0.3;
    for _ in 0..80 {
        let middle = (low + high) * 0.5;
        if -middle + 2. * tau * -(-middle / tau).exp_m1() > 0. {
            low = middle;
        } else {
            high = middle;
        }
    }
    c.update(&set, 0.390625 + (low + high) * 0.5, true, true)
        .unwrap();
    assert_eq!(c.state(), State::ExitBridge);
    assert!(c.playback_rate() < 0.);
    close(c.pose(), &reference);
}

#[test]
fn restart_during_settle_retraces_exit_instead_of_starting_new_entry() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    c.update(&set, 0., true, true).unwrap();
    c.update(&set, 0.5, false, true).unwrap();
    c.update(&set, 0.90625, true, true).unwrap();
    assert_eq!(c.state(), State::Settle);
    let mut saw_reverse_exit = false;
    for tick in 1..1000 {
        c.update(&set, 0.90625 + tick as f64 / 1000., true, true)
            .unwrap();
        assert_ne!(c.state(), State::Entry);
        if c.state() == State::Exit && c.playback_rate() < 0. {
            saw_reverse_exit = true;
        }
        if c.state() == State::Loop {
            break;
        }
    }
    assert!(saw_reverse_exit);
    assert_eq!(c.state(), State::Loop);
    assert!(c.playback_rate() < 0.);
}

#[test]
fn rapid_input_changes_keep_rates_bounded_and_disabled_reaches_ready() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    for tick in 0..800 {
        c.update(&set, tick as f64 / 1000., tick % 7 < 4, true)
            .unwrap();
        assert!(c.playback_rate().is_finite() && c.playback_rate().abs() <= 1. + 1e-12);
        for value in c.pose().bone_locals.iter().chain(&c.pose().actor_globals) {
            assert!(value.translation.is_finite() && value.rotation.is_finite());
            assert!(value.scale.min_element() > 0.);
        }
    }
    c.update(&set, 1., true, false).unwrap();
    c.update(&set, 5., true, false).unwrap();
    assert_eq!(c.state(), State::Ready);
    assert_eq!(c.playback_rate(), 0.);
}

#[test]
fn very_large_finite_clock_remains_valid_and_reset_does_not_keep_old_phase() {
    let set = decode(&fixture());
    let mut c = controller(&set);
    c.update(&set, 0., true, true).unwrap();
    c.update(&set, f64::MAX, true, true).unwrap();
    assert_eq!(c.state(), State::Loop);
    assert_eq!(c.playback_rate(), 1.);
    for value in c.pose().bone_locals.iter().chain(&c.pose().actor_globals) {
        assert!(
            value.translation.is_finite() && value.rotation.is_finite() && value.scale.is_finite()
        );
    }
    c.update(&set, f64::MAX, false, true).unwrap();
    assert_eq!(
        c.state(),
        State::ExitBridge,
        "same timestamp cannot finish the exit"
    );
    c.update(&set, 0., true, true).unwrap();
    assert_eq!(c.state(), State::Entry);
    assert_eq!(c.pose(), &set.sample("ready", 0.).unwrap());
}
