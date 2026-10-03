//! Native looping walk clock, driven by committed movement rather than raw W input.
use crate::viewmodel_animation::{AnimationError, AnimationSet, Result};
#[derive(Clone, Debug, Default)]
pub struct AuthoredWalk {
    started: Option<f64>,
    last_time: f64,
}
impl AuthoredWalk {
    pub fn validate_clip(animation: &AnimationSet, name: &str) -> Result<()> {
        let clip = animation
            .clips()
            .iter()
            .find(|clip| clip.name == name)
            .ok_or_else(|| AnimationError(format!("missing required regular walk clip: {name}")))?;
        if !clip.looping || clip.duration() <= 0. {
            return Err(AnimationError(format!(
                "regular walk clip {name} must loop with positive duration"
            )));
        }
        Ok(())
    }
    pub fn reset(&mut self, time: f64) {
        self.started = None;
        self.last_time = time;
    }
    pub fn committed_step(
        &mut self,
        start: f64,
        end: f64,
        moving: bool,
        eligible: bool,
    ) -> Result<()> {
        if start != self.last_time || !start.is_finite() || !end.is_finite() || end < start {
            return Err(AnimationError(
                "walk observer needs contiguous committed ticks; reset explicitly".into(),
            ));
        }
        if moving && eligible {
            if self.started.is_none() {
                self.started = Some(start);
            }
        } else {
            self.started = None;
        }
        self.last_time = end;
        Ok(())
    }
    pub fn seconds(&self) -> Option<f64> {
        self.started.map(|start| self.last_time - start)
    }
}
