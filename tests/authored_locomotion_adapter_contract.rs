//! Full-pose ownership contracts; synthetic assets contain no private geometry.
use glam::{Mat4, Quat, Vec3};
use vector_range::{
    authored_locomotion_adapter::{
        AuthoredLocomotionAdapter, LocomotionInput, PoseBindings, PresentationAction,
    },
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathConfig},
    skinned_asset::crc32,
    viewmodel_animation::{AnimationSet, Transform},
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
fn encode(clips: &[Clip]) -> Vec<u8> {
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
    bytes
}
fn decode(clips: &[Clip]) -> AnimationSet {
    AnimationSet::decode(&encode(clips)).unwrap()
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

fn adapter(set: &AnimationSet) -> AuthoredLocomotionAdapter {
    AuthoredLocomotionAdapter::new(set, config(), 0.).unwrap()
}
fn sprint() -> LocomotionInput {
    LocomotionInput {
        sprinting: true,
        priority: None,
    }
}
fn action(action: PresentationAction) -> LocomotionInput {
    LocomotionInput {
        sprinting: false,
        priority: Some(action),
    }
}
#[test]
fn event_captures_previous_intent_at_exact_time_and_yields_all_output() {
    let set = decode(&fixture());
    for at in [0., 0.05, 0.249, 0.25, 0.375, 1.2345] {
        for reason in [
            PresentationAction::Reload,
            PresentationAction::Ads,
            PresentationAction::Mantle,
            PresentationAction::Fire,
            PresentationAction::Other,
        ] {
            let mut a = adapter(&set);
            let mut path = AuthoredLocomotionPath::new(&set, config(), 0.).unwrap();
            a.committed_tick(&set, 0., sprint()).unwrap();
            path.update(&set, 0., true, true).unwrap();
            path.update(&set, at, true, true).unwrap();
            let h = a.committed_tick(&set, at, action(reason)).unwrap().unwrap();
            assert_eq!(h.pose(), path.pose());
            assert_eq!(h.simulation_time(), at);
            assert_eq!(h.action(), reason);
            h.validate_receiver(&set).unwrap();
            assert!(a.pose().is_none());
            assert_eq!(a.pending_handoff().unwrap().id(), h.id());
        }
    }
}
#[test]
fn inactive_owner_never_advances_or_restarts_until_explicit_matching_return() {
    let set = decode(&fixture());
    let mut a = adapter(&set);
    a.committed_tick(&set, 0., sprint()).unwrap();
    let h = a
        .committed_tick(&set, 0.125, action(PresentationAction::Reload))
        .unwrap()
        .unwrap();
    for tick in 0..240 {
        let time = 0.125 + tick as f64 / 120.;
        assert!(a
            .committed_tick(&set, time, action(PresentationAction::Ads))
            .unwrap()
            .is_none());
        assert_eq!(a.pending_handoff().unwrap().pose(), h.pose());
        assert!(a.pose().is_none());
    }
    a.committed_tick(&set, 3., sprint()).unwrap();
    assert!(a.pose().is_none());
    let ready = a.ready_pose().clone();
    a.return_ready(&set, h.id(), 3., &ready).unwrap();
    assert_eq!(a.pose().unwrap(), &ready);
    a.committed_tick(&set, 3.125, sprint()).unwrap();
    assert_eq!(
        a.pose().unwrap(),
        &set.sample_clamped("entry", 0.125).unwrap()
    );
}
#[test]
fn return_rejects_changed_full_pose_visibility_stale_id_and_active_priority() {
    let set = decode(&fixture());
    let mut a = adapter(&set);
    a.committed_tick(&set, 0., sprint()).unwrap();
    let h = a
        .committed_tick(&set, 0.125, action(PresentationAction::Reload))
        .unwrap()
        .unwrap();
    let ready = a.ready_pose().clone();
    assert!(a.return_ready(&set, h.id(), 0.125, &ready).is_err());
    a.committed_tick(&set, 1., LocomotionInput::default())
        .unwrap();
    assert!(a.return_ready(&set, h.id() + 1, 1., &ready).is_err());
    assert!(a.return_ready(&set, h.id(), 1.1, &ready).is_err());
    for field in 0..5 {
        let mut bad = ready.clone();
        match field {
            0 => bad.bone_locals[0].translation.x += 0.0000001,
            1 => bad.actor_globals[0].rotation = Quat::from_rotation_y(0.000001),
            2 => bad.actor_visible[0] = false,
            3 => bad.bone_locals[0].scale.x += 0.000001,
            _ => bad.actor_globals.clear(),
        }
        assert!(a.return_ready(&set, h.id(), 1., &bad).is_err());
        assert_eq!(a.pending_handoff().unwrap().pose(), h.pose());
        assert!(a.pose().is_none());
    }
    let mut equivalent = ready.clone();
    equivalent.sample_time = 42.;
    equivalent.bone_locals[0].rotation = -equivalent.bone_locals[0].rotation;
    equivalent.actor_globals[0].rotation = -equivalent.actor_globals[0].rotation;
    a.return_ready(&set, h.id(), 1., &equivalent).unwrap();
    assert_eq!(a.pose().unwrap(), &ready);
}
#[test]
fn explicit_reset_invalidates_old_callbacks_and_never_reuses_ids() {
    let set = decode(&fixture());
    let mut a = adapter(&set);
    let old = a
        .committed_tick(&set, 0.2, action(PresentationAction::Reload))
        .unwrap()
        .unwrap();
    assert!(a.committed_tick(&set, 0., sprint()).is_err());
    assert_eq!(a.pending_handoff().unwrap().id(), old.id());
    a.reset(&set, 0.).unwrap();
    let new = a
        .committed_tick(&set, 0.2, action(PresentationAction::Ads))
        .unwrap()
        .unwrap();
    assert_ne!(old.id(), new.id());
    a.committed_tick(&set, 0.3, LocomotionInput::default())
        .unwrap();
    let ready = a.ready_pose().clone();
    assert!(a.return_ready(&set, old.id(), 0.3, &ready).is_err());
    a.return_ready(&set, new.id(), 0.3, &ready).unwrap();
}
#[test]
fn invalid_times_and_same_time_reads_preserve_complete_pose() {
    let set = decode(&fixture());
    let mut a = adapter(&set);
    a.committed_tick(&set, 0., sprint()).unwrap();
    a.committed_tick(&set, 0.125, sprint()).unwrap();
    let pose = a.pose().unwrap().clone();
    for t in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -1., 0.124] {
        assert!(a
            .committed_tick(&set, t, LocomotionInput::default())
            .is_err());
        assert_eq!(a.pose().unwrap(), &pose);
        assert_eq!(a.simulation_time(), 0.125);
    }
    for _ in 0..100 {
        assert_eq!(a.pose().unwrap(), &pose);
        a.committed_tick(&set, 0.125, sprint()).unwrap();
        assert_eq!(a.pose().unwrap(), &pose);
    }
}
#[test]
fn bindings_reject_same_dimensions_with_different_names_rest_and_companions() {
    fn reframe(mut bytes: Vec<u8>) -> AnimationSet {
        let size = (bytes.len() - 24) as u32;
        let checksum = crc32(&bytes[24..]);
        bytes[12..16].copy_from_slice(&size.to_le_bytes());
        bytes[16..20].copy_from_slice(&checksum.to_le_bytes());
        AnimationSet::decode(&bytes).unwrap()
    }
    let original = encode(&fixture());
    let set = decode(&fixture());
    let bindings = PoseBindings::from_animation(&set);
    let find = |text: &[u8]| {
        original
            .windows(text.len())
            .position(|w| w == text)
            .unwrap()
    };
    let joint = find(b"arbitrary-joint");
    let actor = find(b"arbitrary-socket");
    let mesh_count = actor + b"arbitrary-socket".len();
    assert!(bindings.matches(&decode(&fixture())));
    for variant in 0..6 {
        let mut bytes = original.clone();
        match variant {
            0 => bytes[24..28].copy_from_slice(&1_u32.to_le_bytes()),
            1 => bytes[28..32].copy_from_slice(&1_u32.to_le_bytes()),
            2 => bytes[joint] = b'z',
            3 => bytes[actor] = b'z',
            4 => bytes[mesh_count + 4 + 48..mesh_count + 4 + 52]
                .copy_from_slice(&0.01_f32.to_le_bytes()),
            _ => {
                bytes[mesh_count..mesh_count + 4].copy_from_slice(&1_u32.to_le_bytes());
                bytes.splice(mesh_count + 4..mesh_count + 4, 0_u32.to_le_bytes());
            }
        }
        let foreign = reframe(bytes);
        assert!(!bindings.matches(&foreign));
        let mut a = adapter(&set);
        a.committed_tick(&set, 0., sprint()).unwrap();
        let pose = a.pose().unwrap().clone();
        assert!(a.committed_tick(&foreign, 0.125, sprint()).is_err());
        assert_eq!(a.pose().unwrap(), &pose);
        let h = a
            .committed_tick(&set, 0.125, action(PresentationAction::Reload))
            .unwrap()
            .unwrap();
        assert!(h.validate_receiver(&foreign).is_err());
        a.committed_tick(&set, 1., LocomotionInput::default())
            .unwrap();
        let ready = a.ready_pose().clone();
        assert!(a.return_ready(&foreign, h.id(), 1., &ready).is_err());
        assert!(a.reset(&foreign, 0.).is_err());
        assert!(a.pose().is_none());
        assert_eq!(a.simulation_time(), 1.);
    }
}
#[test]
fn committed_simulation_step_uses_actual_action_start_not_end_of_tick() {
    use glam::Vec2;
    use vector_range::{
        settings::Settings,
        sim::{Input, Simulation, FIXED_DT},
    };
    let set = decode(&fixture());
    let cfg = Settings::default();
    for reason in [PresentationAction::Reload, PresentationAction::Ads] {
        let mut sim = Simulation::new();
        let mut a = adapter(&set);
        let mut expected = AuthoredLocomotionPath::new(&set, config(), 0.).unwrap();
        expected.update(&set, 0., true, true).unwrap();
        let run = Input {
            movement: Vec2::Y,
            sprint: true,
            ..Input::default()
        };
        for _ in 0..40 {
            let start = sim.time;
            sim.update(run, &cfg, FIXED_DT);
            assert!(a.committed_step(&set, start, &sim).unwrap().is_none());
        }
        let start = sim.time;
        expected.update(&set, start, true, true).unwrap();
        sim.player.ammo = 2;
        sim.update(
            Input {
                reload: reason == PresentationAction::Reload,
                ads: reason == PresentationAction::Ads,
                ..Input::default()
            },
            &cfg,
            FIXED_DT,
        );
        let h = a.committed_step(&set, start, &sim).unwrap().unwrap();
        assert_eq!(h.simulation_time(), start);
        assert_eq!(h.pose(), expected.pose());
        assert_eq!(h.action(), reason);
        assert_eq!(a.simulation_time(), sim.time);
        assert!(a.pose().is_none());
        if reason == PresentationAction::Reload {
            assert_eq!(sim.player.reload_ready_at, start + cfg.reload_time as f64);
            assert_eq!(sim.player.reload_left, cfg.reload_time);
        } else {
            assert!(sim.player.ads > 0.);
        }
    }
}
#[test]
fn adapter_cannot_delay_reload_credit_ready_or_firing() {
    use vector_range::{
        settings::Settings,
        sim::{Input, Simulation, FIXED_DT},
    };
    let set = decode(&fixture());
    let cfg = Settings::default();
    let mut sim = Simulation::new();
    let mut baseline = Simulation::new();
    sim.player.ammo = 2;
    baseline.player.ammo = 2;
    let mut a = adapter(&set);
    let mut first = None;
    for tick in 0..500 {
        let input = Input {
            reload: tick == 0,
            fire: tick > 0,
            ..Input::default()
        };
        let start = sim.time;
        sim.update(input, &cfg, FIXED_DT);
        baseline.update(input, &cfg, FIXED_DT);
        let handoff = a.committed_step(&set, start, &sim).unwrap();
        if tick == 0 {
            first = handoff;
        } else {
            assert!(handoff.is_none());
        }
        assert_eq!(sim.time, baseline.time);
        assert_eq!(sim.player.ammo, baseline.player.ammo);
        assert_eq!(sim.player.reserve, baseline.player.reserve);
        assert_eq!(
            sim.player.reload_credit_at,
            baseline.player.reload_credit_at
        );
        assert_eq!(sim.player.reload_ready_at, baseline.player.reload_ready_at);
        assert_eq!(sim.player.reload_left, baseline.player.reload_left);
        assert_eq!(sim.stats.shots, baseline.stats.shots);
        assert_eq!(sim.player.last_shot_at, baseline.player.last_shot_at);
    }
    let h = first.unwrap();
    assert_eq!(h.action(), PresentationAction::Reload);
    assert_eq!(h.simulation_time(), 0.);
    assert!(sim.stats.shots > 0);
    assert!(a.pose().is_none());
}
#[test]
fn committed_step_rejects_skipped_rewound_and_invalid_ticks_atomically() {
    use vector_range::sim::Simulation;
    let set = decode(&fixture());
    let mut sim = Simulation::new();
    let mut a = adapter(&set);
    let ready = a.pose().unwrap().clone();
    for (start, end) in [(0.1, 0.2), (0., -1.), (0., f64::NAN), (0., f64::INFINITY)] {
        sim.time = end;
        assert!(a.committed_step(&set, start, &sim).is_err());
        assert_eq!(a.pose().unwrap(), &ready);
        assert_eq!(a.simulation_time(), 0.);
    }
}
