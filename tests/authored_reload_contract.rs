use vector_range::{
    authored_reload::{AuthoredReload, ReloadSlot},
    settings::Settings,
    sim::{Input, Simulation},
};

fn tick(sim: &mut Simulation, view: &mut AuthoredReload, input: Input, cfg: &Settings, dt: f32) {
    let start = sim.time;
    sim.update(input, cfg, dt);
    view.committed_step(start, sim).unwrap();
}
#[test]
fn r_accepted_once_plays_native_seconds_and_exits_without_changing_gameplay() {
    let cfg = Settings::m4_candidate();
    let mut sim = Simulation::new();
    sim.player.ammo = 12;
    let mut view = AuthoredReload::new(0.1, Some(0.2)).unwrap();
    let mut baseline = Simulation::new();
    baseline.player.ammo = 12;
    for index in 0..600 {
        let input = Input {
            reload: index == 0,
            ..Input::default()
        };
        baseline.update(input, &cfg, 1. / 120.);
        tick(&mut sim, &mut view, input, &cfg, 1. / 120.);
        assert_eq!(sim.player.ammo, baseline.player.ammo);
        assert_eq!(sim.player.reserve, baseline.player.reserve);
        assert_eq!(sim.player.reload_ready_at, baseline.player.reload_ready_at);
        assert_eq!(
            sim.player.reload_credit_at,
            baseline.player.reload_credit_at
        );
        if index == 0 {
            let sample = view.sample().unwrap();
            assert_eq!(sample.slot, ReloadSlot::Tactical);
            assert!((sample.seconds - 1. / 120.).abs() < 1e-6);
        }
        if index == 60 {
            assert_eq!(view.sample().unwrap().seconds, 0.1);
        }
    }
    assert!(view.sample().is_none());
}
#[test]
fn full_magazine_rejected_r_does_not_play() {
    let mut sim = Simulation::new();
    let mut view = AuthoredReload::new(10., Some(10.)).unwrap();
    tick(
        &mut sim,
        &mut view,
        Input {
            reload: true,
            ..Input::default()
        },
        &Settings::m4_candidate(),
        1. / 120.,
    );
    assert!(view.sample().is_none());
}
#[test]
fn empty_reload_native_tail_pause_and_reset() {
    let mut sim = Simulation::new();
    sim.player.ammo = 0;
    let mut view = AuthoredReload::new(10., Some(10.)).unwrap();
    let cfg = Settings::m4_candidate();
    tick(
        &mut sim,
        &mut view,
        Input {
            reload: true,
            ..Input::default()
        },
        &cfg,
        1. / 120.,
    );
    assert_eq!(view.sample().unwrap().slot, ReloadSlot::Empty);
    let paused = view.sample();
    view.committed_step(sim.time, &sim).unwrap();
    assert_eq!(view.sample(), paused);
    for _ in 0..600 {
        tick(&mut sim, &mut view, Input::default(), &cfg, 1. / 120.);
    }
    assert_eq!(sim.player.reload_left, 0.);
    assert!(view.sample().unwrap().seconds > 5.);
    sim.reset();
    view.reset(sim.time);
    assert!(view.sample().is_none());
}
#[test]
fn missing_empty_slot_is_explicit_and_never_plays_tactical() {
    let mut sim = Simulation::new();
    sim.player.ammo = 0;
    let mut view = AuthoredReload::new(2.6026, None).unwrap();
    tick(
        &mut sim,
        &mut view,
        Input {
            reload: true,
            ..Input::default()
        },
        &Settings::m4_candidate(),
        1. / 120.,
    );
    assert!(view.sample().is_none());
    assert_eq!(view.missing_slot(), Some(ReloadSlot::Empty));
    assert!(sim.player.reload_left > 0.);
}
#[test]
fn repeated_r_and_sprint_cancel_preserve_authority() {
    let mut sim = Simulation::new();
    sim.player.ammo = 12;
    let mut view = AuthoredReload::new(2.6026, None).unwrap();
    let cfg = Settings::m4_candidate();
    let reload = Input {
        reload: true,
        ..Input::default()
    };
    tick(&mut sim, &mut view, reload, &cfg, 1. / 120.);
    let first = view.sample().unwrap().seconds;
    tick(&mut sim, &mut view, reload, &cfg, 1. / 120.);
    assert!(view.sample().unwrap().seconds > first);
    tick(
        &mut sim,
        &mut view,
        Input {
            movement: macroquad::math::Vec2::Y,
            sprint: true,
            ..Input::default()
        },
        &cfg,
        1. / 120.,
    );
    assert_eq!(sim.player.reload_left, 0.);
    assert!(view.sample().is_none());
}

fn synthetic_clip(looping: bool) -> vector_range::viewmodel_animation::AnimationSet {
    fn word(out: &mut Vec<u8>, value: u32) {
        out.extend(value.to_le_bytes());
    }
    fn name(out: &mut Vec<u8>, value: &str) {
        out.extend((value.len() as u16).to_le_bytes());
        out.extend(value.as_bytes());
    }
    let mut payload = Vec::new();
    word(&mut payload, 0);
    word(&mut payload, 0);
    word(&mut payload, 1);
    name(&mut payload, "synthetic");
    word(&mut payload, u32::MAX);
    word(&mut payload, 0); // no rigid actors
    word(&mut payload, 1);
    name(&mut payload, "revision_any_name");
    word(&mut payload, u32::from(looping));
    word(&mut payload, 2);
    for time in [0_f32, 2.] {
        for value in [time, time, 0., 0., 0., 0., 0., 1., 1., 1., 1.] {
            payload.extend(value.to_le_bytes());
        }
    }
    let mut bytes = b"VRANIM01".to_vec();
    word(&mut bytes, 1);
    word(&mut bytes, payload.len() as u32);
    word(&mut bytes, vector_range::skinned_asset::crc32(&payload));
    word(&mut bytes, 0);
    bytes.extend(payload);
    vector_range::viewmodel_animation::AnimationSet::decode(&bytes).unwrap()
}
#[test]
fn synthetic_named_clip_samples_native_pose_and_rejects_missing_or_looping() {
    let set = synthetic_clip(false);
    assert_eq!(
        AuthoredReload::clip_duration(&set, "revision_any_name").unwrap(),
        2.
    );
    let pose = set.sample_clamped("revision_any_name", 0.5).unwrap();
    assert!((pose.bone_locals[0].translation.x - 0.5).abs() < 1e-6);
    assert!(AuthoredReload::clip_duration(&set, "missing_required").is_err());
    assert!(AuthoredReload::clip_duration(&synthetic_clip(true), "revision_any_name").is_err());
}
