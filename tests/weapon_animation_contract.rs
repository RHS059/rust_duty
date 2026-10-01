//! Public contract tests for the standalone, renderer-independent animation.
//!
//! Run without a Cargo project:
//! rustc --edition=2021 --test tests/weapon_animation_contract.rs -o /tmp/weapon-animation-tests
//! /tmp/weapon-animation-tests
//!
//! These tests check presentation invariants. They deliberately do not assert
//! gameplay state, ammunition changes, firing gates, or recovered retail keys.
//! Default visual timing reflects secondhand integrator notes from a newer-era
//! BETA clip, not directly viewed footage or verified 2009 retail fidelity.
//! Tactical release timing is authored where those notes provide no evidence.
//! Left-hand modes are authored renderer blend hints, ordered as support,
//! magazine, receiver, open; they do not encode gameplay or recovered poses.

#[path = "../src/weapon_animation.rs"]
mod weapon_animation;

use weapon_animation::{
    reload_progress_at, sample_transition, sample_weapon_animation,
    sample_weapon_animation_with_timing, AnimationInput, ReloadVisualTiming, WeaponAnimationPose,
    ADS_SECONDS, EMPTY_RELOAD_SECONDS, SPRINT_OUT_SECONDS, TACTICAL_RELOAD_SECONDS,
};

const RIGHT_GRIP: [f32; 3] = [0.037, -0.095, 0.153];
const LEFT_GRIP: [f32; 3] = [-0.068, -0.112, -0.205];
const MAGAZINE_SEAT_HAND: [f32; 3] = [-0.046, -0.150, 0.010];
const RECEIVER_HAND: [f32; 3] = [-0.05519356, -0.1048773, -0.03914053];
const SUPPORT_BLEND: [f32; 4] = [1.0, 0.0, 0.0, 0.0];
const MAGAZINE_BLEND: [f32; 4] = [0.0, 1.0, 0.0, 0.0];
const RECEIVER_BLEND: [f32; 4] = [0.0, 0.0, 1.0, 0.0];
const OPEN_BLEND: [f32; 4] = [0.0, 0.0, 0.0, 1.0];
const EPSILON: f32 = 1.0e-6;

fn close(actual: f32, expected: f32) {
    assert!(
        (actual - expected).abs() <= EPSILON,
        "expected {expected:?}, got {actual:?}"
    );
}

fn close3(actual: [f32; 3], expected: [f32; 3]) {
    for i in 0..3 {
        close(actual[i], expected[i]);
    }
}

fn close4(actual: [f32; 4], expected: [f32; 4]) {
    for i in 0..4 {
        close(actual[i], expected[i]);
    }
}

fn channels(pose: WeaponAnimationPose) -> [f32; 23] {
    [
        pose.weapon_translation[0],
        pose.weapon_translation[1],
        pose.weapon_translation[2],
        pose.weapon_euler_yxz[0],
        pose.weapon_euler_yxz[1],
        pose.weapon_euler_yxz[2],
        pose.magazine_translation[0],
        pose.magazine_translation[1],
        pose.magazine_translation[2],
        pose.right_grip[0],
        pose.right_grip[1],
        pose.right_grip[2],
        pose.left_grip[0],
        pose.left_grip[1],
        pose.left_grip[2],
        pose.bolt_translation[0],
        pose.bolt_translation[1],
        pose.bolt_translation[2],
        pose.trigger_pull,
        pose.left_hand_blend[0],
        pose.left_hand_blend[1],
        pose.left_hand_blend[2],
        pose.left_hand_blend[3],
    ]
}

fn close_pose(actual: WeaponAnimationPose, expected: WeaponAnimationPose) {
    for (actual, expected) in channels(actual).iter().zip(channels(expected).iter()) {
        close(*actual, *expected);
    }
}

fn bounded(pose: WeaponAnimationPose) {
    for value in channels(pose) {
        assert!(value.is_finite(), "non-finite animation output: {pose:?}");
        // Broad contract bounds catch explosive input propagation without
        // pinning the exact artistic amplitude of every authored curve.
        assert!(value.abs() <= 4.0, "unbounded animation output: {pose:?}");
    }
    assert!((0.0..=1.0).contains(&pose.trigger_pull));
    for weight in pose.left_hand_blend {
        assert!(
            weight.is_finite() && (0.0..=1.0).contains(&weight),
            "invalid left-hand blend weight: {pose:?}"
        );
    }
    close(pose.left_hand_blend.iter().sum(), 1.0);
}

fn reload(t: f32, credit: f32, empty: bool) -> AnimationInput {
    AnimationInput {
        reload_progress: Some(t),
        reload_credit_fraction: credit,
        empty_reload: empty,
        ..AnimationInput::default()
    }
}

