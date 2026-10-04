//! Synthetic complete controller contracts; no reference video match is inferred.
use macroquad::math::{Mat4, Quat, Vec3};
use vector_range::{
    animation_manifest::{AdsReference, DirectionalWalkClips},
    authored_ads::AdsSlot,
    authored_locomotion_path::{AuthoredLocomotionPathConfig, AuthoredLocomotionPathState},
    layered_locomotion::{AnchoredPoseBlend, LayerSources, LayeredLocomotion},
    sim::Simulation,
    viewmodel_animation::{AnimationSet, Transform, ViewmodelPose},
};
fn word(out: &mut Vec<u8>, value: u32) {
    out.extend(value.to_le_bytes());
}
fn name(out: &mut Vec<u8>, value: &str) {
    out.extend((value.len() as u16).to_le_bytes());
    out.extend(value.as_bytes());
}
fn floats(out: &mut Vec<u8>, values: &[f32]) {
    for x in values {
        out.extend(x.to_le_bytes());
    }
}
fn trs(out: &mut Vec<u8>, value: Transform) {
    floats(out, &value.translation.to_array());
    floats(out, &value.rotation.to_array());
    floats(out, &value.scale.to_array());
}
fn anchor(x: f32) -> Transform {
    Transform {
        translation: Vec3::new(x, 0.2 * x, 0.1 * x),
        rotation: Quat::from_rotation_z(x),
        scale: Vec3::ONE,
    }
}
fn fixture() -> AnimationSet {
    let mut p = Vec::new();
    word(&mut p, 0);
    word(&mut p, 0);
    word(&mut p, 2);
    name(&mut p, "root");
    word(&mut p, u32::MAX);
    name(&mut p, "hand");
    word(&mut p, 0);
    word(&mut p, 1);
    name(&mut p, "weapon");
    word(&mut p, 0);
    floats(&mut p, &Mat4::IDENTITY.to_cols_array());
    let clips = [
        ("ready", false, vec![(0., 0.)]),
        ("jump_takeoff", false, vec![(0., 0.), (0.2, -0.1)]),
        ("jump_air", false, vec![(0., -0.1), (0.4, 0.1)]),
        ("jump_land", false, vec![(0., 0.1), (0.2, -0.1), (0.5, 0.)]),
        ("run_in", false, vec![(0., 0.), (0.25, 0.2)]),
        ("run", true, vec![(0., 0.2), (0.25, 0.3), (0.5, 0.2)]),
        ("bridge0", false, vec![(0., 0.2), (0.125, 0.1)]),
        ("bridge1", false, vec![(0., 0.3), (0.125, 0.1)]),
        ("run_out", false, vec![(0., 0.1), (0.125, 0.05)]),
        ("settle", false, vec![(0., 0.05), (0.125, 0.)]),
        (
            "walk",
            true,
            vec![
                (0., 0.),
                (0.125, 0.005),
                (0.25, 0.),
                (0.375, -0.005),
                (0.5, 0.),
            ],
        ),
        (
            "walk_forward",
            true,
            vec![(0., 0.002), (0.25, 0.007), (0.5, 0.002)],
        ),
        (
            "walk_backward",
            true,
            vec![(0., -0.002), (0.25, -0.007), (0.5, -0.002)],
        ),
        (
            "walk_left",
            true,
            vec![(0., 0.003), (0.25, 0.009), (0.5, 0.003)],
        ),
        (
            "walk_right",
            true,
            vec![(0., -0.003), (0.25, -0.009), (0.5, -0.003)],
        ),
        ("ads_in", false, vec![(0., 0.), (0.25, 0.4)]),
        ("ads", true, vec![(0., 0.4), (1., 0.4)]),
        ("ads_out", false, vec![(0., 0.4), (0.25, 0.)]),
    ];
    word(&mut p, clips.len() as u32);
    for (clip, looping, frames) in clips {
        name(&mut p, clip);
        word(&mut p, u32::from(looping));
        word(&mut p, frames.len() as u32);
        for (time, x) in frames {
            floats(&mut p, &[time]);
            trs(&mut p, anchor(x));
            trs(
                &mut p,
                Transform {
                    translation: Vec3::new(0.1, 0.2, 0.3),
                    ..Transform::IDENTITY
                },
            );
            trs(&mut p, anchor(x));
            p.push(1);
        }
    }
    let mut bytes = b"VRANIM01".to_vec();
    word(&mut bytes, 1);
    word(&mut bytes, p.len() as u32);
    word(&mut bytes, vector_range::skinned_asset::crc32(&p));
    word(&mut bytes, 0);
    bytes.extend(p);
    AnimationSet::decode(&bytes).unwrap()
}
fn sources(set: &AnimationSet) -> LayerSources<'_> {
    LayerSources {
        jump: None,
        locomotion: set,
        walk: Some(set),
        ads: Some(set),
    }
}
fn controller(set: &AnimationSet) -> LayeredLocomotion {
    LayeredLocomotion::new(
        sources(set),
        AuthoredLocomotionPathConfig {
            ready_clip: "ready".into(),
            entry_clip: "run_in".into(),
            loop_clip: "run".into(),
            exit_bridge_clips: vec!["bridge0".into(), "bridge1".into()],
            exit_clip: "run_out".into(),
            settle_clip: "settle".into(),
            rate_response_seconds: 0.05,
            residual_decay_seconds: 0.03,
        },
        Some("walk"),
        Some(AdsReference {
            asset: "test.vra".into(),
            entry_clip: "ads_in".into(),
            hold_clip: "ads".into(),
            exit_clip: "ads_out".into(),
        }),
        "weapon",
    )
    .unwrap()
}
fn step(
    set: &AnimationSet,
    layers: &mut LayeredLocomotion,
    sim: &mut Simulation,
    dt: f64,
    walk: bool,
    ads: bool,
    run: bool,
) {
    let start = sim.time;
    sim.time += dt;
    sim.player.grounded = true;
    sim.player.velocity = if walk || run { Vec3::X } else { Vec3::ZERO };
    sim.player.ads_requested = ads;
    sim.player.sprinting = run;
    layers
        .committed_step(sources(set), start, sim, false)
        .unwrap();
}

