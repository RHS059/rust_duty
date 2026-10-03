//! Regression targets from the reviewed native tactical captures. These keep
//! the weapon-IK hierarchy change from replacing the fitted reload gestures.
use macroquad::math::{EulerRot, Mat4, Quat, Vec3};
use vector_range::arms::{ArmFreeHandPose, ArmModel};
use vector_range::skinned_asset::{Bone, SkinnedAsset};
use vector_range::view_animation::{HandPresentationFrames, ViewAnimation, WeaponFrame};
use vector_range::weapon_animation::{
    effective_hand_orientation, AnimationInput, WeaponAnimationPose,
};
use vector_range::weapon_ik::{blend_hand_constraint, HandPose, WeaponIkRig};

const HIP: Vec3 = Vec3::new(0.05930, -0.04831, -0.30806);

fn rotation_error(a: Quat, b: Quat) -> f32 {
    // q and -q describe the same rigid orientation.
    1. - a.normalize().dot(b.normalize()).abs()
}

fn synthetic_arms() -> ArmModel {
    let mut bones = Vec::new();
    for (side, shoulder_x) in [("l", 0.2), ("r", -0.2)] {
        let start = bones.len();
        for (segment, name) in ["upperarm", "lowerarm", "hand"].into_iter().enumerate() {
            let position = if segment == 0 {
                Vec3::new(shoulder_x, 1.4, 0.1)
            } else {
                Vec3::X * 0.35
            };
            bones.push(Bone {
                name: format!("{name}_{side}"),
                parent: (segment > 0).then_some(start + segment.saturating_sub(1)),
                rest_local: Mat4::from_translation(position).to_cols_array(),
                inverse_bind: Mat4::IDENTITY.to_cols_array(),
            });
        }
    }
    ArmModel::new(SkinnedAsset {
        bones,
        meshes: Vec::new(),
    })
    .expect("original synthetic fixture must load without a GPU")
}

fn assert_wrist(global: Mat4, expected: HandPose) {
    let (_, orientation, position) = global.to_scale_rotation_translation();
    assert!(
        position.distance(expected.position) < 0.00001,
        "wrist position {position:?} differs from {expected:?}"
    );
    assert!(
        rotation_error(orientation, expected.orientation) < 0.000001,
        "wrist orientation {orientation:?} differs from {expected:?}"
    );
}

fn in_frame(hand: HandPose, frame: Mat4) -> HandPose {
    HandPose::new(
        frame.transform_point3(hand.position),
        frame.to_scale_rotation_translation().1 * hand.orientation,
    )
}

fn body_frame() -> Mat4 {
    Mat4::from_rotation_translation(Quat::from_euler(EulerRot::YXZ, 0.04118, -0.01252, 0.), HIP)
}

fn routed_frame(
    presentation: &mut ViewAnimation,
    input: AnimationInput,
    completed: bool,
    now: f64,
    weapon_only_motion: Mat4,
) -> (WeaponAnimationPose, HandPresentationFrames) {
    let pose = presentation.sample_input(input, completed, now);
    let body = body_frame();
    let live = weapon_only_motion * body * WeaponFrame::new(Vec3::ZERO, &pose).matrix;
    (pose, presentation.hand_presentation().frames(body, live))
}

