//! Concurrent authored walk, ADS and run presentation, on committed time only.
//! No reference-match approval is implied by these runtime continuity contracts.
use crate::{
    animation_manifest::{AdsReference, DirectionalWalkClips},
    authored_ads::AuthoredAds,
    authored_locomotion_adapter::PoseBindings,
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathConfig},
    authored_walk::{AuthoredWalk, ForwardAdsSamples, WalkLayerInput, WalkPoseLayer},
    sim::Simulation,
    viewmodel_animation::{AnimationError, AnimationSet, Result, Transform, ViewmodelPose},
};
use macroquad::math::{Mat4, Vec3};

pub const RUN_FADE_IN_SECONDS: f64 = 0.16;
pub const RUN_FADE_OUT_SECONDS: f64 = 0.22;

/// Source sets stay with their renderer, avoiding a copy of every baked frame.
#[derive(Clone, Copy)]
pub struct LayerSources<'a> {
    pub locomotion: &'a AnimationSet,
    pub walk: Option<&'a AnimationSet>,
    pub ads: Option<&'a AnimationSet>,
}

/// Shared weapon-space pose blending retains attached hands through a crossfade.
/// Bone globals are interpolated relative to the weapon, then rebuilt as locals.
/// This preserves contact, but does not promise exact intermediate bone lengths.
#[derive(Clone, Debug)]
pub struct AnchoredPoseBlend {
    bindings: PoseBindings,
    anchor: usize,
}
impl AnchoredPoseBlend {
    pub fn new(animation: &AnimationSet, anchor: &str) -> Result<Self> {
        Ok(Self {
            bindings: PoseBindings::from_animation(animation),
            anchor: animation
                .actors()
                .iter()
                .position(|a| a.name == anchor)
                .ok_or_else(|| AnimationError(format!("missing layer anchor actor: {anchor}")))?,
        })
    }
    pub fn blend(
        &self,
        animation: &AnimationSet,
        from: &ViewmodelPose,
        to: &ViewmodelPose,
        weight: f32,
    ) -> Result<ViewmodelPose> {
        if !self.bindings.matches(animation) || !weight.is_finite() || !(0. ..=1.).contains(&weight)
        {
            return Err(AnimationError(
                "invalid anchored blend bindings or weight".into(),
            ));
        }
        animation.blend_poses(from, to, 0.)?;
        if weight == 0. {
            return Ok(from.clone());
        }
        if weight == 1. {
            return Ok(to.clone());
        }
        let a = from.actor_globals[self.anchor];
        let b = to.actor_globals[self.anchor];
        let output = Transform {
            translation: a.translation.lerp(b.translation, weight),
            rotation: a.rotation.slerp(b.rotation, weight).normalize(),
            scale: a.scale.lerp(b.scale, weight),
        }
        .matrix();
        let relative = |pose: &ViewmodelPose| -> Result<ViewmodelPose> {
            let inverse = pose.actor_globals[self.anchor].matrix().inverse();
            let globals = animation.bone_globals(pose, Mat4::IDENTITY)?;
            let mut pose = pose.clone();
            pose.bone_locals = globals
                .into_iter()
                .map(|global| transform(inverse * global))
                .collect::<Result<Vec<_>>>()?;
            for actor in &mut pose.actor_globals {
                *actor = transform(inverse * actor.matrix())?;
            }
            Ok(pose)
        };
        let mut pose = animation.blend_poses(&relative(from)?, &relative(to)?, weight)?;
        let globals: Vec<_> = pose
            .bone_locals
            .iter()
            .map(|bone| output * bone.matrix())
            .collect();
        for (index, bone) in animation.bones().iter().enumerate() {
            pose.bone_locals[index] = transform(bone.parent.map_or(globals[index], |parent| {
                globals[parent].inverse() * globals[index]
            }))?;
        }
        for actor in &mut pose.actor_globals {
            *actor = transform(output * actor.matrix())?;
        }
        animation.blend_poses(&pose, &pose, 0.)
    }
}
fn transform(matrix: Mat4) -> Result<Transform> {
    if !matrix.is_finite() {
        return Err(AnimationError("non-finite layered pose".into()));
    }
    let (scale, rotation, translation) = matrix.to_scale_rotation_translation();
    if !rotation.is_finite()
        || rotation.length_squared() <= 1e-8
        || !scale.is_finite()
        || scale.min_element() <= 1e-8
    {
        return Err(AnimationError("invalid layered transform".into()));
    }
    let value = Transform {
        scale,
        rotation: rotation.normalize(),
        translation,
    };
    if !value.matrix().abs_diff_eq(matrix, 5e-5) {
        return Err(AnimationError(
            "layered blending does not support shear".into(),
        ));
    }
    Ok(value)
}

