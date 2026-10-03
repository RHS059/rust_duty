//! Opt-in canonical export + committed gameplay replay, without a graphics context.
use std::collections::BTreeSet;
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_ads::{gameplay_ads_replay_input, AdsSlot, AuthoredAds},
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathState},
    authored_reload::AuthoredReload,
    authored_walk::AuthoredWalk,
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
    let mut walk = AuthoredWalk::default();
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
            p.grounded && p.speed() > 0.1,
            !is_reload
                && !is_ads
                && !p.ads_requested
                && p.reload_left <= 0.
                && !p.sprinting
                && p.mantle.is_none()
                && p.ads <= 0.
                && p.shot_kick <= 0.
                && path.state() == AuthoredLocomotionPathState::Ready,
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
            assert!(walk.seconds().is_none());
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
    assert!(sim.stats.shots >= 1 && sim.player.ammo == 30);
    assert!(ads.sample().is_none() && reload.sample().is_none() && walk.seconds().is_none());
    assert_eq!(path.state(), AuthoredLocomotionPathState::Ready);
    println!("Committed input replay evaluated {poses} canonical ADS source poses, both reversal directions, walking/sprint/fire/reload interruptions and final ready; gameplay unchanged");
}
