//! Source-observed tactical support contact, open release, and initial drop.
use vector_range::weapon_animation::{
    effective_hand_orientation, effective_magazine_orientation, sample_weapon_animation,
    sample_weapon_animation_with_timing, AnimationInput, ReloadVisualTiming, WeaponAnimationPose,
    HAND_MODE_ORIENTATIONS, LEFT_GRIP,
};

fn sample_source(seconds: f32) -> WeaponAnimationPose {
    sample_weapon_animation(AnimationInput {
        reload_progress: Some((seconds - 7.8) / 2.21),
        ..Default::default()
    })
}

fn distance(a: [f32; 3], b: [f32; 3]) -> f32 {
    a.into_iter()
        .zip(b)
        .map(|(a, b)| (a - b).powi(2))
        .sum::<f32>()
        .sqrt()
}

#[test]
fn support_contact_is_retained_through_observed_source_8_1081() {
    for step in 0..=180 {
        let pose = sample_source(7.8 + 0.3081 * step as f32 / 180.);
        assert!(distance(pose.left_grip, LEFT_GRIP) < 1e-6);
        assert!(pose.left_hand_blend[0] > 0.99999);
        assert!(pose.left_hand_blend[1] < 1e-6);
        let dot: f32 = effective_hand_orientation(&pose)
            .into_iter()
            .zip(HAND_MODE_ORIENTATIONS[0])
            .map(|(a, b)| a * b)
            .sum();
        assert!(dot.abs() > 0.99999);
        assert_eq!(pose.seated_magazine_translation, [0.; 3]);
    }
}

#[test]
fn support_release_opens_away_from_weapon_without_a_seated_magazine_grasp() {
    let open = sample_source(8.2082);
    let drop = sample_source(8.3083);
    for pose in [open, drop] {
        assert!(pose.left_hand_blend[3] > 0.99999);
        assert!(pose.left_hand_blend[1] < 1e-5);
        assert!(pose.left_grip[0] < LEFT_GRIP[0] - 0.12);
        assert!(distance(pose.left_grip, [-0.046, -0.150, 0.010]) > 0.17);
        assert!(
            pose.magazine_visibility[0],
            "old magazine remains in the weapon"
        );
        assert!(
            !pose.magazine_visibility[1],
            "replacement is still offscreen"
        );
        assert_eq!(pose.seated_magazine_translation, [0.; 3]);
        assert_eq!(pose.seated_magazine_euler_yxz, [0.; 3]);
    }
    assert!(drop.left_grip[1] < open.left_grip[1] - 0.10);
    for step in 1..=120 {
        let source = 8.1081 + (8.3083 - 8.1081) * step as f32 / 120.;
        let pose = sample_source(source);
        assert!(
            pose.left_hand_blend[1] < 1e-5,
            "premature magazine grip at {source}"
        );
        assert_eq!(pose.seated_magazine_translation, [0.; 3]);
    }
}

#[test]
fn first_visible_replacement_at_source_8_50_is_rigidly_attached_to_the_hand() {
    use macroquad::math::Quat;
    for phase in [(8.50_f32 - 7.8) / 2.21, 0.316742, 0.3205882] {
        let pose = sample_weapon_animation(AnimationInput {
            reload_progress: Some(phase),
            ..Default::default()
        });
        assert_eq!(pose.magazine_visibility, [true, true]);
        assert!(pose.left_hand_blend[1] > 0.99999);
        let wrist = std::array::from_fn(|axis| {
            [-0.046, -0.150, 0.010][axis] + pose.magazine_translation[axis]
        });
        assert!(distance(pose.left_grip, wrist) < 1e-6);
        let hand = Quat::from_array(effective_hand_orientation(&pose));
        let expected = Quat::from_array(effective_magazine_orientation(&pose))
            * Quat::from_array(HAND_MODE_ORIENTATIONS[1]);
        assert!(hand.dot(expected).abs() > 0.99999);
        assert_eq!(pose.seated_magazine_translation, [0.; 3]);
    }
}

#[test]
fn retimed_initial_release_keeps_contact_open_drop_and_later_fetch_ordered() {
    for timing in [
        ReloadVisualTiming::for_reload(false),
        ReloadVisualTiming {
            release_start: 0.05,
            release_end: 0.10,
            insert_start: 0.35,
            insert_end: 0.48,
            receiver_start: 0.70,
            receiver_end: 0.85,
        },
    ] {
        let span = timing.release_end - timing.release_start;
        let fetch_span = timing.insert_start - timing.release_end;
        let departure = timing.release_start + span * (0.0681 / 0.26);
        let open = timing.release_start + span * (0.1682 / 0.26);
        let drop = timing.release_end + fetch_span * (0.0083 / 0.4421);
        let fetch = timing.release_end + fetch_span * (0.2085 / 0.4421);
        let at = |phase| {
            sample_weapon_animation_with_timing(
                AnimationInput {
                    reload_progress: Some(phase),
                    ..Default::default()
                },
                timing,
            )
        };
        assert_eq!(at(departure).left_grip, LEFT_GRIP);
        assert_eq!(at(departure).left_hand_blend, [1., 0., 0., 0.]);
        assert_eq!(at(open).left_hand_blend, [0., 0., 0., 1.]);
        assert_eq!(at(drop).left_hand_blend, [0., 0., 0., 1.]);
        assert_eq!(at(fetch).left_hand_blend, [0., 1., 0., 0.]);
        assert!(at(drop).left_grip[1] < at(open).left_grip[1]);
    }
}