/// Four native-time HIP loops share one walk clock. The weights are camera-relative
/// horizontal motion, exponentially eased without resetting when direction changes.
#[derive(Clone, Debug)]
struct DirectionalWalk {
    clips: DirectionalWalkClips,
    weights: [f64; 4],
}
impl DirectionalWalk {
    fn update(&mut self, simulation: &Simulation, dt: f64, new_cycle: bool) -> (f64, f64) {
        let player = &simulation.player;
        if !player.grounded || player.speed() <= 0.1 || player.sprinting || player.mantle.is_some()
        {
            return (self.weights[0], self.weights[0]);
        }
        let forward = Vec3::new(player.yaw.cos(), 0., player.yaw.sin());
        let right = forward.cross(Vec3::Y);
        let along = f64::from(player.velocity.dot(forward));
        let across = f64::from(player.velocity.dot(right));
        let sum = along.abs() + across.abs();
        let target = [
            along.max(0.) / sum,
            (-along).max(0.) / sum,
            (-across).max(0.) / sum,
            across.max(0.) / sum,
        ];
        let amount = if new_cycle {
            1.
        } else {
            1. - (-dt / 0.06).exp()
        };
        let previous_forward = if new_cycle {
            target[0]
        } else {
            self.weights[0]
        };
        for (weight, target) in self.weights.iter_mut().zip(target) {
            *weight += (target - *weight) * amount;
        }
        (previous_forward, target[0])
    }
    fn pose(
        &self,
        set: &AnimationSet,
        seconds: f64,
        blend: &AnchoredPoseBlend,
    ) -> Result<ViewmodelPose> {
        let mut result = None;
        let mut total = 0.;
        for (clip, weight) in self.clips.names().into_iter().zip(self.weights) {
            if weight <= 0. {
                continue;
            }
            let source = set.sample(clip, seconds as f32)?;
            total += weight;
            result = Some(match result {
                None => source,
                Some(previous) => blend.blend(set, &previous, &source, (weight / total) as f32)?,
            });
        }
        result.ok_or_else(|| AnimationError("empty directional layer weights".into()))
    }
}

