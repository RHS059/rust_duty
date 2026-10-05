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
        eprintln!(
            "Real asset validation not requested; set RUST_DUTY_ANIMATION_MANIFEST in export CI"
        );
        return;
    };
    let manifest = AnimationManifest::load(std::path::Path::new(&path)).unwrap();
    let (locomotion, _, _) =
        AnimationSet::load_with_companions(&manifest.locomotion_asset).unwrap();
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
        let input = Input {
            reload: index == 0,
            ..Input::default()
        };
        let start = simulation.time;
        simulation.update(input, &settings, 1. / 120.);
        baseline.update(input, &settings, 1. / 120.);
        observer.committed_step(start, &simulation).unwrap();
        assert_eq!(simulation.player.ammo, baseline.player.ammo);
        assert_eq!(simulation.player.reserve, baseline.player.reserve);
        assert_eq!(
            simulation.player.reload_ready_at,
            baseline.player.reload_ready_at
        );
        assert_eq!(
            simulation.player.reload_credit_at,
            baseline.player.reload_credit_at
        );
        if let Some(sample) = observer.sample() {
            let pose = reload
                .sample_clamped(&manifest.tactical.clip, sample.seconds as f32)
                .unwrap();
            assert!(!reload
                .skin_palette(&pose, &skin.bones, game_model_root())
                .unwrap()
                .is_empty());
            assert_eq!(
                reload
                    .actor_matrices(&pose, game_model_root())
                    .unwrap()
                    .len(),
                reload.actors().len()
            );
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

#[test]
fn real_forward_movement_plays_bound_walk_then_returns_to_ready() {
    use vector_range::authored_walk::AuthoredWalk;
    let Some(path) = std::env::var_os("RUST_DUTY_ANIMATION_MANIFEST") else {
        return;
    };
    let manifest = AnimationManifest::load(std::path::Path::new(&path)).unwrap();
    let Some(reference) = manifest.regular_walk else {
        eprintln!("Authored regular_walk slot is explicitly unavailable");
        return;
    };
    let (animation, skin, _) = AnimationSet::load_with_companions(&reference.asset).unwrap();
    AuthoredWalk::validate_clip(&animation, &reference.clip).unwrap();
    let duration = animation
        .clips()
        .iter()
        .find(|clip| clip.name == reference.clip)
        .unwrap()
        .duration();
    let mut simulation = Simulation::new();
    let mut baseline = Simulation::new();
    let initial_position = simulation.player.position;
    let settings = Settings::m4_candidate();
    let mut walk = AuthoredWalk::default();
    let mut samples = 0;
    let mut previous_seconds = 0.;
    let mut moved = false;
    for _ in 0..444 {
        let start = simulation.time;
        let input = Input {
            movement: if (0.25..2.25).contains(&start) {
                glam::Vec2::Y
            } else {
                glam::Vec2::ZERO
            },
            ..Input::default()
        };
        simulation.update(input, &settings, 1. / 120.);
        baseline.update(input, &settings, 1. / 120.);
        assert_eq!(simulation.player.position, baseline.player.position);
        assert_eq!(simulation.player.velocity, baseline.player.velocity);
        assert!(!simulation.player.sprinting);
        walk.committed_step(
            start,
            simulation.time,
            simulation.player.grounded && simulation.player.speed() > 0.1,
            true,
        )
        .unwrap();
        if let Some(seconds) = walk.seconds() {
            assert!(seconds > previous_seconds);
            previous_seconds = seconds;
            let pose = animation.sample(&reference.clip, seconds as f32).unwrap();
            assert!(!animation
                .skin_palette(&pose, &skin.bones, game_model_root())
                .unwrap()
                .is_empty());
            assert_eq!(
                animation
                    .actor_matrices(&pose, game_model_root())
                    .unwrap()
                    .len(),
                animation.actors().len()
            );
            samples += 1;
            moved |= simulation.player.position.distance(initial_position) > 0.5;
        }
    }
    assert!(moved && samples > 100);
    assert!(previous_seconds > f64::from(duration) * 2.);
    assert!(walk.seconds().is_none());
    assert!(simulation.player.speed() <= 0.1);
    println!("Committed forward movement sampled {samples} authored poses across multiple native loops, then stopped; movement unchanged");
}