#[test]
fn saved_xyz_placement_follows_interrupted_visual_ads_without_changing_settings() {
    use vector_range::settings::{Settings, WalkTranslation};
    let set = fixture();
    for hz in [30_f64, 60., 120.] {
        for signs in 0..8 {
            let axis = |bit| if signs & (1 << bit) == 0 { -0.2 } else { 0.2 };
            let mut settings = Settings::default();
            settings.set_viewmodel(axis(0), axis(1));
            settings.set_viewmodel_z(axis(2));
            settings.set_walking_translation("test", WalkTranslation([-1., 0.4, 1.]));
            let saved = settings.clone();
            let hip = settings.viewmodel_offset(0.);
            let mut layers = controller(&set)
                .with_ads_wip_policy(false, Some(0.30))
                .unwrap();
            let mut sim = Simulation::new();
            for (aim, seconds) in [
                (true, 0.1),
                (false, 0.04),
                (true, 0.5),
                (false, 0.08),
                (true, 0.04),
                (false, 0.5),
            ] {
                let before = settings.viewmodel_offset(layers.visual_ads_amount());
                step(&set, &mut layers, &mut sim, 0., true, aim, false);
                assert_eq!(
                    settings.viewmodel_offset(layers.visual_ads_amount()),
                    before,
                    "changing intent without time must not snap placement"
                );
                for _ in 0..(seconds * hz).ceil() as usize {
                    let before = settings.viewmodel_offset(layers.visual_ads_amount());
                    step(&set, &mut layers, &mut sim, 1. / hz, true, aim, false);
                    let offset = settings.viewmodel_offset(layers.visual_ads_amount());
                    assert!(
                        (offset - before).abs().max_element()
                            <= 0.2 * 1.5 / (0.30 * hz as f32) + 1e-6
                    );
                    assert!(offset.abs().cmple(hip.abs()).all());
                    assert_eq!(
                        settings, saved,
                        "render placement cannot alter saved controls"
                    );
                }
                if seconds == 0.5 {
                    assert_eq!(
                        settings.viewmodel_offset(layers.visual_ads_amount()),
                        if aim { Vec3::ZERO } else { hip }
                    );
                }
            }
            step(&set, &mut layers, &mut sim, 0.5, true, true, false);
            assert_eq!(
                settings.viewmodel_offset(layers.visual_ads_amount()),
                Vec3::ZERO
            );
            step(&set, &mut layers, &mut sim, 1. / hz, true, true, true);
            assert!(layers.visual_ads_amount() < layers.ads().unwrap().aim_amount());
            step(&set, &mut layers, &mut sim, 0.5, true, true, true);
            assert_eq!(settings.viewmodel_offset(layers.visual_ads_amount()), hip);
        }
    }
}

