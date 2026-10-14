//! Behavior contracts for the weapon hierarchy and independent constraint layer.
use glam::{Mat4, Quat, Vec3};
use vector_range::weapon_animation::{HAND_MODE_ORIENTATIONS, LEFT_GRIP, RIGHT_GRIP};
use vector_range::weapon_ik::{
    blend_hand_constraint, HandPose, WeaponIkRig, LEFT_HAND_WEAPON_IK, RIGHT_HAND_WEAPON_IK,
    WEAPON_BONE,
};

fn close_position(actual: Vec3, expected: Vec3) {
    assert!(
        actual.distance(expected) < 2e-6,
        "position {actual:?} differs from {expected:?}"
    );
}

fn close_orientation(actual: Quat, expected: Quat) {
    assert!((actual.length_squared() - 1.).abs() < 2e-6);
    assert!(
        actual.dot(expected.normalize()).abs() > 1. - 2e-6,
        "orientation {actual:?} differs from {expected:?}"
    );
}

#[test]
fn named_ik_bones_are_children_of_the_weapon_and_evaluate_their_parent_edges() {
    let root =
        Mat4::from_rotation_translation(Quat::from_rotation_y(0.62), Vec3::new(0.27, -0.32, -0.44));
    let rig = WeaponIkRig::new(root);
    let bones = rig.bones();
    assert_eq!(bones[WEAPON_BONE].name, "weapon");
    assert_eq!(bones[WEAPON_BONE].parent, None);
    for (index, name) in [
        (LEFT_HAND_WEAPON_IK, "left_hand_weapon_ik"),
        (RIGHT_HAND_WEAPON_IK, "right_hand_weapon_ik"),
    ] {
        assert_eq!(bones[index].name, name);
        assert_eq!(bones[index].parent, Some(WEAPON_BONE));
        assert_eq!(
            rig.global_transforms()[index],
            root * bones[index].local_transform
        );
    }
}

#[test]
fn default_grips_preserve_the_calibrated_position_and_wrist_orientation() {
    let targets = WeaponIkRig::default().targets();
    close_position(targets.left.position, Vec3::from_array(LEFT_GRIP));
    close_position(targets.right.position, Vec3::from_array(RIGHT_GRIP));
    close_orientation(
        targets.left.orientation,
        Quat::from_array(HAND_MODE_ORIENTATIONS[0]),
    );
    close_orientation(
        targets.right.orientation,
        Quat::from_xyzw(0.07290045, 0.7246968, -0.01205607, -0.6850947).normalize(),
    );
    assert!((targets.right.orientation * Vec3::Z).dot(-Vec3::X) > 0.95);
}

#[test]
fn both_targets_follow_bob_rotation_translation_and_nonuniform_scale() {
    let local = WeaponIkRig::default_grips();
    let mut rig = WeaponIkRig::default();
    for frame in 0..120 {
        let t = frame as f32 * 0.07;
        let rotation = Quat::from_rotation_y(t * 0.31) * Quat::from_rotation_x(0.1 * t.sin());
        let root = Mat4::from_scale_rotation_translation(
            Vec3::new(0.65, 1.2, 0.9),
            rotation,
            Vec3::new(0.3 + t.sin() * 0.02, -0.3 + t.cos() * 0.013, -0.5),
        );
        rig.set_root(root);
        let targets = rig.targets();
        for (grip, target) in [(local.left, targets.left), (local.right, targets.right)] {
            close_position(target.position, root.transform_point3(grip.position));
            close_orientation(target.orientation, rotation * grip.orientation);
            let final_hand = blend_hand_constraint(
                HandPose::new(Vec3::new(20., 30., 40.), Quat::IDENTITY),
                target,
                1.,
            );
            assert_eq!(final_hand, target);
        }
    }
}