#[test]
fn reviewed_tactical_key_poses_survive_the_ik_hierarchy_change() {
    // Native elapsed = frame * 1001 / 60000. The paired reference is source
    // frame 468 + native frame. Do not normalize source PTS a second time.
    // Frames 102/108 retain the reviewed wrist positions with the accepted
    // Trial1 open-hand preorientation for the underhand return. Frames 112/120
    // use the accepted candidate-2 underside-handguard support calibration;
    // those two expected transforms intentionally supersede the old side grip.
    let cases = [
        (
            102,
            [-0.061268516, -0.22377563, -0.5448383],
            [0.7751243, 0.3011538, -0.48749068, 0.26616064],
        ),
        (
            108,
            [-0.03442742, -0.16111463, -0.5205663],
            [0.7807078, 0.13258737, -0.25490323, 0.5549237],
        ),
        (
            112,
            [-0.01182713, -0.15755598, -0.5103226],
            [0.71689624, 0.09682563, -0.11275402, 0.68115425],
        ),
        (
            120,
            [-0.01440052, -0.19185373, -0.50489396],
            [0.6875854, 0.114_551_7, -0.10965414, 0.7085762],
        ),
    ];
    let arms = synthetic_arms();
    for (native_frame, position, orientation) in cases {
        let elapsed = native_frame as f32 * 1001. / 60000.;
        let phase = elapsed / 2.21;
        let mut presentation = ViewAnimation::default();
        let pose = presentation.sample_input(
            AnimationInput {
                reload_progress: Some(phase),
                ..Default::default()
            },
            false,
            elapsed as f64,
        );
        let weapon = WeaponFrame::with_orientation(
            HIP,
            Quat::from_euler(EulerRot::YXZ, 0.04118, -0.01252, 0.),
            &pose,
        );
        let wrist = weapon.point(Vec3::from_array(pose.left_grip));
        let wrist_rotation = weapon.matrix.to_scale_rotation_translation().1
            * Quat::from_array(effective_hand_orientation(&pose));
        assert!(
            wrist.distance(Vec3::from_array(position)) < 0.00001,
            "native frame {native_frame}: fitted wrist moved: {wrist:?}"
        );
        assert!(
            rotation_error(wrist_rotation, Quat::from_array(orientation)) < 0.000001,
            "native frame {native_frame}: fitted wrist orientation changed"
        );
        let routed = presentation
            .hand_presentation()
            .frames(body_frame(), weapon.matrix);
        let globals = arms.posed_globals_with_weapon_ik(
            &routed.targets,
            routed.free_frame,
            &pose,
            routed.free_hands,
            routed.influences,
            pose.left_hand_blend,
        );
        assert_wrist(
            globals[2],
            HandPose::new(Vec3::from_array(position), Quat::from_array(orientation)),
        );
    }
}

#[test]
fn actual_presentation_routing_keeps_released_hand_and_held_prop_off_weapon_motion() {
    let arms = synthetic_arms();
    for (empty, phase) in [(false, 0.316742), (false, 0.77), (true, 0.45)] {
        let mut calm = ViewAnimation::default();
        let mut moving = ViewAnimation::default();
        let input = AnimationInput {
            reload_progress: Some(phase),
            empty_reload: empty,
            ..Default::default()
        };
        let (calm_pose, calm_route) = routed_frame(&mut calm, input, false, 3., Mat4::IDENTITY);
        let weapon_motion = Mat4::from_rotation_translation(
            Quat::from_rotation_z(0.09),
            Vec3::new(0.02, 0.012, -0.015),
        );
        let (moving_pose, moving_route) = routed_frame(
            &mut moving,
            AnimationInput {
                recoil: 0.9,
                sprint: 0.15,
                ..input
            },
            false,
            3.,
            weapon_motion,
        );
        assert_eq!(calm_route.influences, [0., 1.]);
        assert_eq!(moving_route.influences, [0., 1.]);
        assert_eq!(calm_route.free_frame, moving_route.free_frame);
        assert_eq!(calm_route.free_hands, moving_route.free_hands);
        let calm_globals = arms.posed_globals_with_weapon_ik(
            &calm_route.targets,
            calm_route.free_frame,
            &calm_pose,
            calm_route.free_hands,
            calm_route.influences,
            calm_pose.left_hand_blend,
        );
        let moving_globals = arms.posed_globals_with_weapon_ik(
            &moving_route.targets,
            moving_route.free_frame,
            &moving_pose,
            moving_route.free_hands,
            moving_route.influences,
            moving_pose.left_hand_blend,
        );
        assert_wrist(
            moving_globals[2],
            HandPose::new(
                calm_globals[2].w_axis.truncate(),
                calm_globals[2].to_scale_rotation_translation().1,
            ),
        );
        assert_wrist(moving_globals[5], moving_route.targets.right);
        assert!(
            calm_route
                .targets
                .right
                .position
                .distance(moving_route.targets.right.position)
                > 0.01
        );
        if calm_pose.left_hand_blend[1] >= 0.99 {
            let live =
                weapon_motion * body_frame() * WeaponFrame::new(Vec3::ZERO, &moving_pose).matrix;
            let prop = moving
                .hand_presentation()
                .held_magazine_matrix(body_frame(), live);
            let seat = Vec3::from_array(vector_range::arms::FITTED_MAGAZINE_WRIST);
            assert!(
                moving_globals[2]
                    .w_axis
                    .truncate()
                    .distance(prop.transform_point3(seat))
                    < 0.00001,
                "released hand lost its held magazine under live weapon motion: empty={empty}, phase={phase}, error={}mm, clip_offset={:?}, free_hand={:?}, actual_hand={:?}, prop_seat={:?}",
                moving_globals[2].w_axis.truncate().distance(prop.transform_point3(seat)) * 1000.,
                moving.hand_presentation().clip_pose.magazine_translation,
                moving_route.free_hands.left.position,
                moving_globals[2].w_axis.truncate(),
                prop.transform_point3(seat),
            );
        }
    }
}

