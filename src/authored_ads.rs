//! Native, reversible authored ADS playback driven by committed simulation state.
//!
//! No IK, camera offsets, normalized gameplay-phase posing, or synthesized ADS
//! motion. Reversal retraces the currently visible source transition at 1x time.
use crate::{
    animation_manifest::AdsReference,
    authored_locomotion_adapter::PoseBindings,
    sim::Simulation,
    viewmodel_animation::{AnimationError, AnimationSet, Result, ViewmodelPose},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AdsSlot {
    Entry,
    Hold,
    Exit,
}
impl AdsSlot {
    pub fn route(self) -> &'static str {
        match self {
            Self::Entry => "ads.entry",
            Self::Hold => "ads.hold",
            Self::Exit => "ads.exit",
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AdsSample {
    pub slot: AdsSlot,
    pub seconds: f64,
    /// -1 retraces the current clip; +1 advances its authored timeline.
    pub direction: i8,
}

#[derive(Clone, Debug)]
pub struct AuthoredAds {
    clips: AdsReference,
    durations: [f64; 3],
    sample: Option<AdsSample>,
    last_time: f64,
}
impl AuthoredAds {
    /// Require complete canonical companion bindings and connected source poses.
    /// Static hold is intentional: release at any point must join exit(0) exactly.
    pub fn new(
        animation: &AnimationSet,
        locomotion: &AnimationSet,
        ready_clip: &str,
        clips: AdsReference,
    ) -> Result<Self> {
        if !PoseBindings::from_animation(locomotion).matches(animation) {
            return Err(AnimationError(
                "ADS requires canonical locomotion companion bindings".into(),
            ));
        }
        let mut durations = [0.; 3];
        for (index, name) in [&clips.entry_clip, &clips.hold_clip, &clips.exit_clip]
            .into_iter()
            .enumerate()
        {
            let clip = animation
                .clips()
                .iter()
                .find(|clip| &clip.name == name)
                .ok_or_else(|| AnimationError(format!("missing required ADS clip: {name}")))?;
            if clip.duration() <= 0. || clip.looping != (index == 1) {
                return Err(AnimationError(format!(
                    "ADS clip {name} needs positive native duration and {} playback",
                    if index == 1 { "looping" } else { "non-looping" }
                )));
            }
            durations[index] = f64::from(clip.duration());
        }
        let ready = locomotion.sample_clamped(ready_clip, 0.)?;
        let entry_start = animation.sample_clamped(&clips.entry_clip, 0.)?;
        let entry_end = animation.sample_clamped(&clips.entry_clip, durations[0] as f32)?;
        let hold = animation.sample_clamped(&clips.hold_clip, 0.)?;
        let exit_start = animation.sample_clamped(&clips.exit_clip, 0.)?;
        let exit_end = animation.sample_clamped(&clips.exit_clip, durations[2] as f32)?;
        for (name, left, right) in [
            ("ready -> entry", &ready, &entry_start),
            ("entry -> hold", &entry_end, &hold),
            ("hold -> exit", &hold, &exit_start),
            ("exit -> ready", &exit_end, &ready),
        ] {
            if !same_pose(left, right) {
                return Err(AnimationError(format!(
                    "disconnected authored ADS seam: {name}"
                )));
            }
        }
        let hold_clip = animation
            .clips()
            .iter()
            .find(|clip| clip.name == clips.hold_clip)
            .unwrap();
        for &time in hold_clip.times() {
            if !same_pose(&hold, &animation.sample_clamped(&clips.hold_clip, time)?) {
                return Err(AnimationError(
                    "ADS hold must preserve the authored hold/exit connection at every frame"
                        .into(),
                ));
            }
        }
        Ok(Self {
            clips,
            durations,
            sample: None,
            last_time: 0.,
        })
    }
    pub fn reset(&mut self, time: f64) {
        self.sample = None;
        self.last_time = time;
    }
    pub fn sample(&self) -> Option<AdsSample> {
        self.sample
    }
    /// Native transition progress, continuous through both reversal directions.
    pub fn aim_amount(&self) -> f32 {
        self.sample.map_or(0., |sample| {
            let t = match sample.slot {
                AdsSlot::Entry => sample.seconds / self.duration(AdsSlot::Entry),
                AdsSlot::Hold => 1.,
                AdsSlot::Exit => 1. - sample.seconds / self.duration(AdsSlot::Exit),
            }
            .clamp(0., 1.);
            (t * t * (3. - 2. * t)) as f32
        })
    }
    pub fn duration(&self, slot: AdsSlot) -> f64 {
        self.durations[match slot {
            AdsSlot::Entry => 0,
            AdsSlot::Hold => 1,
            AdsSlot::Exit => 2,
        }]
    }
    pub fn clip(&self, slot: AdsSlot) -> &str {
        match slot {
            AdsSlot::Entry => &self.clips.entry_clip,
            AdsSlot::Hold => &self.clips.hold_clip,
            AdsSlot::Exit => &self.clips.exit_clip,
        }
    }
    pub fn pose(&self, animation: &AnimationSet) -> Result<Option<ViewmodelPose>> {
        self.sample
            .map(|sample| {
                if sample.slot == AdsSlot::Hold {
                    animation.sample(self.clip(sample.slot), sample.seconds as f32)
                } else {
                    animation.sample_clamped(self.clip(sample.slot), sample.seconds as f32)
                }
            })
            .transpose()
    }
    /// Observe exactly once after each fixed Simulation::update. Reload cuts to
    /// its independently validated rig; sprint/mantle return along authored ADS.
    /// A sprint transition must reach ready before a new ADS entry can acquire it.
    pub fn committed_step(
        &mut self,
        start: f64,
        simulation: &Simulation,
        reload_visual_active: bool,
        locomotion_ready: bool,
    ) -> Result<()> {
        let end = simulation.time;
        if !start.is_finite() || !end.is_finite() || start != self.last_time || end < start {
            return Err(AnimationError(
                "ADS observer needs contiguous committed ticks; reset explicitly".into(),
            ));
        }
        if end == start {
            return Ok(()); // Pause/render calls cannot change direction or ownership.
        }
        self.last_time = end;
        let player = &simulation.player;
        if reload_visual_active || player.reload_left > 0. {
            self.sample = None;
            return Ok(());
        }
        let requested = player.ads_requested && !player.sprinting && player.mantle.is_none();
        if self.sample.is_none() {
            if !requested || !locomotion_ready {
                return Ok(());
            }
            self.sample = Some(AdsSample {
                slot: AdsSlot::Entry,
                seconds: 0.,
                direction: 1,
            });
        }
        let mut remaining = end - start;
        // At most one transition and the hold remain. The loop also handles
        // unusually long valid ticks without dropping native elapsed time.
        while remaining > 0. {
            let Some(mut sample) = self.sample else {
                break;
            };
            match sample.slot {
                AdsSlot::Hold if requested => {
                    sample.seconds += remaining;
                    sample.direction = 1;
                    self.sample = Some(sample);
                    break;
                }
                AdsSlot::Hold => {
                    self.sample = Some(AdsSample {
                        slot: AdsSlot::Exit,
                        seconds: 0.,
                        direction: 1,
                    });
                }
                AdsSlot::Entry | AdsSlot::Exit => {
                    sample.direction = if requested == (sample.slot == AdsSlot::Entry) {
                        1
                    } else {
                        -1
                    };
                    let duration = self.duration(sample.slot);
                    let until_endpoint = if sample.direction > 0 {
                        duration - sample.seconds
                    } else {
                        sample.seconds
                    };
                    let consumed = remaining.min(until_endpoint.max(0.));
                    sample.seconds = (sample.seconds + consumed * f64::from(sample.direction))
                        .clamp(0., duration);
                    remaining -= consumed;
                    if consumed < until_endpoint {
                        self.sample = Some(sample);
                        break;
                    }
                    let reached_hold = (sample.slot == AdsSlot::Entry) == (sample.direction > 0);
                    self.sample = reached_hold.then_some(AdsSample {
                        slot: AdsSlot::Hold,
                        seconds: 0.,
                        direction: 1,
                    });
                }
            }
        }
        Ok(())
    }
}

/// Decode-rounding tolerance only, never a pose correction or approval gate.
fn same_pose(a: &ViewmodelPose, b: &ViewmodelPose) -> bool {
    a.actor_visible == b.actor_visible
        && a.bone_locals.len() == b.bone_locals.len()
        && a.actor_globals.len() == b.actor_globals.len()
        && a.bone_locals
            .iter()
            .chain(&a.actor_globals)
            .zip(b.bone_locals.iter().chain(&b.actor_globals))
            .all(|(a, b)| {
                a.translation.abs_diff_eq(b.translation, 1e-5)
                    && a.scale.abs_diff_eq(b.scale, 1e-5)
                    && (a.rotation.abs_diff_eq(b.rotation, 1e-5)
                        || a.rotation.abs_diff_eq(-b.rotation, 1e-5))
            })
}

/// Deterministic input-only native capture replay, shared by runtime and tests.
/// The simulation decides aim, firing, reload acceptance and actual movement.
pub fn gameplay_ads_replay_input(time: f64) -> crate::sim::Input {
    use macroquad::math::Vec2;
    crate::sim::Input {
        ads: (0.25..0.75).contains(&time)
            || (1.25..(1. + 1. / 3.)).contains(&time)
            || (1.375..1.9).contains(&time)
            || (2.0..2.5).contains(&time)
            || (2.9..3.5).contains(&time)
            || (4.2..8.4).contains(&time),
        movement: if (2.5..4.2).contains(&time) {
            Vec2::Y
        } else {
            Vec2::ZERO
        },
        sprint: (3.5..4.2).contains(&time),
        fire: (4.8..5.0).contains(&time),
        reload: (5.1..5.15).contains(&time),
        ..crate::sim::Input::default()
    }
}

pub fn gameplay_ads_replay_segment(time: f64) -> &'static str {
    if time < 1.25 {
        "complete_cycle"
    } else if time < 1.9 {
        "entry_reversal"
    } else if time < 2.5 {
        "exit_reversal"
    } else if time < 2.9 {
        "walk"
    } else if time < 3.5 {
        "walk_to_ads"
    } else if time < 4.2 {
        "sprint_interrupt"
    } else if time < 4.8 {
        "sprint_to_ads"
    } else if time < 5.1 {
        "fire_while_aiming"
    } else if time < 8.4 {
        "reload_interrupt_and_return"
    } else {
        "final_exit"
    }
}
