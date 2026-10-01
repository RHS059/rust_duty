//! Bounded VRANIM01 playback of baked Blender animation, in standard glTF axes.
//!
//! This module never solves IK or invents poses. Translation/scale use linear
//! interpolation and rotations use shortest-path slerp. Rigid geometry is baked
//! in rest-global coordinates: its matrix is root * actor-global * inverse-rest.
//! Apply [`game_model_root`] once, to the complete model, for the game convention.
use crate::{
    asset::WeaponAsset,
    skinned_asset::{crc32, Bone, SkinnedAsset},
};
use macroquad::math::{Mat4, Quat, Vec3};
use std::{collections::HashSet, fmt, fs::File, io::Read, path::Path};

pub const MAX_FILE: usize = 128 * 1024 * 1024;
pub const MAX_BONES: usize = 128;
pub const MAX_ACTORS: usize = 256;
pub const MAX_MESHES: usize = 256;
pub const MAX_CLIPS: usize = 128;
pub const MAX_FRAMES: usize = 65_536;
pub const MAX_TRANSFORMS: usize = 2_000_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnimationError(pub String);
impl fmt::Display for AnimationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AnimationError {}
pub type Result<T> = std::result::Result<T, AnimationError>;
fn error(message: impl Into<String>) -> AnimationError {
    AnimationError(message.into())
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Transform {
    pub translation: Vec3,
    /// Quaternion in XYZW order, normalized by the decoder.
    pub rotation: Quat,
    pub scale: Vec3,
}
impl Transform {
    pub const IDENTITY: Self = Self {
        translation: Vec3::ZERO,
        rotation: Quat::IDENTITY,
        scale: Vec3::ONE,
    };
    pub fn matrix(self) -> Mat4 {
        Mat4::from_scale_rotation_translation(self.scale, self.rotation, self.translation)
    }
    fn validate(self) -> Result<()> {
        if !self.translation.is_finite() || !self.rotation.is_finite() || !self.scale.is_finite() {
            return Err(error("non-finite transform"));
        }
        if self.translation.abs().max_element() > 10_000. {
            return Err(error("translation exceeds 10000"));
        }
        if self.scale.min_element() <= 1e-8 || self.scale.max_element() > 10_000. {
            return Err(error("scale outside (1e-8, 10000]"));
        }
        let q = self.rotation.to_array();
        let length = q.iter().map(|v| f64::from(*v).powi(2)).sum::<f64>().sqrt();
        if (length - 1.).abs() > 1e-4 {
            return Err(error("quaternion is not unit length"));
        }
        Ok(())
    }
    fn interpolate(self, other: Self, amount: f32) -> Self {
        let a = self.rotation;
        let mut b = other.rotation;
        let mut dot = a.dot(b);
        if dot < 0. {
            b = -b;
            dot = -dot;
        }
        let rotation = if dot > 0.9995 {
            (a * (1. - amount) + b * amount).normalize()
        } else {
            let angle = dot.clamp(-1., 1.).acos();
            ((a * ((1. - amount) * angle).sin() + b * (amount * angle).sin()) / angle.sin())
                .normalize()
        };
        Self {
            translation: self.translation.lerp(other.translation, amount),
            rotation,
            scale: self.scale.lerp(other.scale, amount),
        }
    }
}
#[derive(Debug, Clone)]
pub struct AnimationBone {
    pub name: String,
    pub parent: Option<usize>,
}
#[derive(Debug, Clone)]
pub struct RigidActor {
    pub name: String,
    /// VRMESH01 primitive indices. An empty list denotes a socket-only actor.
    pub mesh_indices: Vec<usize>,
    pub inverse_rest_global: Mat4,
}
#[derive(Debug, Clone)]
pub struct AnimationClip {
    pub name: String,
    pub looping: bool,
    times: Vec<f32>,
    bone_locals: Vec<Transform>,
    actor_globals: Vec<Transform>,
    actor_visible: Vec<bool>,
}
impl AnimationClip {
    pub fn duration(&self) -> f32 {
        *self.times.last().unwrap_or(&0.)
    }
    pub fn frame_count(&self) -> usize {
        self.times.len()
    }
    pub fn times(&self) -> &[f32] {
        &self.times
    }
}
#[derive(Debug, Clone, PartialEq)]
pub struct ViewmodelPose {
    /// The effective clamped or wrapped clip time, in seconds.
    pub sample_time: f32,
    pub bone_locals: Vec<Transform>,
    pub actor_globals: Vec<Transform>,
    pub actor_visible: Vec<bool>,
}
#[derive(Debug, Clone)]
pub struct AnimationSet {
    skin_crc32: u32,
    mesh_crc32: u32,
    bones: Vec<AnimationBone>,
    actors: Vec<RigidActor>,
    clips: Vec<AnimationClip>,
    // Parents precede children here, independently of the file's bone ordering.
    evaluation_order: Vec<usize>,
}

struct Reader<'a> {
    bytes: &'a [u8],
    pos: usize,
}
impl<'a> Reader<'a> {
    fn remaining(&self) -> usize {
        self.bytes.len() - self.pos
    }
    fn take(&mut self, size: usize) -> Result<&'a [u8]> {
        let end = self
            .pos
            .checked_add(size)
            .ok_or_else(|| error("offset overflow"))?;
        let result = self
            .bytes
            .get(self.pos..end)
            .ok_or_else(|| error("truncated animation"))?;
        self.pos = end;
        Ok(result)
    }
    fn u16(&mut self) -> Result<u16> {
        Ok(u16::from_le_bytes(self.take(2)?.try_into().unwrap()))
    }
    fn u32(&mut self) -> Result<u32> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }
    fn i32(&mut self) -> Result<i32> {
        Ok(self.u32()? as i32)
    }
    fn float(&mut self) -> Result<f32> {
        let value = f32::from_bits(self.u32()?);
        if !value.is_finite() {
            return Err(error("non-finite float"));
        }
        Ok(value)
    }
    fn floats<const N: usize>(&mut self) -> Result<[f32; N]> {
        let mut values = [0.; N];
        for value in &mut values {
            *value = self.float()?;
        }
        Ok(values)
    }
    fn name(&mut self) -> Result<String> {
        let size = self.u16()? as usize;
        if !(1..=128).contains(&size) {
            return Err(error("name must have 1..128 UTF-8 bytes"));
        }
        let value =
            std::str::from_utf8(self.take(size)?).map_err(|_| error("invalid UTF-8 name"))?;
        if value.contains('\0') {
            return Err(error("NUL in name"));
        }
        Ok(value.to_owned())
    }
    fn matrix(&mut self) -> Result<Mat4> {
        let values = self.floats::<16>()?;
        validate_matrix(&values)?;
        Ok(Mat4::from_cols_array(&values))
    }
    fn transform(&mut self) -> Result<Transform> {
        let mut transform = Transform {
            translation: Vec3::from_array(self.floats()?),
            rotation: Quat::from_array(self.floats()?),
            scale: Vec3::from_array(self.floats()?),
        };
        transform.validate()?;
        transform.rotation = transform.rotation.normalize();
        Ok(transform)
    }
}
fn validate_matrix(m: &[f32; 16]) -> Result<()> {
    if m.iter().any(|v| !v.is_finite()) {
        return Err(error("non-finite matrix"));
    }
    if m[3] != 0. || m[7] != 0. || m[11] != 0. || m[15] != 1. {
        return Err(error("matrix is not affine"));
    }
    let [a, b, c, d, e, f, g, h, i] =
        [m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]].map(f64::from);
    let determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if determinant == 0. {
        return Err(error("matrix is singular"));
    }
    Ok(())
}
fn read_bounded(path: &Path) -> Result<Vec<u8>> {
    let file = File::open(path).map_err(|e| error(format!("{}: {e}", path.display())))?;
    if file.metadata().map_err(|e| error(e.to_string()))?.len() > MAX_FILE as u64 {
        return Err(error("asset exceeds 128 MiB"));
    }
    let mut bytes = Vec::new();
    file.take((MAX_FILE + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|e| error(e.to_string()))?;
    if bytes.len() > MAX_FILE {
        return Err(error("asset exceeds 128 MiB"));
    }
    Ok(bytes)
}

/// Exact 180-degree Y rotation. Apply only at the complete model's root.
pub fn game_model_root() -> Mat4 {
    Mat4::from_scale(Vec3::new(-1., 1., -1.))
}

impl AnimationSet {
    pub fn bones(&self) -> &[AnimationBone] {
        &self.bones
    }
    pub fn actors(&self) -> &[RigidActor] {
        &self.actors
    }
    pub fn clips(&self) -> &[AnimationClip] {
        &self.clips
    }
    pub fn companion_checksums(&self) -> (u32, u32) {
        (self.skin_crc32, self.mesh_crc32)
    }
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        Self::decode(&read_bounded(path.as_ref())?)
    }
    /// Loads and validates the same-stem .vra, .vrs and .vrm companions.
    pub fn load_with_companions(
        path: impl AsRef<Path>,
    ) -> Result<(Self, SkinnedAsset, WeaponAsset)> {
        let path = path.as_ref();
        let animation = Self::load(path)?;
        let skin_bytes = read_bounded(&path.with_extension("vrs"))?;
        let mesh_bytes = read_bounded(&path.with_extension("vrm"))?;
        let skin =
            SkinnedAsset::decode(&skin_bytes).map_err(|e| error(format!("skin companion: {e}")))?;
        let mesh =
            WeaponAsset::decode(&mesh_bytes).map_err(|e| error(format!("mesh companion: {e}")))?;
        animation.validate_companions(&skin_bytes, &mesh_bytes, &skin.bones, mesh.meshes.len())?;
        Ok((animation, skin, mesh))
    }
    pub fn decode(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > MAX_FILE {
            return Err(error("animation exceeds 128 MiB"));
        }
        let mut r = Reader { bytes, pos: 0 };
        if r.take(8)? != b"VRANIM01" {
            return Err(error("wrong animation magic"));
        }
        if r.u32()? != 1 {
            return Err(error("unsupported animation version"));
        }
        let length = r.u32()? as usize;
        let checksum = r.u32()?;
        if r.u32()? != 0 {
            return Err(error("reserved header flags must be zero"));
        }
        if length != r.remaining() {
            return Err(error("payload length mismatch"));
        }
        if crc32(&bytes[r.pos..]) != checksum {
            return Err(error("payload checksum mismatch"));
        }
        let skin_crc32 = r.u32()?;
        let mesh_crc32 = r.u32()?;
        let bone_count = r.u32()? as usize;
        if !(1..=MAX_BONES).contains(&bone_count) {
            return Err(error("bone count outside 1..128"));
        }
        let mut bones = Vec::with_capacity(bone_count);
        let mut names = HashSet::new();
        for _ in 0..bone_count {
            let name = r.name()?;
            if !names.insert(name.clone()) {
                return Err(error("duplicate bone name"));
            }
            let parent = r.i32()?;
            if parent < -1 || parent >= bone_count as i32 {
                return Err(error("bone parent outside skeleton"));
            }
            bones.push(AnimationBone {
                name,
                parent: if parent == -1 {
                    None
                } else {
                    Some(parent as usize)
                },
            });
        }
        let mut evaluation_order = Vec::with_capacity(bone_count);
        let mut evaluated = vec![false; bone_count];
        while evaluation_order.len() < bone_count {
            let before = evaluation_order.len();
            for (index, bone) in bones.iter().enumerate() {
                if !evaluated[index] && bone.parent.is_none_or(|parent| evaluated[parent]) {
                    evaluated[index] = true;
                    evaluation_order.push(index);
                }
            }
            if before == evaluation_order.len() {
                return Err(error("cycle in bone hierarchy"));
            }
        }
        let actor_count = r.u32()? as usize;
        if actor_count > MAX_ACTORS {
            return Err(error("actor count exceeds 256"));
        }
        let mut actors = Vec::with_capacity(actor_count);
        names.clear();
        let mut assigned_meshes = [false; MAX_MESHES];
        for _ in 0..actor_count {
            let name = r.name()?;
            if !names.insert(name.clone()) {
                return Err(error("duplicate actor name"));
            }
            let count = r.u32()? as usize;
            if count > MAX_MESHES || count * 4 + 64 > r.remaining() {
                return Err(error("invalid actor mesh binding count"));
            }
            let mut mesh_indices = Vec::with_capacity(count);
            for _ in 0..count {
                let mesh = r.u32()? as usize;
                if mesh >= MAX_MESHES {
                    return Err(error("actor mesh index exceeds 255"));
                }
                if assigned_meshes[mesh] {
                    return Err(error("duplicate rigid mesh assignment"));
                }
                assigned_meshes[mesh] = true;
                mesh_indices.push(mesh);
            }
            let inverse_rest_global = r.matrix()?;
            actors.push(RigidActor {
                name,
                mesh_indices,
                inverse_rest_global,
            });
        }
        let clip_count = r.u32()? as usize;
        if !(1..=MAX_CLIPS).contains(&clip_count) {
            return Err(error("clip count outside 1..128"));
        }
        let mut clips = Vec::with_capacity(clip_count);
        names.clear();
        let mut total_transforms = 0usize;
        for _ in 0..clip_count {
            let name = r.name()?;
            if !names.insert(name.clone()) {
                return Err(error("duplicate clip name"));
            }
            let flags = r.u32()?;
            if flags > 1 {
                return Err(error("unsupported clip flags"));
            }
            let frame_count = r.u32()? as usize;
            if !(1..=MAX_FRAMES).contains(&frame_count) {
                return Err(error("frame count outside 1..65536"));
            }
            let transforms = frame_count
                .checked_mul(bone_count + actor_count)
                .ok_or_else(|| error("transform count overflow"))?;
            total_transforms = total_transforms
                .checked_add(transforms)
                .ok_or_else(|| error("transform budget overflow"))?;
            if total_transforms > MAX_TRANSFORMS {
                return Err(error("aggregate transform budget exceeded"));
            }
            let required = transforms
                .checked_mul(40)
                .and_then(|n| {
                    frame_count
                        .checked_mul(4 + actor_count)
                        .and_then(|m| n.checked_add(m))
                })
                .ok_or_else(|| error("frame size overflow"))?;
            if required > r.remaining() {
                return Err(error("truncated animation frames"));
            }
            let mut times = Vec::with_capacity(frame_count);
            let mut bone_locals = Vec::with_capacity(frame_count * bone_count);
            let mut actor_globals = Vec::with_capacity(frame_count * actor_count);
            let mut actor_visible = Vec::with_capacity(frame_count * actor_count);
            for frame in 0..frame_count {
                let time = r.float()?;
                if (frame == 0 && time != 0.) || (frame > 0 && time <= times[frame - 1]) {
                    return Err(error(
                        "frame times must start at zero and strictly increase",
                    ));
                }
                times.push(time);
                for _ in 0..bone_count {
                    bone_locals.push(r.transform()?);
                }
                for _ in 0..actor_count {
                    actor_globals.push(r.transform()?);
                }
                for _ in 0..actor_count {
                    let value = r.take(1)?[0];
                    if value > 1 {
                        return Err(error("visibility must be 0 or 1"));
                    }
                    actor_visible.push(value == 1);
                }
            }
            clips.push(AnimationClip {
                name,
                looping: flags == 1,
                times,
                bone_locals,
                actor_globals,
                actor_visible,
            });
        }
        if r.remaining() != 0 {
            return Err(error("unexpected trailing animation data"));
        }
        Ok(Self {
            skin_crc32,
            mesh_crc32,
            bones,
            actors,
            clips,
            evaluation_order,
        })
    }
    /// The bones and mesh count must be decoded from these exact companion bytes.
    /// Validates complete-file CRCs, exact skeleton identity and complete, unique
    /// rigid primitive coverage. Use load_with_companions for untrusted files.
    pub fn validate_companions(
        &self,
        vrs_bytes: &[u8],
        vrm_bytes: &[u8],
        bones: &[Bone],
        mesh_count: usize,
    ) -> Result<()> {
        if vrs_bytes.len() > MAX_FILE || vrm_bytes.len() > MAX_FILE {
            return Err(error("companion exceeds 128 MiB"));
        }
        if crc32(vrs_bytes) != self.skin_crc32 || crc32(vrm_bytes) != self.mesh_crc32 {
            return Err(error("animation companion checksum mismatch"));
        }
        self.validate_skeleton(bones)?;
        if mesh_count > MAX_MESHES {
            return Err(error("companion mesh count exceeds 256"));
        }
        let mut assigned = vec![false; mesh_count];
        for actor in &self.actors {
            for &index in &actor.mesh_indices {
                let entry = assigned
                    .get_mut(index)
                    .ok_or_else(|| error("actor mesh index outside companion"))?;
                if *entry {
                    return Err(error("duplicate rigid mesh assignment"));
                }
                *entry = true;
            }
        }
        if assigned.iter().any(|entry| !entry) {
            return Err(error("unbound rigid mesh primitive"));
        }
        Ok(())
    }
    fn validate_skeleton(&self, bones: &[Bone]) -> Result<()> {
        if bones.len() != self.bones.len()
            || bones
                .iter()
                .zip(&self.bones)
                .any(|(a, b)| a.name != b.name || a.parent != b.parent)
        {
            return Err(error("animation skeleton does not match companion"));
        }
        Ok(())
    }
    pub fn sample(&self, clip_name: &str, time: f32) -> Result<ViewmodelPose> {
        self.sample_impl(clip_name, time, false)
    }
    /// Preserve authored endpoints, even for looping clips, for parity checks.
    pub fn sample_clamped(&self, clip_name: &str, time: f32) -> Result<ViewmodelPose> {
        self.sample_impl(clip_name, time, true)
    }
    fn sample_impl(&self, clip_name: &str, time: f32, clamp: bool) -> Result<ViewmodelPose> {
        if !time.is_finite() {
            return Err(error("sample time must be finite"));
        }
        let clip = self
            .clips
            .iter()
            .find(|clip| clip.name == clip_name)
            .ok_or_else(|| error(format!("unknown clip: {clip_name}")))?;
        let duration = clip.duration();
        let sample_time = if duration == 0. {
            0.
        } else if clip.looping && !clamp {
            let wrapped = time.rem_euclid(duration);
            if wrapped >= duration {
                0.
            } else {
                wrapped
            }
        } else {
            time.clamp(0., duration)
        };
        let next = clip.times.partition_point(|&at| at <= sample_time);
        let earlier = next.saturating_sub(1);
        let later = next.min(clip.times.len() - 1);
        let amount = if earlier == later {
            0.
        } else {
            (sample_time - clip.times[earlier]) / (clip.times[later] - clip.times[earlier])
        };
        let sample = |tracks: &[Transform], count: usize| {
            (0..count)
                .map(|i| {
                    let a = tracks[earlier * count + i];
                    if amount == 0. {
                        a
                    } else {
                        a.interpolate(tracks[later * count + i], amount)
                    }
                })
                .collect()
        };
        Ok(ViewmodelPose {
            sample_time,
            bone_locals: sample(&clip.bone_locals, self.bones.len()),
            actor_globals: sample(&clip.actor_globals, self.actors.len()),
            actor_visible: clip.actor_visible
                [earlier * self.actors.len()..(earlier + 1) * self.actors.len()]
                .to_vec(),
        })
    }
    fn validate_pose(&self, pose: &ViewmodelPose) -> Result<()> {
        if pose.bone_locals.len() != self.bones.len()
            || pose.actor_globals.len() != self.actors.len()
            || pose.actor_visible.len() != self.actors.len()
        {
            return Err(error("pose dimensions do not match animation set"));
        }
        if !pose.sample_time.is_finite() {
            return Err(error("pose time must be finite"));
        }
        for transform in pose.bone_locals.iter().chain(&pose.actor_globals) {
            transform.validate()?;
        }
        Ok(())
    }
    /// Generic local-TRS blending only; no IK, constraints, or gameplay offsets.
    /// Visibility switches to the second pose at weight 0.5; time is interpolated.
    pub fn blend_poses(
        &self,
        a: &ViewmodelPose,
        b: &ViewmodelPose,
        weight: f32,
    ) -> Result<ViewmodelPose> {
        if !weight.is_finite() || !(0. ..=1.).contains(&weight) {
            return Err(error("blend weight outside 0..1"));
        }
        self.validate_pose(a)?;
        self.validate_pose(b)?;
        if weight == 0. {
            return Ok(a.clone());
        }
        if weight == 1. {
            return Ok(b.clone());
        }
        let blend = |x: &[Transform], y: &[Transform]| {
            x.iter()
                .zip(y)
                .map(|(&a, &b)| a.interpolate(b, weight))
                .collect()
        };
        Ok(ViewmodelPose {
            sample_time: a.sample_time * (1. - weight) + b.sample_time * weight,
            bone_locals: blend(&a.bone_locals, &b.bone_locals),
            actor_globals: blend(&a.actor_globals, &b.actor_globals),
            actor_visible: if weight < 0.5 {
                a.actor_visible.clone()
            } else {
                b.actor_visible.clone()
            },
        })
    }
    /// Global joint matrices in original bone index order, with root applied once.
    pub fn bone_globals(&self, pose: &ViewmodelPose, root: Mat4) -> Result<Vec<Mat4>> {
        self.validate_pose(pose)?;
        validate_matrix(&root.to_cols_array())?;
        let mut globals = vec![Mat4::IDENTITY; self.bones.len()];
        for &index in &self.evaluation_order {
            let parent = self.bones[index].parent.map_or(root, |p| globals[p]);
            globals[index] = parent * pose.bone_locals[index].matrix();
            validate_matrix(&globals[index].to_cols_array())?;
        }
        Ok(globals)
    }
    pub fn skin_palette(
        &self,
        pose: &ViewmodelPose,
        bones: &[Bone],
        root: Mat4,
    ) -> Result<Vec<Mat4>> {
        self.validate_skeleton(bones)?;
        let globals = self.bone_globals(pose, root)?;
        globals
            .iter()
            .zip(bones)
            .map(|(global, bone)| {
                validate_matrix(&bone.inverse_bind)?;
                let matrix = *global * Mat4::from_cols_array(&bone.inverse_bind);
                validate_matrix(&matrix.to_cols_array())?;
                Ok(matrix)
            })
            .collect()
    }
    /// One matrix per actor, including sockets. Visibility is kept separately.
    pub fn actor_matrices(&self, pose: &ViewmodelPose, root: Mat4) -> Result<Vec<Mat4>> {
        self.validate_pose(pose)?;
        validate_matrix(&root.to_cols_array())?;
        self.actors
            .iter()
            .zip(&pose.actor_globals)
            .map(|(actor, transform)| {
                let matrix = root * transform.matrix() * actor.inverse_rest_global;
                validate_matrix(&matrix.to_cols_array())?;
                Ok(matrix)
            })
            .collect()
    }
}