#[test]
fn public_types_are_copy_debug_partial_eq_and_default() {
    fn check_traits<T: Copy + std::fmt::Debug + PartialEq + Default>() {}
    check_traits::<AnimationInput>();
    check_traits::<WeaponAnimationPose>();
}

#[test]
fn default_input_is_idle_with_documented_rest_grips() {
    let input = AnimationInput::default();
    assert_eq!(input.reload_progress, None);
    assert!(
        !input.empty_reload,
        "empty reload must be an explicit caller choice"
    );
    close(input.reload_credit_fraction, 1.1 / 2.029);
    close(input.ads, 0.0);
    close(input.recoil, 0.0);
    close(input.sprint, 0.0);
    let pose = sample_weapon_animation(input);
    close3(pose.weapon_translation, [0.0; 3]);
    close3(pose.weapon_euler_yxz, [0.0; 3]);
    close3(pose.magazine_translation, [0.0; 3]);
    close3(pose.bolt_translation, [0.0; 3]);
    close3(pose.right_grip, RIGHT_GRIP);
    close3(pose.left_grip, LEFT_GRIP);
    close4(pose.left_hand_blend, SUPPORT_BLEND);
    assert_eq!(pose, WeaponAnimationPose::default());
    bounded(pose);
}

#[test]
fn reload_endpoints_match_no_reload_with_the_same_other_channels() {
    for empty in [false, true] {
        for (ads, recoil, sprint) in [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.3, 0.6, 0.8)] {
            let input = AnimationInput {
                empty_reload: empty,
                ads,
                recoil,
                sprint,
                ..AnimationInput::default()
            };
            let idle = sample_weapon_animation(input);
            for t in [0.0, 1.0] {
                close_pose(
                    sample_weapon_animation(AnimationInput {
                        reload_progress: Some(t),
                        ..input
                    }),
                    idle,
                );
            }
        }
    }
}

#[test]
fn inactive_completed_and_invalid_reload_progress_keep_the_support_hand_mode() {
    for empty in [false, true] {
        for progress in [
            None,
            Some(0.0),
            Some(1.0),
            Some(-1.0),
            Some(2.0),
            Some(-f32::MAX),
            Some(f32::MAX),
            Some(f32::NEG_INFINITY),
            Some(f32::INFINITY),
            Some(f32::NAN),
        ] {
            let pose = sample_weapon_animation(AnimationInput {
                reload_progress: progress,
                empty_reload: empty,
                ads: 0.8,
                recoil: 0.75,
                sprint: 0.6,
                ..AnimationInput::default()
            });
            bounded(pose);
            close4(pose.left_hand_blend, SUPPORT_BLEND);
        }
    }
}

#[test]
fn tactical_hand_modes_stage_support_open_pickup_then_return_without_receiver() {
    for timing in [
        ReloadVisualTiming::for_reload(false),
        timing_from_fields([0.08, 0.16, 0.31, 0.43, 0.61, 0.82]),
    ] {
        let fetch_mid = timing.release_end + (timing.insert_start - timing.release_end) * 0.50;
        let settle_end = timing.insert_end + (1.0 - timing.insert_end) * 0.27;
        for t in [
            fetch_mid,
            timing.insert_start,
            timing.insert_end,
            settle_end,
        ] {
            let pose = sample_weapon_animation_with_timing(reload(t, 0.54, false), timing);
            bounded(pose);
            close4(pose.left_hand_blend, MAGAZINE_BLEND);
        }
        {
            let t = timing.release_start * 0.50;
            let pose = sample_weapon_animation_with_timing(reload(t, 0.54, false), timing);
            bounded(pose);
            close4(pose.left_hand_blend, [1.0, 0.0, 0.0, 0.0]);
        }
        // Observed initial release stays on the fore-end, then opens freely;
        // the hand does not grasp the seated old magazine on its way downward.
        {
            let release_span = timing.release_end - timing.release_start;
            let departure = timing.release_start + release_span * (0.0681 / 0.26);
            let open = timing.release_start + release_span * (0.1682 / 0.26);
            let pose = sample_weapon_animation_with_timing(reload(departure, 0.54, false), timing);
            close4(pose.left_hand_blend, [1.0, 0.0, 0.0, 0.0]);
            let pose = sample_weapon_animation_with_timing(reload(open, 0.54, false), timing);
            close4(pose.left_hand_blend, [0.0, 0.0, 0.0, 1.0]);
        }
        for i in 0..=2000 {
            let pose =
                sample_weapon_animation_with_timing(reload(i as f32 / 2000.0, 0.54, false), timing);
            bounded(pose);
            close(pose.left_hand_blend[2], 0.0);
        }
    }
}

