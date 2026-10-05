//! Named, rest-checked cross-pack poses and continuous returns to live motion.
use crate::{
    authored_locomotion_adapter::PoseBindings,
    layered_locomotion::AnchoredPoseBlend,
    skinned_asset::SkinnedAsset,
    viewmodel_animation::{AnimationError, AnimationSet, Result, Transform, ViewmodelPose},
};
use glam::{Mat4, Vec3};

pub const RETURN_SECONDS: f64 = 0.20;

/// The reload importer conjugates rigid actors into FBX/glTF mesh-local axes.
/// Canonical actors retain the original mesh-local basis. Bone globals already
/// share the same basis, which is checked independently through inverse binds.
pub fn canonical_to_reload_actor_basis() -> Mat4 {
    Mat4::from_cols(
        Vec3::X.extend(0.),
        Vec3::Z.extend(0.),
        (-Vec3::Y).extend(0.),
        Vec3::ZERO.extend(1.),
    )
}

fn transform(matrix: Mat4) -> Result<Transform> {
    let (scale, rotation, translation) = matrix.to_scale_rotation_translation();
    let value = Transform {
        scale,
        rotation: rotation.normalize(),
        translation,
    };
    if !matrix.is_finite()
        || !value.matrix().abs_diff_eq(matrix, 5e-5)
        || scale.min_element() <= 1e-8
    {
        return Err(AnimationError("unsupported return-pose transform".into()));
    }
    Ok(value)
}

/// Reindex complete evaluated globals by name. Companion CRC equality is never
/// bypassed: each set keeps its own validated renderer, geometry and bindings.
#[derive(Clone, Debug)]
pub struct PoseReturnMap {
    source: PoseBindings,
    destination: PoseBindings,
    bones: Vec<usize>,
    actors: Vec<Option<usize>>,
    actor_basis: Mat4,
}
impl PoseReturnMap {
    pub fn new(
        source: &AnimationSet,
        source_skin: &SkinnedAsset,
        destination: &AnimationSet,
        destination_skin: &SkinnedAsset,
        actor_basis: Mat4,
    ) -> Result<Self> {
        for (set, skin) in [(source, source_skin), (destination, destination_skin)] {
            if skin.bones.len() != set.bones().len()
                || skin
                    .bones
                    .iter()
                    .zip(set.bones())
                    .any(|(a, b)| a.name != b.name || a.parent != b.parent)
            {
                return Err(AnimationError(
                    "return skeleton does not match companion".into(),
                ));
            }
        }
        if source.bones().len() != destination.bones().len() || !actor_basis.is_finite() {
            return Err(AnimationError(
                "incompatible return skeleton or actor basis".into(),
            ));
        }
        let mut bones = Vec::new();
        for (index, bone) in destination.bones().iter().enumerate() {
            let from = source
                .bones()
                .iter()
                .position(|b| b.name == bone.name)
                .ok_or_else(|| AnimationError(format!("missing return bone {}", bone.name)))?;
            let parent_name = |set: &AnimationSet, parent: Option<usize>| {
                parent.map(|i| set.bones()[i].name.clone())
            };
            if parent_name(source, source.bones()[from].parent)
                != parent_name(destination, bone.parent)
                || !Mat4::from_cols_array(&source_skin.bones[from].inverse_bind).abs_diff_eq(
                    Mat4::from_cols_array(&destination_skin.bones[index].inverse_bind),
                    1e-5,
                )
            {
                return Err(AnimationError(format!(
                    "incompatible return rest/hierarchy for {}",
                    bone.name
                )));
            }
            bones.push(from);
        }
        let actors = destination
            .actors()
            .iter()
            .map(|actor| source.actors().iter().position(|a| a.name == actor.name))
            .collect();
        Ok(Self {
            source: PoseBindings::from_animation(source),
            destination: PoseBindings::from_animation(destination),
            bones,
            actors,
            actor_basis,
        })
    }
    pub fn pose(
        &self,
        source: &AnimationSet,
        destination: &AnimationSet,
        pose: &ViewmodelPose,
        template: &ViewmodelPose,
    ) -> Result<ViewmodelPose> {
        if !self.source.matches(source) || !self.destination.matches(destination) {
            return Err(AnimationError("return bindings changed".into()));
        }
        destination.blend_poses(template, template, 0.)?;
        let from = source.bone_globals(pose, Mat4::IDENTITY)?;
        let globals: Vec<_> = self.bones.iter().map(|&i| from[i]).collect();
        let mut result = template.clone();
        for (i, bone) in destination.bones().iter().enumerate() {
            result.bone_locals[i] = transform(
                bone.parent
                    .map_or(globals[i], |p| globals[p].inverse() * globals[i]),
            )?;
        }
        for (i, from) in self.actors.iter().enumerate() {
            if let Some(from) = from {
                result.actor_globals[i] =
                    transform(pose.actor_globals[*from].matrix() * self.actor_basis)?;
                result.actor_visible[i] = pose.actor_visible[*from];
            } else {
                result.actor_visible[i] = false;
            }
        }
        result.sample_time = pose.sample_time;
        destination.blend_poses(&result, &result, 0.)
    }
}

#[derive(Clone, Debug)]
pub struct PoseReturn {
    from: ViewmodelPose,
    opacity: Vec<f32>,
    began: f64,
}
impl PoseReturn {
    pub fn new(from: ViewmodelPose, opacity: Vec<f32>, began: f64) -> Self {
        Self {
            from,
            opacity,
            began,
        }
    }
    pub fn weight(&self, time: f64) -> f32 {
        let t = ((time - self.began) / RETURN_SECONDS).clamp(0., 1.);
        (t * t * (3. - 2. * t)) as f32
    }
    pub fn pose(
        &self,
        animation: &AnimationSet,
        blend: &AnchoredPoseBlend,
        target: &ViewmodelPose,
        time: f64,
    ) -> Result<(ViewmodelPose, Vec<f32>)> {
        if !time.is_finite()
            || !self.began.is_finite()
            || self.opacity.len() != target.actor_visible.len()
            || self
                .opacity
                .iter()
                .any(|v| !v.is_finite() || !(0. ..=1.).contains(v))
        {
            return Err(AnimationError("invalid return clock or opacity".into()));
        }
        let weight = self.weight(time);
        let mut pose = blend.blend(animation, &self.from, target, weight)?;
        let mut opacity = Vec::with_capacity(target.actor_visible.len());
        for (i, &visible) in target.actor_visible.iter().enumerate() {
            let alpha = self.opacity[i] + (f32::from(u8::from(visible)) - self.opacity[i]) * weight;
            // Visibility changes fade at the actual old/new transform instead
            // of interpolating an invisible actor's identity placeholder.
            if !visible {
                pose.actor_globals[i] = self.from.actor_globals[i];
            } else if self.opacity[i] == 0. {
                pose.actor_globals[i] = target.actor_globals[i];
            }
            pose.actor_visible[i] = alpha > 0.;
            opacity.push(alpha);
        }
        Ok((pose, opacity))
    }
}