#[test]
fn saved_placement_keeps_full_aimed_pose_and_optical_ray_at_every_slider_extreme() {
    use vector_range::settings::Settings;
    for x in [-0.2, 0., 0.2] {
        for y in [-0.2, 0., 0.2] {
            for z in [-0.2, 0., 0.2] {
                let mut settings = Settings::default();
                settings.set_viewmodel(x, y);
                settings.set_viewmodel_z(z);
                let offset = settings.viewmodel_offset(1.);
                assert_eq!(offset, Vec3::ZERO);
                for depth in [0.23306687, 0.5932643] {
                    assert_eq!(
                        Vec3::new(0., 0., -depth) + offset,
                        Vec3::new(0., 0., -depth)
                    );
                }
                assert_eq!(settings.viewmodel_offset(0.), Vec3::new(x, y, z));
            }
        }
    }
}
fn close(a: &ViewmodelPose, b: &ViewmodelPose, tolerance: f32) {
    for (a, b) in a
        .bone_locals
        .iter()
        .chain(&a.actor_globals)
        .zip(b.bone_locals.iter().chain(&b.actor_globals))
    {
        assert!(
            a.matrix().abs_diff_eq(b.matrix(), tolerance),
            "pose mismatch {a:?} {b:?}"
        );
    }
}
#[test]
fn run_enters_on_same_tick_that_aim_and_walk_fade_out() {
    let set = fixture();
    let mut layers = controller(&set);
    let mut sim = Simulation::new();
    step(&set, &mut layers, &mut sim, 0.5, true, true, false);
    let phase = layers.walk().seconds().unwrap();
    step(&set, &mut layers, &mut sim, 1. / 120., false, false, true);
    assert_eq!(layers.ads().unwrap().sample().unwrap().slot, AdsSlot::Exit);
    assert_eq!(layers.path().state(), AuthoredLocomotionPathState::Entry);
    assert!(layers.run_weight() > 0. && layers.run_weight() < 1.);
    assert!(layers.walk().weight() > 0. && layers.walk().weight() < 1.);
    assert!(layers.walk().seconds().unwrap() > phase);
    assert_ne!(layers.pose(), layers.path().pose());
}
#[test]
fn run_exit_does_not_serialize_walk_or_ads_reentry() {
    let set = fixture();
    let mut layers = controller(&set);
    let mut sim = Simulation::new();
    step(&set, &mut layers, &mut sim, 0.5, true, true, false);
    step(&set, &mut layers, &mut sim, 0.08, false, false, true);
    let phase = layers.walk().seconds().unwrap();
    let run = layers.run_weight();
    step(&set, &mut layers, &mut sim, 1. / 120., true, true, false);
    assert!(layers.run_weight() < run && layers.run_weight() > 0.);
    assert_ne!(layers.path().state(), AuthoredLocomotionPathState::Ready);
    assert_eq!(layers.ads().unwrap().sample().unwrap().direction, -1);
    assert!(layers.walk().seconds().unwrap() > phase);
    let prior = layers.pose().clone();
    step(&set, &mut layers, &mut sim, 1e-7, false, false, true);
    close(&prior, layers.pose(), 1e-5);
}
#[test]
fn repeated_paused_reads_and_invalid_ticks_cannot_mutate_pose_or_phase() {
    let set = fixture();
    let mut layers = controller(&set);
    let mut sim = Simulation::new();
    step(&set, &mut layers, &mut sim, 0.06, true, true, false);
    let before = layers.pose().clone();
    let clock = layers.walk().seconds();
    let weight = layers.run_weight();
    for _ in 0..20 {
        step(&set, &mut layers, &mut sim, 0., false, false, true);
        assert_eq!(layers.pose(), &before);
    }
    assert!(layers
        .committed_step(sources(&set), sim.time + 1., &sim, false)
        .is_err());
    assert_eq!(layers.pose(), &before);
    assert_eq!(layers.walk().seconds(), clock);
    assert_eq!(layers.run_weight(), weight);
}
#[test]
fn layer_endpoints_and_reversals_are_independent_of_tick_partition() {
    let set = fixture();
    let mut a = controller(&set);
    let mut b = a.clone();
    let mut x = Simulation::new();
    let mut y = Simulation::new();
    for (dt, walk, ads, run) in [
        (0.4, true, true, false),
        (0.08, false, false, true),
        (0.03, true, true, false),
        (0.1, false, false, true),
        (0.08, true, false, false),
    ] {
        step(&set, &mut a, &mut x, dt, walk, ads, run);
        step(&set, &mut b, &mut y, dt * 0.4, walk, ads, run);
        step(&set, &mut b, &mut y, dt * 0.6, walk, ads, run);
        close(a.pose(), b.pose(), 2e-5);
        assert!((a.run_weight() - b.run_weight()).abs() < 1e-6);
        assert!((a.walk().weight() - b.walk().weight()).abs() < 1e-6);
    }
}
#[test]
fn attached_hand_remains_in_weapon_space_through_all_layer_combinations() {
    let set = fixture();
    let mut layers = controller(&set);
    let mut sim = Simulation::new();
    for tick in 0..500 {
        let run = (tick / 31) % 3 == 1;
        let ads = (tick / 43) % 2 == 0;
        let walk = (tick / 19) % 4 != 0;
        step(&set, &mut layers, &mut sim, 1. / 120., walk, ads, run);
        let pose = layers.pose();
        let globals = set.bone_globals(pose, Mat4::IDENTITY).unwrap();
        let hand = pose.actor_globals[0].matrix().inverse() * globals[1];
        assert!(hand.w_axis.truncate().distance(Vec3::new(0.1, 0.2, 0.3)) < 2e-6);
    }
}
#[test]
fn anchored_blend_has_exact_endpoints_and_validates_before_indexing() {
    let set = fixture();
    let blend = AnchoredPoseBlend::new(&set, "weapon").unwrap();
    let a = set.sample_clamped("ready", 0.).unwrap();
    let b = set.sample_clamped("ads", 0.).unwrap();
    assert_eq!(blend.blend(&set, &a, &b, 0.).unwrap(), a);
    assert_eq!(blend.blend(&set, &a, &b, 1.).unwrap(), b);
    assert!(blend.blend(&set, &a, &b, f32::NAN).is_err());
    let mut malformed = b.clone();
    malformed.actor_globals.clear();
    assert!(blend.blend(&set, &a, &malformed, 0.).is_err());
    assert!(AnchoredPoseBlend::new(&set, "absent").is_err());
}

