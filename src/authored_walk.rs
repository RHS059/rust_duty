//! Committed-time walk envelope and weapon-relative layering of authored poses.
use crate::{
    authored_locomotion_adapter::PoseBindings,
    viewmodel_animation::{AnimationError, AnimationSet, Result, Transform, ViewmodelPose},
};
use glam::{Mat4, Quat, Vec3};

pub const WALK_FADE_IN_SECONDS: f64 = 0.16;
pub const WALK_FADE_OUT_SECONDS: f64 = 0.22;

#[derive(Clone, Debug, Default)]
pub struct AuthoredWalk {
    started: Option<f64>,
    last_time: f64,
    envelope: f64,
    phase_seconds: f64,
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
        self.envelope = 0.;
        self.phase_seconds = 0.;
        self.last_time = time;
    }
    /// Ineligible means an incompatible owner (reload/reset), not ADS or sprint.
    /// Ordinary stopping and sprint entry fade the layer, retaining its phase.
    pub fn committed_step(
        &mut self,
        start: f64,
        end: f64,
        moving: bool,
        eligible: bool,
    ) -> Result<()> {
        self.committed_step_with_phase(start, end, moving, eligible, end - start)
    }
    /// Accumulate native phase explicitly; never multiply elapsed time by a changing rate.
    pub fn committed_step_with_phase(
        &mut self,
        start: f64,
        end: f64,
        moving: bool,
        eligible: bool,
        phase_advance: f64,
    ) -> Result<()> {
        if !phase_advance.is_finite() || phase_advance < 0. {
            return Err(AnimationError("invalid native walk phase advance".into()));
        }
        if start != self.last_time || !start.is_finite() || !end.is_finite() || end < start {
            return Err(AnimationError(
                "walk observer needs contiguous committed ticks; reset explicitly".into(),
            ));
        }
        if end == start {
            return Ok(());
        }
        if !eligible {
            self.reset(end);
            return Ok(());
        }
        if moving {
            if self.started.is_none() {
                self.started = Some(start);
                self.phase_seconds = 0.;
            }
            self.envelope = (self.envelope + (end - start) / WALK_FADE_IN_SECONDS).min(1.);
        } else {
            self.envelope = (self.envelope - (end - start) / WALK_FADE_OUT_SECONDS).max(0.);
            if self.envelope == 0. {
                self.started = None;
                self.phase_seconds = 0.;
            }
        }
        if self.started.is_some() {
            self.phase_seconds += phase_advance;
        }
        self.last_time = end;
        Ok(())
    }
    pub fn seconds(&self) -> Option<f64> {
        self.started.map(|_| self.phase_seconds)
    }
    pub fn weight(&self) -> f32 {
        (self.envelope * self.envelope * (3. - 2. * self.envelope)) as f32
    }
}