#[test]
fn cancellation_keeps_a_visible_held_magazine_at_the_constrained_hand() {
    let arms = synthetic_arms();
    let seat = Vec3::from_array(vector_range::arms::FITTED_MAGAZINE_WRIST);
    for (empty_reload, phase) in [(false, 0.316742), (true, 0.45)] {
        let mut presentation = ViewAnimation::default();
        routed_frame(
            &mut presentation,
            AnimationInput {
                reload_progress: Some(phase),
                empty_reload,
                ..Default::default()
            },
            false,
            20.,
            Mat4::IDENTITY,
        );
        routed_frame(
            &mut presentation,
            AnimationInput::default(),
            false,
            20.01,
            Mat4::IDENTITY,
        );
        for elapsed in [0.007, 0.014, 0.028, 0.042, 0.056] {
            let (pose, route) = routed_frame(
                &mut presentation,
                AnimationInput::default(),
                false,
                20.01 + elapsed,
                Mat4::IDENTITY,
            );
            if !pose.magazine_visibility[1] {
                continue;
            }
            let live = body_frame() * WeaponFrame::new(Vec3::ZERO, &pose).matrix;
            let prop = presentation
                .hand_presentation()
                .held_magazine_matrix(body_frame(), live);
            let globals = arms.posed_globals_with_weapon_ik(
                &route.targets,
                route.free_frame,
                &pose,
                route.free_hands,
                route.influences,
                pose.left_hand_blend,
            );
            let error = globals[2]
                .w_axis
                .truncate()
                .distance(prop.transform_point3(seat));
            assert!(error < 0.005,
                "cancel elapsed {elapsed:.3}, empty={empty_reload}: visible held magazine is {:.2}mm from wrist; influence={:?}",
                error * 1000., route.influences);
        }
    }
}