fn directions() -> DirectionalWalkClips {
    DirectionalWalkClips {
        forward: "walk_forward".into(),
        backward: "walk_backward".into(),
        left: "walk_left".into(),
        right: "walk_right".into(),
    }
}
#[test]
fn four_camera_relative_directions_share_the_hip_clock_and_ads_layer() {
    let set = fixture();
    for (index, velocity) in [Vec3::X, -Vec3::X, -Vec3::Z, Vec3::Z]
        .into_iter()
        .enumerate()
    {
        let mut layers = controller(&set)
            .with_directional_walk(&set, directions())
            .unwrap();
        let mut sim = Simulation::new();
        sim.player.yaw = 0.;
        sim.player.grounded = true;
        sim.player.velocity = velocity;
        sim.time = 0.25;
        layers
            .committed_step(sources(&set), 0., &sim, false)
            .unwrap();
        let weights = layers.directional_weights().unwrap();
        assert_eq!(weights[index], 1.);
        assert_eq!(weights.iter().sum::<f64>(), 1.);
        close(
            layers.pose(),
            &set.sample(directions().names()[index], 0.25).unwrap(),
            2e-5,
        );
        let phase = layers.walk().seconds().unwrap();
        sim.player.ads_requested = true;
        let start = sim.time;
        sim.time += 0.25;
        layers
            .committed_step(sources(&set), start, &sim, false)
            .unwrap();
        assert_eq!(layers.directional_weights().unwrap(), weights);
        assert_eq!(layers.walk().seconds().unwrap(), phase + 0.25);
        assert_eq!(layers.ads().unwrap().sample().unwrap().slot, AdsSlot::Hold);
    }
}
#[test]
fn direction_reversal_is_continuous_and_pause_cannot_change_weights() {
    let set = fixture();
    let mut layers = controller(&set)
        .with_directional_walk(&set, directions())
        .unwrap();
    let mut sim = Simulation::new();
    sim.player.yaw = 0.;
    step(&set, &mut layers, &mut sim, 0.25, true, false, false);
    let before = layers.pose().clone();
    let weights = layers.directional_weights().unwrap();
    sim.player.velocity = -Vec3::X;
    layers
        .committed_step(sources(&set), sim.time, &sim, false)
        .unwrap();
    assert_eq!(layers.directional_weights().unwrap(), weights);
    let start = sim.time;
    sim.time += 1e-7;
    layers
        .committed_step(sources(&set), start, &sim, false)
        .unwrap();
    close(&before, layers.pose(), 1e-5);
    let weights = layers.directional_weights().unwrap();
    assert!(weights[0] > 0.99 && weights[1] > 0.);
    assert!((weights.iter().sum::<f64>() - 1.).abs() < 1e-12);
    assert!((layers.walk().seconds().unwrap() - sim.time).abs() < 1e-12);
}
#[test]
fn directional_weights_are_partition_independent_and_incomplete_sources_fail() {
    let set = fixture();
    let mut a = controller(&set)
        .with_directional_walk(&set, directions())
        .unwrap();
    let mut sim = Simulation::new();
    sim.player.yaw = 0.;
    step(&set, &mut a, &mut sim, 0.25, true, false, false);
    let mut b = a.clone();
    sim.player.velocity = -Vec3::Z;
    let start = sim.time;
    sim.time += 0.1;
    a.committed_step(sources(&set), start, &sim, false).unwrap();
    sim.time = start + 0.04;
    b.committed_step(sources(&set), start, &sim, false).unwrap();
    sim.time = start + 0.1;
    b.committed_step(sources(&set), start + 0.04, &sim, false)
        .unwrap();
    close(a.pose(), b.pose(), 2e-5);
    for (x, y) in a
        .directional_weights()
        .unwrap()
        .into_iter()
        .zip(b.directional_weights().unwrap())
    {
        assert!((x - y).abs() < 1e-12);
    }
    let mut missing = directions();
    missing.left = "missing".into();
    assert!(controller(&set)
        .with_directional_walk(&set, missing)
        .is_err());
    assert!(a.with_directional_walk(&set, directions()).is_err());
}

