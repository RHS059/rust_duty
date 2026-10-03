//! Committed-time walk envelope and weapon-relative layering of authored poses.
use crate::{
    authored_locomotion_adapter::PoseBindings,
    viewmodel_animation::{AnimationError, AnimationSet, Result, Transform, ViewmodelPose},
};
use macroquad::math::{Mat4, Quat, Vec3};

pub const WALK_FADE_IN_SECONDS: f64 = 0.16;
pub const WALK_FADE_OUT_SECONDS: f64 = 0.22;

#[derive(Clone, Debug, Default)]
pub struct AuthoredWalk {
    started: Option<f64>,
    last_time: f64,
    envelope: f64,
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
            }
            self.envelope = (self.envelope + (end - start) / WALK_FADE_IN_SECONDS).min(1.);
        } else {
            self.envelope = (self.envelope - (end - start) / WALK_FADE_OUT_SECONDS).max(0.);
            if self.envelope == 0. {
                self.started = None;
            }
        }
        self.last_time = end;
        Ok(())
    }
    pub fn seconds(&self) -> Option<f64> {
        self.started.map(|start| self.last_time - start)
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
        })
    }
    pub fn pose(
        &self,
        animation: &AnimationSet,
        base: &ViewmodelPose,
        walk: &ViewmodelPose,
        weight: f32,
        aim: f32,
    ) -> Result<ViewmodelPose> {
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
        let twist = Quat::from_xyzw(0., 0., rotation.z, rotation.w);
        if twist.length_squared() <= 1e-8 {
            return Err(AnimationError(
                "walk rotation has no finite optical-axis twist".into(),
            ));
        }
        let rotation = rotation.slerp(twist.normalize(), aim);
        let translation = translation.lerp(Vec3::new(0., 0., translation.z), aim);
        let offset = Mat4::from_rotation_translation(
            Quat::IDENTITY.slerp(rotation, weight),
            translation * weight,
        );
        let output_anchor = offset * base_anchor;
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
        // At full ADS the source aim articulation is retained exactly. Only the
        // shared rigid walking offset is added; no per-hand offsets or IK.
        let mut result = animation.blend_poses(&from, &to, weight * (1. - aim))?;
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
