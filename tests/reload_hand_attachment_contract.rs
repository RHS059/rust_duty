//! Geometric hand/prop attachment contracts. These are presentation constraints,
//! independent of ammunition credit, root framing, and gameplay duration.
use vector_range::arms::FITTED_MAGAZINE_WRIST;
use vector_range::weapon_animation::{
    sample_weapon_animation, AnimationInput, ReloadVisualTiming, WeaponAnimationPose,
};

fn sample(empty_reload: bool, phase: f32) -> WeaponAnimationPose {
    sample_weapon_animation(AnimationInput {
        empty_reload,
        reload_progress: Some(phase),
        ..AnimationInput::default()
    })
}

fn magazine_wrist_error(pose: &WeaponAnimationPose) -> f32 {
    pose.left_grip
        .iter()
        .zip(FITTED_MAGAZINE_WRIST)
        .zip(pose.magazine_translation)
        .map(|((&hand, bind_wrist), magazine_offset)| (hand - bind_wrist - magazine_offset).powi(2))
        .sum::<f32>()
        .sqrt()
}

fn assert_held_magazine(pose: WeaponAnimationPose, phase: f32) {
    let distance = magazine_wrist_error(&pose);
    assert!(
        pose.left_hand_blend[1] >= 0.99,
        "phase {phase:.5}: visible held magazine needs magazine grip, modes {:?}",
        pose.left_hand_blend,
    );
    assert!(
        distance <= 0.005,
        "phase {phase:.5}: held magazine is {:.2} mm from fitted wrist; maximum 5 mm; hand {:?}, magazine offset {:?}",
        distance * 1000., pose.left_grip, pose.magazine_translation,
    );
}

#[test]
fn tactical_removal_replacement_and_seating_preserve_magazine_attachment() {
    let timing = ReloadVisualTiming::for_reload(false);
    let settle_end = timing.insert_end + (1. - timing.insert_end) * 0.12;
    // Source 8.1081 still supports the fore-end; 8.2082–8.3083 shows an open
    // free hand while the old magazine remains seated. Closed replacement
    // attachment begins at the fitted 8.5085 s fetch key, not actor release_start.
    let fetch_mid =
        timing.release_end + (timing.insert_start - timing.release_end) * (0.2085 / 0.4421);
    for step in 0..=240 {
        let phase = fetch_mid + (settle_end - fetch_mid) * step as f32 / 240.;
        assert_held_magazine(sample(false, phase), phase);
    }
}

#[test]
fn empty_visible_replacement_pickup_through_seating_keeps_magazine_in_hand() {
    // The supplied reference shows the replacement in the left hand around
    // 14.90 s, normalized against the observed 14.0–16.2 s action (~0.409).
    // The discarded magazine may travel independently before this window.
    let pickup = 0.409;
    let insertion = ReloadVisualTiming::for_reload(true).insert_end;
    for step in 0..=240 {
        let phase = pickup + (insertion - pickup) * step as f32 / 240.;
        assert_held_magazine(sample(true, phase), phase);
    }
}

#[test]
fn empty_discard_is_not_accidentally_welded_to_the_hand() {
    // Preserve the intentionally airborne old magazine. Fixing replacement
    // pickup by attaching the one prop to the hand for the entire reload would
    // erase this gesture and would make the other contract pass incorrectly.
    // Observed airborne discard around14.40–14.48, before the offscreen swap.
    for phase in [0.18, 0.20, 0.22] {
        let pose = sample(true, phase);
        assert!(
            magazine_wrist_error(&pose) > 0.10,
            "phase {phase}: discarded magazine must separate from the hand"
        );
    }
}