#[test]
fn thirty_and_sixty_hz_render_sampling_observe_identical_committed_layers() {
    use vector_range::{
        layered_locomotion::gameplay_layered_replay_input, settings::Settings, sim::FIXED_DT,
    };
    let set = fixture();
    fn replay(set: &AnimationSet, hz: u32) -> std::collections::BTreeMap<u64, (u32, [f64; 4])> {
        let mut controller = controller(set)
            .with_directional_walk(set, directions())
            .unwrap();
        let mut sim = Simulation::new();
        let cfg = Settings::m4_candidate();
        let mut output = std::collections::BTreeMap::new();
        let mut tick = 0;
        for frame in 0..=11 * hz {
            let target = vector_range::clock::capture_tick_target(u64::from(frame), hz).unwrap();
            while tick < target {
                let start = sim.time;
                sim.update(gameplay_layered_replay_input(start), &cfg, FIXED_DT);
                controller
                    .committed_step(sources(set), start, &sim, false)
                    .unwrap();
                tick += 1;
            }
            assert_eq!((sim.time * 120.).round() as u64, target);
            output.insert(
                (sim.time * 120.).round() as u64,
                (
                    controller.pose_crc32(),
                    controller.directional_weights().unwrap(),
                ),
            );
        }
        output
    }
    let thirty = replay(&set, 30);
    let sixty = replay(&set, 60);
    let mut compared = 0;
    for (time, sample) in thirty {
        if let Some(other) = sixty.get(&time) {
            assert_eq!(&sample, other);
            compared += 1;
        }
    }
    assert!(compared >= 330);
}