#[test]
fn empty_hand_modes_support_through_discard_then_grip_replacement_and_receiver() {
    for timing in [
        ReloadVisualTiming::for_reload(true),
        timing_from_fields([0.08, 0.16, 0.31, 0.43, 0.61, 0.82]),
    ] {
        let fetch_span = timing.insert_start - timing.release_end;
        let open_end = timing.release_end + fetch_span * 0.30;
        let replacement_grip = timing.release_end + fetch_span * 0.60;
        let receiver_mid =
            timing.receiver_start + (timing.receiver_end - timing.receiver_start) * 0.50;
        for (t, expected) in [
            (0.0, SUPPORT_BLEND),
            (timing.release_start, SUPPORT_BLEND),
            (timing.release_end, OPEN_BLEND),
            (open_end, OPEN_BLEND),
            (replacement_grip, MAGAZINE_BLEND),
            (timing.insert_start, MAGAZINE_BLEND),
            (timing.insert_end, MAGAZINE_BLEND),
            (timing.receiver_start, RECEIVER_BLEND),
            (receiver_mid, RECEIVER_BLEND),
            (timing.receiver_end, RECEIVER_BLEND),
            (1.0, SUPPORT_BLEND),
        ] {
            let pose = sample_weapon_animation_with_timing(reload(t, 0.54, true), timing);
            bounded(pose);
            close4(pose.left_hand_blend, expected);
        }
        for (t, expected) in [
            (timing.release_start * 0.50, SUPPORT_BLEND),
            (
                timing.release_start + (timing.release_end - timing.release_start) * 0.50,
                [0.5, 0., 0., 0.5],
            ),
            (
                open_end + (replacement_grip - open_end) * 0.50,
                [0.0, 0.5, 0.0, 0.5],
            ),
        ] {
            let pose = sample_weapon_animation_with_timing(reload(t, 0.54, true), timing);
            bounded(pose);
            close4(pose.left_hand_blend, expected);
        }
    }
}

#[test]
fn hand_modes_do_not_depend_on_ads_recoil_sprint_or_credit_metadata() {
    for empty in [false, true] {
        for i in 0..=1000 {
            let input = reload(i as f32 / 1000.0, 0.54, empty);
            let expected = sample_weapon_animation(input).left_hand_blend;
            for value in [
                0.0,
                0.5,
                1.0,
                f32::NAN,
                f32::NEG_INFINITY,
                f32::INFINITY,
                -f32::MAX,
                f32::MAX,
            ] {
                let pose = sample_weapon_animation(AnimationInput {
                    reload_credit_fraction: value,
                    ads: value,
                    recoil: value,
                    sprint: value,
                    ..input
                });
                bounded(pose);
                assert_eq!(pose.left_hand_blend, expected);
            }
        }
    }
}

#[test]
fn supplied_ads_does_not_add_a_second_base_ads_position() {
    let idle = sample_weapon_animation(AnimationInput::default());
    for ads in [0.0, 0.25, 0.5, 0.75, 1.0] {
        let pose = sample_weapon_animation(AnimationInput {
            ads,
            ..AnimationInput::default()
        });
        close3(pose.weapon_translation, idle.weapon_translation);
        close3(pose.weapon_euler_yxz, idle.weapon_euler_yxz);
        close3(pose.right_grip, RIGHT_GRIP);
        close3(pose.left_grip, LEFT_GRIP);
    }
}

#[test]
fn right_grip_stays_on_its_absolute_weapon_local_socket() {
    for empty in [false, true] {
        for i in 0..=1000 {
            let input = AnimationInput {
                ads: 0.65,
                recoil: 0.4,
                sprint: 0.25,
                ..reload(i as f32 / 1000.0, 0.54, empty)
            };
            close3(sample_weapon_animation(input).right_grip, RIGHT_GRIP);
        }
    }
}

#[test]
fn neither_default_reload_invents_unconfirmed_bolt_travel() {
    for empty in [false, true] {
        for i in 0..=2000 {
            let pose = sample_weapon_animation(reload(i as f32 / 2000.0, 0.54, empty));
            close3(pose.bolt_translation, [0.0; 3]);
        }
    }
}

#[test]
fn credit_fraction_is_metadata_and_never_changes_visual_pose() {
    let credits = [
        0.0,
        f32::MIN_POSITIVE,
        0.000_001,
        0.25,
        0.4,
        1.1 / 2.029,
        0.7,
        0.999_999,
        1.0,
        -1.0,
        2.0,
        -f32::MAX,
        f32::MAX,
        f32::NEG_INFINITY,
        f32::INFINITY,
        f32::NAN,
    ];
    for empty in [false, true] {
        for i in 0..=1000 {
            let input = AnimationInput {
                ads: 0.4,
                recoil: 0.7,
                sprint: 0.2,
                ..reload(i as f32 / 1000.0, 0.54, empty)
            };
            let expected = sample_weapon_animation(input);
            for credit in credits {
                assert_eq!(
                    sample_weapon_animation(AnimationInput {
                        reload_credit_fraction: credit,
                        ..input
                    }),
                    expected,
                    "credit metadata affected visuals: t={:?}, credit={credit}, empty={empty}",
                    input.reload_progress
                );
            }
        }
    }
}

