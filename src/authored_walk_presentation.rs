//! Restore the existing walk bob around an unchanged, complete authored rig.
//!
//! Only committed simulation ticks advance this layer. It never modifies an
//! animation pose, hand attachment, gameplay state, or the authored sprint path.
use crate::{
    locomotion_presentation::{LocomotionInput, LocomotionPresentation},
    viewmodel_animation::game_model_root,
};
use macroquad::math::{Mat4, Vec3};

/// A captured walking offset settles once when sprint takes over. This is not
/// another oscillator over the authored entry/loop/exit animation.
pub const WALK_ROOT_TRANSITION_SECONDS: f64 = 0.100;

#[derive(Clone, Copy, Debug)]
struct Transition {
    start: f64,
    from: f32,
}

#[derive(Clone, Debug)]
pub struct AuthoredWalkPresentation {
    motion: LocomotionPresentation,
    last_time: Option<f64>,
    ready: bool,
    transition: Option<Transition>,
    offset: f32,
}

impl Default for AuthoredWalkPresentation {
    fn default() -> Self {
        Self {
            motion: LocomotionPresentation::default(),
            last_time: None,
            ready: true,
            transition: None,
            offset: 0.,
        }
    }
}

impl AuthoredWalkPresentation {
    pub fn reset(&mut self, simulation_time: f64) {
        *self = Self::default();
        self.motion.reset(simulation_time);
        self.last_time = simulation_time.is_finite().then(|| simulation_time.max(0.));
    }

    /// `ready` is the authored path state, not merely `!sprinting`: an exit or
    /// interrupted entry still owns motion until its complete ready endpoint.
    /// Input changes take effect at this timestamp, after the old interval has
    /// been evaluated. ADS only retains the legacy bob attenuation here; this
    /// layer does not implement or acquire ADS/reload presentation ownership.
    pub fn sample(&mut self, simulation_time: f64, ready: bool, input: LocomotionInput) {
        if !simulation_time.is_finite() {
            return;
        }
        let now = simulation_time.max(0.);
        if self.last_time.is_some_and(|last| now < last) {
            self.reset(now);
        }
        let bob = self
            .motion
            .sample(
                now,
                LocomotionInput {
                    sprint: 0.,
                    speed: if ready { input.speed } else { 0. },
                    ads: input.ads,
                },
            )
            .bob;
        let target = if self.ready { bob } else { 0. };
        let current = if let Some(transition) = self.transition {
            let elapsed = (now - transition.start) / WALK_ROOT_TRANSITION_SECONDS;
            if elapsed >= 1. {
                self.transition = None;
                target
            } else {
                let t = elapsed.clamp(0., 1.) as f32;
                let weight = t * t * (3. - 2. * t);
                transition.from * (1. - weight) + target * weight
            }
        } else {
            target
        };
        if ready != self.ready {
            // Capture the exact displayed root at either boundary. In
            // particular, rapid entry reversals cannot reveal a hidden bob.
            self.transition = Some(Transition {
                start: now,
                from: current,
            });
            self.ready = ready;
        }
        self.offset = current;
        self.last_time = Some(now);
    }

    pub fn offset(&self) -> f32 {
        self.offset
    }

    /// Apply this same root to both skin and rigid actors. Authored bone locals
    /// and actor globals remain untouched, preserving their relative contact.
    pub fn model_root(&self) -> Mat4 {
        Mat4::from_translation(Vec3::new(0., self.offset, 0.)) * game_model_root()
    }
}
