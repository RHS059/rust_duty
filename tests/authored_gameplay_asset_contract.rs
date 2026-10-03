//! Opt-in real-export contract used by the automatic Blender -> game CI job.
//! No GL context or procedural posing: evaluate the same poses the renderer uses.
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_locomotion_path::AuthoredLocomotionPath,
    authored_reload::AuthoredReload,
    settings::Settings,
    sim::{Input, Simulation},
    viewmodel_animation::{game_model_root, AnimationSet},
};
#[test]
fn full_export_plays_on_committed_r_and_returns_to_locomotion() {
    let Some(path) = std::env::var_os("RUST_DUTY_ANIMATION_MANIFEST") else {
        eprintln!("Real asset validation not requested; set RUST_DUTY_ANIMATION_MANIFEST in export CI");
        return;
    };
    let manifest = AnimationManifest::load(std::path::Path::new(&path)).unwrap();
    let (locomotion, _, _) = AnimationSet::load_with_companions(&manifest.locomotion_asset).unwrap();
    let mut path = AuthoredLocomotionPath::new(&locomotion, manifest.locomotion, 0.).unwrap();
    let (reload, skin, _) = AnimationSet::load_with_companions(&manifest.tactical.asset).unwrap();
    let duration = AuthoredReload::clip_duration(&reload, &manifest.tactical.clip).unwrap();
    let mut observer = AuthoredReload::new(duration, None).unwrap();
    let mut simulation = Simulation::new();
    simulation.player.ammo = 12;
    let mut baseline = Simulation::new();
    baseline.player.ammo = 12;
    let settings = Settings::m4_candidate();
    let steps = ((duration.max(f64::from(settings.reload_time)) + 1.) * 120.).ceil() as usize;
    let mut rendered = 0;
    let mut exited = false;
    for index in 0..steps {
        let input = Input { reload: index == 0, ..Input::default() };
        let start = simulation.time;
        simulation.update(input, &settings, 1. / 120.);
        baseline.update(input, &settings, 1. / 120.);
        observer.committed_step(start, &simulation).unwrap();
        assert_eq!(simulation.player.ammo, baseline.player.ammo);
        assert_eq!(simulation.player.reserve, baseline.player.reserve);
        assert_eq!(simulation.player.reload_ready_at, baseline.player.reload_ready_at);
        assert_eq!(simulation.player.reload_credit_at, baseline.player.reload_credit_at);
        if let Some(sample) = observer.sample() {
            let pose = reload.sample_clamped(&manifest.tactical.clip, sample.seconds as f32).unwrap();
            assert!(!reload.skin_palette(&pose, &skin.bones, game_model_root()).unwrap().is_empty());
            assert_eq!(reload.actor_matrices(&pose, game_model_root()).unwrap().len(), reload.actors().len());
            rendered += 1;
        } else if rendered > 0 {
            path.reset(&locomotion, simulation.time).unwrap();
            assert!(!path.pose().bone_locals.is_empty());
            exited = true;
        }
    }
    assert!(rendered > 1 && exited);
    println!("Committed R sampled {rendered} complete native reload poses over {duration:.6}s and exited; gameplay unchanged");
}