#[derive(Clone, Debug)]
pub struct LayeredLocomotion {
    path: AuthoredLocomotionPath,
    walk: AuthoredWalk,
    walk_clip: Option<String>,
    directional_walk: Option<DirectionalWalk>,
    walk_layer: Option<WalkPoseLayer>,
    ads: Option<AuthoredAds>,
    blend: AnchoredPoseBlend,
    ready: ViewmodelPose,
    pose: ViewmodelPose,
    run_envelope: f64,
    last_time: f64,
    reload_active: bool,
    receiver_ads_wip: bool,
    forward_ads_v9_wip: bool,
}
impl LayeredLocomotion {
    pub fn set_walk_translation(&mut self, value: crate::settings::WalkTranslation) {
        if let Some(layer) = &mut self.walk_layer {
            layer.set_translation_adjustment(value);
        }
    }
    pub fn new(
        sources: LayerSources<'_>,
        config: AuthoredLocomotionPathConfig,
        walk_clip: Option<&str>,
        ads: Option<AdsReference>,
        anchor: &str,
    ) -> Result<Self> {
        let path = AuthoredLocomotionPath::new(sources.locomotion, config.clone(), 0.)?;
        let ready = path.pose().clone();
        let walk_layer = match (sources.walk, walk_clip) {
            (Some(set), Some(clip)) => {
                AuthoredWalk::validate_clip(set, clip)?;
                Some(WalkPoseLayer::new(
                    set,
                    sources.locomotion,
                    &config.ready_clip,
                    anchor,
                )?)
            }
            (None, None) => None,
            _ => {
                return Err(AnimationError(
                    "walk source and clip must be supplied together".into(),
                ))
            }
        };
        let ads = match (sources.ads, ads) {
            (Some(set), Some(clips)) => Some(AuthoredAds::new(
                set,
                sources.locomotion,
                &config.ready_clip,
                clips,
            )?),
            (None, None) => None,
            _ => {
                return Err(AnimationError(
                    "ADS source and clips must be supplied together".into(),
                ))
            }
        };
        Ok(Self {
            blend: AnchoredPoseBlend::new(sources.locomotion, anchor)?,
            path,
            walk: AuthoredWalk::default(),
            walk_clip: walk_clip.map(str::to_owned),
            directional_walk: None,
            walk_layer,
            ads,
            pose: ready.clone(),
            ready,
            run_envelope: 0.,
            last_time: 0.,
            reload_active: false,
            receiver_ads_wip: false,
            forward_ads_v9_wip: false,
        })
    }
    pub fn with_ads_wip_policy(
        mut self,
        receiver: bool,
        visual_seconds: Option<f64>,
    ) -> Result<Self> {
        self.receiver_ads_wip = receiver;
        if let Some(layer) = &mut self.walk_layer {
            layer.use_receiver_v4_wip(receiver);
        }
        if let Some(seconds) = visual_seconds {
            if let Some(ads) = self.ads.take() {
                self.ads = Some(ads.with_visual_transition_seconds(seconds)?);
            }
        }
        Ok(self)
    }
    /// Authored forward v9; other directions explicitly keep v4 as WIP fallback.
    pub fn with_forward_ads_v9_policy(mut self, active: bool) -> Result<Self> {
        if self.last_time != 0. || (active && !self.receiver_ads_wip) {
            return Err(AnimationError(
                "v9 requires unstarted receiver ADS layers".into(),
            ));
        }
        self.forward_ads_v9_wip = active;
        Ok(self)
    }
    /// Optional reviewed four-direction clips; absent data preserves the old walk.
    /// This is an initialization operation, not a live pose-reset API.
    pub fn with_directional_walk(
        mut self,
        set: &AnimationSet,
        clips: DirectionalWalkClips,
    ) -> Result<Self> {
        if self.last_time != 0. || self.walk_clip.is_none() || !self.blend.bindings.matches(set) {
            return Err(AnimationError(
                "directional walk needs unstarted canonical walk bindings".into(),
            ));
        }
        for clip in clips.names() {
            AuthoredWalk::validate_clip(set, clip)?;
        }
        self.directional_walk = Some(DirectionalWalk {
            clips,
            weights: [1., 0., 0., 0.],
        });
        Ok(self)
    }
    /// Forward, backward, left, right; unchanged through stops and sprint fades.
    pub fn directional_weights(&self) -> Option<[f64; 4]> {
        self.directional_walk.as_ref().map(|walk| walk.weights)
    }
    /// All layers observe the same committed interval. Run never waits for ADS
    /// exit, and a returning run never prevents ADS/walk from blending back in.
    /// Reversals preserve each native clock and current envelope. Errors are atomic.
    pub fn committed_step(
        &mut self,
        sources: LayerSources<'_>,
        start: f64,
        simulation: &Simulation,
        reload_active: bool,
    ) -> Result<()> {
        let end = simulation.time;
        if start != self.last_time || !start.is_finite() || !end.is_finite() || end < start {
            return Err(AnimationError(
                "layers require contiguous committed ticks; reset explicitly".into(),
            ));
        }
        if end == start {
            return Ok(());
        }
        for source in [Some(sources.locomotion), sources.walk, sources.ads]
            .into_iter()
            .flatten()
        {
            if !self.blend.bindings.matches(source) {
                return Err(AnimationError(
                    "canonical layer source bindings changed during playback".into(),
                ));
            }
        }
        let mut next = self.clone();
        next.step(sources, start, simulation, reload_active)?;
        *self = next;
        Ok(())
    }
    fn step(
        &mut self,
        sources: LayerSources<'_>,
        start: f64,
        simulation: &Simulation,
        reload_active: bool,
    ) -> Result<()> {
        let end = simulation.time;
        if reload_active || self.reload_active {
            self.path.reset(sources.locomotion, start)?;
            self.run_envelope = 0.;
        }
        if let Some(ads) = &mut self.ads {
            // Ready is always the underlying ADS base, even under a run layer.
            ads.committed_step(start, simulation, reload_active, true)?;
        }
        let player = &simulation.player;
        let run = player.sprinting && !reload_active && player.reload_left <= 0.;
        self.path.update(sources.locomotion, start, run, true)?;
        self.path.update(sources.locomotion, end, run, true)?;
        self.run_envelope = if run {
            (self.run_envelope + (end - start) / RUN_FADE_IN_SECONDS).min(1.)
        } else {
            (self.run_envelope - (end - start) / RUN_FADE_OUT_SECONDS).max(0.)
        };
        let eligible = self.walk_clip.is_some() && !reload_active && player.reload_left <= 0.;
        let moving =
            player.grounded && player.speed() > 0.1 && !player.sprinting && player.mantle.is_none();
        let new_cycle = self.walk.seconds().is_none();
        let forward_curve = self
            .directional_walk
            .as_mut()
            .map(|direction| direction.update(simulation, end - start, new_cycle));
        let aim_integral = self.ads.as_ref().map_or(0., AuthoredAds::last_aim_integral);
        let forward_aim_integral = if self.forward_ads_v9_wip {
            forward_curve.map_or(0., |(from, target)| {
                self.ads
                    .as_ref()
                    .map_or(0., |ads| ads.last_aim_weighted_integral(from, target, 0.06))
            })
        } else {
            0.
        };
        let phase_advance = if self.receiver_ads_wip {
            (end - start - 0.15 * aim_integral - 0.05 * forward_aim_integral).max(0.)
        } else {
            end - start
        };
        self.walk
            .committed_step_with_phase(start, end, moving, eligible, phase_advance)?;
        let mut pose = match (&self.ads, sources.ads) {
            (Some(ads), Some(set)) => ads.pose(set)?.unwrap_or_else(|| self.ready.clone()),
            (None, None) => self.ready.clone(),
            _ => return Err(AnimationError("ADS source changed during playback".into())),
        };
        if let (Some(layer), Some(clip), Some(seconds), Some(set)) = (
            &self.walk_layer,
            &self.walk_clip,
            self.walk.seconds(),
            sources.walk,
        ) {
            let walk = match &self.directional_walk {
                Some(direction) => direction.pose(set, seconds, &self.blend)?,
                None => set.sample(clip, seconds as f32)?,
            };
            let forward_samples = if self.forward_ads_v9_wip {
                self.directional_walk
                    .as_ref()
                    .map(|direction| {
                        let clip = &direction.clips.forward;
                        let duration = set
                            .clips()
                            .iter()
                            .find(|candidate| &candidate.name == clip)
                            .ok_or_else(|| AnimationError("missing v9 forward clip".into()))?
                            .duration();
                        Ok::<_, AnimationError>((
                            set.sample(clip, seconds as f32)?,
                            set.sample(clip, seconds as f32 + duration * 0.5)?,
                            direction.weights[0] as f32,
                        ))
                    })
                    .transpose()?
            } else {
                None
            };
            pose = layer.pose_with_input(
                sources.locomotion,
                &pose,
                WalkLayerInput {
                    walk: &walk,
                    weight: self.walk.weight(),
                    aim: self.ads.as_ref().map_or(0., AuthoredAds::aim_amount),
                    lateral: self
                        .directional_weights()
                        .map_or(0., |weights| (weights[2] + weights[3]) as f32),
                    forward_ads: forward_samples
                        .as_ref()
                        .map(|(primary, half_period, weight)| ForwardAdsSamples {
                            primary,
                            half_period,
                            weight: *weight,
                        }),
                },
            )?;
        } else if self.walk_clip.is_some() && sources.walk.is_none() {
            return Err(AnimationError("walk source changed during playback".into()));
        }
        self.pose = self.blend.blend(
            sources.locomotion,
            &pose,
            self.path.pose(),
            self.run_weight(),
        )?;
        self.last_time = end;
        self.reload_active = reload_active;
        Ok(())
    }
    pub fn reset(&mut self, animation: &AnimationSet, time: f64) -> Result<()> {
        let mut next = self.clone();
        next.path.reset(animation, time)?;
        next.walk.reset(time);
        if let Some(direction) = &mut next.directional_walk {
            direction.weights = [1., 0., 0., 0.];
        }
        if let Some(ads) = &mut next.ads {
            ads.reset(time);
        }
        next.pose = next.ready.clone();
        next.run_envelope = 0.;
        next.last_time = time;
        next.reload_active = false;
        *self = next;
        Ok(())
    }
    pub fn pose(&self) -> &ViewmodelPose {
        &self.pose
    }
    /// Deterministic pose-only diagnostic checksum; not file authentication.
    pub fn pose_crc32(&self) -> u32 {
        let mut bytes = Vec::new();
        for transform in self.pose.bone_locals.iter().chain(&self.pose.actor_globals) {
            for value in transform
                .translation
                .to_array()
                .into_iter()
                .chain(transform.rotation.to_array())
                .chain(transform.scale.to_array())
            {
                bytes.extend(value.to_bits().to_le_bytes());
            }
        }
        bytes.extend(
            self.pose
                .actor_visible
                .iter()
                .map(|&visible| u8::from(visible)),
        );
        crate::skinned_asset::crc32(&bytes)
    }
    pub fn path(&self) -> &AuthoredLocomotionPath {
        &self.path
    }
    pub fn walk_clip(&self) -> Option<&str> {
        if let Some(direction) = &self.directional_walk {
            let index = direction
                .weights
                .iter()
                .enumerate()
                .max_by(|a, b| a.1.total_cmp(b.1))
                .map_or(0, |(index, _)| index);
            Some(direction.clips.names()[index])
        } else {
            self.walk_clip.as_deref()
        }
    }
    pub fn walk(&self) -> &AuthoredWalk {
        &self.walk
    }
    pub fn ads(&self) -> Option<&AuthoredAds> {
        self.ads.as_ref()
    }
    pub fn walk_min_rate(&self) -> f32 {
        if self.forward_ads_v9_wip && self.directional_walk.is_some() {
            0.80
        } else if self.receiver_ads_wip {
            0.85
        } else {
            1.
        }
    }
    pub fn run_weight(&self) -> f32 {
        (self.run_envelope * self.run_envelope * (3. - 2. * self.run_envelope)) as f32
    }
}

