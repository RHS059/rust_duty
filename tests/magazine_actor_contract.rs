use vector_range::weapon_animation::{sample_weapon_animation, AnimationInput};
fn at(source: f32, empty: bool) -> vector_range::weapon_animation::WeaponAnimationPose {
    let (start, duration) = if empty { (14., 2.2) } else { (7.8, 2.21) };
    sample_weapon_animation(AnimationInput {
        reload_progress: Some((source - start) / duration),
        empty_reload: empty,
        ..Default::default()
    })
}
#[test]
fn tactical_fetch_overlaps_seated_old_mag_then_drops_it() {
    let fetch = at(8.5252, false);
    assert_eq!(fetch.magazine_visibility, [true, true]);
    assert_eq!(fetch.seated_magazine_translation, [0.; 3]);
    assert!(
        fetch
            .magazine_translation
            .iter()
            .map(|v| v * v)
            .sum::<f32>()
            > 0.01
    );
    let drop = at(8.60, false);
    assert_eq!(drop.magazine_visibility, [true, true]);
    assert!(drop.seated_magazine_translation[0] < 0.);
    assert!(drop.seated_magazine_translation[1] < 0.);
    assert_eq!(at(8.68, false).magazine_visibility, [false, true]);
    let inserted = at(8.995, false);
    assert_eq!(inserted.magazine_translation, [0.; 3]);
    assert_eq!(inserted.magazine_visibility, [false, true]);
}
#[test]
fn empty_old_discard_and_replacement_are_separate_visible_roles() {
    let drop = at(14.4, true);
    assert_eq!(drop.magazine_visibility, [true, false]);
    assert!(drop.seated_magazine_translation[0] < -0.25);
    let held = at(14.9, true);
    assert_eq!(held.magazine_visibility, [false, true]);
    assert_eq!(held.left_hand_blend, [0., 1., 0., 0.]);
}

#[test]
fn closed_magazine_wrist_and_prop_share_one_quaternion_path() {
    use glam::Quat;
    use vector_range::weapon_animation::{
        effective_hand_orientation, effective_magazine_orientation, HAND_MODE_ORIENTATIONS,
    };
    for empty in [false, true] {
        for i in 1..1000 {
            let p = sample_weapon_animation(AnimationInput {
                reload_progress: Some(i as f32 / 1000.),
                empty_reload: empty,
                ..Default::default()
            });
            if p.left_hand_blend[1] > 0.999999 {
                let hand = Quat::from_array(effective_hand_orientation(&p));
                let expected = Quat::from_array(effective_magazine_orientation(&p))
                    * Quat::from_array(HAND_MODE_ORIENTATIONS[1]);
                assert!(
                    hand.dot(expected).abs() > 0.99999,
                    "detached angular grip at {i}, empty={empty}"
                );
            }
        }
    }
}
#[test]
fn receiver_slap_has_distinct_open_release_and_withdrawal() {
    for source in [15.5155, 15.6156, 15.8158, 15.9159] {
        assert!(at(source, true).left_hand_blend[3] > 0.99);
    }
    assert!(at(15.7157, true).left_hand_blend[2] > 0.99);
}

#[test]
fn tactical_support_is_complete_by_observed_native_frame_112() {
    use vector_range::weapon_animation::LEFT_GRIP;
    for frame in 112..=146 {
        let phase = (frame as f32 * (1001. / 60000.) / 2.21).min(1.);
        let p = sample_weapon_animation(AnimationInput {
            reload_progress: Some(phase),
            ..Default::default()
        });
        assert_eq!(p.left_grip, LEFT_GRIP);
        assert_eq!(p.left_hand_blend, [1., 0., 0., 0.]);
    }
}

#[test]
fn tactical_fore_end_arrival_has_the_observed_open_then_wrap_keys() {
    for frame in [102., 108.] {
        let p = sample_weapon_animation(AnimationInput {
            reload_progress: Some(frame * (1001. / 60000.) / 2.21),
            ..Default::default()
        });
        assert!(
            p.left_hand_blend[3] > 0.9999,
            "hand must remain open at nativeframe{frame}"
        );
    }
    let p = sample_weapon_animation(AnimationInput {
        reload_progress: Some(110. * (1001. / 60000.) / 2.21),
        ..Default::default()
    });
    assert!(p.left_hand_blend[0] > 0.45 && p.left_hand_blend[0] < 0.55);
}