/// Blend articulation in the declared weapon actor's space, then apply one
/// shared rigid motion to gun and hands. This avoids independent world-space
/// lerps pulling attached hands away from the weapon during start/stop or ADS.
#[derive(Clone, Debug)]
pub struct WalkPoseLayer {
    anchor: usize,
    ready: ViewmodelPose,
    bindings: PoseBindings,
    receiver_v4_wip: bool,
    translation_gain: Vec3,
}
/// The auxiliary sample is derived from the same accumulated native clock.
pub struct ForwardAdsSamples<'a> {
    pub primary: &'a ViewmodelPose,
    pub half_period: &'a ViewmodelPose,
    pub weight: f32,
}
pub struct WalkLayerInput<'a> {
    pub walk: &'a ViewmodelPose,
    pub weight: f32,
    pub aim: f32,
    pub lateral: f32,
    pub forward_ads: Option<ForwardAdsSamples<'a>>,
}
impl WalkPoseLayer {
    pub fn new(
        animation: &AnimationSet,
        locomotion: &AnimationSet,
        ready_clip: &str,
        anchor_name: &str,
    ) -> Result<Self> {
        let bindings = PoseBindings::from_animation(locomotion);
        if !bindings.matches(animation) {
            return Err(AnimationError(
                "walk layer requires canonical companion bindings".into(),
            ));
        }
        let anchor = animation
            .actors()
            .iter()
            .position(|actor| actor.name == anchor_name)
            .ok_or_else(|| AnimationError(format!("missing walk anchor actor: {anchor_name}")))?;
        Ok(Self {
            anchor,
            ready: locomotion.sample_clamped(ready_clip, 0.)?,
            bindings,
            receiver_v4_wip: false,
            translation_gain: Vec3::ONE,
        })
    }
    pub fn use_receiver_v4_wip(&mut self, active: bool) {
        self.receiver_v4_wip = active;
    }
    pub fn set_translation_adjustment(&mut self, value: crate::settings::WalkTranslation) {
        self.translation_gain = value.gains();
    }
    pub fn pose(
        &self,
        animation: &AnimationSet,
        base: &ViewmodelPose,
        walk: &ViewmodelPose,
        weight: f32,
        aim: f32,
    ) -> Result<ViewmodelPose> {
        self.pose_directional(animation, base, walk, weight, aim, 0.)
    }
    pub fn pose_directional(
        &self,
        animation: &AnimationSet,
        base: &ViewmodelPose,
        walk: &ViewmodelPose,
        weight: f32,
        aim: f32,
        lateral: f32,
    ) -> Result<ViewmodelPose> {
        self.pose_with_input(
            animation,
            base,
            WalkLayerInput {
                walk,
                weight,
                aim,
                lateral,
                forward_ads: None,
            },
        )
    }
    pub fn pose_with_input(
        &self,
        animation: &AnimationSet,
        base: &ViewmodelPose,
        input: WalkLayerInput<'_>,
    ) -> Result<ViewmodelPose> {
        let WalkLayerInput {
            walk,
            weight,
            aim,
            lateral,
            forward_ads,
        } = input;
        let forward_weight = forward_ads.as_ref().map_or(0., |source| source.weight);
        if !forward_weight.is_finite() || !(0. ..=1.).contains(&forward_weight) {
            return Err(AnimationError("invalid forward ADS weight".into()));
        }
        if !lateral.is_finite() || !(0. ..=1.).contains(&lateral) {
            return Err(AnimationError("invalid lateral layer weight".into()));
        }
        if !self.bindings.matches(animation)
            || !weight.is_finite()
            || !aim.is_finite()
            || !(0. ..=1.).contains(&weight)
            || !(0. ..=1.).contains(&aim)
        {
            return Err(AnimationError(
                "invalid walk layer bindings or weights".into(),
            ));
        }
        // Validate complete dimensions/transforms before indexing either pose.
        animation.blend_poses(base, walk, 0.)?;
        if weight == 0. {
            return Ok(base.clone());
        }
        let base_anchor = base.actor_globals[self.anchor].matrix();
        let walk_anchor = walk.actor_globals[self.anchor].matrix();
        let delta = walk_anchor * self.ready.actor_globals[self.anchor].matrix().inverse();
        let (scale, rotation, translation) = delta.to_scale_rotation_translation();
        if !scale.abs_diff_eq(Vec3::ONE, 1e-4) {
            return Err(AnimationError("walk anchor motion must be rigid".into()));
        }
        // Full ADS keeps the two authored sight landmarks on the optical ray:
        // retain only the source walk's depth and roll components. Transverse
        // translation or pitch/yaw, even attenuated, separates the sights from
        // the camera ray. The phase continues and no new bob curve is invented.
        let (mut aim_rotation, mut aim_translation) = if self.receiver_v4_wip {
            receiver_v4_offset(delta, lateral)?
        } else {
            let twist = Quat::from_xyzw(0., 0., rotation.z, rotation.w);
            if twist.length_squared() <= 1e-8 {
                return Err(AnimationError(
                    "walk rotation has no finite optical-axis twist".into(),
                ));
            }
            (twist.normalize(), Vec3::new(0., 0., translation.z))
        };
        if let Some(source) = forward_ads {
            animation.blend_poses(base, source.primary, 0.)?;
            animation.blend_poses(base, source.half_period, 0.)?;
            let inverse_ready = self.ready.actor_globals[self.anchor].matrix().inverse();
            let (rotation, translation) = receiver_v9_offset(
                source.primary.actor_globals[self.anchor].matrix() * inverse_ready,
                source.half_period.actor_globals[self.anchor].matrix() * inverse_ready,
            )?;
            aim_rotation = aim_rotation.slerp(rotation, forward_weight);
            aim_translation = aim_translation.lerp(translation, forward_weight);
        }
        let rotation = rotation.slerp(aim_rotation, aim);
        let translation = translation.lerp(aim_translation, aim);
        let offset = Mat4::from_rotation_translation(
            Quat::IDENTITY.slerp(rotation, weight),
            translation * weight,
        );
        let mut output_anchor = offset * base_anchor;
        // The bound weapon actor and source righthand_prop share an origin.
        // Scale its walking displacement about the current unwalked pose, not
        // the absolute placement or the rigid offset's world-origin term.
        // Applying the resulting anchor to ALL globals preserves hand contact.
        if self.translation_gain != Vec3::ONE {
            let neutral = base_anchor.w_axis.truncate();
            let displacement = output_anchor.w_axis.truncate() - neutral;
            output_anchor.w_axis = (neutral + displacement * self.translation_gain).extend(1.);
        }
        let relative = |pose: &ViewmodelPose, anchor: Mat4| -> Result<ViewmodelPose> {
            let inverse = anchor.inverse();
            let globals = animation.bone_globals(pose, Mat4::IDENTITY)?;
            let mut pose = pose.clone();
            // Temporarily store globals in this vector for interpolation. Using
            // local-chain lerps here would allow wrist drift as elbows rotate.
            pose.bone_locals = globals
                .into_iter()
                .map(|global| transform(inverse * global))
                .collect::<Result<Vec<_>>>()?;
            for actor in &mut pose.actor_globals {
                *actor = transform(inverse * actor.matrix())?;
            }
            Ok(pose)
        };
        let from = relative(base, base_anchor)?;
        let to = relative(walk, walk_anchor)?;
        // v4 retains the full aimed articulation; v9 mixes fifteen percent of
        // primary-phase articulation at full forward aim. No per-hand IK.
        let mut result = animation.blend_poses(
            &from,
            &to,
            weight * ((1. - aim) + 0.15 * aim * forward_weight),
        )?;
        if forward_weight > 0. {
            // Extra v9 articulation belongs to the deform skeleton. Rigid
            // actors retain the existing held attachment transforms in ADS.
            result.actor_globals = animation
                .blend_poses(&from, &to, weight * (1. - aim))?
                .actor_globals;
        }
        let globals: Vec<_> = result
            .bone_locals
            .iter()
            .map(|bone| output_anchor * bone.matrix())
            .collect();
        for (index, bone) in animation.bones().iter().enumerate() {
            result.bone_locals[index] = transform(bone.parent.map_or(globals[index], |parent| {
                globals[parent].inverse() * globals[index]
            }))?;
        }
        for actor in &mut result.actor_globals {
            *actor = transform(output_anchor * actor.matrix())?;
        }
        animation.blend_poses(&result, &result, 0.)
    }
}
fn transform(matrix: Mat4) -> Result<Transform> {
    if !matrix.is_finite() {
        return Err(AnimationError("non-finite walk layer matrix".into()));
    }
    let (scale, rotation, translation) = matrix.to_scale_rotation_translation();
    if !rotation.is_finite()
        || rotation.length_squared() <= 1e-8
        || !scale.is_finite()
        || scale.min_element() <= 1e-8
    {
        return Err(AnimationError(
            "invalid walk layer matrix decomposition".into(),
        ));
    }
    let value = Transform {
        scale,
        rotation: rotation.normalize(),
        translation,
    };
    if !value.matrix().abs_diff_eq(matrix, 5e-5) {
        return Err(AnimationError(
            "walk layer does not support sheared transforms".into(),
        ));
    }
    Ok(value)
}