#[test]
fn default_visual_timings_match_the_documented_secondhand_and_authored_presets() {
    let tactical = ReloadVisualTiming::for_reload(false);
    let empty = ReloadVisualTiming::for_reload(true);
    for (actual, expected) in [
        (tactical.release_start, 0.24 / 2.21),
        (tactical.release_end, 0.50 / 2.21),
        (tactical.insert_start, 0.9421 / 2.21),
        (tactical.insert_end, 1.10 / 2.21),
        (tactical.receiver_start, 0.682),
        (tactical.receiver_end, 0.773),
        (empty.release_start, 0.14),
        (empty.release_end, 0.18),
        (empty.insert_start, 1.0484 / 2.2),
        (empty.insert_end, 1.2152 / 2.2),
        (empty.receiver_start, 1.6823 / 2.2),
        (empty.receiver_end, 1.7824 / 2.2),
    ] {
        close(actual, expected);
    }
    for empty in [false, true] {
        let timing = ReloadVisualTiming::for_reload(empty);
        for i in 0..=1000 {
            let input = reload(i as f32 / 1000.0, 0.54, empty);
            assert_eq!(
                sample_weapon_animation_with_timing(input, timing),
                sample_weapon_animation(input)
            );
        }
    }
}

#[test]
fn normalized_visual_windows_recover_observation_notes_within_one_reference_frame() {
    // This verifies transcription of secondhand approximate notes, not direct
    // frame measurements, engine event timing, or the gameplay durations.
    let tactical = ReloadVisualTiming::for_reload(false);
    let empty = ReloadVisualTiming::for_reload(true);
    let reference_frame_seconds = 1.0 / 59.94;
    for (phase, start, duration, observed) in [
        (tactical.insert_start, 7.8, 2.21, 8.7421),
        (tactical.insert_end, 7.8, 2.21, 8.9),
        (empty.release_start, 14.0, 2.2, 14.3),
        (empty.release_end, 14.0, 2.2, 14.4),
        (empty.insert_start, 14.0, 2.2, 15.0484),
        (empty.insert_end, 14.0, 2.2, 15.2152),
        (empty.receiver_start, 14.0, 2.2, 15.6823),
        (empty.receiver_end, 14.0, 2.2, 15.7824),
    ] {
        let reconstructed = start + f64::from(phase) * duration;
        assert!(
            (reconstructed - observed).abs() < reference_frame_seconds,
            "visual window transcription differs: {reconstructed} vs {observed}"
        );
    }
}

#[test]
fn magazine_seats_at_visual_insert_end_independently_of_credit() {
    for empty in [false, true] {
        let timing = ReloadVisualTiming::for_reload(empty);
        for credit in [0.25, 0.4, 0.7, 0.8, f32::NAN] {
            let seated = sample_weapon_animation(reload(timing.insert_end, credit, empty));
            close3(seated.magazine_translation, [0.0; 3]);
            close3(seated.left_grip, MAGAZINE_SEAT_HAND);
            let before = sample_weapon_animation(reload(
                (timing.insert_start + timing.insert_end) * 0.5,
                credit,
                empty,
            ));
            assert!(
                before.magazine_translation[1] < -0.001,
                "replacement seated too early"
            );
            for i in 0..=100 {
                let t = timing.insert_end + (1.0 - timing.insert_end) * i as f32 / 100.0;
                close3(
                    sample_weapon_animation(reload(t, credit, empty)).magazine_translation,
                    [0.0; 3],
                );
            }
        }
    }
}

