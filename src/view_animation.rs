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
        let r = pose.weapon_euler_yxz;
        Self {
            matrix: Mat4::from_translation(base + Vec3::from_array(pose.weapon_translation))
                * Mat4::from_quat(Quat::from_euler(EulerRot::YXZ, r[0], r[1], r[2])),
        }
    }
    pub fn point(self, local: Vec3) -> Vec3 {
        self.matrix.transform_point3(local)
    }
}
#[derive(Default)]
pub struct ViewAnimation {
    previous: WeaponAnimationPose,
    was_reloading: bool,
    cancellation: Option<(WeaponAnimationPose, f64)>,
}
impl ViewAnimation {
    /// Blend only residual reload motion, then compose current recoil/trigger.
    /// Natural completion is authoritative from the simulation ready milestone.
    pub fn sample_input(
        &mut self,
        input: AnimationInput,
        completed: bool,
        now: f64,
    ) -> WeaponAnimationPose {
        if completed && input.reload_progress.is_none() {
            self.was_reloading = false;
            self.cancellation = None;
        }
        let live = sample_weapon_animation(AnimationInput {
            reload_progress: None,
            ..input
        });
        let reload = sample_weapon_animation(AnimationInput {
            reload_progress: input.reload_progress,
            reload_credit_fraction: input.reload_credit_fraction,
            empty_reload: input.empty_reload,
            ..Default::default()
        });
        let mut pose = self.sample(reload, input.reload_progress.is_some(), now);
        for i in 0..3 {
            pose.weapon_translation[i] += live.weapon_translation[i];
            pose.weapon_euler_yxz[i] += live.weapon_euler_yxz[i];
            pose.magazine_translation[i] += live.magazine_translation[i];
            pose.bolt_translation[i] += live.bolt_translation[i];
        }
        pose.trigger_pull = live.trigger_pull;
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
        right_grip: xyz(a.right_grip, b.right_grip, t),
        left_grip: xyz(a.left_grip, b.left_grip, t),
        bolt_translation: xyz(a.bolt_translation, b.bolt_translation, t),
        trigger_pull: a.trigger_pull + (b.trigger_pull - a.trigger_pull) * t,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
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
