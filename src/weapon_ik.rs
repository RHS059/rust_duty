//! Weapon-parented hand targets and a separate hand constraint layer.
//!
//! Evaluate the weapon hierarchy after locomotion, sway and recoil. Supply the
//! authored hand pose in the same camera/world space as the hierarchy root, then
//! blend it toward its grip target. An influence of zero leaves that authored
//! pose independent of subsequent weapon motion, as required during a reload.

use macroquad::math::{Mat3, Mat4, Quat, Vec3};

use crate::weapon_animation::{HAND_MODE_ORIENTATIONS, LEFT_GRIP, RIGHT_GRIP};

pub const WEAPON_BONE: usize = 0;
pub const LEFT_HAND_WEAPON_IK: usize = 1;
pub const RIGHT_HAND_WEAPON_IK: usize = 2;

/// Position and rigid orientation, in whichever space the caller supplies.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct HandPose {
    pub position: Vec3,
    pub orientation: Quat,
}

impl HandPose {
    pub fn new(position: Vec3, orientation: Quat) -> Self {
        Self {
            position,
            orientation: unit_orientation(orientation),
        }
    }

    pub fn transform(self) -> Mat4 {
        Mat4::from_rotation_translation(self.orientation, self.position)
    }
}

/// A real local transform in the runtime bone graph. The root's transform maps
/// weapon space into the caller's camera/world space; children are weapon-local.
#[derive(Clone, Copy, Debug)]
pub struct WeaponIkBone {
    pub name: &'static str,
    pub parent: Option<usize>,
    pub local_transform: Mat4,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct WeaponIkTargets {
    pub left: HandPose,
    pub right: HandPose,
}

/// Fixed three-bone topology with independently configurable grip transforms.
/// Both target bones are direct children of `weapon`, never of either hand.
#[derive(Clone, Debug)]
pub struct WeaponIkRig {
    bones: [WeaponIkBone; 3],
}

impl WeaponIkRig {
    pub fn new(root: Mat4) -> Self {
        let grips = Self::default_grips();
        Self::with_grips(root, grips.left, grips.right)
    }

    /// Calibrated weapon-local wrist frames matching the existing hand skin.
    pub fn default_grips() -> WeaponIkTargets {
        // Right bone-local +X runs opposite wrist-to-knuckle; its palm faces +Z.
        // Keep the rigid basis calibrated by arms::right_wrist_rotation.
        let x = Vec3::new(0., 0.20, 0.980).normalize();
        let z = -Vec3::X;
        WeaponIkTargets {
            left: HandPose::new(
                Vec3::from_array(LEFT_GRIP),
                Quat::from_array(HAND_MODE_ORIENTATIONS[0]),
            ),
            right: HandPose::new(
                Vec3::from_array(RIGHT_GRIP),
                Quat::from_mat3(&Mat3::from_cols(x, z.cross(x), z)),
            ),
        }
    }

    pub fn with_grips(root: Mat4, left: HandPose, right: HandPose) -> Self {
        Self {
            bones: [
                WeaponIkBone {
                    name: "weapon",
                    parent: None,
                    local_transform: root,
                },
                WeaponIkBone {
                    name: "left_hand_weapon_ik",
                    parent: Some(WEAPON_BONE),
                    local_transform: HandPose::new(left.position, left.orientation).transform(),
                },
                WeaponIkBone {
                    name: "right_hand_weapon_ik",
                    parent: Some(WEAPON_BONE),
                    local_transform: HandPose::new(right.position, right.orientation).transform(),
                },
            ],
        }
    }

    pub fn bones(&self) -> &[WeaponIkBone; 3] {
        &self.bones
    }

    pub fn set_root(&mut self, root: Mat4) {
        self.bones[WEAPON_BONE].local_transform = root;
    }

    pub fn set_left_grip(&mut self, pose: HandPose) {
        self.bones[LEFT_HAND_WEAPON_IK].local_transform =
            HandPose::new(pose.position, pose.orientation).transform();
    }

    pub fn set_right_grip(&mut self, pose: HandPose) {
        self.bones[RIGHT_HAND_WEAPON_IK].local_transform =
            HandPose::new(pose.position, pose.orientation).transform();
    }

    /// Resolve each actual parent edge rather than treating the targets as
    /// unrelated renamed points. The fixed topology is in parent-first order.
    pub fn global_transforms(&self) -> [Mat4; 3] {
        let mut globals = [Mat4::IDENTITY; 3];
        for (index, bone) in self.bones.iter().enumerate() {
            globals[index] = bone.parent.map_or(bone.local_transform, |parent| {
                globals[parent] * bone.local_transform
            });
        }
        globals
    }

    pub fn targets(&self) -> WeaponIkTargets {
        let globals = self.global_transforms();
        let mut rotations = [Quat::IDENTITY; 3];
        for (index, bone) in self.bones.iter().enumerate() {
            let local = unit_orientation(bone.local_transform.to_scale_rotation_translation().1);
            rotations[index] = unit_orientation(
                bone.parent
                    .map_or(local, |parent| rotations[parent] * local),
            );
        }
        // Compose rigid orientations along the graph separately: decomposing a
        // scaled parent * rotated child can otherwise turn shear into wrist roll.
        let pose = |index: usize| HandPose {
            position: globals[index].w_axis.truncate(),
            orientation: rotations[index],
        };
        WeaponIkTargets {
            left: pose(LEFT_HAND_WEAPON_IK),
            right: pose(RIGHT_HAND_WEAPON_IK),
        }
    }
}

impl Default for WeaponIkRig {
    fn default() -> Self {
        Self::new(Mat4::IDENTITY)
    }
}

fn unit_orientation(orientation: Quat) -> Quat {
    let length_squared = orientation.length_squared();
    if length_squared.is_finite() && length_squared > 1e-12 {
        orientation.normalize()
    } else {
        Quat::IDENTITY
    }
}

/// Apply one constraint after the animation layer. Both endpoints must already
/// be in the same camera/world space; this function never transforms `animated`
/// through the weapon root. Finite influences clamp to [0, 1]; non-finite values
/// release the constraint. Endpoints are exact, including their orientations.
pub fn blend_hand_constraint(animated: HandPose, target: HandPose, influence: f32) -> HandPose {
    let influence = if influence.is_finite() {
        influence.clamp(0., 1.)
    } else {
        0.
    };
    if influence == 0. {
        return animated;
    }
    if influence == 1. {
        return target;
    }
    let from = unit_orientation(animated.orientation);
    let to = unit_orientation(target.orientation);
    let to = if from.dot(to) < 0. { -to } else { to };
    HandPose {
        position: animated.position.lerp(target.position, influence),
        orientation: unit_orientation(from.slerp(to, influence)),
    }
}