#[test]
fn valid_timing_override_moves_visual_insertion_without_changing_credit_metadata() {
    let timing = ReloadVisualTiming {
        release_start: 0.08,
        release_end: 0.16,
        insert_start: 0.31,
        insert_end: 0.43,
        receiver_start: 0.61,
        receiver_end: 0.82,
    };
    for empty in [false, true] {
        let custom =
            sample_weapon_animation_with_timing(reload(timing.insert_end, 0.9, empty), timing);
        close3(custom.magazine_translation, [0.0; 3]);
        close3(custom.left_grip, MAGAZINE_SEAT_HAND);
        let default = sample_weapon_animation(reload(timing.insert_end, 0.9, empty));
        assert!(
            default
                .magazine_translation
                .iter()
                .map(|v| v * v)
                .sum::<f32>()
                > 0.001_f32.powi(2),
            "override did not move insertion timing"
        );
        for i in 0..=1000 {
            let input = AnimationInput {
                ads: 0.6,
                recoil: 0.3,
                sprint: 0.2,
                ..reload(i as f32 / 1000.0, 0.9, empty)
            };
            let expected = sample_weapon_animation_with_timing(input, timing);
            bounded(expected);
            close3(expected.right_grip, RIGHT_GRIP);
            close3(expected.bolt_translation, [0.0; 3]);
            for credit in [0.0, 0.25, 0.8, 1.0, f32::NAN, f32::INFINITY] {
                assert_eq!(
                    sample_weapon_animation_with_timing(
                        AnimationInput {
                            reload_credit_fraction: credit,
                            ..input
                        },
                        timing
                    ),
                    expected
                );
            }
            // Overrides remain pure under repeated and out-of-order sampling.
            let _ = sample_weapon_animation_with_timing(
                reload(1.0 - i as f32 / 1000.0, 0.9, empty),
                timing,
            );
            assert_eq!(sample_weapon_animation_with_timing(input, timing), expected);
        }
        for t in [0.0, 1.0] {
            let input = AnimationInput {
                ads: 0.6,
                recoil: 0.3,
                sprint: 0.2,
                ..reload(t, 0.9, empty)
            };
            close_pose(
                sample_weapon_animation_with_timing(input, timing),
                sample_weapon_animation(AnimationInput {
                    reload_progress: None,
                    ..input
                }),
            );
        }
    }
}

fn timing_from_fields(fields: [f32; 6]) -> ReloadVisualTiming {
    ReloadVisualTiming {
        release_start: fields[0],
        release_end: fields[1],
        insert_start: fields[2],
        insert_end: fields[3],
        receiver_start: fields[4],
        receiver_end: fields[5],
    }
}

#[test]
fn invalid_visual_timing_falls_back_to_the_whole_reload_kind_preset() {
    // Every untouched field deliberately differs from the default. A partial
    // repair would therefore fail these full-pose comparisons.
    let valid = [0.08, 0.16, 0.31, 0.43, 0.61, 0.82];
    let mut invalid = Vec::new();
    for field in 0..valid.len() {
        for bad in [
            f32::NAN,
            f32::NEG_INFINITY,
            f32::INFINITY,
            -f32::MAX,
            f32::MAX,
            -0.1,
            0.0,
            1.0,
            1.1,
        ] {
            let mut fields = valid;
            fields[field] = bad;
            invalid.push(timing_from_fields(fields));
        }
    }
    for field in 0..valid.len() - 1 {
        let mut equal = valid;
        equal[field + 1] = equal[field];
        invalid.push(timing_from_fields(equal));
        let mut reversed = valid;
        reversed.swap(field, field + 1);
        invalid.push(timing_from_fields(reversed));
    }
    for empty in [false, true] {
        for &timing in &invalid {
            for i in 0..=200 {
                let input = AnimationInput {
                    ads: 0.3,
                    recoil: 0.4,
                    sprint: 0.2,
                    ..reload(i as f32 / 200.0, f32::NAN, empty)
                };
                let actual = sample_weapon_animation_with_timing(input, timing);
                bounded(actual);
                assert_eq!(
                    actual,
                    sample_weapon_animation(input),
                    "invalid timing did not use whole fallback"
                );
            }
        }
    }
}

#[test]
fn tightly_spaced_valid_visual_windows_remain_finite_and_endpoint_safe() {
    // Derived midpoints can round onto neighboring keys at f32 resolution.
    // These profiles promise finite output, not a renderable visual duration.
    let subnormal = timing_from_fields(std::array::from_fn(|i| f32::from_bits(i as u32 + 1)));
    let adjacent = timing_from_fields(std::array::from_fn(|i| {
        f32::from_bits(0.5_f32.to_bits() + i as u32)
    }));
    let near_end = timing_from_fields(std::array::from_fn(|i| {
        f32::from_bits(1.0_f32.to_bits() - 6 + i as u32)
    }));
    for empty in [false, true] {
        for timing in [subnormal, adjacent, near_end] {
            let boundaries = [
                timing.release_start,
                timing.release_end,
                timing.insert_start,
                timing.insert_end,
                timing.receiver_start,
                timing.receiver_end,
            ];
            for t in boundaries
                .into_iter()
                .chain((0..=1000).map(|i| i as f32 / 1000.0))
            {
                let pose = sample_weapon_animation_with_timing(reload(t, 0.54, empty), timing);
                bounded(pose);
                close3(pose.right_grip, RIGHT_GRIP);
                close3(pose.bolt_translation, [0.0; 3]);
            }
            for t in [0.0, 1.0] {
                close_pose(
                    sample_weapon_animation_with_timing(reload(t, 0.54, empty), timing),
                    sample_weapon_animation(AnimationInput::default()),
                );
            }
        }
    }
}

