//! Cosmetic reload cancellation crossfade. Never feeds movement, aim rays or ammo.
use crate::weapon_animation::{sample_weapon_animation, AnimationInput, WeaponAnimationPose};
use macroquad::math::{EulerRot, Mat4, Quat, Vec3};
/// One frame shared by gun meshes, arm grip targets, and muzzle effects.
#[derive(Clone, Copy)]
pub struct WeaponFrame {
    pub matrix: Mat4,
}
impl WeaponFrame {
    pub fn new(base: Vec3, pose: &WeaponAnimationPose) -> Self {
        Self::with_orientation(base, Quat::IDENTITY, pose)
    }
    pub fn with_orientation(base: Vec3, orientation: Quat, pose: &WeaponAnimationPose) -> Self {
        let r = pose.weapon_euler_yxz;
        Self {
            matrix: Mat4::from_rotation_translation(orientation, base)
                * Mat4::from_translation(Vec3::from_array(pose.weapon_translation))
                * Mat4::from_quat(Quat::from_euler(EulerRot::YXZ, r[0], r[1], r[2])),
        }
    }
    pub fn point(self, local: Vec3) -> Vec3 {
        self.matrix.transform_point3(local)
    }
}
/// Independent authored reload frame and hand channels. Finger articulation is
/// intentionally separate from these constraint influences.
#[derive(Clone, Copy)]
pub struct HandPresentation {
    pub clip_pose: WeaponAnimationPose,
    pub influences: [f32; 2],
    recovery: Option<(crate::weapon_ik::HandPose, f32)>,
    body_free_override: Option<crate::weapon_ik::HandPose>,
    prop_pose_override: Option<WeaponAnimationPose>,
}
impl Default for HandPresentation {
    fn default() -> Self {
        Self {
            clip_pose: WeaponAnimationPose::default(),
            influences: [1., 1.],
            recovery: None,
            body_free_override: None,
            prop_pose_override: None,
        }
    }
}
/// Pure caller routing shared by rendering and regression tests. Weapon-only
/// recoil/sway belongs in live_weapon, never in the released hand's clip frame.
pub struct HandPresentationFrames {
    pub targets: crate::weapon_ik::WeaponIkTargets,
    pub free_frame: Mat4,
    pub free_hands: crate::arms::ArmFreeHandPose,
    pub influences: [f32; 2],
}
impl HandPresentation {
    /// Replacement magazine follows the same unconstrained clip as its grasp.
    /// Once seated at its bind transform it belongs to the weapon again.
    pub fn held_magazine_matrix(self, body_frame: Mat4, live_weapon: Mat4) -> Mat4 {
        let p = self.prop_pose_override.unwrap_or(self.clip_pose);
        let local = magazine_frame_with_orientation(
            Mat4::IDENTITY,
            Vec3::from_array(p.magazine_translation),
            Quat::from_array(crate::weapon_animation::effective_magazine_orientation(&p)),
        );
        let route = self.frames(body_frame, live_weapon);
        if p.left_hand_blend[1] >= 0.99 {
            // The prop and palm recover together during interruption. This is
            // the same single constraint blend used by the final arm solver.
            let (_, rotation, _) = route.free_frame.to_scale_rotation_translation();
            let free = crate::weapon_ik::HandPose::new(
                route
                    .free_frame
                    .transform_point3(route.free_hands.left.position),
                rotation * route.free_hands.left.orientation,
            );
            let constrained = crate::weapon_ik::blend_hand_constraint(
                free,
                route.targets.left,
                route.influences[0],
            );
            let prop_frame = body_frame * WeaponFrame::new(Vec3::ZERO, &p).matrix;
            let (_, prop_rotation, _) = prop_frame.to_scale_rotation_translation();
            let prop_hand = crate::weapon_ik::HandPose::new(
                prop_frame.transform_point3(Vec3::from_array(p.left_grip)),
                prop_rotation
                    * Quat::from_array(crate::weapon_animation::effective_hand_orientation(&p)),
            );
            constrained.transform() * prop_hand.transform().inverse() * prop_frame * local
        } else if local.abs_diff_eq(Mat4::IDENTITY, 1e-5) {
            live_weapon
        } else {
            route.free_frame * local
        }
    }
    pub fn frames(self, body_frame: Mat4, live_weapon: Mat4) -> HandPresentationFrames {
        let p = self.clip_pose;
        let defaults = crate::weapon_ik::WeaponIkRig::default_grips();
        let mut result = HandPresentationFrames {
            targets: crate::weapon_ik::WeaponIkRig::new(live_weapon).targets(),
            free_frame: body_frame * WeaponFrame::new(Vec3::ZERO, &p).matrix,
            free_hands: crate::arms::ArmFreeHandPose {
                left: crate::weapon_ik::HandPose::new(
                    Vec3::from_array(p.left_grip),
                    Quat::from_array(crate::weapon_animation::effective_hand_orientation(&p)),
                ),
                right: crate::weapon_ik::HandPose::new(
                    Vec3::from_array(p.right_grip),
                    defaults.right.orientation,
                ),
            },
            influences: self.influences,
        };
        if let Some(free) = self.body_free_override {
            result.free_frame = body_frame;
            result.free_hands.left = free;
        }
        if let Some((from, t)) = self.recovery {
            let (_, r, _) = result.free_frame.to_scale_rotation_translation();
            let free = crate::weapon_ik::HandPose::new(
                result
                    .free_frame
                    .transform_point3(result.free_hands.left.position),
                r * result.free_hands.left.orientation,
            );
            let goal = crate::weapon_ik::blend_hand_constraint(
                free,
                result.targets.left,
                result.influences[0],
            );
            let (_, body_r, _) = body_frame.to_scale_rotation_translation();
            let from = crate::weapon_ik::HandPose::new(
                body_frame.transform_point3(from.position),
                body_r * from.orientation,
            );
            let mixed = crate::weapon_ik::blend_hand_constraint(from, goal, t);
            result.free_frame = body_frame;
            result.free_hands.left = crate::weapon_ik::HandPose::new(
                body_frame.inverse().transform_point3(mixed.position),
                body_r.inverse() * mixed.orientation,
            );
            result.influences[0] = 0.;
        }
        result
    }
}
#[derive(Default)]
pub struct ViewAnimation {
    visual_clock: crate::reference_motion::ReloadVisualClock,
    previous_reload: Option<(f32, bool)>,
    reload_ready_phase: Option<(bool, f32)>,
    reload_origin: Option<(f64, bool)>,
    restart_pending: bool,
    hand_presentation: HandPresentation,
    hand_cancellation: Option<(HandPresentation, f64)>,
    previous: WeaponAnimationPose,
    last_output: WeaponAnimationPose,
    hand_restart: Option<(crate::weapon_ik::HandPose, f64)>,
    hand_restart_prop: Option<WeaponAnimationPose>,
    weapon_restart: Option<(WeaponAnimationPose, f64)>,
    was_reloading: bool,
    cancellation: Option<(WeaponAnimationPose, f64)>,
}
impl ViewAnimation {
    pub fn hand_presentation(&self) -> HandPresentation {
        self.hand_presentation
    }
    pub fn presentation_progress(
        &mut self,
        progress: Option<f32>,
        duration: f32,
        empty: bool,
        completed: bool,
        now: f64,
    ) -> Option<f32> {
        if progress.is_some() && duration.is_finite() && duration > 0. {
            self.reload_ready_phase = Some((
                empty,
                duration / crate::reference_motion::visual_duration(empty),
            ));
        }
        if let Some(phase) = progress {
            let start = now - (phase * duration) as f64;
            // Match the visual clock's session detection, including a render
            // gap long enough for the replacement phase to exceed the old one.
            self.restart_pending |= self.was_reloading
                && self.reload_origin.is_some_and(|(previous, was_empty)| {
                    (start - previous).abs() > 0.001 || empty != was_empty
                });
            self.reload_origin = Some((start, empty));
        } else if !completed {
            self.reload_origin = None;
        }
        self.visual_clock
            .phase(progress, duration, empty, completed, now)
    }

