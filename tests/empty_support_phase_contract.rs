//! Focused expectations for the early-empty support-phase correction.
//! This does not replace or validate fitted wrist coordinates or native images.
#[path = "../src/weapon_animation.rs"]
#[allow(dead_code)]
mod weapon_animation;
use weapon_animation::{sample_weapon_animation, AnimationInput, ReloadVisualTiming, LEFT_GRIP};

#[test]
fn empty_hand_stays_on_existing_support_anchor_until_discard() {
    let timing = ReloadVisualTiming::for_reload(true);
    for t in [timing.release_start * 0.5, timing.release_start] {
        let pose = sample_weapon_animation(AnimationInput {
            reload_progress: Some(t),
            empty_reload: true,
            ..Default::default()
        });
        assert_eq!(pose.left_grip, LEFT_GRIP);
        assert_eq!(pose.left_hand_blend, [1.0, 0.0, 0.0, 0.0]);
    }
}

#[test]
fn discard_still_moves_magazine_and_then_transitions_to_open_sweep() {
    let timing = ReloadVisualTiming::for_reload(true);
    let sample = |t| {
        sample_weapon_animation(AnimationInput {
            reload_progress: Some(t),
            empty_reload: true,
            ..Default::default()
        })
    };
    let discarded = sample(timing.release_end);
    assert_eq!(discarded.left_hand_blend, [0., 0., 0., 1.]);
    assert_eq!(discarded.left_grip, [-0.07967767, -0.08977185, -0.1718748]);
    assert!(discarded.magazine_translation[0] < -0.25);
    let sweep = sample(timing.release_end + (timing.insert_start - timing.release_end) * 0.30);
    assert_eq!(sweep.left_hand_blend, [0.0, 0.0, 0.0, 1.0]);
}