#[test]
fn empty_reload_discards_magazine_left_and_releases_it_from_the_hand() {
    let timing = ReloadVisualTiming::for_reload(true);
    let mut leftward_throw = false;
    let mut released = false;
    for i in 0..=1000 {
        let t =
            timing.release_start + (timing.insert_start - timing.release_start) * i as f32 / 1000.0;
        let pose = sample_weapon_animation(reload(t, 0.54, true));
        if pose.seated_magazine_translation[0] < -0.25 {
            leftward_throw = true;
            let hand_relative_to_seat = pose.left_grip[0] - MAGAZINE_SEAT_HAND[0];
            if (hand_relative_to_seat - pose.seated_magazine_translation[0]).abs() > 0.15 {
                released = true;
            }
        }
    }
    assert!(
        leftward_throw,
        "empty magazine did not travel clearly leftward"
    );
    assert!(
        released,
        "left hand never visibly separated from the discarded magazine"
    );
}

#[test]
fn replacement_magazine_rises_from_below_during_visual_insertion() {
    for empty in [false, true] {
        let timing = ReloadVisualTiming::for_reload(empty);
        let mut previous_y = sample_weapon_animation(reload(timing.insert_start, 0.54, empty))
            .magazine_translation[1];
        assert!(
            previous_y < -0.05,
            "replacement should start below its seat"
        );
        for i in 1..=100 {
            let t =
                timing.insert_start + (timing.insert_end - timing.insert_start) * i as f32 / 100.0;
            let pose = sample_weapon_animation(reload(t, 0.54, empty));
            assert!(
                pose.magazine_translation[1] >= previous_y - EPSILON,
                "replacement did not rise toward its seat"
            );
            assert!(
                pose.magazine_translation[1] <= EPSILON,
                "replacement overshot above its seat"
            );
            previous_y = pose.magazine_translation[1];
        }
        close(previous_y, 0.0);
    }
}

#[test]
fn only_empty_reload_has_a_post_insertion_receiver_area_hand_gesture() {
    let timing = ReloadVisualTiming::for_reload(true);
    let mut empty_reached_receiver = false;
    for i in 0..=1000 {
        let t = timing.receiver_start
            + (timing.receiver_end - timing.receiver_start) * i as f32 / 1000.0;
        assert!(t > timing.insert_end);
        let empty = sample_weapon_animation(reload(t, 0.54, true));
        let tactical = sample_weapon_animation(reload(t, 0.54, false));
        let empty_distance: f32 = empty
            .left_grip
            .iter()
            .zip(RECEIVER_HAND.iter())
            .map(|(a, b)| (a - b).powi(2))
            .sum();
        if empty_distance < 0.025_f32.powi(2) {
            empty_reached_receiver = true;
            assert!(
                tactical.left_hand_blend[2] == 0.0,
                "tactical unexpectedly has a receiver gesture"
            );
        }
        close3(empty.magazine_translation, [0.0; 3]);
        close3(tactical.magazine_translation, [0.0; 3]);
        close3(empty.bolt_translation, [0.0; 3]);
        close3(tactical.bolt_translation, [0.0; 3]);
    }
    assert!(
        empty_reached_receiver,
        "empty reload lacks a receiver-area hand gesture"
    );
}

#[test]
fn no_reload_keeps_magazine_and_bolt_seated() {
    for empty in [false, true] {
        let pose = sample_weapon_animation(AnimationInput {
            empty_reload: empty,
            ads: 0.8,
            recoil: 0.75,
            sprint: 0.6,
            ..AnimationInput::default()
        });
        close3(pose.magazine_translation, [0.0; 3]);
        close3(pose.bolt_translation, [0.0; 3]);
    }
}

#[test]
fn presentation_sampling_is_deterministic_and_order_independent() {
    let inputs: Vec<_> = (0..257)
        .map(|i| AnimationInput {
            reload_progress: Some(i as f32 / 256.0),
            reload_credit_fraction: 0.51,
            empty_reload: i % 2 == 0,
            ads: (i % 11) as f32 / 10.0,
            recoil: (i % 7) as f32 / 6.0,
            sprint: (i % 5) as f32 / 4.0,
        })
        .collect();
    let expected: Vec<_> = inputs
        .iter()
        .copied()
        .map(sample_weapon_animation)
        .collect();
    for i in (0..inputs.len()).rev() {
        assert_eq!(sample_weapon_animation(inputs[i]), expected[i]);
    }
    // A full permutation, rather than just monotonically increasing time.
    for step in 0..inputs.len() {
        let i = (step * 73) % inputs.len();
        assert_eq!(sample_weapon_animation(inputs[i]), expected[i]);
    }
}

