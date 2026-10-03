//! Opt-in playback adapter for Blender-baked viewmodels. No procedural posing.
use macroquad::prelude::*;
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathState},
    authored_reload::{AuthoredReload, ReloadSlot},
    authored_walk::AuthoredWalk,
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
    reload: Option<AuthoredReload>,
    reload_renderers: Vec<AuthoredViewmodel>,
    reload_indices: [Option<usize>; 2],
    warning: Option<String>,
    walk: AuthoredWalk,
    walk_index: Option<usize>,
}
impl AuthoredViewmodel {
    /// Requires an initialized render context, like the existing mesh adapters.
    pub fn load(path: &str, clip: &str, fixed_time: Option<f32>) -> Result<Self, String> {
        if fixed_time.is_some_and(|time| !time.is_finite()) {
            return Err("authored viewmodel time must be finite".into());
        }
        let (animation, skin, weapon) =
            AnimationSet::load_with_companions(path).map_err(|e| e.to_string())?;
        let sample_clip = clip;
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
            locomotion: None,
            reload: None,
            reload_renderers: Vec::new(),
            reload_indices: [None, None],
            warning: None,
            walk: AuthoredWalk::default(),
            walk_index: None,
        })
    }
    /// Gameplay route: every semantic slot binds data, and each complete model
    /// retains its own CRC-checked skin and rigid companions. No cross-rig poses.
    pub fn load_manifest(path: &std::path::Path) -> Result<Self, String> {
        let manifest = AnimationManifest::load(path)?;
        let asset_name = |path: &std::path::Path| {
            path.to_str()
                .map(str::to_owned)
                .ok_or_else(|| "animation asset path is not Unicode".to_owned())
        };
        let mut model = Self::load(
            &asset_name(&manifest.locomotion_asset)?,
            &manifest.locomotion.ready_clip,
            None,
        )?;
        model.locomotion = Some(
            AuthoredLocomotionPath::new(&model.animation, manifest.locomotion, 0.)
                .map_err(|e| e.to_string())?,
        );
        let mut durations = [None, None];
        let mut references = Vec::new();
        for (slot, reference) in [Some(manifest.tactical), manifest.empty]
            .into_iter()
            .enumerate()
        {
            let Some(reference) = reference else {
                continue;
            };
            let index = if let Some(index) = references.iter().position(|item| item == &reference) {
                index
            } else {
                let renderer =
                    Self::load(&asset_name(&reference.asset)?, &reference.clip, Some(0.))?;
                references.push(reference.clone());
                model.reload_renderers.push(renderer);
                references.len() - 1
            };
            let renderer = &model.reload_renderers[index];
            durations[slot] = Some(
                AuthoredReload::clip_duration(&renderer.animation, &reference.clip)
                    .map_err(|e| e.to_string())?,
            );
            model.reload_indices[slot] = Some(index);
        }
        model.reload = Some(
            AuthoredReload::new(
                durations[0].ok_or("missing tactical reload slot")?,
                durations[1],
            )
            .map_err(|e| e.to_string())?,
        );
        if let Some(reference) = manifest.regular_walk {
            let renderer = Self::load(&asset_name(&reference.asset)?, &reference.clip, None)?;
            AuthoredWalk::validate_clip(&renderer.animation, &reference.clip)
                .map_err(|e| e.to_string())?;
            model.walk_index = Some(model.reload_renderers.len());
            model.reload_renderers.push(renderer);
        }
        let mut missing = vec!["ADS", "fire", "mantle"];
        if durations[1].is_none() {
            missing.insert(0, "empty reload");
        }
        if model.walk_index.is_none() {
            missing.insert(0, "regular walk");
        }
        model.warning = Some(format!(
            "Authored WIP: {} clips unavailable; whole-model cuts",
            missing.join(", ")
        ));
        Ok(model)
    }
    pub fn reload_sample(&self) -> Option<vector_range::authored_reload::ReloadSample> {
        self.reload.as_ref().and_then(AuthoredReload::sample)
    }
    pub fn walk_sample(&self) -> Option<f64> {
        if self.reload_sample().is_some() {
            return None;
        }
        self.walk.seconds()
    }
    pub fn walk_duration(&self) -> Option<f64> {
        let renderer = self.reload_renderers.get(self.walk_index?)?;
        renderer
            .animation
            .clips()
            .iter()
            .find(|clip| clip.name == renderer.clip)
            .map(|clip| f64::from(clip.duration()))
    }
    pub fn tactical_duration(&self) -> Option<f64> {
        let renderer = self.reload_renderers.get(self.reload_indices[0]?)?;
        AuthoredReload::clip_duration(&renderer.animation, &renderer.clip).ok()
    }
    pub fn warning(&self) -> Option<&str> {
        self.warning.as_deref()
    }
    /// Exactly one committed observer, shared by real keyboard and replay input.
    pub fn committed_step(&mut self, start: f64, simulation: &vector_range::sim::Simulation) {
        if self.error.is_some() {
            return;
        }
        let was_reload = self
            .reload
            .as_ref()
            .and_then(AuthoredReload::sample)
            .is_some();
        if let Some(reload) = &mut self.reload {
            if let Err(error) = reload.committed_step(start, simulation) {
                self.error = Some(error.to_string());
                return;
            }
            if reload.missing_slot().is_some() {
                self.warning = Some("Missing authored empty-reload slot: gameplay continues; ready/locomotion shown".into());
            }
        }
        let is_reload = self
            .reload
            .as_ref()
            .and_then(AuthoredReload::sample)
            .is_some();
        if was_reload && !is_reload {
            // Explicit whole-model route cut, not adapter pose reacquisition.
            // The reload pack can have a different actor map and bind CRC.
            if let Some(path) = &mut self.locomotion {
                if let Err(error) = path.reset(&self.animation, start) {
                    self.error = Some(error.to_string());
                    return;
                }
            }
        }
        self.update_locomotion(
            start,
            simulation.time,
            simulation.player.sprinting && !is_reload,
        );
        let player = &simulation.player;
        let eligible = self.walk_index.is_some()
            && !is_reload
            && player.reload_left <= 0.
            && !player.sprinting
            && player.mantle.is_none()
            && player.ads <= 0.
            && player.shot_kick <= 0.
            && self
                .locomotion
                .as_ref()
                .is_some_and(|path| path.state() == AuthoredLocomotionPathState::Ready);
        if let Err(error) = self.walk.committed_step(
            start,
            simulation.time,
            player.grounded && player.speed() > 0.1,
            eligible,
        ) {
            self.error = Some(error.to_string());
        }
    }
    pub fn reset(&mut self, time: f64) {
        self.walk.reset(time);
        if let Some(reload) = &mut self.reload {
            reload.reset(time);
        }
        if let Some(path) = &mut self.locomotion {
            if let Err(error) = path.reset(&self.animation, time) {
                self.error = Some(error.to_string());
            }
        }
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
    pub fn draw(&mut self, simulation_time: f64) {
        if self.error.is_some() {
            return;
        }
        if let Err(error) = self.draw_checked(simulation_time) {
            eprintln!("Authored viewmodel playback failed: {error}");
            self.error = Some(error);
        }
    }
    fn draw_checked(&mut self, simulation_time: f64) -> Result<(), String> {
        if let Some(sample) = self.reload.as_ref().and_then(AuthoredReload::sample) {
            let slot = if sample.slot == ReloadSlot::Empty {
                1
            } else {
                0
            };
            let index = self.reload_indices[slot].ok_or("missing active reload renderer")?;
            let renderer = &mut self.reload_renderers[index];
            let pose = renderer
                .animation
                .sample_clamped(&renderer.clip, sample.seconds as f32)
                .map_err(|e| e.to_string())?;
            return renderer.draw_pose(&pose);
        }
        if let (Some(index), Some(seconds)) = (self.walk_index, self.walk.seconds()) {
            let renderer = &mut self.reload_renderers[index];
            let pose = renderer
                .animation
                .sample(&renderer.clip, seconds as f32)
                .map_err(|e| e.to_string())?;
            return renderer.draw_pose(&pose);
        }
        if let Some(path) = &self.locomotion {
            let pose = path.pose().clone();
            return self.draw_pose(&pose);
        }
        let time = self.fixed_time.unwrap_or(simulation_time as f32);
        let pose = if self.fixed_time.is_some() {
            self.animation().sample_clamped(&self.clip, time)
        } else {
            self.animation().sample(&self.clip, time)
        }
        .map_err(|e| e.to_string())?;
        self.draw_pose(&pose)
    }
    /// Render one complete evaluated pose from this animation set. The gameplay
    /// adapter owns which presentation supplies it; no two pose owners are mixed
    /// here. Skin and actor dimension/transform validation is retained.
    pub fn draw_pose(&mut self, pose: &ViewmodelPose) -> Result<(), String> {
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
                vertex.position = p;
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
                transforms[mesh] = actors[index];
                visibility[mesh] = pose.actor_visible[index];
            }
        }
        self.weapon.draw_authored_parts(&transforms, &visibility);
        Ok(())
    }
}
