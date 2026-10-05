//! Actual packaged rig mapping, live-target return and interrupted fade witnesses.
use glam::Mat4;
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_pose_return::{
        canonical_to_reload_actor_basis, PoseReturn, PoseReturnMap, RETURN_SECONDS,
    },
    layered_locomotion::AnchoredPoseBlend,
    viewmodel_animation::AnimationSet,
};

#[test]
fn packaged_reload_returns_to_live_motion_with_named_bindings_and_retired_extra_actor() {
    let Some(path) = std::env::var_os("RUST_DUTY_ANIMATION_MANIFEST") else {
        return;
    };
    let manifest = AnimationManifest::load(std::path::Path::new(&path)).unwrap();
    let (base, base_skin, _) =
        AnimationSet::load_with_companions(&manifest.locomotion_asset).unwrap();
    let (reload, reload_skin, _) =
        AnimationSet::load_with_companions(&manifest.tactical.asset).unwrap();
    let basis = canonical_to_reload_actor_basis();
    let map = PoseReturnMap::new(&base, &base_skin, &reload, &reload_skin, basis).unwrap();
    let blend = AnchoredPoseBlend::new(&reload, &manifest.layer_anchor_actor).unwrap();
    let extra = reload
        .actors()
        .iter()
        .position(|a| !base.actors().iter().any(|b| a.name == b.name))
        .unwrap();
    assert_ne!(base.companion_checksums(), reload.companion_checksums());
    assert_ne!(base.actors().len(), reload.actors().len());
    for source_seconds in [0.08, 0.75, 1.5, 2.6026] {
        let source = reload
            .sample_clamped(&manifest.tactical.clip, source_seconds)
            .unwrap();
        let alpha: Vec<_> = source
            .actor_visible
            .iter()
            .map(|&v| f32::from(u8::from(v)))
            .collect();
        let fade = PoseReturn::new(source.clone(), alpha.clone(), 0.);
        for frame in 0..=24 {
            let time = frame as f64 / 120.;
            let target = base
                .sample(&manifest.locomotion.loop_clip, time as f32)
                .unwrap();
            let mapped = map.pose(&base, &reload, &target, &source).unwrap();
            let before = base.bone_globals(&target, Mat4::IDENTITY).unwrap();
            let after = reload.bone_globals(&mapped, Mat4::IDENTITY).unwrap();
            for (i, bone) in reload.bones().iter().enumerate() {
                let j = base
                    .bones()
                    .iter()
                    .position(|b| b.name == bone.name)
                    .unwrap();
                assert!(after[i].abs_diff_eq(before[j], 5e-5));
            }
            for (i, actor) in reload.actors().iter().enumerate() {
                if let Some(j) = base.actors().iter().position(|a| a.name == actor.name) {
                    assert!((mapped.actor_globals[i].matrix() * basis.inverse())
                        .abs_diff_eq(target.actor_globals[j].matrix(), 5e-6));
                }
            }
            let (pose, opacity) = fade.pose(&reload, &blend, &mapped, time).unwrap();
            assert!((opacity[extra] - alpha[extra] * (1. - fade.weight(time))).abs() < 1e-6);
            if source.actor_visible[extra] {
                assert_eq!(pose.actor_globals[extra], source.actor_globals[extra]);
            }
            if frame == 0 {
                assert_eq!(pose, source);
            }
            if frame == 8 {
                let restart = PoseReturn::new(pose.clone(), opacity.clone(), time);
                let (restarted, restarted_alpha) =
                    restart.pose(&reload, &blend, &source, time).unwrap();
                assert_eq!(
                    restarted, pose,
                    "restarting a return cannot reset the current pose"
                );
                assert_eq!(restarted_alpha, opacity);
            }
            if frame == 24 {
                assert_eq!(time, RETURN_SECONDS);
                assert_eq!(opacity[extra], 0.);
                assert!(!pose.actor_visible[extra]);
                for (a, b) in pose.bone_locals.iter().zip(&mapped.bone_locals) {
                    assert_eq!(a, b);
                }
            }
        }
    }
    // The capture must actually cancel while the reload-only actor is visible.
    let mut sim = vector_range::sim::Simulation::new();
    sim.player.ammo = 12;
    let duration = vector_range::authored_reload::AuthoredReload::clip_duration(
        &reload,
        &manifest.tactical.clip,
    )
    .unwrap();
    let mut observer = vector_range::authored_reload::AuthoredReload::new(duration, None).unwrap();
    let mut visible_cancellations = 0;
    for _ in 0..780 {
        let start = sim.time;
        sim.update(
            vector_range::authored_reload::gameplay_return_replay_input(start),
            &vector_range::settings::Settings::m4_candidate(),
            vector_range::sim::FIXED_DT,
        );
        observer.committed_step(start, &sim).unwrap();
        if let Some(ended) = observer.ended_this_step() {
            if ended.seconds < duration
                && reload
                    .sample_clamped(&manifest.tactical.clip, ended.seconds as f32)
                    .unwrap()
                    .actor_visible[extra]
            {
                visible_cancellations += 1;
            }
        }
    }
    assert!(
        visible_cancellations >= 1,
        "diagnostic input must reach a visible reload-only prop before cancellation"
    );
    let mut incompatible = reload_skin.clone();
    incompatible.bones[0].inverse_bind[12] += 0.01;
    assert!(PoseReturnMap::new(&base, &base_skin, &reload, &incompatible, basis).is_err());
    let from = reload.sample_clamped(&manifest.tactical.clip, 0.).unwrap();
    let bad = PoseReturn::new(from.clone(), vec![], 0.);
    assert!(bad.pose(&reload, &blend, &from, 0.).is_err());
    let mut wrong = from.clone();
    wrong.actor_visible.clear();
    let ready = base
        .sample_clamped(&manifest.locomotion.ready_clip, 0.)
        .unwrap();
    assert!(map.pose(&base, &reload, &ready, &wrong).is_err());
}