#[test]
fn dense_sampling_is_finite_bounded_and_continuous() {
    for empty in [false, true] {
        for credit in [0.25, 1.1 / 2.029, 0.8] {
            let mut previous = sample_weapon_animation(reload(0.0, credit, empty));
            for i in 1..=10_000 {
                let t = i as f32 / 10_000.0;
                let current = sample_weapon_animation(reload(t, credit, empty));
                bounded(current);
                for (a, b) in channels(previous).iter().zip(channels(current).iter()) {
                    assert!(
                        (a - b).abs() < 0.02,
                        "discontinuity at t={t}, credit={credit}, empty={empty}: {previous:?} -> {current:?}"
                    );
                }
                previous = current;
            }
        }
    }
}

#[test]
fn visual_timing_boundaries_are_continuous_from_both_sides() {
    for empty in [false, true] {
        for timing in [
            ReloadVisualTiming::for_reload(empty),
            ReloadVisualTiming {
                release_start: 0.08,
                release_end: 0.16,
                insert_start: 0.31,
                insert_end: 0.43,
                receiver_start: 0.61,
                receiver_end: 0.82,
            },
        ] {
            let fetch_span = timing.insert_start - timing.release_end;
            for boundary in [
                timing.release_start,
                timing.release_end,
                timing.release_end + fetch_span * 0.30,
                timing.release_end + fetch_span * 0.50,
                timing.release_end + fetch_span * 0.60,
                timing.insert_start,
                timing.insert_end,
                timing.insert_end + (1.0 - timing.insert_end) * 0.27,
                timing.receiver_start,
                timing.receiver_end,
                timing.receiver_start + (timing.receiver_end - timing.receiver_start) * 0.50,
            ] {
                let at = channels(sample_weapon_animation_with_timing(
                    reload(boundary, 0.54, empty),
                    timing,
                ));
                for t in [boundary - 0.000_001, boundary + 0.000_001] {
                    let adjacent = channels(sample_weapon_animation_with_timing(
                        reload(t, 0.54, empty),
                        timing,
                    ));
                    for i in 0..at.len() {
                        assert!(
                            (at[i] - adjacent[i]).abs() < 0.000_1,
                            "jump at visual boundary {boundary}"
                        );
                    }
                }
            }
        }
    }
}

#[test]
fn invalid_inputs_cannot_leak_nan_infinity_or_unbounded_offsets() {
    let bad = [
        f32::NAN,
        f32::NEG_INFINITY,
        f32::INFINITY,
        -f32::MAX,
        f32::MAX,
        -1.0,
        2.0,
    ];
    for empty in [false, true] {
        for value in bad {
            let input = reload(0.6, 1.1 / 2.029, empty);
            bounded(sample_weapon_animation(AnimationInput {
                reload_progress: Some(value),
                ..input
            }));
            bounded(sample_weapon_animation(AnimationInput {
                reload_credit_fraction: value,
                ..input
            }));
            bounded(sample_weapon_animation(AnimationInput {
                ads: value,
                ..input
            }));
            bounded(sample_weapon_animation(AnimationInput {
                recoil: value,
                ..input
            }));
            bounded(sample_weapon_animation(AnimationInput {
                sprint: value,
                ..input
            }));
            bounded(sample_weapon_animation(AnimationInput {
                reload_progress: Some(value),
                reload_credit_fraction: value,
                ads: value,
                recoil: value,
                sprint: value,
                ..input
            }));
        }
    }
}

#[test]
fn zero_one_and_tiny_credit_fractions_remain_safe() {
    for empty in [false, true] {
        for credit in [0.0, f32::MIN_POSITIVE, 0.000_001, 0.999_999, 1.0] {
            for i in 0..=1000 {
                bounded(sample_weapon_animation(reload(
                    i as f32 / 1000.0,
                    credit,
                    empty,
                )));
            }
        }
    }
}

#[test]
fn published_candidate_timing_constants_have_the_documented_units() {
    assert_eq!(ADS_SECONDS, 0.250);
    assert_eq!(SPRINT_OUT_SECONDS, 0.300);
    assert_eq!(TACTICAL_RELOAD_SECONDS, 2.029);
    assert_eq!(EMPTY_RELOAD_SECONDS, 2.359);
}

#[test]
fn timestamp_adapter_clamps_start_midpoint_completion_and_overshoot() {
    for duration in [TACTICAL_RELOAD_SECONDS, EMPTY_RELOAD_SECONDS] {
        assert_eq!(reload_progress_at(10.0, 10.0, duration), Some(0.0));
        close(
            reload_progress_at(10.0 + duration * 0.5, 10.0, duration).unwrap(),
            0.5,
        );
        close(
            reload_progress_at(10.0 + duration, 10.0, duration).unwrap(),
            1.0,
        );
        assert_eq!(reload_progress_at(100.0, 10.0, duration), Some(1.0));
    }
    // Large finite timestamps can overflow their difference. The returned
    // progress must nevertheless remain finite and clamped.
    assert_eq!(reload_progress_at(f64::MAX, -f64::MAX, 1.0), Some(1.0));
}

