//! First-person legs/body presentation state. Read-only over the simulation:
//! the body never writes the camera, eye height, aim, or collision.
//!
//! Ownership:
//! - Camera/eye: `Simulation` (`Player::eye`). Body/head animation never drives it.
//! - Arms and hands: the existing viewmodel. The body hides its own arms and
//!   head (`arms_visible`/`head_visible` false), so hands are never duplicated
//!   and the camera never sees inside the head.
//! - Torso: offset behind the camera by `torso_back` so it is never clipped.
//! - Feet: this module. Planted feet are world-locked; moving feet advance by
//!   distance travelled, not time, so ground speed and stride always agree.
use crate::action::{smoothstep, ActionSlot};
use crate::sim::{Action, DivePhase, Simulation};
use glam::{vec3, Vec3};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BodyPose {
    Standing,
    Crouched,
    Prone,
    Airborne,
    Mantling,
    Sliding,
    Diving,
    DiveImpact,
    Hanging,
    PullUp,
    Mounted,
    Dead,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct BodyTuning {
    /// Max body twist from view yaw while moving (degrees).
    pub max_twist: f32,
    /// Stationary view/body difference that triggers a turn-in-place (degrees).
    pub turn_threshold: f32,
    /// Body yaw response (1/s).
    pub turn_rate: f32,
    pub stride_length: f32,
    pub stance_width: f32,
    pub torso_back: f32,
    /// A planted foot further than this from its rest spot steps (m).
    pub replant_distance: f32,
}
impl Default for BodyTuning {
    fn default() -> Self {
        Self {
            max_twist: 60.,
            turn_threshold: 70.,
            turn_rate: 10.,
            stride_length: 1.4,
            stance_width: 0.12,
            torso_back: 0.25,
            replant_distance: 0.25,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct BodyFrame {
    pub pose: BodyPose,
    pub yaw: f32,
    pub pelvis: Vec3,
    pub feet: [Vec3; 2],
    /// True when a foot is world-locked this frame.
    pub planted: [bool; 2],
    pub head_visible: bool,
    pub arms_visible: bool,
    pub torso_back: f32,
}

#[derive(Clone, Debug, Default)]
pub struct BodyPresentation {
    yaw: Option<f32>,
    turning: bool,
    planted: [Option<Vec3>; 2],
    planted_yaw: f32,
    stride: f32,
    last_position: Option<Vec3>,
}

fn wrap(a: f32) -> f32 {
    (a + std::f32::consts::PI).rem_euclid(std::f32::consts::TAU) - std::f32::consts::PI
}

impl BodyPresentation {
    pub fn reset(&mut self) {
        *self = Self::default();
    }

    pub fn pose(sim: &Simulation) -> BodyPose {
        let p = &sim.player;
        if p.dead() {
            return BodyPose::Dead;
        }
        if let Some(m) = p.mantle {
            return if m.from_hang {
                BodyPose::PullUp
            } else {
                BodyPose::Mantling
            };
        }
        match p.action {
            Action::Slide(_) => return BodyPose::Sliding,
            Action::Dive(d) if d.phase == DivePhase::Impact => return BodyPose::DiveImpact,
            Action::Dive(_) => return BodyPose::Diving,
            Action::Hang(_) => return BodyPose::Hanging,
            Action::None => {}
        }
        if p.mount.is_some() {
            BodyPose::Mounted
        } else if !p.grounded {
            BodyPose::Airborne
        } else if p.prone {
            BodyPose::Prone
        } else if p.crouched {
            BodyPose::Crouched
        } else {
            BodyPose::Standing
        }
    }

    /// Pelvis height above the feet for a pose, scaled with the live eye height
    /// so stance transitions never show an incorrect stance height.
    fn pelvis_height(pose: BodyPose, eye: f32) -> f32 {
        match pose {
            BodyPose::Prone | BodyPose::DiveImpact | BodyPose::Diving | BodyPose::Dead => 0.15,
            BodyPose::Sliding => 0.3,
            _ => eye * 0.62,
        }
    }

    pub fn update(&mut self, sim: &Simulation, dt: f32, t: &BodyTuning) -> BodyFrame {
        let p = &sim.player;
        let pose = Self::pose(sim);
        let view = p.yaw;
        let mut yaw = self.yaw.unwrap_or(view);
        let velocity = vec3(p.velocity.x, 0., p.velocity.z);
        let moving = velocity.length() > 0.3;
        let facing = sim.action_pose().contacts.body_facing;
        let target = if facing.length_squared() > 0.5 {
            // Hang/mount: align to the support, not to look.
            facing.z.atan2(facing.x)
        } else if moving {
            let heading = velocity.z.atan2(velocity.x);
            let mut diff = wrap(heading - view);
            if diff.abs() > 100_f32.to_radians() {
                // Backpedal: face the view and walk backward.
                diff = wrap(diff - std::f32::consts::PI);
            }
            self.turning = false;
            view + diff.clamp(-t.max_twist.to_radians(), t.max_twist.to_radians())
        } else {
            if wrap(view - yaw).abs() > t.turn_threshold.to_radians() {
                self.turning = true;
            }
            if self.turning {
                view
            } else {
                yaw
            }
        };
        // Exact exponential approach: identical for any frame partition.
        yaw += wrap(target - yaw) * (1. - (-t.turn_rate * dt.max(0.)).exp());
        if self.turning && wrap(view - yaw).abs() < 2_f32.to_radians() {
            self.turning = false;
        }
        self.yaw = Some(yaw);

        let forward = vec3(yaw.cos(), 0., yaw.sin());
        let right = forward.cross(Vec3::Y);
        let travelled = self.last_position.map_or(0., |last| {
            vec3(p.position.x - last.x, 0., p.position.z - last.z).length()
        });
        self.last_position = Some(p.position);
        let grounded = p.grounded
            && matches!(
                pose,
                BodyPose::Standing | BodyPose::Crouched | BodyPose::Prone | BodyPose::Mounted
            );
        let mut feet = [Vec3::ZERO; 2];
        let mut planted = [false; 2];
        for (i, side) in [-1_f32, 1.].into_iter().enumerate() {
            let rest = p.position + right * side * t.stance_width;
            if grounded && !moving {
                if self.planted[i].is_none() {
                    self.planted[i] = Some(rest);
                    self.planted_yaw = yaw;
                }
                let spot = self.planted[i].unwrap_or(rest);
                // Turn-in-place or drift: step to the new rest spot.
                let turned = wrap(yaw - self.planted_yaw).abs() > 40_f32.to_radians();
                if turned && i == 1 {
                    self.planted_yaw = yaw;
                }
                let spot = if turned || (spot - rest).length() > t.replant_distance {
                    self.planted[i] = Some(rest);
                    rest
                } else {
                    spot
                };
                feet[i] = spot;
                planted[i] = true;
            } else {
                self.planted[i] = None;
                if grounded {
                    let phase = self.stride + if i == 0 { 0. } else { 0.5 };
                    let swing = (phase * std::f32::consts::TAU).sin();
                    let dir = velocity.normalize_or_zero();
                    feet[i] = rest + dir * swing * t.stride_length * 0.25;
                } else {
                    // Airborne/hanging/traversal: feet follow the body; no ground lock.
                    feet[i] = rest;
                }
            }
            let ground = sim
                .ground_height(feet[i].x, feet[i].z, p.position.y + 0.5)
                .filter(|_| grounded);
            feet[i].y = ground.unwrap_or(p.position.y);
        }
        if grounded && moving {
            self.stride = (self.stride + travelled / t.stride_length).fract();
        }
        let eye = p.eye_height;
        let pelvis_height = Self::pelvis_height(pose, eye);
        let lean = match sim.action_pose().slot {
            Some(ActionSlot::LedgeCatch) => smoothstep(sim.action_pose().normalized),
            _ => 1.,
        };
        BodyFrame {
            pose,
            yaw,
            pelvis: p.position + Vec3::Y * pelvis_height * lean - forward * t.torso_back,
            feet,
            planted,
            head_visible: false,
            arms_visible: false,
            torso_back: t.torso_back,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::settings::Settings;
    use crate::sim::{Aabb, Block, Input, Ramp, FIXED_DT};
    use glam::vec2;

    fn flat() -> Simulation {
        let mut s = Simulation::new();
        s.blocks = vec![Block {
            bounds: Aabb {
                min: vec3(-50., -1., -50.),
                max: vec3(50., 0., 50.),
            },
            kind: 0,
        }];
        s.ramps.clear();
        s.player.position = vec3(0., 0., 20.);
        s
    }

    #[test]
    fn small_turns_keep_feet_locked_and_large_turns_step() {
        let mut s = flat();
        let t = BodyTuning::default();
        let mut body = BodyPresentation::default();
        let first = body.update(&s, 1. / 60., &t);
        assert_eq!(first.planted, [true, true]);
        s.player.yaw += 0.3;
        for _ in 0..30 {
            let f = body.update(&s, 1. / 60., &t);
            assert_eq!(f.feet, first.feet, "no sliding on a small turn");
        }
        s.player.yaw += 1.5;
        let mut stepped = false;
        for _ in 0..120 {
            let f = body.update(&s, 1. / 60., &t);
            stepped |= f.feet != first.feet;
        }
        assert!(stepped);
        let f = body.update(&s, 1. / 60., &t);
        assert!(wrap(f.yaw - s.player.yaw).abs() < 3_f32.to_radians());
    }

    #[test]
    fn body_yaw_is_frame_rate_independent_and_bounded_while_moving() {
        let t = BodyTuning::default();
        let mut results = Vec::new();
        for fps in [30, 60, 144, 240] {
            let mut s = flat();
            s.player.velocity = vec3(4., 0., 0.);
            s.player.yaw = 0.;
            let mut body = BodyPresentation::default();
            body.update(&s, 0., &t);
            // Strafe: body twists toward movement but stays within max twist.
            s.player.velocity = vec3(0., 0., 4.);
            let mut f = body.update(&s, 0., &t);
            for _ in 0..fps {
                f = body.update(&s, 1. / fps as f32, &t);
            }
            assert!(f.yaw <= t.max_twist.to_radians() + 1e-4);
            results.push(f.yaw);
        }
        for r in &results {
            assert!((r - results[0]).abs() < 1e-4);
        }
    }

    #[test]
    fn stride_follows_distance_and_feet_sit_on_slopes() {
        let mut s = flat();
        s.ramps = vec![Ramp {
            x: 0.,
            z: 20.,
            width: 6.,
            length: 10.,
            height: 10. * 20_f32.to_radians().tan(),
        }];
        let cfg = Settings::default();
        let mut body = BodyPresentation::default();
        let t = BodyTuning::default();
        let walk = Input {
            movement: vec2(0., 1.),
            ..Input::default()
        };
        s.player.yaw = -std::f32::consts::FRAC_PI_2;
        s.player.position = vec3(0., 0., 19.);
        for _ in 0..120 {
            s.update(walk, &cfg, FIXED_DT);
            let f = body.update(&s, FIXED_DT, &t);
            for foot in f.feet {
                let ground = s
                    .ground_height(foot.x, foot.z, s.player.position.y + 0.5)
                    .unwrap();
                assert!((foot.y - ground).abs() < 1e-4, "foot on the actual surface");
            }
        }
        assert!(s.player.position.y > 0.5, "walked up the slope");
    }

    #[test]
    fn stance_and_traversal_poses_never_drive_the_camera() {
        let mut s = flat();
        let cfg = Settings::default();
        let mut body = BodyPresentation::default();
        let t = BodyTuning::default();
        for (input, expected) in [
            (
                Input {
                    crouch: true,
                    ..Input::default()
                },
                BodyPose::Crouched,
            ),
            (
                Input {
                    prone: true,
                    ..Input::default()
                },
                BodyPose::Prone,
            ),
            (Input::default(), BodyPose::Standing),
        ] {
            for _ in 0..120 {
                s.update(input, &cfg, FIXED_DT);
            }
            let eye = s.player.eye();
            let f = body.update(&s, 1. / 60., &t);
            assert_eq!(f.pose, expected);
            assert_eq!(s.player.eye(), eye);
            assert!(!f.head_visible && !f.arms_visible);
            assert!(f.pelvis.y < eye.y, "pelvis below the camera");
        }
    }
}