#[test]
fn wip_ads_rate_integrates_phase_without_recomputing_or_resetting_prior_walk_time() {
    let set = fixture();
    let mut layers = controller(&set)
        .with_ads_wip_policy(true, Some(0.30))
        .unwrap();
    let mut sim = Simulation::new();
    step(&set, &mut layers, &mut sim, 10., true, false, false);
    assert_eq!(layers.walk().seconds(), Some(10.));
    step(&set, &mut layers, &mut sim, 0.30, true, true, false);
    assert!((layers.walk().seconds().unwrap() - 10.2775).abs() < 1e-9);
    step(&set, &mut layers, &mut sim, 1., true, true, false);
    assert!((layers.walk().seconds().unwrap() - 11.1275).abs() < 1e-9);
    let before = layers.walk().seconds().unwrap();
    step(&set, &mut layers, &mut sim, 0.05, true, false, false);
    assert!(layers.walk().seconds().unwrap() > before);
    let mut b = layers.clone();
    let start = sim.time;
    let end = start + 0.1;
    sim.player.ads_requested = true;
    sim.time = end;
    layers
        .committed_step(sources(&set), start, &sim, false)
        .unwrap();
    sim.time = start + 0.04;
    b.committed_step(sources(&set), start, &sim, false).unwrap();
    sim.time = end;
    b.committed_step(sources(&set), start + 0.04, &sim, false)
        .unwrap();
    assert!((layers.walk().seconds().unwrap() - b.walk().seconds().unwrap()).abs() < 1e-10);
    close(layers.pose(), b.pose(), 2e-5);
}

#[test]
fn walking_axes_scale_only_neutral_relative_displacement_and_preserve_grips() {
    use vector_range::{authored_walk::WalkPoseLayer, settings::WalkTranslation};
    let set = fixture();
    let base = set.sample_clamped("ads", 0.).unwrap();
    let walk = set.sample("walk_forward", 0.15).unwrap();
    let mut layer = WalkPoseLayer::new(&set, &set, "ready", "weapon").unwrap();
    for aim in [0., 0.35, 1.] {
        for weight in [0., 0.4, 1.] {
            layer.set_translation_adjustment(WalkTranslation::default());
            let current = layer.pose(&set, &base, &walk, weight, aim).unwrap();
            let neutral = base.actor_globals[0].translation;
            let displacement = current.actor_globals[0].translation - neutral;
            for values in [
                [-1., 0., 0.],
                [0., -1., 0.],
                [0., 0., -1.],
                [1., 0.5, -0.5],
                [-1.; 3],
            ] {
                let adjustment = WalkTranslation(values);
                layer.set_translation_adjustment(adjustment);
                let adjusted = layer.pose(&set, &base, &walk, weight, aim).unwrap();
                let expected = neutral + displacement * adjustment.gains();
                assert!(adjusted.actor_globals[0]
                    .translation
                    .abs_diff_eq(expected, 2e-6));
                assert!(adjusted.actor_globals[0]
                    .rotation
                    .abs_diff_eq(current.actor_globals[0].rotation, 2e-6));
                let original_globals = set.bone_globals(&current, Mat4::IDENTITY).unwrap();
                let adjusted_globals = set.bone_globals(&adjusted, Mat4::IDENTITY).unwrap();
                for (a, b) in original_globals.iter().zip(adjusted_globals) {
                    let relative_a = current.actor_globals[0].matrix().inverse() * *a;
                    let relative_b = adjusted.actor_globals[0].matrix().inverse() * b;
                    assert!(relative_a.abs_diff_eq(relative_b, 3e-6));
                }
                if weight == 0. {
                    assert_eq!(adjusted, base);
                }
            }
        }
    }
}

#[test]
fn walk_settings_leave_idle_reload_and_full_sprint_output_unchanged() {
    use vector_range::settings::WalkTranslation;
    let set = fixture();
    for (moving, sprint, reload) in [
        (false, false, false),
        (false, true, false),
        (true, false, true),
    ] {
        let mut original = controller(&set);
        let mut adjusted = original.clone();
        adjusted.set_walk_translation(WalkTranslation([-1., 1., 0.5]));
        let mut sim = Simulation::new();
        sim.player.velocity = if moving { Vec3::X } else { Vec3::ZERO };
        sim.player.sprinting = sprint;
        sim.time = 0.5;
        original
            .committed_step(sources(&set), 0., &sim, reload)
            .unwrap();
        adjusted
            .committed_step(sources(&set), 0., &sim, reload)
            .unwrap();
        assert_eq!(original.pose(), adjusted.pose());
    }
}