#[test]
fn released_authored_hand_stays_independent_of_weapon_motion() {
    let authored = HandPose::new(
        Vec3::new(-0.26, -0.41, -0.28),
        Quat::from_rotation_z(1.1) * Quat::from_rotation_x(-0.8),
    );
    for frame in 0..80 {
        let t = frame as f32 * 0.08;
        let rig = WeaponIkRig::new(Mat4::from_scale_rotation_translation(
            Vec3::splat(0.5 + t),
            Quat::from_rotation_y(t),
            Vec3::new(t, t.sin(), t.cos()),
        ));
        assert_eq!(
            blend_hand_constraint(authored, rig.targets().left, 0.),
            authored
        );
        assert_eq!(
            blend_hand_constraint(authored, rig.targets().right, 0.),
            authored
        );
    }
}

#[test]
fn independent_hand_channels_blend_once_between_animation_and_anchor() {
    let rotation = Quat::from_rotation_y(0.51);
    let rig = WeaponIkRig::new(Mat4::from_rotation_translation(
        rotation,
        Vec3::new(0.1, -0.3, -0.5),
    ));
    let targets = rig.targets();
    let authored = HandPose::new(Vec3::new(-0.3, -0.7, -0.2), Quat::from_rotation_x(-0.7));
    for alpha in [0.1, 0.25, 0.5, 0.75, 0.9] {
        let blended = blend_hand_constraint(authored, targets.left, alpha);
        close_position(
            blended.position,
            authored.position * (1. - alpha) + targets.left.position * alpha,
        );
        close_orientation(
            blended.orientation,
            authored.orientation.slerp(targets.left.orientation, alpha),
        );
    }
    // Releasing the support hand does not release the firing hand.
    assert_eq!(blend_hand_constraint(authored, targets.left, 0.), authored);
    assert_eq!(
        blend_hand_constraint(authored, targets.right, 1.),
        targets.right
    );
}

#[test]
fn wrist_blend_uses_the_shortest_quaternion_arc() {
    let a = HandPose::new(Vec3::ZERO, Quat::from_rotation_z(170_f32.to_radians()));
    let b = HandPose::new(Vec3::ONE, Quat::from_rotation_z(-170_f32.to_radians()));
    let midpoint = blend_hand_constraint(a, b, 0.5);
    close_orientation(
        midpoint.orientation,
        Quat::from_rotation_z(std::f32::consts::PI),
    );
    close_position(midpoint.orientation * Vec3::X, -Vec3::X);
    let opposite_quaternion = HandPose {
        orientation: -a.orientation,
        ..a
    };
    close_orientation(
        blend_hand_constraint(a, opposite_quaternion, 0.4).orientation,
        a.orientation,
    );
}

#[test]
fn finite_influences_clamp_and_nonfinite_influences_release_the_constraint() {
    let a = HandPose::new(Vec3::ZERO, Quat::from_rotation_x(0.6));
    let b = HandPose::new(Vec3::ONE, Quat::from_rotation_y(1.3));
    for alpha in [-99., -0.01, f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
        assert_eq!(blend_hand_constraint(a, b, alpha), a);
    }
    for alpha in [1., 1.01, 99.] {
        assert_eq!(blend_hand_constraint(a, b, alpha), b);
    }
}

#[test]
fn changing_a_local_grip_keeps_the_topology_and_other_grip_unchanged() {
    let root = Mat4::from_rotation_translation(Quat::from_rotation_z(-0.3), Vec3::ONE);
    let custom_left = HandPose::new(Vec3::new(-0.1, 0.2, -0.3), Quat::from_rotation_y(0.4));
    let custom_right = HandPose::new(Vec3::new(0.1, -0.2, 0.3), Quat::from_rotation_x(-0.4));
    let mut rig = WeaponIkRig::new(root);
    let original_right = rig.targets().right;
    rig.set_left_grip(custom_left);
    assert_eq!(rig.targets().right, original_right);
    close_position(
        rig.targets().left.position,
        root.transform_point3(custom_left.position),
    );
    rig.set_right_grip(custom_right);
    close_position(
        rig.targets().right.position,
        root.transform_point3(custom_right.position),
    );
    assert_eq!(rig.bones()[LEFT_HAND_WEAPON_IK].parent, Some(WEAPON_BONE));
    assert_eq!(rig.bones()[RIGHT_HAND_WEAPON_IK].parent, Some(WEAPON_BONE));
    assert_eq!(
        rig.targets(),
        WeaponIkRig::with_grips(root, custom_left, custom_right).targets()
    );
}
