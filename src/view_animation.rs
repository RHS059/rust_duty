//! Cosmetic reload cancellation crossfade. Never feeds movement, aim rays or ammo.
use crate::weapon_animation::WeaponAnimationPose;
#[derive(Default)]
pub struct ViewAnimation {
    previous: WeaponAnimationPose,
    was_reloading: bool,
    cancellation: Option<(WeaponAnimationPose, f64)>,
}
impl ViewAnimation {
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
