//! Opt-in canonical export + committed gameplay replay, without a graphics context.
use std::collections::BTreeSet;
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_ads::{gameplay_ads_replay_input, AdsSlot, AuthoredAds},
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathState},
    authored_reload::AuthoredReload,
    authored_walk::{AuthoredWalk, WalkPoseLayer},
    settings::Settings,
    sim::{Simulation, FIXED_DT},
    viewmodel_animation::{game_model_root, AnimationSet},
};
#[test]
fn canonical_ads_pack_plays_committed_replay_and_preserves_every_gameplay_outcome() {
    let Some(path) = std::env::var_os("RUST_DUTY_ANIMATION_MANIFEST") else {
        return;
    };
    let manifest = AnimationManifest::load(std::path::Path::new(&path)).unwrap();
    let reference = manifest
        .ads
        .expect("ADS is required in the source-to-game export");
    let (locomotion, _, _) =
        AnimationSet::load_with_companions(&manifest.locomotion_asset).unwrap();
    let (animation, skin, _) = AnimationSet::load_with_companions(&reference.asset).unwrap();
    let mut ads = AuthoredAds::new(
        &animation,
        &locomotion,
        &manifest.locomotion.ready_clip,
        reference,
    )
    .unwrap();
    let mut path = AuthoredLocomotionPath::new(&locomotion, manifest.locomotion, 0.).unwrap();
    let (reload_set, _, _) = AnimationSet::load_with_companions(&manifest.tactical.asset).unwrap();
    let mut reload = AuthoredReload::new(
        AuthoredReload::clip_duration(&reload_set, &manifest.tactical.clip).unwrap(),
        None,
    )
    .unwrap();
    let walk_reference = manifest.regular_walk.as_ref().unwrap();
    let (walking, _, _) = AnimationSet::load_with_companions(&walk_reference.asset).unwrap();
    let layer = WalkPoseLayer::new(
        &walking,
        &locomotion,
        "normal_ready",
        manifest.walk_anchor_actor.as_deref().unwrap(),
    )
    .unwrap();
    let mut walk = AuthoredWalk::default();
    let mut aimed_walk_samples = 0;
    let mut last_walk_time = None;

    let mut sim = Simulation::new();
    sim.player.ammo = 12;
    let mut baseline = Simulation::new();
    baseline.player.ammo = 12;
    let cfg = Settings::m4_candidate();
    let mut routes = BTreeSet::new();
    let mut reversed_entry = false;
    let mut reversed_exit = false;
    let mut poses = 0;
    for _ in 0..1104 {
        let start = sim.time;
        let input = gameplay_ads_replay_input(start);
        sim.update(input, &cfg, FIXED_DT);
        baseline.update(input, &cfg, FIXED_DT);
        let was_reload = reload.sample().is_some();
        reload.committed_step(start, &sim).unwrap();
        let is_reload = reload.sample().is_some();
        if was_reload && !is_reload {
            path.reset(&locomotion, start).unwrap();
        }
        ads.committed_step(
            start,
            &sim,
            is_reload,
            path.state() == AuthoredLocomotionPathState::Ready,
        )
        .unwrap();
        let is_ads = ads.sample().is_some();
        let sprint = sim.player.sprinting && !is_reload && !is_ads;
        path.update(&locomotion, start, sprint, true).unwrap();
        path.update(&locomotion, sim.time, sprint, true).unwrap();
        let p = &sim.player;
        walk.committed_step(
            start,
            sim.time,
            p.grounded
                && p.speed() > 0.1
                && !p.sprinting
                && p.mantle.is_none()
                && path.state() == AuthoredLocomotionPathState::Ready,
            !is_reload && p.reload_left <= 0.,
        )
        .unwrap();
        assert_eq!(p.position, baseline.player.position);
        assert_eq!(p.velocity, baseline.player.velocity);
        assert_eq!(p.ads, baseline.player.ads);
        assert_eq!(p.stamina, baseline.player.stamina);
        assert_eq!(p.sprinting, baseline.player.sprinting);
        assert_eq!(p.ammo, baseline.player.ammo);
        assert_eq!(p.reserve, baseline.player.reserve);
        assert_eq!(p.reload_credit_at, baseline.player.reload_credit_at);
        assert_eq!(p.reload_ready_at, baseline.player.reload_ready_at);
        assert_eq!(p.next_shot_at, baseline.player.next_shot_at);
        assert_eq!(sim.stats.shots, baseline.stats.shots);
        if is_reload {
            assert!(!is_ads);
            routes.insert("reload.tactical");
        } else if let Some(sample) = ads.sample() {
            routes.insert(sample.slot.route());
            reversed_entry |= sample.slot == AdsSlot::Entry && sample.direction < 0;
            reversed_exit |= sample.slot == AdsSlot::Exit && sample.direction < 0;
            let pose = ads.pose(&animation).unwrap().unwrap();
            let direct = if sample.slot == AdsSlot::Hold {
                animation.sample(ads.clip(sample.slot), sample.seconds as f32)
            } else {
                animation.sample_clamped(ads.clip(sample.slot), sample.seconds as f32)
            }
            .unwrap();
            assert_eq!(pose, direct, "runtime poses must be actual source samples");
            let palette = animation
                .skin_palette(&pose, &skin.bones, game_model_root())
                .unwrap();
            assert!(!palette.is_empty() && palette.iter().all(|matrix| matrix.is_finite()));
            assert_eq!(
                animation
                    .actor_matrices(&pose, game_model_root())
                    .unwrap()
                    .len(),
                animation.actors().len()
            );
            if let Some(seconds) = walk.seconds() {
                if let Some(previous) = last_walk_time {
                    assert!(seconds > previous, "ADS must not restart the walk phase");
                }
                last_walk_time = Some(seconds);
                let walk_pose = walking
                    .sample(&walk_reference.clip, seconds as f32)
                    .unwrap();
                let layered = layer
                    .pose(
                        &animation,
                        &pose,
                        &walk_pose,
                        walk.weight(),
                        ads.aim_amount(),
                    )
                    .unwrap();
                animation
                    .skin_palette(&layered, &skin.bones, game_model_root())
                    .unwrap();
                if sample.slot == AdsSlot::Hold {
                    assert_ne!(layered, pose, "aimed movement must remain animated");
                    aimed_walk_samples += 1;
                    // Full aim adds exactly one rigid transform to every bone and
                    // actor: source grip and sight geometry cannot separate.
                    let delta = layered.actor_globals[1].matrix()
                        * pose.actor_globals[1].matrix().inverse();
                    for z in [-0.2, -0.6] {
                        let ray = delta.transform_point3(glam::vec3(0., 0., z));
                        assert!(
                            ray.x.abs() < 2e-6 && ray.y.abs() < 2e-6,
                            "full ADS walking must retain the camera optical ray"
                        );
                    }
                    let before = animation.bone_globals(&pose, glam::Mat4::IDENTITY).unwrap();
                    let after = animation
                        .bone_globals(&layered, glam::Mat4::IDENTITY)
                        .unwrap();
                    for (a, b) in before.iter().zip(&after) {
                        assert!((delta * *a).abs_diff_eq(*b, 2e-5));
                    }
                    for (a, b) in pose.actor_globals.iter().zip(&layered.actor_globals) {
                        assert!((delta * a.matrix()).abs_diff_eq(b.matrix(), 2e-5));
                    }
                }
            } else {
                last_walk_time = None;
            }
            poses += 1;
        } else if walk.seconds().is_some() {
            routes.insert("regular_walk");
        } else if path.state() == AuthoredLocomotionPathState::Ready {
            routes.insert("ready");
        } else {
            routes.insert("locomotion");
        }
    }
    assert_eq!(
        routes,
        BTreeSet::from([
            "ads.entry",
            "ads.hold",
            "ads.exit",
            "reload.tactical",
            "regular_walk",
            "ready",
            "locomotion"
        ])
    );
    assert!(reversed_entry && reversed_exit && poses > 200);
    assert!(
        aimed_walk_samples > 20,
        "walk must remain active during ADS hold"
    );
    assert!(sim.stats.shots >= 1 && sim.player.ammo == 30);
    assert!(ads.sample().is_none() && reload.sample().is_none() && walk.seconds().is_none());
    assert_eq!(path.state(), AuthoredLocomotionPathState::Ready);
    println!("Committed input replay evaluated {poses} canonical ADS source poses, both reversal directions, walking/sprint/fire/reload interruptions and final ready; gameplay unchanged");
}
