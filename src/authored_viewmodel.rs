//! Opt-in playback adapter for Blender-baked viewmodels. No procedural posing.
use vector_range::draw::facade::*;
use vector_range::scene_lighting::SceneLighting;
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_ads::{AdsSample, AuthoredAds},
    authored_locomotion_path::AuthoredLocomotionPathState,
    authored_pose_return::{canonical_to_reload_actor_basis, PoseReturn, PoseReturnMap},
    authored_reload::{AuthoredReload, ReloadSlot},
    layered_locomotion::{AnchoredPoseBlend, LayerSources, LayeredLocomotion},
    skinned_asset::SkinnedAsset,
    viewmodel_animation::{game_model_root, AnimationSet, ViewmodelPose},
};

struct SkinBatch {
    source_mesh: usize,
    source_vertices: Vec<usize>,
    mesh: Mesh,
}
struct ReloadPresentation {
    index: usize,
    pose: ViewmodelPose,
    opacity: Vec<f32>,
    fade: Option<PoseReturn>,
    outgoing: bool,
    from_ads: f32,
    visible_ads: f32,
    weight: f32,
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
    jump_index: Option<usize>,
    return_map: Option<PoseReturnMap>,
    return_blend: Option<AnchoredPoseBlend>,
    reload_presentation: Option<ReloadPresentation>,
    /// Hip cant (radians) about the weapon actor's bore line.
    cant: f32,
}
/// Read-only evaluated source pose for independent CPU diagnostics. This does
/// not expose batched vertices or claim native submission/rendering evidence.
#[allow(dead_code)]
pub struct SourcePoseSnapshot<'a> {
    pub animation: &'a AnimationSet,
    pub pose: ViewmodelPose,
    pub root: Mat4,
    pub actor_opacity: Option<Vec<f32>>,
}
impl AuthoredViewmodel {
    /// Set the hip cant applied at the next draw. Gameplay owns the value.
    pub fn set_cant(&mut self, radians: f32) {
        self.cant = if radians.is_finite() { radians } else { 0. };
    }
    pub fn set_walk_translation(&mut self, value: vector_range::settings::WalkTranslation) {
        if let Some(layers) = &mut self.locomotion {
            layers.set_walk_translation(value);
        }
    }
    /// Snapshot the same effective pose selected by `draw_checked`, before
    /// batching. A separate decoder must own expected source mesh inventories.
    /// The current diagnostic supports uncanted poses only; unsupported state
    /// returns an error instead of silently approximating the source geometry.
    #[allow(dead_code)]
    pub fn source_pose_snapshot(
        &self,
        simulation_time: f64,
        root: Mat4,
    ) -> Result<SourcePoseSnapshot<'_>, String> {
        if let Some(error) = &self.error {
            return Err(error.clone());
        }
        if !simulation_time.is_finite() || !root.is_finite() || self.cant != 0. {
            return Err("source pose diagnostic requires finite time/root and zero cant".into());
        }
        if let Some(visual) = &self.reload_presentation {
            let renderer = &self.reload_renderers[visual.index];
            return Ok(SourcePoseSnapshot {
                animation: &renderer.animation,
                pose: visual.pose.clone(),
                root,
                actor_opacity: Some(visual.opacity.clone()),
            });
        }
        let pose = if let Some(layers) = &self.locomotion {
            layers.pose().clone()
        } else {
            let time = self.fixed_time.unwrap_or(simulation_time as f32);
            if self.fixed_time.is_some() {
                self.animation.sample_clamped(&self.clip, time)
            } else {
                self.animation.sample(&self.clip, time)
            }
            .map_err(|error| error.to_string())?
        };
        Ok(SourcePoseSnapshot {
            animation: &self.animation,
            pose,
            root,
            actor_opacity: None,
        })
    }
    /// Loads CPU mesh and texture descriptors without requiring a render context.
    pub fn load(path: &str, clip: &str, fixed_time: Option<f32>) -> Result<Self, String> {
        if fixed_time.is_some_and(|time| !time.is_finite()) {
            return Err("authored viewmodel time must be finite".into());
        }
        let (animation, skin, weapon) =
            AnimationSet::load_with_companions(path).map_err(|e| e.to_string())?;
        let sample_clip = clip;
        // Fail before preparing mesh descriptors if the requested clip is absent.
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
                let texture = Texture::rgba8(
                    part.texture_width,
                    part.texture_height,
                    &pixels,
                    Sampler {
                        filter: FilterMode::Linear,
                        wrap_x: WrapMode::Repeat,
                        wrap_y: WrapMode::Repeat,
                    },
                )
                .map_err(|error| format!("authored skin mesh {source_mesh} texture: {error}"))?;
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
            jump_index: None,
            return_map: None,
            return_blend: None,
            reload_presentation: None,
            cant: 0.,
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
                let mut renderer =
                    Self::load(&asset_name(&reference.asset)?, &reference.clip, Some(0.))?;
                renderer.return_map = Some(
                    PoseReturnMap::new(
                        &model.animation,
                        &model.skin,
                        &renderer.animation,
                        &renderer.skin,
                        canonical_to_reload_actor_basis(),
                    )
                    .map_err(|error| error.to_string())?,
                );
                renderer.return_blend = Some(
                    AnchoredPoseBlend::new(&renderer.animation, &manifest.layer_anchor_actor)
                        .map_err(|error| error.to_string())?,
                );
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
        if let Some(path) = &manifest.jump_asset {
            let renderer = Self::load(&asset_name(path)?, "jump_takeoff", None)?;
            model.jump_index = Some(model.reload_renderers.len());
            model.reload_renderers.push(renderer);
        }
        let ready_clip = manifest.locomotion.ready_clip.clone();
        model.locomotion = Some(
            LayeredLocomotion::new(
                LayerSources {
                    jump: model
                        .jump_index
                        .map(|i| &model.reload_renderers[i].animation),
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
        if let Some(index) = model.jump_index {
            model.locomotion = Some(
                model
                    .locomotion
                    .take()
                    .ok_or("missing shared layers")?
                    .with_jump(
                        &model.reload_renderers[index].animation,
                        &model.animation,
                        &ready_clip,
                        &manifest.layer_anchor_actor,
                    )
                    .map_err(|error| error.to_string())?,
            );
        }
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
                .and_then(|layers| layers.with_forward_ads_v9_policy(manifest.forward_ads_v9_wip))
                .map_err(|error| error.to_string())?,
        );
        let mut missing = vec!["fire", "mantle"];
        if model.jump_index.is_none() {
            missing.push("jump");
        }
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
            "Authored WIP: {} clips unavailable; reload pose crossfades",
            missing.join(", ")
        ));
        Ok(model)
    }
    pub fn jump_sample(&self) -> Option<vector_range::authored_jump::JumpSample> {
        self.locomotion
            .as_ref()
            .and_then(LayeredLocomotion::jump_sample)
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
    pub fn visual_ads_amount(&self) -> f32 {
        if let Some(visual) = &self.reload_presentation {
            return visual.visible_ads;
        }
        self.locomotion
            .as_ref()
            .map_or(0., LayeredLocomotion::visual_ads_amount)
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
        if self
            .reload_presentation
            .as_ref()
            .is_some_and(|visual| visual.outgoing)
        {
            return "reload.return";
        }
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
        let previous_pose = self.locomotion.as_ref().map(|layers| layers.pose().clone());
        let previous_ads = self.visual_ads_amount();
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
                jump: self.jump_index.map(|i| &self.reload_renderers[i].animation),
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
        if self.error.is_none() {
            if let Some(previous_pose) = previous_pose {
                if let Err(error) = self.update_reload_presentation(
                    start,
                    simulation.time,
                    &previous_pose,
                    previous_ads,
                ) {
                    self.error = Some(error);
                }
            }
        }
    }
    fn update_reload_presentation(
        &mut self,
        start: f64,
        time: f64,
        previous_pose: &ViewmodelPose,
        previous_ads: f32,
    ) -> Result<(), String> {
        if time == start {
            return Ok(());
        }
        let Some(reload) = self.reload.as_ref() else {
            return Ok(());
        };
        let sample = reload.sample();
        let ended = reload.ended_this_step();
        let started = reload.started_this_step();
        let Some(layers) = self.locomotion.as_ref() else {
            return Ok(());
        };
        if let Some(sample) = sample {
            let slot = usize::from(sample.slot == ReloadSlot::Empty);
            let index = self.reload_indices[slot].ok_or("missing active reload renderer")?;
            let renderer = &self.reload_renderers[index];
            let target = renderer
                .animation
                .sample_clamped(&renderer.clip, sample.seconds as f32)
                .map_err(|e| e.to_string())?;
            if started
                || self
                    .reload_presentation
                    .as_ref()
                    .is_none_or(|v| v.outgoing || v.index != index)
            {
                let (from, opacity) = if let Some(previous) = &self.reload_presentation {
                    if previous.index == index {
                        (previous.pose.clone(), previous.opacity.clone())
                    } else {
                        let old = &self.reload_renderers[previous.index];
                        let map = PoseReturnMap::new(
                            &old.animation,
                            &old.skin,
                            &renderer.animation,
                            &renderer.skin,
                            Mat4::IDENTITY,
                        )
                        .map_err(|e| e.to_string())?;
                        let pose = map
                            .pose(&old.animation, &renderer.animation, &previous.pose, &target)
                            .map_err(|e| e.to_string())?;
                        let alpha = renderer
                            .animation
                            .actors()
                            .iter()
                            .map(|a| {
                                old.animation
                                    .actors()
                                    .iter()
                                    .position(|b| a.name == b.name)
                                    .map_or(0., |i| previous.opacity[i])
                            })
                            .collect();
                        (pose, alpha)
                    }
                } else {
                    let pose = renderer
                        .return_map
                        .as_ref()
                        .ok_or("missing reload pose map")?
                        .pose(&self.animation, &renderer.animation, previous_pose, &target)
                        .map_err(|e| e.to_string())?;
                    let alpha = pose
                        .actor_visible
                        .iter()
                        .map(|&v| f32::from(u8::from(v)))
                        .collect();
                    (pose, alpha)
                };
                self.reload_presentation = Some(ReloadPresentation {
                    index,
                    pose: from.clone(),
                    opacity: opacity.clone(),
                    fade: Some(PoseReturn::new(from, opacity, start)),
                    outgoing: false,
                    from_ads: previous_ads,
                    visible_ads: previous_ads,
                    weight: 0.,
                });
            }
            let visual = self.reload_presentation.as_mut().unwrap();
            if let Some(fade) = &visual.fade {
                (visual.pose, visual.opacity) = fade
                    .pose(
                        &renderer.animation,
                        renderer.return_blend.as_ref().unwrap(),
                        &target,
                        time,
                    )
                    .map_err(|e| e.to_string())?;
                visual.visible_ads = visual.from_ads * (1. - fade.weight(time));
                visual.weight = fade.weight(time);
                if fade.weight(time) == 1. {
                    visual.fade = None;
                }
            } else {
                visual.opacity = target
                    .actor_visible
                    .iter()
                    .map(|&v| f32::from(u8::from(v)))
                    .collect();
                visual.pose = target;
                visual.visible_ads = 0.;
            }
        } else if let Some(visual) = &mut self.reload_presentation {
            let renderer = &self.reload_renderers[visual.index];
            if ended.is_some() && !visual.outgoing {
                // Freeze the complete displayed pose, including an interrupted
                // incoming/return blend, so cancellation cannot reset a hand.
                if let Some(ended) = ended {
                    let duration =
                        AuthoredReload::clip_duration(&renderer.animation, &renderer.clip)
                            .map_err(|e| e.to_string())?;
                    if visual.fade.is_none() && ended.seconds >= duration {
                        visual.pose = renderer
                            .animation
                            .sample_clamped(&renderer.clip, ended.seconds as f32)
                            .map_err(|e| e.to_string())?;
                        visual.opacity = visual
                            .pose
                            .actor_visible
                            .iter()
                            .map(|&v| f32::from(u8::from(v)))
                            .collect();
                    }
                }
                visual.fade = Some(PoseReturn::new(
                    visual.pose.clone(),
                    visual.opacity.clone(),
                    start,
                ));
                visual.outgoing = true;
                visual.from_ads = previous_ads;
            }
            let target = renderer
                .return_map
                .as_ref()
                .ok_or("missing reload pose map")?
                .pose(
                    &self.animation,
                    &renderer.animation,
                    layers.pose(),
                    &visual.pose,
                )
                .map_err(|e| e.to_string())?;
            let fade = visual.fade.as_ref().ok_or("missing reload return fade")?;
            (visual.pose, visual.opacity) = fade
                .pose(
                    &renderer.animation,
                    renderer.return_blend.as_ref().unwrap(),
                    &target,
                    time,
                )
                .map_err(|e| e.to_string())?;
            let weight = fade.weight(time);
            visual.weight = weight;
            visual.visible_ads =
                visual.from_ads + (layers.visual_ads_amount() - visual.from_ads) * weight;
            if weight == 1. {
                self.reload_presentation = None;
            }
        }
        Ok(())
    }
    pub fn reload_return_weight(&self) -> Option<f32> {
        self.reload_presentation
            .as_ref()
            .filter(|v| v.outgoing)
            .map(|v| v.weight)
    }
    pub fn reload_extra_opacity(&self) -> f32 {
        self.reload_presentation.as_ref().map_or(0., |visual| {
            self.reload_renderers[visual.index]
                .animation
                .actors()
                .iter()
                .enumerate()
                .filter(|(_, actor)| !self.animation.actors().iter().any(|a| a.name == actor.name))
                .map(|(i, _)| visual.opacity[i])
                .fold(0., f32::max)
        })
    }
    pub fn presented_anchor(&self) -> Option<Vec3> {
        let (set, pose) = if let Some(visual) = &self.reload_presentation {
            (&self.reload_renderers[visual.index].animation, &visual.pose)
        } else {
            (&self.animation, self.locomotion.as_ref()?.pose())
        };
        let index = set
            .actors()
            .iter()
            .position(|actor| actor.name == "hk416_weapon")?;
        Some(game_model_root().transform_point3(pose.actor_globals[index].translation))
    }
    pub fn reset(&mut self, time: f64) {
        self.reload_presentation = None;
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
    /// `root` is a rigid camera-space transform applied to the whole viewmodel
    /// (arms and weapon together, so contacts are preserved). Meters: +X right,
    /// +Y up, -Z forward.
    pub fn draw(&mut self, simulation_time: f64, lighting: SceneLighting, root: Mat4) {
        if self.error.is_some() {
            return;
        }
        if let Err(error) = self.draw_checked(simulation_time, lighting, root) {
            eprintln!("Authored viewmodel playback failed: {error}");
            self.error = Some(error);
        }
    }
    fn draw_checked(
        &mut self,
        simulation_time: f64,
        lighting: SceneLighting,
        root: Mat4,
    ) -> Result<(), String> {
        if let Some(visual) = &self.reload_presentation {
            let renderer = &mut self.reload_renderers[visual.index];
            renderer.cant = self.cant;
            return renderer.draw_pose_opacity(&visual.pose, lighting, root, Some(&visual.opacity));
        }
        if let Some(layers) = &self.locomotion {
            let pose = layers.pose().clone();
            return self.draw_pose(&pose, lighting, root);
        }
        let time = self.fixed_time.unwrap_or(simulation_time as f32);
        let pose = if self.fixed_time.is_some() {
            self.animation().sample_clamped(&self.clip, time)
        } else {
            self.animation().sample(&self.clip, time)
        }
        .map_err(|e| e.to_string())?;
        self.draw_pose(&pose, lighting, root)
    }
    /// Render one complete evaluated pose from this animation set. The gameplay
    /// adapter owns which presentation supplies it; no two pose owners are mixed
    /// here. Skin and actor dimension/transform validation is retained.
    /// Rotate the weapon actor about its bore line and carry every arm bone
    /// with it in weapon space, so grips stay attached (shoulders are offscreen).
    fn cant_root(&self, pose: &ViewmodelPose, root: Mat4) -> Result<Mat4, String> {
        if self.cant == 0. {
            return Ok(root);
        }
        let actors = self.animation.actors();
        let Some(index) = actors
            .iter()
            .position(|a| a.name == "hk416_weapon")
            .or_else(|| actors.iter().position(|a| !a.mesh_indices.is_empty()))
        else {
            return Ok(root);
        };
        let weapon = self
            .animation
            .actor_matrices(pose, root * game_model_root())
            .map_err(|e| e.to_string())?[index];
        Ok(
            vector_range::weapon_sway::cant_about_bore(weapon, self.weapon.muzzle, self.cant)
                * root,
        )
    }
    /// `root` is the rigid camera-space viewmodel transform (see `draw`).
    pub fn draw_pose(
        &mut self,
        pose: &ViewmodelPose,
        lighting: SceneLighting,
        root: Mat4,
    ) -> Result<(), String> {
        self.draw_pose_opacity(pose, lighting, root, None)
    }
    fn draw_pose_opacity(
        &mut self,
        pose: &ViewmodelPose,
        lighting: SceneLighting,
        root: Mat4,
        actor_opacity: Option<&[f32]>,
    ) -> Result<(), String> {
        let root = self.cant_root(pose, root)?;
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
                n = root.transform_vector3(n).try_normalize().unwrap_or(Vec3::Y);
                let shade = lighting.irradiance(n);
                vertex.position = root.transform_point3(p);
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
        let mut opacity = vec![1.; self.rigid_mesh_count];
        for (index, actor) in self.animation.actors().iter().enumerate() {
            for &mesh in &actor.mesh_indices {
                transforms[mesh] = root * actors[index];
                visibility[mesh] = pose.actor_visible[index];
                opacity[mesh] = actor_opacity.map_or(1., |values| values[index]);
            }
        }
        self.weapon
            .draw_authored_parts(&transforms, &visibility, &opacity, lighting);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use vector_range::{
        asset::{AssetMesh, AssetVertex, WeaponAsset},
        draw::Command,
        skinned_asset::{crc32, Bone, SkinMesh, SkinVertex},
    };

    fn contact_fixture() -> AuthoredViewmodel {
        fn words(bytes: &mut Vec<u8>, values: &[u32]) {
            bytes.extend(values.iter().flat_map(|value| value.to_le_bytes()));
        }
        fn floats(bytes: &mut Vec<u8>, values: &[f32]) {
            bytes.extend(values.iter().flat_map(|value| value.to_le_bytes()));
        }
        fn name(bytes: &mut Vec<u8>, value: &str) {
            bytes.extend((value.len() as u16).to_le_bytes());
            bytes.extend(value.as_bytes());
        }

        // Original one-hand/one-prop fixture. Both start at x=2 and animate to
        // x=3, so genuine inverse binds must leave a one-unit translation.
        let inverse_bind = Mat4::from_translation(vec3(-2., 0., 0.)).to_cols_array();
        let mut payload = Vec::new();
        words(&mut payload, &[0, 0, 1]); // Unused companion CRCs; one bone.
        name(&mut payload, "fixture_hand");
        words(&mut payload, &[u32::MAX, 1]); // Root parent; one actor.
        name(&mut payload, "fixture_prop");
        words(&mut payload, &[1, 0]); // Actor binds rigid mesh zero.
        floats(&mut payload, &inverse_bind);
        words(&mut payload, &[1]);
        name(&mut payload, "contact");
        words(&mut payload, &[0, 1]); // Non-looping, one frame.
        floats(&mut payload, &[0.]);
        for _ in 0..2 {
            floats(&mut payload, &[3., 0., 0., 0., 0., 0., 1., 1., 1., 1.]);
        }
        payload.push(1); // Visible actor.
        let mut bytes = b"VRANIM01".to_vec();
        words(&mut bytes, &[1, payload.len() as u32, crc32(&payload), 0]);
        bytes.extend(payload);
        let animation = AnimationSet::decode(&bytes).unwrap();
        let positions = [vec3(2., 1., -1.), vec3(3., 1., -1.), vec3(2., 2., -1.)];
        let skin = SkinnedAsset {
            bones: vec![Bone {
                name: "fixture_hand".into(),
                parent: None,
                rest_local: Mat4::from_translation(vec3(2., 0., 0.)).to_cols_array(),
                inverse_bind,
            }],
            meshes: vec![SkinMesh {
                base_color: [1., 0.5, 0.25, 0.2],
                metallic: 0.,
                roughness: 1.,
                texture_width: 0,
                texture_height: 0,
                rgba: Vec::new(),
                vertices: positions
                    .iter()
                    .map(|position| SkinVertex {
                        position: position.to_array(),
                        normal: Vec3::Y.to_array(),
                        uv: [0.25, 0.75],
                        joints: [0; 8],
                        weights: [1., 0., 0., 0., 0., 0., 0., 0.],
                    })
                    .collect(),
                indices: vec![0, 1, 2],
            }],
        };
        let weapon = crate::weapon_model::WeaponModel::from_asset(WeaponAsset {
            payload_crc32: 0,
            meshes: vec![AssetMesh {
                base_color: skin.meshes[0].base_color,
                metallic: 0.,
                roughness: 1.,
                texture_width: 0,
                texture_height: 0,
                rgba: Vec::new(),
                vertices: positions
                    .iter()
                    .map(|position| AssetVertex {
                        position: position.to_array(),
                        normal: Vec3::Y.to_array(),
                        uv: [0.25, 0.75],
                    })
                    .collect(),
                indices: vec![0, 1, 2],
            }],
        });
        AuthoredViewmodel {
            animation,
            skin,
            batches: vec![SkinBatch {
                source_mesh: 0,
                source_vertices: vec![0, 1, 2],
                mesh: Mesh {
                    vertices: positions
                        .into_iter()
                        .map(|position| Vertex::new2(position, vec2(0.25, 0.75), WHITE))
                        .collect(),
                    indices: vec![0, 1, 2],
                    texture: None,
                },
            }],
            weapon,
            rigid_mesh_count: 1,
            clip: "contact".into(),
            fixed_time: Some(0.),
            error: None,
            locomotion: None,
            reload: None,
            reload_renderers: Vec::new(),
            reload_indices: [None, None],
            warning: None,
            walk_index: None,
            ads_index: None,
            jump_index: None,
            return_map: None,
            return_blend: None,
            reload_presentation: None,
            cant: 0.,
        }
    }

    #[test]
    fn authored_draw_keeps_skinned_hand_and_rigid_weapon_in_one_canted_frame() {
        let mut model = contact_fixture();
        let pose = model.animation.sample_clamped("contact", 0.).unwrap();
        let root = Mat4::from_rotation_translation(
            Quat::from_rotation_x(std::f32::consts::FRAC_PI_2),
            vec3(4., 5., 6.),
        );
        let parent = Mat4::from_translation(vec3(0., 0., -2.));
        let lighting = SceneLighting {
            direction_to_light: Vec3::X,
            ambient: 0.25,
            diffuse: 0.5,
        };
        // Expected coordinates are independent of the production palette,
        // actor-matrix and cant helpers. Before cant: (3-x, 5+z, 6+y).
        // The computed muzzle puts the camera-space bore through
        // (0.5, 3.99, 7.5), parallel to Y. A positive quarter-turn gives
        // (y-1, 5+z, 5+x). The caller's parent then subtracts two from Z.
        for (cant, expected, normal, rgb) in [
            (
                0.,
                [vec3(1., 4., 5.), vec3(0., 4., 5.), vec3(1., 4., 6.)],
                Vec3::Z,
                [63, 31, 15],
            ),
            (
                std::f32::consts::FRAC_PI_2,
                [vec3(0., 4., 5.), vec3(0., 4., 6.), vec3(1., 4., 5.)],
                Vec3::X,
                [191, 95, 47],
            ),
        ] {
            model.set_cant(cant);
            begin_frame(640, 480, 1.).unwrap();
            with_model_matrix(parent, || {
                model
                    .draw_pose_opacity(&pose, lighting, root, Some(&[0.5]))
                    .unwrap();
                assert_eq!(current_model_matrix().unwrap(), parent);
            });
            assert_eq!(current_model_matrix().unwrap(), Mat4::IDENTITY);
            let list = take_draw_list().unwrap();
            let meshes: Vec<_> = list
                .commands
                .iter()
                .filter_map(|command| match command {
                    Command::Mesh { mesh, model, blend } => Some((mesh, model, blend)),
                    _ => None,
                })
                .collect();
            assert_eq!(meshes.len(), 2, "one skinned hand and one rigid weapon");
            assert_eq!(*meshes[0].1, parent, "skin root is baked exactly once");
            for (index, (mesh, transform, blend)) in meshes.into_iter().enumerate() {
                assert_eq!(*blend, BlendMode::Alpha);
                assert_eq!(mesh.indices, [0, 1, 2]);
                assert_eq!(mesh.vertices.len(), 3);
                for (vertex, expected) in mesh.vertices.iter().zip(expected) {
                    let actual = transform.transform_point3(vertex.position);
                    assert!(
                        actual.abs_diff_eq(expected, 1e-5),
                        "draw {index}, cant {cant}: {actual:?} != {expected:?}"
                    );
                    assert!(transform
                        .transform_vector3(vertex.normal.truncate())
                        .abs_diff_eq(normal, 1e-5));
                    assert_eq!(vertex.uv, vec2(0.25, 0.75));
                    assert_eq!(
                        vertex.color,
                        [rgb[0], rgb[1], rgb[2], if index == 0 { 255 } else { 128 }],
                        "actor opacity must not fade the skinned hand"
                    );
                }
            }
        }
    }

    fn layered_contact_fixture() -> AuthoredViewmodel {
        fn words(bytes: &mut Vec<u8>, values: &[u32]) {
            bytes.extend(values.iter().flat_map(|v| v.to_le_bytes()));
        }
        fn floats(bytes: &mut Vec<u8>, values: &[f32]) {
            bytes.extend(values.iter().flat_map(|v| v.to_le_bytes()));
        }
        fn name(bytes: &mut Vec<u8>, value: &str) {
            bytes.extend((value.len() as u16).to_le_bytes());
            bytes.extend(value.as_bytes());
        }
        let mut model = contact_fixture();
        let inverse = Mat4::from_translation(vec3(-2., 0., 0.)).to_cols_array();
        let mut payload = Vec::new();
        words(&mut payload, &[0, 0, 1]);
        name(&mut payload, "fixture_hand");
        words(&mut payload, &[u32::MAX, 1]);
        name(&mut payload, "fixture_prop");
        words(&mut payload, &[1, 0]);
        floats(&mut payload, &inverse);
        words(&mut payload, &[2]);
        for (clip, looping) in [("contact", 0), ("contact_loop", 1)] {
            name(&mut payload, clip);
            words(&mut payload, &[looping, 2]);
            for time in [0., 1.] {
                floats(&mut payload, &[time]);
                for _ in 0..2 {
                    floats(&mut payload, &[3., 0., 0., 0., 0., 0., 1., 1., 1., 1.]);
                }
                payload.push(1);
            }
        }
        let mut bytes = b"VRANIM01".to_vec();
        words(&mut bytes, &[1, payload.len() as u32, crc32(&payload), 0]);
        bytes.extend(payload);
        model.animation = AnimationSet::decode(&bytes).unwrap();
        model.locomotion = Some(
            LayeredLocomotion::new(
                LayerSources {
                    locomotion: &model.animation,
                    walk: None,
                    ads: None,
                    jump: None,
                },
                vector_range::authored_locomotion_path::AuthoredLocomotionPathConfig {
                    ready_clip: "contact".into(),
                    entry_clip: "contact".into(),
                    loop_clip: "contact_loop".into(),
                    exit_bridge_clips: vec!["contact".into(), "contact".into()],
                    exit_clip: "contact".into(),
                    settle_clip: "contact".into(),
                    rate_response_seconds: 0.05,
                    residual_decay_seconds: 0.03,
                },
                None,
                None,
                "fixture_prop",
            )
            .unwrap(),
        );
        model
    }

    #[test]
    fn source_snapshot_layered_selection_ignores_batched_skin_and_fallback_clip() {
        let mut model = layered_contact_fixture();
        let expected = model.locomotion.as_ref().unwrap().pose().clone();
        model.clip = "nonexistent_fallback_clip".into();
        model.batches.clear();
        let snapshot = model.source_pose_snapshot(0.5, Mat4::IDENTITY).unwrap();
        assert_eq!(snapshot.pose, expected);
        assert!(std::ptr::eq(snapshot.animation, &model.animation));
    }

    #[test]
    fn source_snapshot_non_fixed_sampling_uses_requested_time() {
        let mut model = layered_contact_fixture();
        model.locomotion = None;
        model.fixed_time = None;
        let snapshot = model.source_pose_snapshot(0.75, Mat4::IDENTITY).unwrap();
        assert_eq!(
            snapshot.pose,
            model.animation.sample("contact", 0.75).unwrap()
        );
        assert_eq!(snapshot.pose.sample_time, 0.75);
    }

    #[test]
    fn source_snapshot_preserves_primary_pose_and_rejects_unsupported_cant() {
        let mut model = contact_fixture();
        let root = Mat4::from_translation(vec3(0.2, -0.2, 0.2));
        let snapshot = model.source_pose_snapshot(12., root).unwrap();
        assert_eq!(
            snapshot.pose,
            model.animation.sample_clamped("contact", 0.).unwrap()
        );
        assert_eq!(snapshot.root, root);
        assert!(snapshot.actor_opacity.is_none());
        assert!(std::ptr::eq(snapshot.animation, &model.animation));
        model.set_cant(0.1);
        assert!(model.source_pose_snapshot(0., root).is_err());
        model.set_cant(0.);
        assert!(model.source_pose_snapshot(f64::NAN, root).is_err());
    }

    #[test]
    fn source_snapshot_uses_reload_pose_provider_and_opacity_without_drawing() {
        let mut model = layered_contact_fixture();
        let renderer = contact_fixture();
        let mut pose = renderer.animation.sample_clamped("contact", 0.).unwrap();
        pose.actor_visible[0] = false;
        model.reload_renderers.push(renderer);
        model.reload_presentation = Some(ReloadPresentation {
            index: 0,
            pose: pose.clone(),
            opacity: vec![0.25],
            fade: None,
            outgoing: false,
            from_ads: 0.,
            visible_ads: 0.,
            weight: 1.,
        });
        let snapshot = model.source_pose_snapshot(0., Mat4::IDENTITY).unwrap();
        assert_eq!(snapshot.pose, pose);
        assert_eq!(snapshot.actor_opacity, Some(vec![0.25]));
        assert!(std::ptr::eq(
            snapshot.animation,
            &model.reload_renderers[0].animation
        ));
    }
}