#[test]
fn timestamp_adapter_rejects_future_start_and_invalid_times_or_durations() {
    assert_eq!(reload_progress_at(9.0, 10.0, 2.0), None);
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert_eq!(reload_progress_at(value, 0.0, 2.0), None);
        assert_eq!(reload_progress_at(1.0, value, 2.0), None);
    }
    for duration in [0.0, -1.0, f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert_eq!(reload_progress_at(1.0, 0.0, duration), None);
    }
}

#[test]
fn timestamp_adapter_feeds_endpoint_safe_sampling() {
    let idle = sample_weapon_animation(AnimationInput::default());
    for now in [9.0, 10.0, 10.0 + TACTICAL_RELOAD_SECONDS, 100.0] {
        let pose = sample_weapon_animation(AnimationInput {
            reload_progress: reload_progress_at(now, 10.0, TACTICAL_RELOAD_SECONDS),
            ..AnimationInput::default()
        });
        close_pose(pose, idle);
    }
}

#[test]
fn transition_respects_full_duration_and_clamps_after_completion() {
    for duration in [ADS_SECONDS, SPRINT_OUT_SECONDS] {
        close(sample_transition(-1.0, 0.0, 0.0, 1.0, duration), 0.0);
        close(sample_transition(0.0, 0.0, 0.0, 1.0, duration), 0.0);
        close(
            sample_transition(duration * 0.5, 0.0, 0.0, 1.0, duration),
            0.5,
        );
        close(sample_transition(duration, 0.0, 0.0, 1.0, duration), 1.0);
        close(
            sample_transition(duration * 10.0, 0.0, 0.0, 1.0, duration),
            1.0,
        );
    }
    // A partial traversal keeps the same speed instead of taking a full
    // duration to cover only part of the normalized range.
    close(sample_transition(0.3, 0.0, 0.2, 0.8, 1.0), 0.5);
    close(sample_transition(0.6, 0.0, 0.2, 0.8, 1.0), 0.8);
}

#[test]
fn interrupted_transition_reversal_preserves_position_and_speed() {
    let interrupted_at = ADS_SECONDS * 0.6;
    let captured = sample_transition(interrupted_at, 0.0, 0.0, 1.0, ADS_SECONDS);
    close(captured, 0.6);
    close(
        sample_transition(interrupted_at, interrupted_at, captured, 0.0, ADS_SECONDS),
        captured,
    );
    close(
        sample_transition(
            interrupted_at + ADS_SECONDS * 0.3,
            interrupted_at,
            captured,
            0.0,
            ADS_SECONDS,
        ),
        0.3,
    );
    close(
        sample_transition(
            interrupted_at + ADS_SECONDS * 0.6,
            interrupted_at,
            captured,
            0.0,
            ADS_SECONDS,
        ),
        0.0,
    );
    close(
        sample_transition(1.0, interrupted_at, captured, 0.0, ADS_SECONDS),
        0.0,
    );
}

#[test]
fn invalid_transition_times_preserve_sanitized_start_and_invalid_duration_snaps() {
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        close(sample_transition(value, 0.0, 0.4, 0.9, 1.0), 0.4);
        close(sample_transition(0.0, value, 0.4, 0.9, 1.0), 0.4);
    }
    close(sample_transition(0.0, 1.0, 0.4, 0.9, 1.0), 0.4);
    for duration in [0.0, -1.0, f64::NAN, f64::INFINITY] {
        close(sample_transition(0.0, 0.0, 0.4, 0.9, duration), 0.9);
    }
    for from in [
        f32::NAN,
        f32::NEG_INFINITY,
        f32::INFINITY,
        -f32::MAX,
        f32::MAX,
    ] {
        for to in [
            f32::NAN,
            f32::NEG_INFINITY,
            f32::INFINITY,
            -f32::MAX,
            f32::MAX,
        ] {
            let value = sample_transition(0.5, 0.0, from, to, 1.0);
            assert!(value.is_finite() && (0.0..=1.0).contains(&value));
        }
    }
}

#[test]
fn transition_is_order_independent_including_repeat_and_reverse_sampling() {
    let times = [0.0, 0.012, 0.100, 0.200, 0.249, 0.25, 10.0];
    let expected: Vec<_> = times
        .iter()
        .map(|&now| sample_transition(now, 0.0, 0.0, 1.0, ADS_SECONDS))
        .collect();
    for i in (0..times.len()).rev() {
        assert_eq!(
            sample_transition(times[i], 0.0, 0.0, 1.0, ADS_SECONDS),
            expected[i]
        );
    }
}
