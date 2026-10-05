//! Actual production-pack layer witnesses, enabled by complete-game CI.
use glam::{Mat4, Vec3};
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_ads::gameplay_ads_replay_input,
    authored_locomotion_path::AuthoredLocomotionPathState,
    authored_reload::AuthoredReload,
    layered_locomotion::{LayerSources, LayeredLocomotion},
    settings::Settings,
    sim::{Simulation, FIXED_DT},
    viewmodel_animation::AnimationSet,
};
#[test]
fn actual_bound_layers_overlap_preserve_grips_and_leave_gameplay_unchanged() {
    let Some(path) = std::env::var_os("RUST_DUTY_ANIMATION_MANIFEST") else {
        return;
    };
    let manifest = AnimationManifest::load(std::path::Path::new(&path)).unwrap();
    let (set, skin, _) = AnimationSet::load_with_companions(&manifest.locomotion_asset).unwrap();
    let walk_ref = manifest.regular_walk.as_ref().unwrap();
    let (walk, _, _) = AnimationSet::load_with_companions(&walk_ref.asset).unwrap();
    let (ads, _, _) =
        AnimationSet::load_with_companions(&manifest.ads.as_ref().unwrap().asset).unwrap();
    let (reload_set, _, _) = AnimationSet::load_with_companions(&manifest.tactical.asset).unwrap();
    let mut reload = AuthoredReload::new(
        AuthoredReload::clip_duration(&reload_set, &manifest.tactical.clip).unwrap(),
        None,
    )
    .unwrap();
    let sources = LayerSources {
        jump: None,
        locomotion: &set,
        walk: Some(&walk),
        ads: Some(&ads),
    };
    let mut layers = LayeredLocomotion::new(
        sources,
        manifest.locomotion.clone(),
        Some(&walk_ref.clip),
        manifest.ads.clone(),
        &manifest.layer_anchor_actor,
    )
    .unwrap();
    if let Some(clips) = manifest.directional_walk.clone() {
        layers = layers.with_directional_walk(&walk, clips).unwrap();
    }
    layers = layers
        .with_ads_wip_policy(
            manifest.receiver_ads_wip,
            manifest.ads_visual_transition_seconds,
        )
        .and_then(|layers| layers.with_forward_ads_v9_policy(manifest.forward_ads_v9_wip))
        .unwrap();
    let anchor = set
        .actors()
        .iter()
        .position(|a| a.name == manifest.layer_anchor_actor)
        .unwrap();
    let wrists: Vec<_> = set
        .bones()
        .iter()
        .enumerate()
        .filter(|(_, b)| b.name == "hand_l" || b.name == "hand_r")
        .map(|(i, _)| i)
        .collect();
    assert_eq!(wrists.len(), 2);
    let ready = layers.pose().clone();
    let ready_globals = set.bone_globals(&ready, Mat4::IDENTITY).unwrap();
    let grips: Vec<_> = wrists
        .iter()
        .map(|&i| ready.actor_globals[anchor].matrix().inverse() * ready_globals[i])
        .collect();
    let mut sim = Simulation::new();
    let mut baseline = Simulation::new();
    let settings = Settings::m4_candidate();
    let mut overlap = 0;
    let mut early_ads = 0;
    let mut max_grip = 0_f32;
    for _ in 0..1200 {
        let start = sim.time;
        let input = gameplay_ads_replay_input(start);
        baseline.update(input, &settings, FIXED_DT);
        sim.update(input, &settings, FIXED_DT);
        reload.committed_step(start, &sim).unwrap();
        layers
            .committed_step(sources, start, &sim, reload.sample().is_some())
            .unwrap();
        assert_eq!(sim.player.position, baseline.player.position);
        assert_eq!(sim.player.ads, baseline.player.ads);
        assert_eq!(sim.player.ammo, baseline.player.ammo);
        assert_eq!(sim.stats.shots, baseline.stats.shots);
        if sim.player.sprinting
            && layers.run_weight() > 0.
            && layers.walk().weight() > 0.
            && layers.ads().unwrap().sample().is_some()
        {
            overlap += 1;
        }
        if sim.player.ads_requested
            && layers.ads().unwrap().sample().is_some()
            && layers.path().state() != AuthoredLocomotionPathState::Ready
            && layers.run_weight() > 0.
        {
            early_ads += 1;
        }
        let pose = layers.pose();
        set.skin_palette(pose, &skin.bones, Mat4::IDENTITY).unwrap();
        let globals = set.bone_globals(pose, Mat4::IDENTITY).unwrap();
        for (&i, grip) in wrists.iter().zip(&grips) {
            let actual = pose.actor_globals[anchor].matrix().inverse() * globals[i];
            max_grip = max_grip.max(actual.w_axis.truncate().distance(grip.w_axis.truncate()));
        }
    }
    assert!(
        overlap >= 10,
        "no simultaneous native run / walking / ADS exit: {overlap}"
    );
    assert!(early_ads > 0, "ADS waited for run path to reach ready");
    assert!(
        max_grip < 0.0001,
        "actual weapon-relative wrist drift {max_grip} m"
    );
    assert_eq!(layers.run_weight(), 0.);
    assert_eq!(layers.walk().weight(), 0.);
    println!("Actual controller replay: {overlap} simultaneous outgoing walk/ADS + incoming run ticks, {early_ads} returning-run ADS ticks, maximum wrist drift {max_grip} m");
    // Rapid mid-layer reversals sample the actual pack at subframe intervals.
    sim.player.velocity = Vec3::X;
    sim.player.grounded = true;
    for index in 0..1000 {
        let start = sim.time;
        sim.time += 1. / 480.;
        sim.player.sprinting = (index / 17) % 3 == 1;
        sim.player.ads_requested = (index / 29) % 2 == 0;
        layers.committed_step(sources, start, &sim, false).unwrap();
        set.skin_palette(layers.pose(), &skin.bones, Mat4::IDENTITY)
            .unwrap();
    }
}
