//! Opt-in playback adapter for Blender-baked viewmodels. No procedural posing.
use macroquad::prelude::*;
use vector_range::{
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathConfig},
    skinned_asset::SkinnedAsset,
    viewmodel_animation::{game_model_root, AnimationSet, ViewmodelPose},
};

struct SkinBatch {
    source_mesh: usize,
    source_vertices: Vec<usize>,
    mesh: Mesh,
}

/// This renderer intentionally has no arm names, wrist fitting, IK, finger curls,
/// reload paths, or asset-specific part numbers. The source clips own every pose.
pub struct AuthoredViewmodel {
    animation: AnimationSet,
    skin: SkinnedAsset,
    batches: Vec<SkinBatch>,
    weapon: crate::weapon_model::WeaponModel,
    rigid_mesh_count: usize,
    clip: String,
    fixed_time: Option<f32>,
    error: Option<String>,
    locomotion: Option<AuthoredLocomotionPath>,
}
impl AuthoredViewmodel {
    /// Requires an initialized render context, like the existing mesh adapters.
    pub fn load(path: &str, clip: &str, fixed_time: Option<f32>) -> Result<Self, String> {
        if fixed_time.is_some_and(|time| !time.is_finite()) {
            return Err("authored viewmodel time must be finite".into());
        }
        let (animation, skin, weapon) =
            AnimationSet::load_with_companions(path).map_err(|e| e.to_string())?;
        let locomotion = if clip == "locomotion" && fixed_time.is_none() {
            Some(
                AuthoredLocomotionPath::new(
                    &animation,
                    AuthoredLocomotionPathConfig {
                        ready_clip: "normal_ready".into(),
                        entry_clip: "normal_entry_connected".into(),
                        loop_clip: "normal_loop".into(),
                        exit_bridge_clips: (0..35)
                            .map(|i| format!("normal_exit_bridge_{i:03}"))
                            .collect(),
                        exit_clip: "normal_exit".into(),
                        settle_clip: "normal_settle".into(),
                        rate_response_seconds: 0.05,
                        residual_decay_seconds: 0.03,
                    },
                    0.,
                )
                .map_err(|e| e.to_string())?,
            )
        } else {
            None
        };
        let sample_clip = if clip == "locomotion" {
            "normal_ready"
        } else {
            clip
        };
        // Fail before creating GPU resources if the requested clip is absent.
        let initial = animation
            .sample_clamped(sample_clip, fixed_time.unwrap_or(0.))
            .map_err(|e| e.to_string())?;
        animation
            .skin_palette(&initial, &skin.bones, game_model_root())
            .map_err(|e| e.to_string())?;
        let rigid_mesh_count = weapon.meshes.len();
        let weapon = crate::weapon_model::WeaponModel::from_asset(weapon);
        let mut batches = Vec::new();
        for (source_mesh, part) in skin.meshes.iter().enumerate() {
            let texture = if part.rgba.is_empty() {
                None
            } else {
                let mut pixels = part.rgba.clone();
                for alpha in pixels.iter_mut().skip(3).step_by(4) {
                    *alpha = 255;
                }
                let texture = Texture2D::from_rgba8(
                    part.texture_width as u16,
                    part.texture_height as u16,
                    &pixels,
                );
                texture.set_filter(FilterMode::Linear);
                unsafe {
                    get_internal_gl().quad_context.texture_set_wrap(
                        texture.raw_miniquad_id(),
                        macroquad::miniquad::TextureWrap::Repeat,
                        macroquad::miniquad::TextureWrap::Repeat,
                    );
                }
                Some(texture)
            };
            for chunk in part.indices.chunks(4_998) {
                let mut remap = std::collections::HashMap::new();
                let mut source_vertices = Vec::new();
                let indices = chunk
                    .iter()
                    .map(|&source| {
                        *remap.entry(source).or_insert_with(|| {
                            let index = source_vertices.len() as u16;
                            source_vertices.push(source as usize);
                            index
                        })
                    })
                    .collect();
                let vertices = source_vertices
                    .iter()
                    .map(|&index| {
                        let v = &part.vertices[index];
                        Vertex::new2(Vec3::from_array(v.position), Vec2::from_array(v.uv), WHITE)
                    })
                    .collect();
                batches.push(SkinBatch {
                    source_mesh,
                    source_vertices,
                    mesh: Mesh {
                        vertices,
                        indices,
                        texture: texture.clone(),
                    },
                });
            }
        }
        eprintln!(
            "Loaded Blender-authored viewmodel: {} bones, {} clips, selected {clip}",
            skin.bones.len(),
            animation.clips().len()
        );
        Ok(Self {
            animation,
            skin,
            batches,
            weapon,
            rigid_mesh_count,
            clip: sample_clip.into(),
            fixed_time,
            error: None,
            locomotion,
        })
    }
    pub fn error(&self) -> Option<&str> {
        self.error.as_deref()
    }
    /// The immutable bindings used by this renderer and its matching companions.
    pub fn animation(&self) -> &AnimationSet {
        &self.animation
    }
    /// Advance only on committed fixed ticks; render frequency never changes motion.
    pub fn update_locomotion(&mut self, start: f64, end: f64, sprinting: bool) {
        if self.error.is_some() {
            return;
        }
        if let Some(path) = &mut self.locomotion {
            if let Err(error) = path
                .update(&self.animation, start, sprinting, true)
                .and_then(|_| path.update(&self.animation, end, sprinting, true))
            {
                self.error = Some(error.to_string());
            }
        }
    }
    pub fn draw(&mut self, simulation_time: f64, offset: Vec3) {
        if self.error.is_some() {
            return;
        }
        if let Err(error) = self.draw_checked(simulation_time, offset) {
            eprintln!("Authored viewmodel playback failed: {error}");
            self.error = Some(error);
        }
    }
    fn draw_checked(&mut self, simulation_time: f64, offset: Vec3) -> Result<(), String> {
        if let Some(path) = &self.locomotion {
            let pose = path.pose().clone();
            return self.draw_pose(&pose, offset);
        }
        let time = self.fixed_time.unwrap_or(simulation_time as f32);
        let pose = if self.fixed_time.is_some() {
            self.animation().sample_clamped(&self.clip, time)
        } else {
            self.animation().sample(&self.clip, time)
        }
        .map_err(|e| e.to_string())?;
        self.draw_pose(&pose, offset)
    }
    /// Render one complete evaluated pose from this animation set. The gameplay
    /// adapter owns which presentation supplies it; no two pose owners are mixed
    /// here. Skin and actor dimension/transform validation is retained.
    /// `offset` is camera-space meters: +X right, +Y up, no forward/back.
    pub fn draw_pose(&mut self, pose: &ViewmodelPose, offset: Vec3) -> Result<(), String> {
        let palette = self
            .animation
            .skin_palette(pose, &self.skin.bones, game_model_root())
            .map_err(|e| e.to_string())?;
        let normals: Vec<_> = palette.iter().map(|m| m.inverse().transpose()).collect();
        let light = vec3(-0.3, 0.8, 0.5).normalize();
        for batch in &mut self.batches {
            let part = &self.skin.meshes[batch.source_mesh];
            for (vertex, &index) in batch.mesh.vertices.iter_mut().zip(&batch.source_vertices) {
                let source = &part.vertices[index];
                let position = Vec3::from_array(source.position);
                let normal = Vec3::from_array(source.normal);
                let mut p = Vec3::ZERO;
                let mut n = Vec3::ZERO;
                for (&joint, &weight) in source.joints.iter().zip(&source.weights) {
                    if weight > 0. {
                        p += palette[joint as usize].transform_point3(position) * weight;
                        n += normals[joint as usize].transform_vector3(normal) * weight;
                    }
                }
                n = n.try_normalize().unwrap_or(Vec3::Y);
                let shade = 0.35 + 0.65 * n.dot(light).max(0.);
                vertex.position = p + offset;
                vertex.normal = n.extend(0.);
                vertex.color = Color::new(
                    part.base_color[0] * shade,
                    part.base_color[1] * shade,
                    part.base_color[2] * shade,
                    1.,
                )
                .into();
            }
            draw_mesh(&batch.mesh);
        }
        let actors = self
            .animation
            .actor_matrices(pose, game_model_root())
            .map_err(|e| e.to_string())?;
        let mut transforms = vec![Mat4::IDENTITY; self.rigid_mesh_count];
        let mut visibility = vec![false; self.rigid_mesh_count];
        for (index, actor) in self.animation.actors().iter().enumerate() {
            for &mesh in &actor.mesh_indices {
                transforms[mesh] = Mat4::from_translation(offset) * actors[index];
                visibility[mesh] = pose.actor_visible[index];
            }
        }
        self.weapon.draw_authored_parts(&transforms, &visibility);
        Ok(())
    }
}
