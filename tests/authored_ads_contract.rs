//! Simulation commits drive the same ADS controller used by the native renderer.
use macroquad::math::{vec3, Vec2};
use vector_range::{
    animation_manifest::AdsReference,
    authored_ads::{AdsSlot, AuthoredAds},
    settings::Settings,
    sim::{Aabb, Block, Input, Simulation, FIXED_DT},
    viewmodel_animation::AnimationSet,
};

fn clips() -> AdsReference {
    AdsReference {
        asset: "test.vra".into(),
        entry_clip: "entry".into(),
        hold_clip: "hold".into(),
        exit_clip: "exit".into(),
    }
}
fn animation(hold_moves: bool, disconnected: bool, bad_loop: bool) -> AnimationSet {
    animation_named(hold_moves, disconnected, bad_loop, "canonical")
}
fn animation_named(
    hold_moves: bool,
    disconnected: bool,
    bad_loop: bool,
    bone: &str,
) -> AnimationSet {
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
    name(&mut payload, bone);
    word(&mut payload, u32::MAX);
    word(&mut payload, 0);
    word(&mut payload, 4);
    for (clip, looping, duration, from, to) in [
        ("ready", true, 1., 0., 0.),
        (
            "entry",
            bad_loop,
            0.25,
            if disconnected { 0.1 } else { 0. },
            1.,
        ),
        ("hold", true, 1., 1., if hold_moves { 1.1 } else { 1. }),
        ("exit", false, 0.2, 1., 0.),
    ] {
        name(&mut payload, clip);
        word(&mut payload, u32::from(looping));
        word(&mut payload, 2);
        for (time, x) in [(0_f32, from), (duration, to)] {
            for value in [time, x, 0., 0., 0., 0., 0., 1., 1., 1., 1.] {
                payload.extend(value.to_le_bytes());
            }
        }
    }
    let mut bytes = b"VRANIM01".to_vec();
    word(&mut bytes, 1);
    word(&mut bytes, payload.len() as u32);
    word(&mut bytes, vector_range::skinned_asset::crc32(&payload));
    word(&mut bytes, 0);
    bytes.extend(payload);
    AnimationSet::decode(&bytes).unwrap()
}
fn fixture() -> (AnimationSet, AuthoredAds, Simulation) {
    let set = animation(false, false, false);
    let ads = AuthoredAds::new(&set, &set, "ready", clips()).unwrap();
    (set, ads, Simulation::new())
}
fn tick(sim: &mut Simulation, ads: &mut AuthoredAds, input: Input, cfg: &Settings) {
    let start = sim.time;
    sim.update(input, cfg, FIXED_DT);
    ads.committed_step(start, sim, false, true).unwrap();
}
fn aim() -> Input {
    Input {
        ads: true,
        ..Input::default()
    }
}
fn pose_x(set: &AnimationSet, ads: &AuthoredAds) -> f32 {
    ads.pose(set)
        .unwrap()
        .map_or(0., |p| p.bone_locals[0].translation.x)
}
#[test]
fn accepted_aim_runs_native_entry_hold_exit_independent_of_gameplay_timing() {
    for cfg in [Settings::default(), Settings::m4_candidate()] {
        let (set, mut ads, mut sim) = fixture();
        let mut baseline = Simulation::new();
        let mut reached_hold = false;
        let mut reached_exit = false;
        for index in 0..160 {
            let input = if index < 90 { aim() } else { Input::default() };
            baseline.update(input, &cfg, FIXED_DT);
            tick(&mut sim, &mut ads, input, &cfg);
            assert_eq!(sim.player.ads, baseline.player.ads);
            assert_eq!(sim.player.ads_requested, baseline.player.ads_requested);
            assert_eq!(sim.player.ammo, baseline.player.ammo);
            assert_eq!(sim.player.position, baseline.player.position);
            if index == 0 {
                let sample = ads.sample().unwrap();
                assert_eq!(sample.slot, AdsSlot::Entry);
                assert!((sample.seconds - f64::from(FIXED_DT)).abs() < 1e-9);
                assert!((pose_x(&set, &ads) - FIXED_DT / 0.25).abs() < 1e-6);
            }
            reached_hold |= ads
                .sample()
                .is_some_and(|sample| sample.slot == AdsSlot::Hold);
            reached_exit |= ads
                .sample()
                .is_some_and(|sample| sample.slot == AdsSlot::Exit);
        }
        assert!(reached_hold && reached_exit);
        assert!(ads.sample().is_none());
        assert_eq!(pose_x(&set, &ads), 0.);
    }
}
#[test]
fn rapid_entry_release_and_reentry_retrace_current_source_pose() {
    let (set, mut ads, mut sim) = fixture();
    let cfg = Settings::m4_candidate();
    for _ in 0..12 {
        tick(&mut sim, &mut ads, aim(), &cfg);
    }
    let before = ads.sample().unwrap();
    let before_x = pose_x(&set, &ads);
    tick(&mut sim, &mut ads, Input::default(), &cfg);
    let reversed = ads.sample().unwrap();
    assert_eq!(reversed.slot, AdsSlot::Entry);
    assert_eq!(reversed.direction, -1);
    assert!((reversed.seconds - (before.seconds - f64::from(FIXED_DT))).abs() < 1e-9);
    assert!((pose_x(&set, &ads) - (before_x - FIXED_DT / 0.25)).abs() < 1e-6);
    tick(&mut sim, &mut ads, aim(), &cfg);
    assert_eq!(ads.sample().unwrap(), before);
    assert!((pose_x(&set, &ads) - before_x).abs() < 1e-6);
}
#[test]
fn exit_reversal_returns_to_hold_without_restart_or_cross_clip_jump() {
    let (set, mut ads, mut sim) = fixture();
    let cfg = Settings::m4_candidate();
    for _ in 0..60 {
        tick(&mut sim, &mut ads, aim(), &cfg);
    }
    for _ in 0..9 {
        tick(&mut sim, &mut ads, Input::default(), &cfg);
    }
    let before = ads.sample().unwrap();
    let before_x = pose_x(&set, &ads);
    tick(&mut sim, &mut ads, aim(), &cfg);
    let reversed = ads.sample().unwrap();
    assert_eq!(reversed.slot, AdsSlot::Exit);
    assert_eq!(reversed.direction, -1);
    assert!((reversed.seconds - (before.seconds - f64::from(FIXED_DT))).abs() < 1e-9);
    assert!((pose_x(&set, &ads) - (before_x + FIXED_DT / 0.2)).abs() < 1e-6);
    for _ in 0..30 {
        tick(&mut sim, &mut ads, aim(), &cfg);
    }
    assert_eq!(ads.sample().unwrap().slot, AdsSlot::Hold);
    assert_eq!(pose_x(&set, &ads), 1.);
}
#[test]
fn rejected_aim_during_reload_does_not_start_and_native_reload_tail_keeps_priority() {
    let (_, mut ads, mut sim) = fixture();
    let cfg = Settings::m4_candidate();
    sim.player.ammo = 12;
    for _ in 0..60 {
        tick(&mut sim, &mut ads, aim(), &cfg);
    }
    tick(
        &mut sim,
        &mut ads,
        Input {
            reload: true,
            ..aim()
        },
        &cfg,
    );
    assert!(sim.player.reload_left > 0.);
    assert!(!sim.player.ads_requested);
    assert!(ads.sample().is_none());
    for _ in 0..300 {
        let start = sim.time;
        sim.update(aim(), &cfg, FIXED_DT);
        ads.committed_step(start, &sim, true, true).unwrap();
        assert!(ads.sample().is_none());
    }
    assert_eq!(sim.player.reload_left, 0.);
    assert!(sim.player.ads_requested);
    tick(&mut sim, &mut ads, aim(), &cfg);
    assert_eq!(ads.sample().unwrap().slot, AdsSlot::Entry);
}
#[test]
fn fire_preserves_authored_aim_and_actual_shots_and_reload_rejection_do_not_restart_it() {
    let (_, mut ads, mut sim) = fixture();
    let cfg = Settings::m4_candidate();
    for _ in 0..60 {
        tick(&mut sim, &mut ads, aim(), &cfg);
    }
    let before = ads.sample().unwrap().seconds;
    tick(
        &mut sim,
        &mut ads,
        Input {
            reload: true,
            ..aim()
        },
        &cfg,
    );
    assert_eq!(sim.player.reload_left, 0.); // Full magazine rejects R.
    assert!(ads.sample().unwrap().seconds > before);
    let ammo = sim.player.ammo;
    tick(
        &mut sim,
        &mut ads,
        Input {
            fire: true,
            ..aim()
        },
        &cfg,
    );
    assert_eq!(sim.player.ammo, ammo - 1);
    assert_eq!(ads.sample().unwrap().slot, AdsSlot::Hold);
}
#[test]
fn sprint_and_mantle_interrupt_without_changing_gameplay_and_walk_keeps_ads() {
    let (_, mut ads, mut sim) = fixture();
    let cfg = Settings::m4_candidate();
    for _ in 0..60 {
        tick(&mut sim, &mut ads, aim(), &cfg);
    }
    tick(
        &mut sim,
        &mut ads,
        Input {
            movement: Vec2::Y,
            ..aim()
        },
        &cfg,
    );
    assert!(sim.player.speed() > 0.);
    assert_eq!(ads.sample().unwrap().slot, AdsSlot::Hold);
    tick(
        &mut sim,
        &mut ads,
        Input {
            movement: Vec2::Y,
            sprint: true,
            ..Input::default()
        },
        &cfg,
    );
    assert!(sim.player.sprinting);
    assert!(!sim.player.ads_requested);
    assert_eq!(ads.sample().unwrap().slot, AdsSlot::Exit);
    for _ in 0..40 {
        tick(&mut sim, &mut ads, Input::default(), &cfg);
    }
    assert!(ads.sample().is_none());
    // A real ledge and normal jump input, never a synthetic mantle state.
    let (_, mut ads, mut sim) = fixture();
    sim.blocks = vec![
        Block {
            bounds: Aabb {
                min: vec3(-20., -1., -20.),
                max: vec3(20., 0., 20.),
            },
            kind: 2,
        },
        Block {
            bounds: Aabb {
                min: vec3(-2., 0., -4.),
                max: vec3(2., 1.2, 0.),
            },
            kind: 2,
        },
    ];
    sim.ramps.clear();
    sim.targets.clear();
    sim.player.position = vec3(0., 0., 1.);
    for _ in 0..60 {
        tick(&mut sim, &mut ads, aim(), &cfg);
    }
    tick(
        &mut sim,
        &mut ads,
        Input {
            movement: Vec2::Y,
            jump: true,
            ..aim()
        },
        &cfg,
    );
    assert!(sim.player.mantle.is_some());
    assert!(!sim.player.ads_requested);
    assert_eq!(ads.sample().unwrap().slot, AdsSlot::Exit);
}
#[test]
fn pending_sprint_exit_defers_ads_then_starts_from_connected_ready() {
    let (_, mut ads, mut sim) = fixture();
    let cfg = Settings::m4_candidate();
    for _ in 0..60 {
        let start = sim.time;
        sim.update(aim(), &cfg, FIXED_DT);
        ads.committed_step(start, &sim, false, false).unwrap();
        assert!(ads.sample().is_none());
    }
    tick(&mut sim, &mut ads, aim(), &cfg);
    assert_eq!(ads.sample().unwrap().slot, AdsSlot::Entry);
    assert!((ads.sample().unwrap().seconds - f64::from(FIXED_DT)).abs() < 1e-9);
}
#[test]
fn pause_repeated_render_and_reset_never_advance_or_restart_playback() {
    let (set, mut ads, mut sim) = fixture();
    tick(&mut sim, &mut ads, aim(), &Settings::m4_candidate());
    let sample = ads.sample();
    let pose = ads.pose(&set).unwrap();
    for _ in 0..200 {
        ads.committed_step(sim.time, &sim, false, true).unwrap();
        assert_eq!(ads.sample(), sample);
        assert_eq!(ads.pose(&set).unwrap(), pose);
    }
    assert!(ads.committed_step(0., &sim, false, true).is_err());
    sim.reset();
    ads.reset(sim.time);
    assert!(ads.sample().is_none());
    assert!(!sim.player.ads_requested);
    tick(&mut sim, &mut ads, aim(), &Settings::m4_candidate());
    assert_eq!(ads.sample().unwrap().seconds, f64::from(FIXED_DT));
}
#[test]
fn required_clips_connections_loop_policy_and_static_hold_fail_visibly() {
    for set in [
        animation(true, false, false),
        animation(false, true, false),
        animation(false, false, true),
    ] {
        assert!(AuthoredAds::new(&set, &set, "ready", clips()).is_err());
    }
    let set = animation(false, false, false);
    let mut renamed = clips();
    renamed.entry_clip = "missing".into();
    assert!(AuthoredAds::new(&set, &set, "ready", renamed).is_err());
}

#[test]
fn canonical_binding_mismatch_is_rejected_before_pose_ownership() {
    let animation = animation(false, false, false);
    let incompatible = animation_named(false, false, false, "different_bone");
    let error = AuthoredAds::new(&animation, &incompatible, "ready", clips()).unwrap_err();
    assert!(error.to_string().contains("companion bindings"));
}
