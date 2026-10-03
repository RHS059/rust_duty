//! Committed gameplay reload -> native-time authored clip playback.
//! This observer never mutates ammunition, credits, readiness, or simulation time.
use crate::{
    sim::Simulation,
    viewmodel_animation::{AnimationError, AnimationSet, Result},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReloadSlot {
    Tactical,
    Empty,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ReloadSample {
    pub slot: ReloadSlot,
    pub seconds: f64,
}
#[derive(Clone, Debug)]
pub struct AuthoredReload {
    durations: [Option<f64>; 2],
    missing_slot: Option<ReloadSlot>,
    last_time: f64,
    observed_deadline: f64,
    active: Option<(ReloadSlot, f64)>,
}
impl AuthoredReload {
    pub fn clip_duration(animation: &AnimationSet, name: &str) -> Result<f64> {
        let clip = animation
            .clips()
            .iter()
            .find(|clip| clip.name == name)
            .ok_or_else(|| AnimationError(format!("missing required reload clip: {name}")))?;
        if clip.looping || clip.duration() <= 0. {
            return Err(AnimationError(format!(
                "reload clip {name} must be non-looping with positive duration"
            )));
        }
        Ok(f64::from(clip.duration()))
    }
    pub fn new(tactical_seconds: f64, empty_seconds: Option<f64>) -> Result<Self> {
        if [Some(tactical_seconds), empty_seconds]
            .iter()
            .flatten()
            .any(|value| !value.is_finite() || *value <= 0.)
        {
            return Err(AnimationError(
                "reload durations must be finite and positive".into(),
            ));
        }
        Ok(Self {
            durations: [Some(tactical_seconds), empty_seconds],
            missing_slot: None,
            last_time: 0.,
            observed_deadline: 0.,
            active: None,
        })
    }
    pub fn reset(&mut self, time: f64) {
        self.last_time = time;
        self.observed_deadline = 0.;
        self.active = None;
        self.missing_slot = None;
    }
    /// Observe after Simulation::update. The persistent accepted deadline also
    /// catches a reload whose gameplay duration fits inside a single fixed tick.
    /// Rejected R input does not change it and cannot restart animation.
    pub fn committed_step(&mut self, start: f64, simulation: &Simulation) -> Result<()> {
        if !start.is_finite()
            || start != self.last_time
            || simulation.time < start
            || !simulation.time.is_finite()
        {
            return Err(AnimationError(
                "reload observer needs contiguous committed ticks; reset explicitly".into(),
            ));
        }
        let player = &simulation.player;
        let deadline = player.reload_ready_at;
        if deadline > 0. && deadline != self.observed_deadline {
            let slot = if player.reload_empty {
                ReloadSlot::Empty
            } else {
                ReloadSlot::Tactical
            };
            if self.durations[if slot == ReloadSlot::Empty { 1 } else { 0 }].is_some() {
                self.active = Some((slot, deadline - f64::from(player.reload_total)));
                self.missing_slot = None;
            } else {
                self.active = None;
                self.missing_slot = Some(slot);
            }
        }
        self.observed_deadline = deadline;
        self.last_time = simulation.time;
        if deadline == 0. {
            self.active = None;
        } // authoritative cancellation
        if let Some((slot, began)) = self.active {
            if simulation.time - began >= self.duration(slot) && player.reload_left <= 0. {
                self.active = None;
            }
        }
        Ok(())
    }
    pub fn sample(&self) -> Option<ReloadSample> {
        self.active.map(|(slot, start)| ReloadSample {
            slot,
            seconds: (self.last_time - start).clamp(0., self.duration(slot)),
        })
    }
    pub fn missing_slot(&self) -> Option<ReloadSlot> {
        self.missing_slot
    }
    fn duration(&self, slot: ReloadSlot) -> f64 {
        self.durations[if slot == ReloadSlot::Empty { 1 } else { 0 }].unwrap_or(0.)
    }
}