#[test]
fn v9_direction_and_aim_rate_integrals_preserve_phase_across_partitioned_ticks() {
    let set = fixture();
    let mut a = controller(&set)
        .with_directional_walk(&set, directions())
        .unwrap()
        .with_ads_wip_policy(true, Some(0.30))
        .unwrap()
        .with_forward_ads_v9_policy(true)
        .unwrap();
    let mut sim = Simulation::new();
    sim.player.yaw = 0.;
    sim.player.velocity = Vec3::X;
    sim.time = 0.2;
    a.committed_step(sources(&set), 0., &sim, false).unwrap();
    let mut b = a.clone();
    sim.player.ads_requested = true;
    sim.player.velocity = Vec3::Z;
    sim.time = 0.65;
    a.committed_step(sources(&set), 0.2, &sim, false).unwrap();
    let mut previous = 0.2;
    for time in [0.213, 0.3, 0.37, 0.49, 0.58, 0.65] {
        sim.time = time;
        b.committed_step(sources(&set), previous, &sim, false)
            .unwrap();
        previous = time;
    }
    assert!((a.walk().seconds().unwrap() - b.walk().seconds().unwrap()).abs() < 1e-10);
    close(a.pose(), b.pose(), 3e-5);
    assert_eq!(a.walk_min_rate(), 0.80);
    let phase = a.walk().seconds();
    a.committed_step(sources(&set), sim.time, &sim, false)
        .unwrap();
    assert_eq!(a.walk().seconds(), phase);
    // Forward return, run overlap, and interrupted ADS exit all keep a single clock.
    sim.player.velocity = Vec3::X;
    sim.player.sprinting = true;
    sim.time += 0.05;
    a.committed_step(sources(&set), previous, &sim, false)
        .unwrap();
    assert!(a.run_weight() > 0. && a.walk().weight() > 0.);
    assert!(a.walk().seconds().unwrap() > phase.unwrap());
}

#[test]
fn v9_without_directional_source_retains_legacy_policy() {
    let set = fixture();
    let mut original = controller(&set)
        .with_ads_wip_policy(true, Some(0.30))
        .unwrap();
    let mut fallback = original.clone().with_forward_ads_v9_policy(true).unwrap();
    let mut sim = Simulation::new();
    sim.player.velocity = Vec3::X;
    sim.player.ads_requested = true;
    sim.time = 0.4;
    original
        .committed_step(sources(&set), 0., &sim, false)
        .unwrap();
    fallback
        .committed_step(sources(&set), 0., &sim, false)
        .unwrap();
    assert_eq!(original.pose(), fallback.pose());
    assert_eq!(original.walk().seconds(), fallback.walk().seconds());
    assert_eq!(fallback.walk_min_rate(), 0.85);
}

#[test]
fn jump_landing_blends_from_actual_pose_at_early_and_late_contact() {
    for contact in [0.1, 0.9] {
        let set = fixture();
        let mut layers = controller(&set)
            .with_jump(&set, &set, "ready", "weapon")
            .unwrap();
        let mut sim = Simulation::new();
        sim.player.last_jump_at = 0.;
        sim.player.grounded = false;
        let sources = LayerSources {
            jump: Some(&set),
            ..sources(&set)
        };
        sim.time = 0.01;
        layers.committed_step(sources, 0., &sim, false).unwrap();
        sim.time = contact - 0.01;
        layers.committed_step(sources, 0.01, &sim, false).unwrap();
        let airborne = layers.pose().clone();
        sim.time = contact;
        sim.player.grounded = true;
        layers
            .committed_step(sources, contact - 0.01, &sim, false)
            .unwrap();
        assert_eq!(
            layers.jump_sample().unwrap().phase,
            vector_range::authored_jump::JumpPhase::Land
        );
        assert_eq!(layers.jump_sample().unwrap().seconds, 0.);
        assert_eq!(layers.pose(), &airborne);
        sim.time += 0.07;
        layers
            .committed_step(sources, contact, &sim, false)
            .unwrap();
        assert_ne!(layers.pose(), &airborne);
    }
}