#[test]
fn cancellation_holds_free_endpoint_and_reacquires_once_then_restart_replaces_it() {
    let mut presentation = ViewAnimation::default();
    let reload = AnimationInput {
        reload_progress: Some(0.77),
        ..Default::default()
    };
    let (_, outgoing) = routed_frame(&mut presentation, reload, false, 10., Mat4::IDENTITY);
    let outgoing_clip = presentation.hand_presentation().clip_pose;
    let (_, beginning) = routed_frame(
        &mut presentation,
        AnimationInput::default(),
        false,
        10.02,
        Mat4::IDENTITY,
    );
    assert_eq!(beginning.free_frame, outgoing.free_frame);
    assert_eq!(beginning.free_hands, outgoing.free_hands);
    assert_eq!(beginning.influences, outgoing.influences);
    let (_, halfway) = routed_frame(
        &mut presentation,
        AnimationInput::default(),
        false,
        10.09,
        Mat4::IDENTITY,
    );
    assert_eq!(presentation.hand_presentation().clip_pose, outgoing_clip);
    assert_eq!(halfway.free_frame, outgoing.free_frame);
    assert_eq!(halfway.free_hands, outgoing.free_hands);
    assert!((halfway.influences[0] - 0.5).abs() < 0.000001);
    assert_eq!(halfway.influences[1], 1.);
    let restart_input = AnimationInput {
        reload_progress: Some(0.815_294_15),
        ..Default::default()
    };
    let (_, restarted) = routed_frame(
        &mut presentation,
        restart_input,
        false,
        10.10,
        Mat4::IDENTITY,
    );
    assert_eq!(restarted.influences, [0., 1.]);
    let (restarted_pose, restarted) = routed_frame(
        &mut presentation,
        restart_input,
        false,
        10.241,
        Mat4::IDENTITY,
    );
    let mut fresh = ViewAnimation::default();
    let (fresh_pose, fresh_route) =
        routed_frame(&mut fresh, restart_input, false, 10.241, Mat4::IDENTITY);
    assert_eq!(restarted_pose, fresh_pose);
    assert_eq!(restarted.free_frame, fresh_route.free_frame);
    assert_eq!(restarted.free_hands, fresh_route.free_hands);
    assert_eq!(restarted.influences, [0., 1.]);
    routed_frame(
        &mut presentation,
        AnimationInput::default(),
        false,
        10.25,
        Mat4::IDENTITY,
    );
    let (_, finished) = routed_frame(
        &mut presentation,
        AnimationInput::default(),
        false,
        10.391,
        Mat4::IDENTITY,
    );
    assert_eq!(finished.influences, [1., 1.]);
}

#[test]
fn a_reload_restart_during_cancellation_preserves_the_current_wrist_pose() {
    let arms = synthetic_arms();
    for portion in [0.25, 0.50, 0.75] {
        let mut presentation = ViewAnimation::default();
        routed_frame(
            &mut presentation,
            AnimationInput {
                reload_progress: Some(0.77),
                ..Default::default()
            },
            false,
            30.,
            Mat4::IDENTITY,
        );
        routed_frame(
            &mut presentation,
            AnimationInput::default(),
            false,
            30.01,
            Mat4::IDENTITY,
        );
        let now = 30.01 + 0.14 * portion;
        let (before_pose, before) = routed_frame(
            &mut presentation,
            AnimationInput::default(),
            false,
            now,
            Mat4::IDENTITY,
        );
        let (after_pose, after) = routed_frame(
            &mut presentation,
            AnimationInput {
                reload_progress: Some(0.),
                ..Default::default()
            },
            false,
            now + 1e-7,
            Mat4::IDENTITY,
        );
        let before_globals = arms.posed_globals_with_weapon_ik(
            &before.targets,
            before.free_frame,
            &before_pose,
            before.free_hands,
            before.influences,
            before_pose.left_hand_blend,
        );
        let after_globals = arms.posed_globals_with_weapon_ik(
            &after.targets,
            after.free_frame,
            &after_pose,
            after.free_hands,
            after.influences,
            after_pose.left_hand_blend,
        );
        let gap = before_globals[2]
            .w_axis
            .truncate()
            .distance(after_globals[2].w_axis.truncate());
        assert!(
            gap < 0.0001,
            "reload restart at {:.0}% cancellation jumps left wrist {:.2}mm",
            portion * 100.,
            gap * 1000.
        );
    }
}

