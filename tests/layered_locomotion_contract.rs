//! Synthetic complete controller contracts; no reference video match is inferred.
use macroquad::math::{Mat4, Quat, Vec3};
use vector_range::{
    animation_manifest::AdsReference,
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