#[test]
fn jump_keeps_ads_clock_and_articulation_and_reload_owns_interruption() {
    let set = fixture();
    let mut layers = controller(&set)
        .with_jump(&set, &set, "ready", "weapon")
        .unwrap();
    let mut baseline = controller(&set);
    let mut sim = Simulation::new();
    sim.player.ads_requested = true;
    let jump_sources = LayerSources {
        jump: Some(&set),
        ..sources(&set)
    };
    for i in 0..100 {
        let start = sim.time;
        if i == 40 {
            sim.player.last_jump_at = start;
            sim.player.grounded = false;
        }
        sim.time += 0.01;
        layers
            .committed_step(jump_sources, start, &sim, false)
            .unwrap();
        baseline
            .committed_step(sources(&set), start, &sim, false)
            .unwrap();
        assert_eq!(layers.visual_ads_amount(), baseline.visual_ads_amount());
    }
    assert!(layers.jump_sample().is_some());
    // At full ADS the jump's x/y translation is projected away, preserving the
    // authored optical placement, but source depth/roll still moves the weapon.
    let aimed = baseline.pose().actor_globals[0];
    let jumped = layers.pose().actor_globals[0];
    assert!(jumped.translation.is_finite());
    assert_ne!(jumped, aimed);
    let start = sim.time;
    sim.time += 0.01;
    layers
        .committed_step(jump_sources, start, &sim, true)
        .unwrap();
    baseline
        .committed_step(sources(&set), start, &sim, true)
        .unwrap();
    assert!(layers.jump_sample().is_none());
    assert_eq!(layers.pose(), baseline.pose());
    let previous = layers.pose().clone();
    // Missing configured source is a real failure and leaves all clocks/pose intact.
    sim.time += 0.01;
    assert!(layers
        .committed_step(sources(&set), start + 0.01, &sim, false)
        .is_err());
    assert_eq!(layers.pose(), &previous);
}

#[test]
fn real_simulation_accepts_one_jump_and_ground_contact_starts_landing() {
    use vector_range::{
        authored_jump::JumpPhase,
        settings::Settings,
        sim::{Input, FIXED_DT},
    };
    let set = fixture();
    let mut layers = controller(&set)
        .with_jump(&set, &set, "ready", "weapon")
        .unwrap();
    let sources = LayerSources {
        jump: Some(&set),
        ..sources(&set)
    };
    let mut sim = Simulation::new();
    let cfg = Settings::default();
    let mut saw_air = false;
    let mut saw_land = false;
    for _ in 0..240 {
        let start = sim.time;
        // Holding raw input must not repeatedly restart the accepted jump.
        sim.update(
            Input {
                jump: true,
                ..Input::default()
            },
            &cfg,
            FIXED_DT,
        );
        layers.committed_step(sources, start, &sim, false).unwrap();
        if let Some(sample) = layers.jump_sample() {
            saw_air |= sample.phase == JumpPhase::Air;
            if sample.phase == JumpPhase::Land {
                assert!(sim.player.grounded);
                saw_land = true;
            }
        }
    }
    assert!(saw_air && saw_land);
    assert!(layers.jump_sample().is_none());
    assert_eq!(sim.player.last_jump_at, 0.);
}

#[test]
fn real_space_to_stand_and_mantle_never_start_jump_layer() {
    use macroquad::math::{vec2, vec3};
    use vector_range::{
        settings::Settings,
        sim::{Aabb, Block, Input, FIXED_DT},
    };
    let set = fixture();
    let cfg = Settings::default();
    for mantle in [false, true] {
        let mut layers = controller(&set)
            .with_jump(&set, &set, "ready", "weapon")
            .unwrap();
        let sources = LayerSources {
            jump: Some(&set),
            ..sources(&set)
        };
        let mut sim = Simulation::new();
        if mantle {
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
                        max: vec3(2., 0.6, 0.),
                    },
                    kind: 2,
                },
            ];
            sim.ramps.clear();
            sim.player.position = vec3(0., 0., 1.);
            sim.player.yaw = -std::f32::consts::FRAC_PI_2;
        } else {
            for _ in 0..60 {
                let start = sim.time;
                sim.update(
                    Input {
                        crouch: true,
                        ..Input::default()
                    },
                    &cfg,
                    FIXED_DT,
                );
                layers.committed_step(sources, start, &sim, false).unwrap();
            }
            assert!(sim.player.crouched);
        }
        let start = sim.time;
        sim.update(
            Input {
                jump: true,
                movement: if mantle { vec2(0., 1.) } else { vec2(0., 0.) },
                ..Input::default()
            },
            &cfg,
            FIXED_DT,
        );
        layers.committed_step(sources, start, &sim, false).unwrap();
        assert_eq!(sim.player.mantle.is_some(), mantle);
        assert!(layers.jump_sample().is_none());
        for _ in 0..120 {
            let start = sim.time;
            sim.update(
                Input {
                    jump: true,
                    ..Input::default()
                },
                &cfg,
                FIXED_DT,
            );
            layers.committed_step(sources, start, &sim, false).unwrap();
            assert!(layers.jump_sample().is_none());
        }
    }
}