#[test]
fn canceling_again_during_restart_preserves_both_wrists_and_finger_weights() {
    let arms = synthetic_arms();
    let mut presentation = ViewAnimation::default();
    routed_frame(
        &mut presentation,
        AnimationInput {
            reload_progress: Some(0.77),
            ..Default::default()
        },
        false,
        40.,
        Mat4::IDENTITY,
    );
    let mut now = 40.01;
    for portion in [0.25, 0.50, 0.75] {
        routed_frame(
            &mut presentation,
            AnimationInput::default(),
            false,
            now,
            Mat4::IDENTITY,
        );
        now += 0.14 * portion;
        routed_frame(
            &mut presentation,
            AnimationInput::default(),
            false,
            now,
            Mat4::IDENTITY,
        );
        now += 1e-7;
        routed_frame(
            &mut presentation,
            AnimationInput {
                reload_progress: Some(0.),
                ..Default::default()
            },
            false,
            now,
            Mat4::IDENTITY,
        );
        now += 0.14 * portion;
        let (before_pose, before) = routed_frame(
            &mut presentation,
            AnimationInput {
                reload_progress: Some((0.14 * portion / 2.21) as f32),
                ..Default::default()
            },
            false,
            now,
            Mat4::IDENTITY,
        );
        now += 1e-7;
        let (after_pose, after) = routed_frame(
            &mut presentation,
            AnimationInput::default(),
            false,
            now,
            Mat4::IDENTITY,
        );
        let previous = arms.posed_globals_with_weapon_ik(
            &before.targets,
            before.free_frame,
            &before_pose,
            before.free_hands,
            before.influences,
            before_pose.left_hand_blend,
        );
        let current = arms.posed_globals_with_weapon_ik(
            &after.targets,
            after.free_frame,
            &after_pose,
            after.free_hands,
            after.influences,
            after_pose.left_hand_blend,
        );
        for hand in [2, 5] {
            assert_wrist(
                current[hand],
                HandPose::new(
                    previous[hand].w_axis.truncate(),
                    previous[hand].to_scale_rotation_translation().1,
                ),
            );
        }
        for (a, b) in before_pose
            .left_hand_blend
            .into_iter()
            .zip(after_pose.left_hand_blend)
        {
            assert!(
                (a - b).abs() < 0.00001,
                "finger weights snapped during cancel/restart"
            );
        }
        now += 0.01;
    }
}

#[test]
fn restarting_a_canceled_magazine_carry_keeps_the_visible_prop_continuous() {
    let seat = Vec3::from_array(vector_range::arms::FITTED_MAGAZINE_WRIST);
    for (empty_reload, phase) in [(false, 0.316742), (true, 0.45)] {
        let mut presentation = ViewAnimation::default();
        routed_frame(
            &mut presentation,
            AnimationInput {
                reload_progress: Some(phase),
                empty_reload,
                ..Default::default()
            },
            false,
            50.,
            Mat4::IDENTITY,
        );
        routed_frame(
            &mut presentation,
            AnimationInput::default(),
            false,
            50.01,
            Mat4::IDENTITY,
        );
        let (before, _) = routed_frame(
            &mut presentation,
            AnimationInput::default(),
            false,
            50.045,
            Mat4::IDENTITY,
        );
        let before_matrix = presentation.hand_presentation().held_magazine_matrix(
            body_frame(),
            body_frame() * WeaponFrame::new(Vec3::ZERO, &before).matrix,
        );
        let (after, _) = routed_frame(
            &mut presentation,
            AnimationInput {
                reload_progress: Some(0.),
                empty_reload,
                ..Default::default()
            },
            false,
            50.0450001,
            Mat4::IDENTITY,
        );
        let after_matrix = presentation.hand_presentation().held_magazine_matrix(
            body_frame(),
            body_frame() * WeaponFrame::new(Vec3::ZERO, &after).matrix,
        );
        assert!(
            before.magazine_visibility[1] && after.magazine_visibility[1],
            "fixture must exercise an actor visible on both sides of restart"
        );
        let gap = before_matrix
            .transform_point3(seat)
            .distance(after_matrix.transform_point3(seat));
        assert!(
            gap < 0.0001,
            "empty={empty_reload}: visible carried prop jumps {:.2}mm on cancellation restart",
            gap * 1000.
        );
    }
}

