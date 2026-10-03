//! Concurrent authored walk, ADS and run presentation, on committed time only.
//! No reference-match approval is implied by these runtime continuity contracts.
use crate::{
    animation_manifest::AdsReference,
    authored_ads::AuthoredAds,
    authored_locomotion_adapter::PoseBindings,
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathConfig},
    authored_walk::{AuthoredWalk, WalkPoseLayer},
    sim::Simulation,
    viewmodel_animation::{AnimationError, AnimationSet, Result, Transform, ViewmodelPose},
};
use macroquad::math::Mat4;

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

#[derive(Clone, Debug)]
pub struct LayeredLocomotion {
    path: AuthoredLocomotionPath,
    walk: AuthoredWalk,
    walk_clip: Option<String>,
    walk_layer: Option<WalkPoseLayer>,
    ads: Option<AuthoredAds>,
    blend: AnchoredPoseBlend,
    ready: ViewmodelPose,
    pose: ViewmodelPose,
    run_envelope: f64,
    last_time: f64,
    reload_active: bool,
}
impl LayeredLocomotion {
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
            walk_layer,
            ads,
            pose: ready.clone(),
            ready,
            run_envelope: 0.,
            last_time: 0.,
            reload_active: false,
        })
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
        self.walk.committed_step(start, end, moving, eligible)?;
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
            let walk = set.sample(clip, seconds as f32)?;
            pose = layer.pose(
                sources.locomotion,
                &pose,
                &walk,
                self.walk.weight(),
                self.ads.as_ref().map_or(0., AuthoredAds::aim_amount),
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
    pub fn path(&self) -> &AuthoredLocomotionPath {
        &self.path
    }
    pub fn walk(&self) -> &AuthoredWalk {
        &self.walk
    }
    pub fn ads(&self) -> Option<&AuthoredAds> {
        self.ads.as_ref()
    }
    pub fn run_weight(&self) -> f32 {
        (self.run_envelope * self.run_envelope * (3. - 2. * self.run_envelope)) as f32
    }
}