/// v4 WIP: frozen receiver witness, shared forty-percent native-motion target,
/// lateral vertical attenuation, optical-axis-only output. No camera fitting/IK.
pub fn receiver_v4_offset(delta_asset: Mat4, lateral: f32) -> Result<(Quat, Vec3)> {
    use crate::viewmodel_animation::game_model_root;
    let root = game_model_root(); // Exact diag(-1,1,-1); self-inverse.
    let delta = root * delta_asset * root;
    let (_, rotation, translation) = delta.to_scale_rotation_translation();
    let full =
        Mat4::from_rotation_translation(Quat::IDENTITY.slerp(rotation, 0.4), translation * 0.4);
    let p0 = Vec3::new(2.8157956e-8, -0.040691406, -0.2020175);
    let target = full.transform_point3(p0);
    if !target.is_finite() || target.z >= -1e-6 {
        return Err(AnimationError("invalid receiver projection depth".into()));
    }
    let u = target.x / -target.z;
    let v0 = p0.y / -p0.z;
    let v = v0 + (target.y / -target.z - v0) * (1. - 0.5 * lateral);
    let radius = u.hypot(v);
    if !radius.is_finite() || radius <= 1e-6 {
        return Err(AnimationError("invalid receiver projection radius".into()));
    }
    let angle = v.atan2(u) - p0.y.atan2(p0.x);
    let theta = angle.sin().atan2(angle.cos());
    let dz = -p0.x.hypot(p0.y) / radius - p0.z;
    let camera =
        Mat4::from_rotation_translation(Quat::from_rotation_z(theta), Vec3::new(0., 0., dz));
    let (_, rotation, translation) = (root * camera * root).to_scale_rotation_translation();
    if !rotation.is_finite() || !translation.is_finite() {
        return Err(AnimationError("nonfinite receiver mapping".into()));
    }
    Ok((rotation, translation))
}