#[test]
fn natural_completion_returns_to_both_grips_without_a_cancellation_tail() {
    let mut presentation = ViewAnimation::default();
    for phase in [0.77, 0.8454902, 0.99, 1.] {
        let (_, routed) = routed_frame(
            &mut presentation,
            AnimationInput {
                reload_progress: Some(phase),
                ..Default::default()
            },
            true,
            phase as f64,
            Mat4::IDENTITY,
        );
        assert_eq!(routed.influences[1], 1.);
        if phase == 1. {
            assert_eq!(routed.influences, [1., 1.]);
        }
    }
    let (pose, finished) = routed_frame(
        &mut presentation,
        AnimationInput::default(),
        true,
        1.01,
        Mat4::IDENTITY,
    );
    assert_eq!(pose, WeaponAnimationPose::default());
    assert_eq!(finished.influences, [1., 1.]);
    assert_eq!(
        presentation.hand_presentation().clip_pose,
        WeaponAnimationPose::default()
    );
}

fn routed_left(phase: f32, weapon_motion: Mat4) -> HandPose {
    let mut presentation = ViewAnimation::default();
    let (_, routed) = routed_frame(
        &mut presentation,
        AnimationInput {
            reload_progress: Some(phase),
            ..Default::default()
        },
        false,
        5.,
        weapon_motion,
    );
    blend_hand_constraint(
        in_frame(routed.free_hands.left, routed.free_frame),
        routed.targets.left,
        routed.influences[0],
    )
}

#[test]
fn detaching_under_weapon_only_motion_is_position_continuous() {
    let event = 0.1394118;
    let weapon_motion = Mat4::from_rotation_translation(
        Quat::from_rotation_y(30_f32.to_radians()),
        Vec3::new(0.1, 0., 0.),
    );
    let mut last_gap = f32::INFINITY;
    for epsilon in [1e-3, 1e-4, 1e-5] {
        let before = routed_left(event - epsilon, weapon_motion);
        let after = routed_left(event + epsilon, weapon_motion);
        let gap = before.position.distance(after.position);
        if epsilon < 1e-3 {
            assert!(
                gap < last_gap * 0.2 + 1e-6,
                "detach gap does not converge to zero: epsilon={epsilon}, gap={}mm, previous={}mm",
                gap * 1000.,
                last_gap * 1000.
            );
        }
        last_gap = gap;
    }
    assert!(
        last_gap < 0.0001,
        "detach has a residual jump of {}mm",
        last_gap * 1000.
    );
}

#[test]
fn routing_applies_common_two_meter_forty_seven_degree_root_once() {
    let mut presentation = ViewAnimation::default();
    let (pose, _) = routed_frame(
        &mut presentation,
        AnimationInput {
            reload_progress: Some(0.77),
            ..Default::default()
        },
        false,
        5.,
        Mat4::IDENTITY,
    );
    let body = body_frame();
    let live = body * WeaponFrame::new(Vec3::ZERO, &pose).matrix;
    let common = Mat4::from_rotation_translation(
        Quat::from_rotation_y(47_f32.to_radians()),
        Vec3::new(2., 0., 0.),
    );
    let base = presentation.hand_presentation().frames(body, live);
    let moved = presentation
        .hand_presentation()
        .frames(common * body, common * live);
    for (original, transformed) in [
        (base.targets.left, moved.targets.left),
        (base.targets.right, moved.targets.right),
        (
            in_frame(base.free_hands.left, base.free_frame),
            in_frame(moved.free_hands.left, moved.free_frame),
        ),
    ] {
        let expected = in_frame(original, common);
        assert!(transformed.position.distance(expected.position) < 0.00001);
        assert!(rotation_error(transformed.orientation, expected.orientation) < 0.000001);
    }
    // The runtime arm solver declares camera/presentation space. Its shoulder
    // root is fixed there; this checks routing covariance, not a native moved
    // shoulder rig or a final-skin common-world-transform capture.
}

