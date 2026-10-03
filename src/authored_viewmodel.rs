//! Opt-in playback adapter for Blender-baked viewmodels. No procedural posing.
use macroquad::prelude::*;
use vector_range::scene_lighting::SceneLighting;
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_ads::{AdsSample, AuthoredAds},
    authored_locomotion_path::AuthoredLocomotionPathState,
    authored_reload::{AuthoredReload, ReloadSlot},
    layered_locomotion::{LayerSources, LayeredLocomotion},
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
    locomotion: Option<LayeredLocomotion>,
    reload: Option<AuthoredReload>,
    reload_renderers: Vec<AuthoredViewmodel>,
    reload_indices: [Option<usize>; 2],
    warning: Option<String>,
    walk_index: Option<usize>,
    ads_index: Option<usize>,
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
            walk_index: None,
            ads_index: None,
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
        let walk_clip = manifest
            .regular_walk
            .as_ref()
            .map(|reference| reference.clip.clone());
        let ads_clips = manifest.ads.clone();
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
            model.walk_index = Some(model.reload_renderers.len());
            model.reload_renderers.push(renderer);
        }
        if let Some(reference) = manifest.ads {
            let renderer = Self::load(&asset_name(&reference.asset)?, &reference.entry_clip, None)?;
            model.ads_index = Some(model.reload_renderers.len());
            model.reload_renderers.push(renderer);
        }
        model.locomotion = Some(
            LayeredLocomotion::new(
                LayerSources {
                    locomotion: &model.animation,
                    walk: model
                        .walk_index
                        .map(|index| &model.reload_renderers[index].animation),
                    ads: model
                        .ads_index
                        .map(|index| &model.reload_renderers[index].animation),
                },
                manifest.locomotion,
                walk_clip.as_deref(),
                ads_clips,
                &manifest.layer_anchor_actor,
            )
            .map_err(|error| error.to_string())?,
        );
        if let Some(clips) = manifest.directional_walk {
            let set = &model.reload_renderers[model
                .walk_index
                .ok_or("missing directional walk renderer")?]
            .animation;
            model.locomotion = Some(
                model
                    .locomotion
                    .take()
                    .ok_or("missing shared layers")?
                    .with_directional_walk(set, clips)
                    .map_err(|error| error.to_string())?,
            );
        }
        model.locomotion = Some(
            model
                .locomotion
                .take()
                .ok_or("missing shared layers")?
                .with_ads_wip_policy(
                    manifest.receiver_ads_wip,
                    manifest.ads_visual_transition_seconds,
                )
                .map_err(|error| error.to_string())?,
        );
        let mut missing = vec!["fire", "mantle"];
        if model.ads_index.is_none() {
            missing.insert(0, "ADS");
        }
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
        self.locomotion
            .as_ref()
            .and_then(|layers| layers.walk().seconds())
    }
    pub fn walk_weight(&self) -> f32 {
        self.locomotion
            .as_ref()
            .map_or(0., |layers| layers.walk().weight())
    }
    pub fn walk_min_rate(&self) -> f32 {
        self.locomotion
            .as_ref()
            .map_or(1., LayeredLocomotion::walk_min_rate)
    }
    pub fn run_weight(&self) -> f32 {
        self.locomotion
            .as_ref()
            .map_or(0., LayeredLocomotion::run_weight)
    }
    pub fn pose_crc32(&self) -> Option<u32> {
        self.locomotion.as_ref().map(LayeredLocomotion::pose_crc32)
    }
    pub fn directional_weights(&self) -> Option<[f64; 4]> {
        self.locomotion
            .as_ref()
            .and_then(LayeredLocomotion::directional_weights)
    }
    pub fn ads_sample(&self) -> Option<AdsSample> {
        self.locomotion
            .as_ref()
            .and_then(LayeredLocomotion::ads)
            .and_then(AuthoredAds::sample)
    }
    pub fn ads_clip(&self) -> Option<&str> {
        let ads = self.locomotion.as_ref()?.ads()?;
        Some(ads.clip(ads.sample()?.slot))
    }
    pub fn ads_duration(&self) -> Option<f64> {
        let ads = self.locomotion.as_ref()?.ads()?;
        Some(ads.duration(ads.sample()?.slot))
    }
    pub fn presentation_route(&self) -> &str {
        if let Some(sample) = self.reload_sample() {
            return if sample.slot == ReloadSlot::Empty {
                "reload.empty"
            } else {
                "reload.tactical"
            };
        }
        if let Some(sample) = self.ads_sample() {
            return sample.slot.route();
        }
        if self.walk_sample().is_some() {
            return "regular_walk";
        }
        match self.locomotion.as_ref().map(|layers| layers.path().state()) {
            Some(AuthoredLocomotionPathState::Ready) => "ready",
            _ => "locomotion",
        }
    }
    pub fn walk_duration(&self) -> Option<f64> {
        let renderer = self.reload_renderers.get(self.walk_index?)?;
        renderer
            .animation
            .clips()
            .iter()
            .find(|clip| {
                clip.name
                    == self
                        .locomotion
                        .as_ref()
                        .and_then(LayeredLocomotion::walk_clip)
                        .unwrap_or(&renderer.clip)
            })
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
        if let Some(layers) = &mut self.locomotion {
            let sources = LayerSources {
                locomotion: &self.animation,
                walk: self
                    .walk_index
                    .map(|index| &self.reload_renderers[index].animation),
                ads: self
                    .ads_index
                    .map(|index| &self.reload_renderers[index].animation),
            };
            if let Err(error) = layers.committed_step(sources, start, simulation, is_reload) {
                self.error = Some(error.to_string());
            }
        }
    }
    pub fn reset(&mut self, time: f64) {
        if let Some(reload) = &mut self.reload {
            reload.reset(time);
        }
        if let Some(layers) = &mut self.locomotion {
            if let Err(error) = layers.reset(&self.animation, time) {
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
    /// `offset` is camera-space meters: +X right, +Y up, no forward/back.
    pub fn draw(&mut self, simulation_time: f64, lighting: SceneLighting, offset: Vec3) {
        if self.error.is_some() {
            return;
        }
        if let Err(error) = self.draw_checked(simulation_time, lighting, offset) {
            eprintln!("Authored viewmodel playback failed: {error}");
            self.error = Some(error);
        }
    }
    fn draw_checked(
        &mut self,
        simulation_time: f64,
        lighting: SceneLighting,
        offset: Vec3,
    ) -> Result<(), String> {
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
            return renderer.draw_pose(&pose, lighting, offset);
        }
        if let Some(layers) = &self.locomotion {
            let pose = layers.pose().clone();
            return self.draw_pose(&pose, lighting, offset);
        }
        let time = self.fixed_time.unwrap_or(simulation_time as f32);
        let pose = if self.fixed_time.is_some() {
            self.animation().sample_clamped(&self.clip, time)
        } else {
            self.animation().sample(&self.clip, time)
        }
        .map_err(|e| e.to_string())?;
        self.draw_pose(&pose, lighting, offset)
    }
    /// Render one complete evaluated pose from this animation set. The gameplay
    /// adapter owns which presentation supplies it; no two pose owners are mixed
    /// here. Skin and actor dimension/transform validation is retained.
    /// `offset` is camera-space meters: +X right, +Y up, no forward/back.
    pub fn draw_pose(
        &mut self,
        pose: &ViewmodelPose,
        lighting: SceneLighting,
        offset: Vec3,
    ) -> Result<(), String> {
        let palette = self
            .animation
            .skin_palette(pose, &self.skin.bones, game_model_root())
            .map_err(|e| e.to_string())?;
        let normals: Vec<_> = palette.iter().map(|m| m.inverse().transpose()).collect();
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
                let shade = lighting.irradiance(n);
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
        self.weapon
            .draw_authored_parts(&transforms, &visibility, lighting);
        Ok(())
    }
}
