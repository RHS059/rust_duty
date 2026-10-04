//! Accepted gameplay jump -> native-time authored presentation phases.
//! This observer never changes physics, input, firing, ADS, or reload state.
use crate::viewmodel_animation::{AnimationError, AnimationSet, Result};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum JumpPhase {
    Takeoff,
    Air,
    Land,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct JumpSample {
    pub phase: JumpPhase,
    pub seconds: f64,
    /// True only after the non-looping air Action reaches its final pose.
    pub holding_air_endpoint: bool,
    /// A launch or actual ground contact changes this serial, never a render sample.
    pub transition_serial: u64,
    pub transition_seconds: f64,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct JumpInput {
    /// Simulation's accepted launch timestamp; raw Space input is not observed.
    pub accepted_jump_at: f64,
    pub grounded: bool,
    /// Reload/mantle ownership suppresses this cosmetic layer without delaying gameplay.
    pub eligible: bool,
}

#[derive(Clone, Copy, Debug)]
enum ActiveJump {
    Flight { launched: f64 },
    Landing { contacted: f64 },
}

#[derive(Clone, Debug)]
pub struct AuthoredJump {
    durations: [f64; 3],
    last_time: f64,
    observed_jump_at: f64,
    active: Option<ActiveJump>,
    transition_at: f64,
    transition_serial: u64,
}

impl AuthoredJump {
    pub fn clip_duration(set: &AnimationSet, name: &str) -> Result<f64> {
        let clip = set
            .clips()
            .iter()
            .find(|clip| clip.name == name)
            .ok_or_else(|| AnimationError(format!("missing required jump clip: {name}")))?;
        if clip.looping || !clip.duration().is_finite() || clip.duration() <= 0. {
            return Err(AnimationError(format!(
                "jump clip {name} must be finite, positive and non-looping"
            )));
        }
        Ok(f64::from(clip.duration()))
    }

    pub fn new(takeoff: f64, air: f64, land: f64) -> Result<Self> {
        let durations = [takeoff, air, land];
        if durations
            .iter()
            .any(|v| !v.is_finite() || *v <= 0. || *v > 60.)
        {
            return Err(AnimationError("invalid native jump durations".into()));
        }
        Ok(Self {
            durations,
            last_time: 0.,
            observed_jump_at: f64::NEG_INFINITY,
            active: None,
            transition_at: 0.,
            transition_serial: 0,
        })
    }

    pub fn reset(&mut self, time: f64) -> Result<()> {
        if !time.is_finite() || time < 0. {
            return Err(AnimationError("invalid jump reset time".into()));
        }
        self.last_time = time;
        self.observed_jump_at = f64::NEG_INFINITY;
        self.active = None;
        self.transition_at = time;
        self.transition_serial = 0;
        Ok(())
    }

    /// Observe one contiguous committed interval after the simulation advances.
    /// Launch uses its accepted timestamp. Landing starts when ground contact is
    /// observed at `end`, not at a reference-video deadline. Pauses are inert.
    pub fn committed_step(&mut self, start: f64, end: f64, input: JumpInput) -> Result<()> {
        if !start.is_finite()
            || !end.is_finite()
            || start != self.last_time
            || end < start
            || !input.accepted_jump_at.is_finite()
            || input.accepted_jump_at > end
        {
            return Err(AnimationError(
                "jump observer needs finite contiguous committed ticks".into(),
            ));
        }
        if end == start {
            return Ok(());
        }
        let new_launch =
            input.accepted_jump_at != self.observed_jump_at && input.accepted_jump_at >= start;
        self.observed_jump_at = input.accepted_jump_at;
        self.last_time = end;
        if !input.eligible {
            self.active = None;
            return Ok(());
        }
        if new_launch {
            self.active = Some(ActiveJump::Flight {
                launched: input.accepted_jump_at,
            });
            self.transition_at = input.accepted_jump_at;
            self.transition_serial = self.transition_serial.wrapping_add(1);
        }
        if matches!(self.active, Some(ActiveJump::Flight { .. })) && input.grounded {
            self.active = Some(ActiveJump::Landing { contacted: end });
            self.transition_at = end;
            self.transition_serial = self.transition_serial.wrapping_add(1);
        }
        if let Some(ActiveJump::Landing { contacted }) = self.active {
            if end - contacted >= self.durations[2] {
                self.active = None;
            }
        }
        Ok(())
    }

    pub fn sample(&self) -> Option<JumpSample> {
        let (phase, seconds, holding) = match self.active? {
            ActiveJump::Flight { launched } => {
                let age = (self.last_time - launched).max(0.);
                if age < self.durations[0] {
                    (JumpPhase::Takeoff, age, false)
                } else {
                    let air = age - self.durations[0];
                    (
                        JumpPhase::Air,
                        air.min(self.durations[1]),
                        air >= self.durations[1],
                    )
                }
            }
            ActiveJump::Landing { contacted } => (
                JumpPhase::Land,
                (self.last_time - contacted).clamp(0., self.durations[2]),
                false,
            ),
        };
        Some(JumpSample {
            phase,
            seconds,
            holding_air_endpoint: holding,
            transition_serial: self.transition_serial,
            transition_seconds: (self.last_time - self.transition_at).max(0.),
        })
    }

    pub fn duration(&self, phase: JumpPhase) -> f64 {
        self.durations[match phase {
            JumpPhase::Takeoff => 0,
            JumpPhase::Air => 1,
            JumpPhase::Land => 2,
        }]
    }
}