#[test]
fn solved_free_hand_ignores_live_weapon_motion_while_other_hand_stays_bound() {
    let arms = synthetic_arms();
    let free_frame =
        Mat4::from_rotation_translation(Quat::from_rotation_y(0.17), Vec3::new(0.08, -0.02, 0.01));
    let free = ArmFreeHandPose {
        left: HandPose::new(Vec3::new(-0.22, -0.30, -0.55), Quat::from_rotation_x(0.41)),
        right: HandPose::new(Vec3::new(0.17, -0.25, -0.44), Quat::from_rotation_z(-0.32)),
    };
    let authored = [
        in_frame(free.left, free_frame),
        in_frame(free.right, free_frame),
    ];
    // These legacy channels must not leak into the new independent free path.
    let misleading_legacy_pose = WeaponAnimationPose {
        left_grip: [8., -9., 7.],
        right_grip: [-7., 9., 8.],
        left_hand_euler_yxz: [1.4, -0.8, 0.9],
        ..Default::default()
    };
    for step in 0..24 {
        let t = step as f32 / 23.;
        let live_root = Mat4::from_rotation_translation(
            Quat::from_euler(EulerRot::YXZ, -0.18 + t * 0.36, 0.08 * t, -0.06 * t),
            HIP + Vec3::new(0.05 * t, 0.012 * (t * 6.).sin(), -0.025 * t),
        );
        let targets = WeaponIkRig::new(live_root).targets();
        for influences in [[0., 1.], [1., 0.], [0., 0.], [1., 1.]] {
            let globals = arms.posed_globals_with_weapon_ik(
                &targets,
                free_frame,
                &misleading_legacy_pose,
                free,
                influences,
                [0., 0., 0., 1.],
            );
            assert_wrist(
                globals[2],
                if influences[0] == 0. {
                    authored[0]
                } else {
                    targets.left
                },
            );
            assert_wrist(
                globals[5],
                if influences[1] == 0. {
                    authored[1]
                } else {
                    targets.right
                },
            );
        }
    }
}

#[test]
fn actual_arm_solver_blends_each_free_channel_to_its_anchor_once() {
    let arms = synthetic_arms();
    let frame =
        Mat4::from_rotation_translation(Quat::from_rotation_z(0.12), Vec3::new(0.01, -0.02, 0.));
    let free = ArmFreeHandPose {
        left: HandPose::new(Vec3::new(-0.22, -0.30, -0.55), Quat::from_rotation_x(0.41)),
        right: HandPose::new(Vec3::new(0.17, -0.25, -0.44), Quat::from_rotation_z(-0.32)),
    };
    let targets = WeaponIkRig::new(Mat4::from_rotation_translation(
        Quat::from_rotation_y(0.26),
        HIP,
    ))
    .targets();
    for influences in [[0.25, 0.70], [0.50, 0.20], [0.90, 0.40]] {
        let globals = arms.posed_globals_with_weapon_ik(
            &targets,
            frame,
            &WeaponAnimationPose::default(),
            free,
            influences,
            [1., 0., 0., 0.],
        );
        for (bone, animated, anchor, alpha) in [
            (2, in_frame(free.left, frame), targets.left, influences[0]),
            (5, in_frame(free.right, frame), targets.right, influences[1]),
        ] {
            let to = if animated.orientation.dot(anchor.orientation) < 0. {
                -anchor.orientation
            } else {
                anchor.orientation
            };
            let expected = HandPose::new(
                animated.position * (1. - alpha) + anchor.position * alpha,
                animated.orientation.slerp(to, alpha),
            );
            assert_wrist(globals[bone], expected);
        }
    }
}
