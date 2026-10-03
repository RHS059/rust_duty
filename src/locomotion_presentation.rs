//! Simulation-clock-driven cosmetic locomotion, independent of gameplay state.
//!
//! Feed this layer the current movement targets and apply its outputs only to
//! the weapon presentation and its attached hands. Never use the eased sprint
//! amount to gate firing, movement, stamina, ADS, or other simulation behavior.

use std::f64::consts::TAU;

/// A critically damped step is 95% settled after this interval. The same
/// response in either direction preserves velocity during rapid reversals.
pub const SPRINT_RESPONSE_SECONDS: f64 = 0.240;
const SPEED_RESPONSE_SECONDS: f64 = 0.180;
const ADS_RESPONSE_SECONDS: f64 = 0.100;
// (1 + x) * exp(-x) = 0.05 at this x.
const SETTLE_95: f64 = 4.743_864_518_390_578;
const WALK_ANGULAR_FREQUENCY: f64 = 10.;
/// Dominant visible low-carry cycle in source frames 4452..4662 (74.2..77.7s):
/// 36 manual samples, two-harmonic fit ~1.71 +/-0.04 Hz. This is weapon motion,
/// not an inferred footstep cadence or gameplay speed. Ready cadence is retained.
pub const LOW_CARRY_CYCLE_SECONDS: f64 = 0.584;
const RUN_ANGULAR_FREQUENCY: f64 = TAU / LOW_CARRY_CYCLE_SECONDS;
const REFERENCE_SPEED: f64 = 7.2;
const MAX_SPEED: f64 = 18.;
const BOB_METERS: f64 = 0.010;

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct LocomotionInput {
    /// Cosmetic sprint/lowering target in [0, 1], usually the current sprint
    /// flag converted to a float. Mantle lowering may use the same target.
    pub sprint: f32,
    /// Horizontal movement speed in metres per second, not a normalized input.
    pub speed: f32,
    /// Current ADS target/fraction in [0, 1], used only to attenuate bob.
    pub ads: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LocomotionPose {
    /// Smooth lowering amount for the existing weapon sprint pose.
    pub sprint: f32,
    /// Vertical weapon/body bob in metres.
    pub bob: f32,
    pub bob_amplitude: f32,
    /// Radians per second. Changes continuously with the sprint blend.
    pub bob_angular_frequency: f32,
    /// Oscillator phase modulo TAU. Wrapping does not reset the visible bob.
    pub phase: f64,
}

impl Default for LocomotionPose {
    fn default() -> Self {
        Self {
            sprint: 0.,
            bob: 0.,
            bob_amplitude: 0.,
            bob_angular_frequency: WALK_ANGULAR_FREQUENCY as f32,
            phase: 0.,
        }
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct DampedChannel {
    value: f64,
    velocity: f64,
    target: f64,
}

impl DampedChannel {
    /// Exact critically damped evolution for a held target, including its
    /// integral. No per-frame Euler steps or velocity resets are involved.
    fn advance(&mut self, dt: f64, response: f64) -> f64 {
        let omega = SETTLE_95 / response;
        let offset = self.value - self.target;
        let coefficient = self.velocity + omega * offset;
        let x = omega * dt;
        if x > 700. {
            // Avoid infinity * zero on huge but finite clock hitches. The
            // omitted exponential tail is below floating-point significance.
            let integral = self.target * dt + offset / omega + coefficient / (omega * omega);
            self.value = self.target;
            self.velocity = 0.;
            return integral;
        }
        let decay = (-x).exp();
        let one_minus_decay = -(-x).exp_m1();
        let integral = self.target * dt
            + offset * one_minus_decay / omega
            + coefficient * (one_minus_decay - x * decay) / (omega * omega);
        self.value = self.target + (offset + coefficient * dt) * decay;
        self.velocity = (self.velocity - omega * coefficient * dt) * decay;
        integral
    }
}

/// Stateful presentation sampler with deterministic, analytic time evolution.
/// A target supplied at time `t` takes effect at `t`; the preceding interval
/// belongs to the previous target. Sampling that same target more often does
/// not change the result. Supply input changes at their simulation timestamps
/// when comparing different render cadences.
#[derive(Clone, Debug, Default)]
pub struct LocomotionPresentation {
    last_time: Option<f64>,
    sprint: DampedChannel,
    speed: DampedChannel,
    ads: DampedChannel,
    phase: f64,
}

impl LocomotionPresentation {
    /// Start at rest with a fresh phase, e.g. on respawn or level restart.
    /// Backward simulation time also performs this reset automatically.
    pub fn reset(&mut self, simulation_time: f64) {
        *self = Self::default();
        if simulation_time.is_finite() {
            self.last_time = Some(simulation_time.max(0.));
        }
    }

    /// Samples cosmetics without changing the inputs or gameplay state.
    /// Repeated time (including pause) freezes the output; target changes are
    /// retained for resumption. A non-finite clock ignores the entire sample.
    /// Non-finite targets safely tend toward rest, while finite targets clamp
    /// to their documented ranges (speed: 0..18 metres per second).
    pub fn sample(&mut self, simulation_time: f64, input: LocomotionInput) -> LocomotionPose {
        if !simulation_time.is_finite() {
            return self.output();
        }
        let now = simulation_time.max(0.);
        if let Some(previous) = self.last_time {
            if now < previous {
                self.reset(now);
            } else {
                let dt = now - previous;
                if dt > 0. {
                    let sprint_integral = self.sprint.advance(dt, SPRINT_RESPONSE_SECONDS);
                    self.speed.advance(dt, SPEED_RESPONSE_SECONDS);
                    self.ads.advance(dt, ADS_RESPONSE_SECONDS);
                    // Integrating frequency preserves the bob phase through
                    // speed changes and reversals. Modular products also keep
                    // very large finite simulation times from overflowing.
                    self.phase = (self.phase
                        + wrapped_product(dt, WALK_ANGULAR_FREQUENCY)
                        + wrapped_product(
                            sprint_integral,
                            RUN_ANGULAR_FREQUENCY - WALK_ANGULAR_FREQUENCY,
                        ))
                    .rem_euclid(TAU);
                }
            }
        }
        self.last_time = Some(now);
        self.sprint.target = clean_target(input.sprint, 1.);
        self.speed.target = clean_target(input.speed, MAX_SPEED);
        self.ads.target = clean_target(input.ads, 1.);
        self.output()
    }

    fn output(&self) -> LocomotionPose {
        let sprint = self.sprint.value.clamp(0., 1.);
        let speed = self.speed.value.clamp(0., MAX_SPEED);
        let ads = self.ads.value.clamp(0., 1.);
        let amplitude = BOB_METERS * (speed / REFERENCE_SPEED).min(1.5) * (1. - ads);
        LocomotionPose {
            sprint: sprint as f32,
            bob: (self.phase.sin() * amplitude) as f32,
            bob_amplitude: amplitude as f32,
            bob_angular_frequency: (WALK_ANGULAR_FREQUENCY
                + (RUN_ANGULAR_FREQUENCY - WALK_ANGULAR_FREQUENCY) * sprint)
                as f32,
            phase: self.phase,
        }
    }
}

fn clean_target(value: f32, maximum: f64) -> f64 {
    if value.is_finite() {
        (value as f64).clamp(0., maximum)
    } else {
        0.
    }
}

fn wrapped_product(value: f64, rate: f64) -> f64 {
    value.rem_euclid(TAU / rate) * rate
}