    /// Blend only residual reload motion, then compose current recoil/trigger.
    /// Natural completion is authoritative from the simulation ready milestone.
    pub fn sample_input(
        &mut self,
        input: AnimationInput,
        completed: bool,
        now: f64,
    ) -> WeaponAnimationPose {
        let was_reloading = self.was_reloading;
        // The visual clock can observe a cancel/restart between renders, with
        // Some on both sides. Recover from the last rendered pose on that edge
        // too, including a new reload begun during the post-ready visual tail.
        let replaced_reload = self.restart_pending
            || match (self.previous_reload, input.reload_progress) {
                (Some((previous, empty)), Some(phase)) => {
                    phase + 1e-5 < previous || input.empty_reload != empty
                }
                _ => false,
            };
        self.restart_pending = false;
        self.previous_reload = input
            .reload_progress
            .map(|phase| (phase, input.empty_reload));
        if input.reload_progress.is_some()
            && (replaced_reload || (!was_reloading && self.hand_cancellation.is_some()))
        {
            let old = self.hand_presentation.frames(
                Mat4::IDENTITY,
                WeaponFrame::new(Vec3::ZERO, &self.last_output).matrix,
            );
            let (_, r, _) = old.free_frame.to_scale_rotation_translation();
            let free = crate::weapon_ik::HandPose::new(
                old.free_frame
                    .transform_point3(old.free_hands.left.position),
                r * old.free_hands.left.orientation,
            );
            self.hand_restart = Some((
                crate::weapon_ik::blend_hand_constraint(free, old.targets.left, old.influences[0]),
                now,
            ));
            self.weapon_restart = Some((self.previous, now));
            self.hand_restart_prop = Some(
                self.hand_presentation
                    .prop_pose_override
                    .unwrap_or(self.hand_presentation.clip_pose),
            );
        }
        if completed && input.reload_progress.is_none() {
            self.hand_cancellation = None;
            self.was_reloading = false;
            self.cancellation = None;
        }
        let live = sample_weapon_animation(AnimationInput {
            reload_progress: None,
            ..input
        });
        let mut reload = sample_weapon_animation(AnimationInput {
            reload_progress: input.reload_progress,
            reload_credit_fraction: input.reload_credit_fraction,
            empty_reload: input.empty_reload,
            ..Default::default()
        });
        if let Some(phase) = input.reload_progress {
            let root = crate::reference_motion::sample_reload_root(phase, input.empty_reload);
            reload.weapon_translation = root.translation;
            reload.weapon_euler_yxz = root.euler_yxz;
        }
        if let Some(phase) = input.reload_progress {
            self.hand_cancellation = None;
            // Free animation already moves to the grip. Raise constraint weight
            // only after arrival, rather than interpolating that motion twice.
            let arrival = if input.empty_reload { 0.955 } else { 0.8454902 };
            let release = if input.empty_reload { 0.14 } else { 0.1394118 };
            let ready = self
                .reload_ready_phase
                .filter(|(empty, _)| *empty == input.empty_reload)
                .map(|(_, phase)| phase)
                .unwrap_or_else(|| {
                    let duration = if input.empty_reload {
                        crate::weapon_animation::EMPTY_RELOAD_SECONDS
                    } else {
                        crate::weapon_animation::TACTICAL_RELOAD_SECONDS
                    };
                    duration as f32 / crate::reference_motion::visual_duration(input.empty_reload)
                });
            // Once the authored hand reaches support, reacquire by gameplay
            // ready so accepted recoil/sprint cannot separate it from the gun.
            // Keep a continuous short ramp even if custom timing is earlier
            // than the fitted arrival. The visual clip and release stay intact.
            let arrival_end = ready.clamp(arrival + 0.03, 1.);
            let smooth = |t: f32| {
                let t = t.clamp(0., 1.);
                t * t * (3. - 2. * t)
            };
            let left = if phase <= release {
                1. - smooth((phase - (release - 0.03)) / 0.03)
            } else if phase >= arrival {
                smooth((phase - arrival) / (arrival_end - arrival))
            } else {
                0.
            };
            self.hand_presentation = HandPresentation {
                clip_pose: reload,
                influences: [left, 1.],
                recovery: None,
                body_free_override: None,
                prop_pose_override: None,
            };
        } else {
            if was_reloading && !completed {
                let mut from = self.hand_presentation;
                if from.recovery.is_some() {
                    let route = from.frames(
                        Mat4::IDENTITY,
                        WeaponFrame::new(Vec3::ZERO, &self.last_output).matrix,
                    );
                    let (_, r, _) = route.free_frame.to_scale_rotation_translation();
                    let free = crate::weapon_ik::HandPose::new(
                        route
                            .free_frame
                            .transform_point3(route.free_hands.left.position),
                        r * route.free_hands.left.orientation,
                    );
                    from.body_free_override = Some(crate::weapon_ik::blend_hand_constraint(
                        free,
                        route.targets.left,
                        route.influences[0],
                    ));
                    from.recovery = None;
                    from.influences[0] = 0.;
                }
                self.hand_cancellation = Some((from, now));
                self.hand_restart = None;
                self.weapon_restart = None;
            }
            self.hand_presentation = if let Some((from, start)) = self.hand_cancellation {
                let t = ((now - start).max(0.) / 0.14).clamp(0., 1.) as f32;
                let t = t * t * (3. - 2. * t);
                if t >= 1. {
                    self.hand_cancellation = None;
                }
                // Keep the outgoing free endpoint fixed, recover by one
                // constraint blend while the weapon recovers independently.
                HandPresentation {
                    clip_pose: from.clip_pose,
                    influences: from.influences.map(|a| a + (1. - a) * t),
                    recovery: from.recovery,
                    body_free_override: from.body_free_override,
                    prop_pose_override: from.prop_pose_override,
                }
            } else {
                HandPresentation::default()
            };
        }
        if let Some((from, start)) = self.hand_restart {
            let t = ((now - start).max(0.) / 0.14).clamp(0., 1.) as f32;
            if t >= 1. {
                self.hand_restart = None;
            } else {
                self.hand_presentation.recovery = Some((from, t * t * (3. - 2. * t)));
                self.hand_presentation.prop_pose_override = self.hand_restart_prop;
            }
        }
        let mut pose = self.sample(reload, input.reload_progress.is_some(), now);
        for i in 0..3 {
            pose.weapon_translation[i] += live.weapon_translation[i];
            pose.weapon_euler_yxz[i] += live.weapon_euler_yxz[i];
            pose.magazine_translation[i] += live.magazine_translation[i];
            pose.bolt_translation[i] += live.bolt_translation[i];
        }
        pose.trigger_pull = live.trigger_pull;
        self.last_output = pose;
        pose
    }
    pub fn sample(
        &mut self,
        target: WeaponAnimationPose,
        reloading: bool,
        now: f64,
    ) -> WeaponAnimationPose {
        if !now.is_finite() {
            *self = Self::default();
            return target;
        }
        if reloading {
            self.cancellation = None;
        } else if self.was_reloading {
            self.cancellation = Some((self.previous, now));
        }
        self.was_reloading = reloading;
        let pose = if let Some((from, start)) = self.cancellation {
            let progress = ((now - start).max(0.) / 0.14).clamp(0., 1.) as f32;
            if progress >= 1. {
                self.cancellation = None;
            }
            blend(from, target, progress * progress * (3. - 2. * progress))
        } else {
            target
        };
        let pose = if let Some((from, start)) = self.weapon_restart {
            let t = ((now - start).max(0.) / 0.14).clamp(0., 1.) as f32;
            if t >= 1. {
                self.weapon_restart = None;
                pose
            } else {
                blend(from, pose, t * t * (3. - 2. * t))
            }
        } else {
            pose
        };
        self.previous = pose;
        pose
    }
}
fn blend(a: WeaponAnimationPose, b: WeaponAnimationPose, t: f32) -> WeaponAnimationPose {
    fn xyz(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] {
        std::array::from_fn(|i| a[i] + (b[i] - a[i]) * t)
    }
    WeaponAnimationPose {
        weapon_translation: xyz(a.weapon_translation, b.weapon_translation, t),
        weapon_euler_yxz: xyz(a.weapon_euler_yxz, b.weapon_euler_yxz, t),
        magazine_translation: xyz(a.magazine_translation, b.magazine_translation, t),
        magazine_euler_yxz: xyz(a.magazine_euler_yxz, b.magazine_euler_yxz, t),
        magazine_orientation_xyzw: if t <= 0. {
            a.magazine_orientation_xyzw
        } else if t >= 1. {
            b.magazine_orientation_xyzw
        } else {
            Some(crate::weapon_animation::slerp_orientation(
                crate::weapon_animation::effective_magazine_orientation(&a),
                crate::weapon_animation::effective_magazine_orientation(&b),
                t,
            ))
        },
        seated_magazine_orientation_xyzw: if t < 0.5 {
            a.seated_magazine_orientation_xyzw
        } else {
            b.seated_magazine_orientation_xyzw
        },
        seated_magazine_translation: xyz(
            a.seated_magazine_translation,
            b.seated_magazine_translation,
            t,
        ),
        seated_magazine_euler_yxz: xyz(a.seated_magazine_euler_yxz, b.seated_magazine_euler_yxz, t),
        magazine_visibility: if t < 0.5 {
            a.magazine_visibility
        } else {
            b.magazine_visibility
        },
        right_grip: xyz(a.right_grip, b.right_grip, t),
        left_grip: xyz(a.left_grip, b.left_grip, t),
        left_hand_euler_yxz: xyz(a.left_hand_euler_yxz, b.left_hand_euler_yxz, t),
        left_hand_orientation_xyzw: if t <= 0. {
            a.left_hand_orientation_xyzw
        } else if t >= 1. {
            b.left_hand_orientation_xyzw
        } else {
            Some(crate::weapon_animation::slerp_orientation(
                crate::weapon_animation::effective_hand_orientation(&a),
                crate::weapon_animation::effective_hand_orientation(&b),
                t,
            ))
        },
        left_hand_blend: {
            let mut weights: [f32; 4] = std::array::from_fn(|i| {
                (a.left_hand_blend[i] + (b.left_hand_blend[i] - a.left_hand_blend[i]) * t).max(0.)
            });
            let sum: f32 = weights.iter().sum();
            if sum > 0. {
                weights.iter_mut().for_each(|w| *w /= sum);
            } else {
                weights = [1., 0., 0., 0.];
            }
            weights
        },
        bolt_translation: xyz(a.bolt_translation, b.bolt_translation, t),
        trigger_pull: a.trigger_pull + (b.trigger_pull - a.trigger_pull) * t,
    }
}
/// Shared rigid transform for the animated magazine, pivoted on its wrist seat.
pub fn magazine_frame(weapon: Mat4, offset: Vec3, euler: Vec3) -> Mat4 {
    let pivot = Vec3::from_array(crate::arms::FITTED_MAGAZINE_WRIST);
    weapon
        * Mat4::from_translation(offset + pivot)
        * Mat4::from_quat(Quat::from_euler(
            macroquad::math::EulerRot::YXZ,
            euler.x,
            euler.y,
            euler.z,
        ))
        * Mat4::from_translation(-pivot)
}
/// Quaternion variant used when prop and wrist share a shortest-path rotation.
pub fn magazine_frame_with_orientation(weapon: Mat4, offset: Vec3, rotation: Quat) -> Mat4 {
    let pivot = Vec3::from_array(crate::arms::FITTED_MAGAZINE_WRIST);
    weapon
        * Mat4::from_translation(offset + pivot)
        * Mat4::from_quat(rotation)
        * Mat4::from_translation(-pivot)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rotated_magazine_keeps_its_fitted_hand_pivot_attached() {
        let pivot = Vec3::from_array(crate::arms::FITTED_MAGAZINE_WRIST);
        let weapon =
            Mat4::from_rotation_y(0.6) * Mat4::from_translation(Vec3::new(0.2, -0.1, -0.3));
        for empty in [false, true] {
            for step in 1..100 {
                let p = sample_weapon_animation(AnimationInput {
                    reload_progress: Some(step as f32 / 100.),
                    empty_reload: empty,
                    ..Default::default()
                });
                let offset = Vec3::from_array(p.magazine_translation);
                let matrix = magazine_frame(weapon, offset, Vec3::from_array(p.magazine_euler_yxz));
                assert!(
                    matrix
                        .transform_point3(pivot)
                        .distance(weapon.transform_point3(pivot + offset))
                        < 1e-6
                );
            }
        }
    }
    #[test]
    fn sampler_idle_sockets_equal_fitted_skin_contract() {
        let pose = sample_weapon_animation(AnimationInput::default());
        assert_eq!(pose.right_grip, crate::arms::FITTED_RIGHT_WRIST);
        assert_eq!(pose.left_grip, crate::arms::FITTED_SUPPORT_WRIST);
        assert_eq!(pose.left_hand_blend, [1., 0., 0., 0.]);
    }
    #[test]
    fn cancellation_blends_normalized_hand_modes_without_losing_live_fire() {
        let from = WeaponAnimationPose {
            left_hand_blend: [0., 0., 1., 0.],
            ..Default::default()
        };
        let to = WeaponAnimationPose::default();
        for i in 0..=100 {
            let p = blend(from, to, i as f32 / 100.);
            assert!((p.left_hand_blend.iter().sum::<f32>() - 1.).abs() < 1e-6);
            assert!(p.left_hand_blend.iter().all(|x| (0. ..=1.).contains(x)));
        }
    }
    #[test]
    fn muzzle_and_grip_share_mesh_transform_in_hip_ads_and_reload() {
        use crate::weapon_animation::{sample_weapon_animation, AnimationInput};
        let muzzle = Vec3::new(0., 0.01, -0.8);
        for ads in [0., 1.] {
            for reload in [None, Some(0.5)] {
                let pose = sample_weapon_animation(AnimationInput {
                    ads,
                    reload_progress: reload,
                    recoil: 1.,
                    ..Default::default()
                });
                let base = Vec3::new(0.12 * (1. - ads), -0.02 * (1. - ads) - 0.041 * ads, -0.32);
                let frame = WeaponFrame::new(base, &pose);
                let r = pose.weapon_euler_yxz;
                let rotated = Quat::from_euler(EulerRot::YXZ, r[0], r[1], r[2]) * muzzle;
                let expected = base + Vec3::from_array(pose.weapon_translation) + rotated;
                assert!(frame.point(muzzle).distance(expected) < 1e-6);
                assert!(frame.point(muzzle).distance(base + muzzle) > 0.01);
                let grip = Vec3::from_array(pose.right_grip);
                assert_eq!(frame.point(grip), frame.matrix.transform_point3(grip));
            }
        }
    }
    #[test]
    fn cancellation_never_suppresses_new_live_recoil_or_trigger() {
        let mut state = ViewAnimation::default();
        state.sample_input(
            AnimationInput {
                reload_progress: Some(0.5),
                ..Default::default()
            },
            false,
            1.,
        );
        for (now, recoil) in [(2., 1.), (2.03, 0.75), (2.06, 0.5)] {
            let input = AnimationInput {
                recoil,
                ..Default::default()
            };
            let pose = state.sample_input(input, false, now);
            assert_eq!(pose.trigger_pull, recoil);
            let live = sample_weapon_animation(input);
            let mut no_fire = state;
            // The next independent comparison uses the same existing cancellation state.
            let residual = no_fire.sample_input(AnimationInput::default(), false, now);
            assert!(
                (pose.weapon_translation[2]
                    - residual.weapon_translation[2]
                    - live.weapon_translation[2])
                    .abs()
                    < 1e-6
            );
            state = no_fire;
        }
    }
    #[test]
    fn natural_completion_with_held_fire_keeps_first_shot_presentation() {
        use crate::{
            settings::Settings,
            sim::{Input, Simulation, FIXED_DT},
        };
        for ammo in [0, 15] {
            for stride in [1, 4, 8] {
                let cfg = Settings::default();
                let mut sim = Simulation::new();
                sim.player.ammo = ammo;
                let mut state = ViewAnimation::default();
                sim.update(
                    Input {
                        reload: true,
                        ..Default::default()
                    },
                    &cfg,
                    FIXED_DT,
                );
                state.sample_input(
                    AnimationInput {
                        reload_progress: Some(0.),
                        ..Default::default()
                    },
                    false,
                    sim.time,
                );
                let mut checked = false;
                for i in 0..600 {
                    sim.update(
                        Input {
                            fire: true,
                            ..Default::default()
                        },
                        &cfg,
                        FIXED_DT,
                    );
                    if i % stride != 0 {
                        continue;
                    }
                    let p = &sim.player;
                    let progress =
                        (p.reload_left > 0.).then(|| 1. - p.reload_left / p.reload_total);
                    let input = AnimationInput {
                        reload_progress: progress,
                        empty_reload: p.reload_empty,
                        recoil: p.shot_kick,
                        ads: p.ads,
                        ..Default::default()
                    };
                    let completed = progress.is_none()
                        && p.reload_ready_at > 0.
                        && sim.time + 1e-6 >= p.reload_ready_at;
                    let pose = state.sample_input(input, completed, sim.time);
                    if sim.stats.shots > 0 {
                        assert_eq!(
                            pose,
                            sample_weapon_animation(AnimationInput {
                                reload_progress: None,
                                ..input
                            })
                        );
                        assert!(pose.trigger_pull > 0.);
                        checked = true;
                        break;
                    }
                }
                assert!(checked);
            }
        }
    }
    #[test]
    fn cancellation_is_continuous_and_settles() {
        let mut state = ViewAnimation::default();
        let from = WeaponAnimationPose {
            weapon_translation: [0.1, 0.2, 0.3],
            ..Default::default()
        };
        let idle = WeaponAnimationPose::default();
        state.sample(from, true, 1.);
        assert_eq!(state.sample(idle, false, 2.), from);
        assert_eq!(state.sample(idle, false, 2.2), idle);
    }
    #[test]
    fn a_new_reload_and_reset_discard_old_crossfade() {
        let mut state = ViewAnimation::default();
        let from = WeaponAnimationPose {
            weapon_translation: [0.1, 0.2, 0.3],
            ..Default::default()
        };
        let idle = WeaponAnimationPose::default();
        state.sample(from, true, 1.);
        state.sample(idle, false, 2.);
        assert_eq!(state.sample(from, true, 2.01), from);
        assert_eq!(ViewAnimation::default().sample(idle, false, 0.), idle);
    }
    #[test]
    fn equal_end_time_ignores_render_partitioning() {
        let target = WeaponAnimationPose {
            weapon_translation: [1., 2., 3.],
            ..Default::default()
        };
        let mut a = ViewAnimation::default();
        let mut b = ViewAnimation::default();
        a.sample(target, true, 0.);
        b.sample(target, true, 0.);
        a.sample(Default::default(), false, 1.);
        b.sample(Default::default(), false, 1.);
        for i in 1..10 {
            a.sample(Default::default(), false, 1. + i as f64 * 0.005);
        }
        assert_eq!(
            a.sample(Default::default(), false, 1.07),
            b.sample(Default::default(), false, 1.07)
        );
    }
}