/// Ordinary-input replay for four HIP/ADS directions and rapid run interruptions.
/// The source assets are not selected or changed by this diagnostic.
pub fn gameplay_layered_replay_input(time: f64) -> crate::sim::Input {
    use macroquad::math::Vec2;
    let movement = if (0.25..2.25).contains(&time) || (8.25..10.).contains(&time) {
        Vec2::Y
    } else if (2.25..4.25).contains(&time) {
        -Vec2::Y
    } else if (4.25..6.25).contains(&time) {
        -Vec2::X
    } else if (6.25..8.25).contains(&time) {
        Vec2::X
    } else {
        Vec2::ZERO
    };
    crate::sim::Input {
        movement,
        ads: (1.25..2.25).contains(&time)
            || (3.25..4.25).contains(&time)
            || (5.25..6.25).contains(&time)
            || (7.25..8.75).contains(&time)
            || (9.0..9.1).contains(&time)
            || (9.2..9.5).contains(&time),
        sprint: (8.75..9.0).contains(&time) || (9.1..9.2).contains(&time),
        ..crate::sim::Input::default()
    }
}
pub fn gameplay_layered_replay_segment(time: f64) -> &'static str {
    if time < 0.25 {
        "ready"
    } else if time < 1.25 {
        "forward_hip"
    } else if time < 2.25 {
        "forward_ads"
    } else if time < 3.25 {
        "backward_hip"
    } else if time < 4.25 {
        "backward_ads"
    } else if time < 5.25 {
        "left_hip"
    } else if time < 6.25 {
        "left_ads"
    } else if time < 7.25 {
        "right_hip"
    } else if time < 8.25 {
        "right_ads"
    } else if time < 8.75 {
        "moving_ads"
    } else if time < 9.5 {
        "rapid_run_interruptions"
    } else if time < 10. {
        "hip_return"
    } else {
        "final_stop"
    }
}
