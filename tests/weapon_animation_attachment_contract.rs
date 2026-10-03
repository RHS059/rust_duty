//! Direct sampler attachment contracts; use the current fitted sampler source.
//! rustc --edition=2021 --test tests/weapon_animation_attachment_contract.rs -o attachment-tests
#[path = "../src/weapon_animation.rs"]
#[allow(dead_code)]
mod weapon_animation;
use weapon_animation::{sample_weapon_animation_with_timing, AnimationInput, ReloadVisualTiming};

fn input(progress: f32) -> AnimationInput {
    AnimationInput {
        reload_progress: Some(progress),
        empty_reload: true,
        ..Default::default()
    }
}

#[test]
fn replacement_wrist_tracks_fitted_magseat_from_pickup_through_insertion() {
    for timing in [
        ReloadVisualTiming::for_reload(true),
        ReloadVisualTiming {
            release_start: 0.08,
            release_end: 0.16,
            insert_start: 0.31,
            insert_end: 0.43,
            receiver_start: 0.61,
            receiver_end: 0.82,
        },
    ] {
        // Derive the renderer-fitted seat from its actual seated pose. Do not
        // hardcode an older grip location or undo the integrator's fitting.
        let seated = sample_weapon_animation_with_timing(input(timing.insert_end), timing);
        let pickup = timing.release_end + (timing.insert_start - timing.release_end) * 0.30;
        for i in 0..=2000 {
            let t = pickup + (timing.insert_end - pickup) * i as f32 / 2000.0;
            let pose = sample_weapon_animation_with_timing(input(t), timing);
            let distance_squared: f32 = (0..3)
                .map(|axis| {
                    let seat = seated.left_grip[axis] - seated.magazine_translation[axis];
                    (pose.left_grip[axis] - (seat + pose.magazine_translation[axis])).powi(2)
                })
                .sum();
            assert!(
                distance_squared <= 0.005_f32.powi(2),
                "detached replacement wrist at q={t}: {}mm",
                distance_squared.sqrt() * 1000.0
            );
        }
    }
}

#[test]
fn reported_empty_attachment_regressions_are_within_five_millimetres() {
    let timing = ReloadVisualTiming::for_reload(true);
    let seated = sample_weapon_animation_with_timing(input(timing.insert_end), timing);
    for t in [0.3413, 0.4019, 0.4095, 0.4323] {
        let pose = sample_weapon_animation_with_timing(input(t), timing);
        let distance_squared: f32 = (0..3)
            .map(|axis| {
                let seat = seated.left_grip[axis] - seated.magazine_translation[axis];
                (pose.left_grip[axis] - (seat + pose.magazine_translation[axis])).powi(2)
            })
            .sum();
        assert!(
            distance_squared <= 0.005_f32.powi(2),
            "attachment error at q={t}: {}mm",
            distance_squared.sqrt() * 1000.0
        );
    }
}
