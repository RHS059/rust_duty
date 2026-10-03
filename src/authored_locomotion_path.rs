//! Candidate playback of authored connected paths, pending real-asset contact QA.
//!
//! Entry reversals retrace entry. Exit reversals retrace a captured-phase bridge,
//! exit and settle path. Only adjacent phase bridge variants are pose-interpolated;
//! there are no wide crossfades. A strictly capped, progress-based local TRS
//! residual corrects the small phase-interpolation seam. Its original error is
//! exposed for QA, and real skinned contacts still require measurement.
use crate::viewmodel_animation::{AnimationError, AnimationSet, Result, ViewmodelPose};

#[derive(Clone, Debug)]
pub struct AuthoredLocomotionPathConfig {
    pub ready_clip: String,
    pub entry_clip: String,
    pub loop_clip: String,
    /// Evenly spaced forward loop phases, excluding the duplicated loop endpoint.
    pub exit_bridge_clips: Vec<String>,
    pub exit_clip: String,
    pub settle_clip: String,
    /// First-order rate response. (0, 0.07] bounds a backward-loop stop's
    /// deceleration to less than 49 ms before its forward bridge starts.
    pub rate_response_seconds: f64,
    /// Small phase-interpolation correction decays by this bridge progress.
    /// Must be finite, positive and shorter than the authored bridge.
    pub residual_decay_seconds: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AuthoredLocomotionPathState {
    Ready,
    Entry,
    Loop,
    ExitBridge,
    Exit,
    Settle,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct BridgeJoinError {
    pub max_bone_local_translation_m: f32,
    pub max_actor_global_translation_m: f32,
    pub max_rotation_radians: f32,
    pub max_scale_component: f32,
    pub visibility_changes: usize,
}

#[derive(Clone, Debug)]
struct BridgeCorrection {
    phase: f64,
    source: ViewmodelPose,
    base: ViewmodelPose,
    error: BridgeJoinError,
}

#[derive(Clone, Copy, Debug)]
enum Segment {
    Ready,
    Entry,
    Loop,
    Exit { phase: f64 },
}

#[derive(Clone, Copy, Debug)]
struct Motion {
    segment: Segment,
    start: f64,
    position: f64,
    rate: f64,
    target: f64,
}
impl Motion {
    fn at(self, time: f64, tau: f64) -> (f64, f64) {
        let dt = time - self.start;
        let decay = (-dt / tau).exp();
        let displacement =
            self.target * dt + (self.rate - self.target) * tau * -(-dt / tau).exp_m1();
        (
            self.position + displacement,
            self.target + (self.rate - self.target) * decay,
        )
    }
    fn relative_position(self, dt: f64, tau: f64) -> f64 {
        self.position + self.target * dt + (self.rate - self.target) * tau * -(-dt / tau).exp_m1()
    }
    fn turn_time(self, tau: f64) -> f64 {
        if self.rate * self.target < 0. {
            tau * ((self.target - self.rate) / self.target).ln()
        } else {
            0.
        }
    }
}

#[derive(Clone, Debug)]
pub struct AuthoredLocomotionPath {
    config: AuthoredLocomotionPathConfig,
    entry_duration: f64,
    loop_duration: f64,
    bridge_duration: f64,
    exit_duration: f64,
    settle_duration: f64,
    motion: Motion,
    wanted_sprint: bool,
    last_time: f64,
    pose: ViewmodelPose,
    last_bridge_join: Option<BridgeJoinError>,
    bridge_correction: Option<BridgeCorrection>,
}

fn valid_time(time: f64) -> Result<()> {
    if time.is_finite() && time >= 0. {
        Ok(())
    } else {
        Err(AnimationError(
            "path simulation time must be finite and nonnegative".into(),
        ))
    }
}
fn duration(set: &AnimationSet, name: &str, looping: bool) -> Result<f64> {
    let clip = set
        .clips()
        .iter()
        .find(|clip| clip.name == name)
        .ok_or_else(|| AnimationError(format!("unknown path clip: {name}")))?;
    if clip.looping != looping || clip.duration() <= 0. {
        return Err(AnimationError(format!(
            "path clip {name} needs positive duration and looping={looping}"
        )));
    }
    Ok(f64::from(clip.duration()))
}
fn pose_error(first: &ViewmodelPose, second: &ViewmodelPose) -> BridgeJoinError {
    let mut error = BridgeJoinError {
        visibility_changes: first
            .actor_visible
            .iter()
            .zip(&second.actor_visible)
            .filter(|(a, b)| a != b)
            .count(),
        ..BridgeJoinError::default()
    };
    for (index, (a, b)) in first
        .bone_locals
        .iter()
        .chain(&first.actor_globals)
        .zip(second.bone_locals.iter().chain(&second.actor_globals))
        .enumerate()
    {
        let distance = (a.translation - b.translation).length();
        if index < first.bone_locals.len() {
            error.max_bone_local_translation_m = error.max_bone_local_translation_m.max(distance);
        } else {
            error.max_actor_global_translation_m =
                error.max_actor_global_translation_m.max(distance);
        }
        let delta = if a.rotation.dot(b.rotation) < 0. {
            a.rotation + b.rotation
        } else {
            a.rotation - b.rotation
        };
        let chord = delta.to_array().iter().map(|v| v * v).sum::<f32>().sqrt();
        error.max_rotation_radians = error
            .max_rotation_radians
            .max(4. * (chord * 0.5).min(1.).asin());
        error.max_scale_component = error
            .max_scale_component
            .max((a.scale - b.scale).abs().max_element());
    }
    error
}
fn require_join(set: &AnimationSet, a: &str, at: f64, b: &str, bt: f64) -> Result<()> {
    let difference = pose_error(
        &set.sample_clamped(a, at as f32)?,
        &set.sample_clamped(b, bt as f32)?,
    );
    if difference.max_bone_local_translation_m > 1e-5
        || difference.max_actor_global_translation_m > 1e-5
        || difference.max_rotation_radians > 1e-4
        || difference.max_scale_component > 1e-5
        || difference.visibility_changes != 0
    {
        return Err(AnimationError(format!(
            "disconnected authored path {a} -> {b}: {difference:?}"
        )));
    }
    Ok(())
}

impl AuthoredLocomotionPath {
    /// Bind to one immutable animation set. Ready holds the authored first pose.
    /// Natural joins and each phase bridge endpoint must match before playback.
    pub fn new(
        set: &AnimationSet,
        config: AuthoredLocomotionPathConfig,
        time: f64,
    ) -> Result<Self> {
        valid_time(time)?;
        if !config.rate_response_seconds.is_finite()
            || config.rate_response_seconds <= 0.
            || config.rate_response_seconds > 0.07
        {
            return Err(AnimationError(
                "path rate response must be in (0, 0.07] seconds".into(),
            ));
        }
        if config.exit_bridge_clips.len() < 2 {
            return Err(AnimationError(
                "path requires at least two ordered phase bridges".into(),
            ));
        }
        let entry_duration = duration(set, &config.entry_clip, false)?;
        let loop_duration = duration(set, &config.loop_clip, true)?;
        let exit_duration = duration(set, &config.exit_clip, false)?;
        let settle_duration = duration(set, &config.settle_clip, false)?;
        let bridge_duration = duration(set, &config.exit_bridge_clips[0], false)?;
        if !config.residual_decay_seconds.is_finite()
            || config.residual_decay_seconds <= 0.
            || config.residual_decay_seconds >= bridge_duration
        {
            return Err(AnimationError(
                "bridge residual decay must be positive and shorter than its clip".into(),
            ));
        }
        require_join(set, &config.ready_clip, 0., &config.entry_clip, 0.)?;
        require_join(
            set,
            &config.entry_clip,
            entry_duration,
            &config.loop_clip,
            0.,
        )?;
        require_join(set, &config.loop_clip, loop_duration, &config.loop_clip, 0.)?;
        require_join(
            set,
            &config.exit_clip,
            exit_duration,
            &config.settle_clip,
            0.,
        )?;
        require_join(
            set,
            &config.settle_clip,
            settle_duration,
            &config.ready_clip,
            0.,
        )?;
        for (index, bridge) in config.exit_bridge_clips.iter().enumerate() {
            if (duration(set, bridge, false)? - bridge_duration).abs() > 1e-7 {
                return Err(AnimationError("phase bridge durations must match".into()));
            }
            require_join(set, bridge, bridge_duration, &config.exit_clip, 0.)?;
            let phase = loop_duration * index as f64 / config.exit_bridge_clips.len() as f64;
            require_join(set, &config.loop_clip, phase, bridge, 0.)?;
        }
        let pose = set.sample_clamped(&config.ready_clip, 0.)?;
        Ok(Self {
            config,
            entry_duration,
            loop_duration,
            bridge_duration,
            exit_duration,
            settle_duration,
            motion: Motion {
                segment: Segment::Ready,
                start: time,
                position: 0.,
                rate: 0.,
                target: 0.,
            },
            wanted_sprint: false,
            last_time: time,
            pose,
            last_bridge_join: None,
            bridge_correction: None,
        })
    }

    /// Restore a fully settled ready pose. Same-time input may start entry.
    pub fn reset(&mut self, set: &AnimationSet, time: f64) -> Result<()> {
        valid_time(time)?;
        let pose = set.sample_clamped(&self.config.ready_clip, 0.)?;
        self.motion = Motion {
            segment: Segment::Ready,
            start: time,
            position: 0.,
            rate: 0.,
            target: 0.,
        };
        self.wanted_sprint = false;
        self.last_time = time;
        self.pose = pose;
        self.last_bridge_join = None;
        self.bridge_correction = None;
        Ok(())
    }

    /// Advance committed intent, then accept input at `time`. Repeated time
    /// never advances a path. A loop-to-bridge join uses its exact cached source
    /// at zero progress; native discrepancy remains available for QA. Disabled only suppresses
    /// sprint; the caller retains immediate ownership of reload/ADS/gameplay.
    /// Invalid input or sample errors leave the controller unchanged.
    pub fn update(
        &mut self,
        set: &AnimationSet,
        time: f64,
        sprint: bool,
        enabled: bool,
    ) -> Result<()> {
        valid_time(time)?;
        if time < self.last_time {
            let mut reset = self.clone();
            reset.reset(set, time)?;
            reset.update(set, time, sprint, enabled)?;
            *self = reset;
            return Ok(());
        }
        let (mut motion, mut join) = self.advance(set, self.motion, time, self.wanted_sprint)?;
        let wanted = sprint && enabled;
        if wanted != self.wanted_sprint {
            let (position, rate) = motion.at(time, self.config.rate_response_seconds);
            motion = match motion.segment {
                Segment::Ready if wanted => Motion {
                    segment: Segment::Entry,
                    start: time,
                    position: 0.,
                    rate: 1.,
                    target: 1.,
                },
                Segment::Ready => motion,
                Segment::Entry => Motion {
                    start: time,
                    position,
                    rate,
                    target: if wanted { 1. } else { -1. },
                    ..motion
                },
                Segment::Loop => Motion {
                    start: time,
                    position: position.rem_euclid(self.loop_duration),
                    rate,
                    target: 1.,
                    ..motion
                },
                Segment::Exit { .. } => Motion {
                    start: time,
                    position,
                    rate,
                    target: if wanted { -1. } else { 1. },
                    ..motion
                },
            };
            let (next, new_join) = self.advance(set, motion, time, wanted)?;
            motion = next;
            if new_join.is_some() {
                join = new_join;
            }
        }
        let correction = join.as_ref().or(self.bridge_correction.as_ref());
        let pose = self.sample_motion(set, motion, time, correction)?;
        self.motion = motion;
        self.wanted_sprint = wanted;
        self.last_time = time;
        self.pose = pose;
        if let Some(correction) = join {
            self.last_bridge_join = Some(correction.error);
            self.bridge_correction = Some(correction);
        }
        Ok(())
    }

    pub fn pose(&self) -> &ViewmodelPose {
        &self.pose
    }
    pub fn simulation_time(&self) -> f64 {
        self.last_time
    }
    pub fn playback_rate(&self) -> f64 {
        self.motion
            .at(self.last_time, self.config.rate_response_seconds)
            .1
    }
    /// Local-TRS/actor error only. This does not measure skinned hand contact.
    pub fn last_bridge_join_error(&self) -> Option<BridgeJoinError> {
        self.last_bridge_join
    }
    pub fn state(&self) -> AuthoredLocomotionPathState {
        use AuthoredLocomotionPathState as State;
        match self.motion.segment {
            Segment::Ready => State::Ready,
            Segment::Entry => State::Entry,
            Segment::Loop => State::Loop,
            Segment::Exit { .. } => {
                let position = self
                    .motion
                    .at(self.last_time, self.config.rate_response_seconds)
                    .0;
                if position < self.bridge_duration {
                    State::ExitBridge
                } else if position < self.bridge_duration + self.exit_duration {
                    State::Exit
                } else {
                    State::Settle
                }
            }
        }
    }

    fn exit_total(&self) -> f64 {
        self.bridge_duration + self.exit_duration + self.settle_duration
    }

    fn sample_bridge(&self, set: &AnimationSet, phase: f64, time: f64) -> Result<ViewmodelPose> {
        let index = phase.rem_euclid(self.loop_duration) / self.loop_duration
            * self.config.exit_bridge_clips.len() as f64;
        let lower = (index.floor() as usize).min(self.config.exit_bridge_clips.len() - 1);
        let upper = (lower + 1) % self.config.exit_bridge_clips.len();
        let first = set.sample_clamped(&self.config.exit_bridge_clips[lower], time as f32)?;
        let second = set.sample_clamped(&self.config.exit_bridge_clips[upper], time as f32)?;
        set.blend_poses(&first, &second, (index - lower as f64).clamp(0., 1.) as f32)
    }

    fn corrected_bridge(
        &self,
        set: &AnimationSet,
        correction: &BridgeCorrection,
        progress: f64,
    ) -> Result<ViewmodelPose> {
        if progress == 0. {
            return Ok(correction.source.clone());
        }
        let mut pose = self.sample_bridge(set, correction.phase, progress)?;
        if progress >= self.config.residual_decay_seconds {
            return Ok(pose);
        }
        let t = progress / self.config.residual_decay_seconds;
        let weight = (1. - t * t * (3. - 2. * t)) as f32;
        for ((target, source), base) in pose
            .bone_locals
            .iter_mut()
            .chain(&mut pose.actor_globals)
            .zip(
                correction
                    .source
                    .bone_locals
                    .iter()
                    .chain(&correction.source.actor_globals),
            )
            .zip(
                correction
                    .base
                    .bone_locals
                    .iter()
                    .chain(&correction.base.actor_globals),
            )
        {
            target.translation += (source.translation - base.translation) * weight;
            target.scale += (source.scale - base.scale) * weight;
            let mut relative = (source.rotation * base.rotation.conjugate()).normalize();
            if relative.w < 0. {
                relative = -relative;
            }
            target.rotation = (macroquad::math::Quat::IDENTITY.slerp(relative, weight)
                * target.rotation)
                .normalize();
        }
        // Reuse the decoder's finite, unit-rotation and positive-scale guards;
        // weight zero performs validation only and returns the corrected pose.
        set.blend_poses(&pose, &pose, 0.)
    }

    fn sample_motion(
        &self,
        set: &AnimationSet,
        motion: Motion,
        time: f64,
        correction: Option<&BridgeCorrection>,
    ) -> Result<ViewmodelPose> {
        let (position, _) = motion.at(time, self.config.rate_response_seconds);
        match motion.segment {
            Segment::Ready => set.sample_clamped(&self.config.ready_clip, 0.),
            Segment::Entry => set.sample_clamped(
                &self.config.entry_clip,
                position.clamp(0., self.entry_duration) as f32,
            ),
            Segment::Loop => set.sample_clamped(
                &self.config.loop_clip,
                position.rem_euclid(self.loop_duration) as f32,
            ),
            Segment::Exit { phase } => {
                if position < self.bridge_duration {
                    let correction =
                        correction
                            .filter(|item| item.phase == phase)
                            .ok_or_else(|| {
                                AnimationError("missing captured bridge correction".into())
                            })?;
                    self.corrected_bridge(set, correction, position.max(0.))
                } else if position < self.bridge_duration + self.exit_duration {
                    set.sample_clamped(
                        &self.config.exit_clip,
                        (position - self.bridge_duration) as f32,
                    )
                } else {
                    set.sample_clamped(
                        &self.config.settle_clip,
                        (position - self.bridge_duration - self.exit_duration) as f32,
                    )
                }
            }
        }
    }

    // Return the earliest boundary of a bounded path. Search brackets depend
    // only on its anchor, never the current tick's dt, so partitioning cannot
    // select different crossing times. Split at the analytic rate-zero point.
    fn boundary(&self, motion: Motion, length: f64) -> (f64, bool) {
        let tau = self.config.rate_response_seconds;
        let turn = motion.turn_time(tau);
        if motion.rate < 0. && motion.position <= 0. {
            return (0., false);
        }
        if motion.rate > 0. && motion.position >= length {
            return (0., true);
        }
        let first_end = motion.relative_position(turn, tau);
        if turn > 0. && (first_end <= 0. || first_end >= length) {
            let upper = first_end >= length;
            return (
                self.crossing(
                    motion,
                    0.,
                    turn,
                    if upper { length } else { 0. },
                    motion.rate > 0.,
                ),
                upper,
            );
        }
        let upper = motion.target > 0.;
        let boundary = if upper { length } else { 0. };
        let far = turn + (boundary - first_end).abs() + 4. * tau + 1.;
        (self.crossing(motion, turn, far, boundary, upper), upper)
    }

    fn crossing(
        &self,
        motion: Motion,
        mut low: f64,
        mut high: f64,
        value: f64,
        increasing: bool,
    ) -> f64 {
        for _ in 0..80 {
            let middle = low + (high - low) * 0.5;
            let position = motion.relative_position(middle, self.config.rate_response_seconds);
            if (position < value) == increasing {
                low = middle;
            } else {
                high = middle;
            }
        }
        low + (high - low) * 0.5
    }

    fn advance(
        &self,
        set: &AnimationSet,
        mut motion: Motion,
        time: f64,
        wanted: bool,
    ) -> Result<(Motion, Option<BridgeCorrection>)> {
        let mut join = None;
        for _ in 0..8 {
            let elapsed = time - motion.start;
            let (event_after, upper) = match motion.segment {
                Segment::Ready => return Ok((motion, join)),
                Segment::Entry => self.boundary(motion, self.entry_duration),
                Segment::Exit { .. } => self.boundary(motion, self.exit_total()),
                Segment::Loop if wanted => return Ok((motion, join)),
                Segment::Loop => (motion.turn_time(self.config.rate_response_seconds), true),
            };
            if event_after > elapsed {
                return Ok((motion, join));
            }
            let event_time = motion.start + event_after;
            let (position, rate) = motion.at(event_time, self.config.rate_response_seconds);
            motion = match motion.segment {
                Segment::Entry if upper => Motion {
                    segment: Segment::Loop,
                    start: event_time,
                    position: 0.,
                    rate,
                    target: 1.,
                },
                Segment::Entry | Segment::Exit { .. } if upper => {
                    // The ready endpoint is terminal. If inertia reached it
                    // after a restart request, start a fresh connected entry.
                    Motion {
                        segment: if wanted {
                            Segment::Entry
                        } else {
                            Segment::Ready
                        },
                        start: event_time,
                        position: 0.,
                        rate: if wanted { 1. } else { 0. },
                        target: if wanted { 1. } else { 0. },
                    }
                }
                Segment::Entry => Motion {
                    segment: if wanted {
                        Segment::Entry
                    } else {
                        Segment::Ready
                    },
                    start: event_time,
                    position: 0.,
                    rate: if wanted { 1. } else { 0. },
                    target: if wanted { 1. } else { 0. },
                },
                Segment::Exit { phase } => Motion {
                    segment: Segment::Loop,
                    start: event_time,
                    position: phase,
                    rate,
                    target: 1.,
                },
                Segment::Loop => {
                    let phase = position.rem_euclid(self.loop_duration);
                    let loop_pose = set.sample_clamped(&self.config.loop_clip, phase as f32)?;
                    let bridge_pose = self.sample_bridge(set, phase, 0.)?;
                    let error = pose_error(&loop_pose, &bridge_pose);
                    if error.max_bone_local_translation_m > 0.002
                        || error.max_actor_global_translation_m > 0.002
                        || error.max_rotation_radians > std::f32::consts::PI / 180.
                        || error.max_scale_component > 1e-4
                        || error.visibility_changes != 0
                    {
                        return Err(AnimationError(format!(
                            "bridge residual exceeds candidate limits: {error:?}"
                        )));
                    }
                    join = Some(BridgeCorrection {
                        phase,
                        source: loop_pose,
                        base: bridge_pose,
                        error,
                    });
                    Motion {
                        segment: Segment::Exit { phase },
                        start: event_time,
                        position: 0.,
                        rate: rate.max(0.),
                        target: 1.,
                    }
                }
                Segment::Ready => return Ok((motion, join)),
            };
        }
        Err(AnimationError(
            "path boundary processing did not converge".into(),
        ))
    }
}