/// Frozen v9 forward WIP: primary horizontal target, half-period vertical target.
/// The comparison-video offset is deliberately absent from runtime sampling.
pub fn receiver_v9_offset(primary_asset: Mat4, half_asset: Mat4) -> Result<(Quat, Vec3)> {
    use crate::viewmodel_animation::game_model_root;
    let root = game_model_root();
    let p0 = Vec3::new(2.8157956e-8, -0.040691406, -0.2020175);
    let projected = |asset: Mat4| -> Result<Vec3> {
        let (scale, rotation, translation) = (root * asset * root).to_scale_rotation_translation();
        if !asset.is_finite() || !scale.abs_diff_eq(Vec3::ONE, 1e-4) || !rotation.is_finite() {
            return Err(AnimationError("invalid v9 rigid source delta".into()));
        }
        let p =
            Mat4::from_rotation_translation(Quat::IDENTITY.slerp(rotation, 0.4), translation * 0.4)
                .transform_point3(p0);
        if !p.is_finite() || p.z >= -1e-6 {
            return Err(AnimationError("invalid v9 receiver depth".into()));
        }
        Ok(p)
    };
    let primary = projected(primary_asset)?;
    let half = projected(half_asset)?;
    let u0 = p0.x / -p0.z;
    let u = u0 + 0.25 * (primary.x / -primary.z - u0);
    let v = half.y / -half.z;
    let radius = u.hypot(v);
    if !radius.is_finite() || radius <= 1e-6 {
        return Err(AnimationError("invalid v9 receiver radius".into()));
    }
    let angle = v.atan2(u) - p0.y.atan2(p0.x);
    let theta = angle.sin().atan2(angle.cos());
    let dz = -p0.x.hypot(p0.y) / radius - p0.z;
    let camera =
        Mat4::from_rotation_translation(Quat::from_rotation_z(theta), Vec3::new(0., 0., dz));
    let (_, rotation, translation) = (root * camera * root).to_scale_rotation_translation();
    Ok((rotation, translation))
}
