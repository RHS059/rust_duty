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

struct HighMantleVisual {
    index: usize,
    pose: Option<ViewmodelPose>,
    opacity: Option<Vec<f32>>,
    fade: Option<PoseReturn>,
    generation: Option<u64>,
    return_began: Option<f64>,
    // Diagnostic observation of the actual mapped target, never an input to motion.
    mapped_target_pose_seconds: Option<f32>,
    target_maps: Vec<(usize, PoseReturnMap)>,
    return_weight: f32,
    procedural_weight: f32,
    visible_ads: f32,
}
impl HighMantleVisual {
    fn new(index: usize, target_maps: Vec<(usize, PoseReturnMap)>) -> Self {
        Self {
            index,
            pose: None,
            opacity: None,
            fade: None,
            generation: None,
            return_began: None,
            mapped_target_pose_seconds: None,
            target_maps,
            return_weight: 1.,
            procedural_weight: 1.,
            visible_ads: 0.,
        }
    }
    fn clear(&mut self) {
        self.pose = None;
        self.opacity = None;
        self.fade = None;
        self.generation = None;
        self.return_began = None;
        self.mapped_target_pose_seconds = None;
        self.return_weight = 1.;
        self.procedural_weight = 1.;
        self.visible_ads = 0.;
    }
}
struct LowVaultReturn {
    fade: PoseReturn,
    weight: f32,
    opacity: Vec<f32>,
}
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
    low_vault: Option<(
        vector_range::authored_low_vault::LowVaultBinding,
        Box<AuthoredViewmodel>,
    )>,
    low_vault_pose: Option<ViewmodelPose>,
    low_vault_return: Option<LowVaultReturn>,
    low_vault_reload_maps: Vec<Option<PoseReturnMap>>,
    low_vault_generation: Option<u64>,
    high_mantle_binding: Option<vector_range::authored_high_mantle::HighMantleBinding>,
    high_mantle: Option<HighMantleVisual>,
    prone_index: Option<usize>,
    prone_camera: Option<std::sync::Arc<vector_range::authored_prone::ProneCameraTrack>>,
    prone_pose: Option<ViewmodelPose>,
    prone_opacity: Option<Vec<f32>>,
    prone_return_pose: Option<PoseReturn>,
    prone_reload_maps: Vec<(usize, PoseReturnMap)>,
    prone_procedural_weight: f32,
    prone_visible_ads: f32,
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
    /// Read-only observer of the actual selected poses and live return target.
    /// Checksums cover poses only, not mesh/native raster parity or art quality.
    pub fn combined_observation(&self, time: f64) -> Result<serde_json::Value, String> {
        use serde_json::json;
        fn crc(pose: &ViewmodelPose) -> u32 {
            let mut bytes = Vec::new();
            for t in pose.bone_locals.iter().chain(&pose.actor_globals) {
                for n in t
                    .translation
                    .to_array()
                    .into_iter()
                    .chain(t.rotation.to_array())
                    .chain(t.scale.to_array())
                {
                    bytes.extend(n.to_bits().to_le_bytes());
                }
            }
            bytes.extend(pose.actor_visible.iter().map(|&v| u8::from(v)));
            vector_range::skinned_asset::crc32(&bytes)
        }
        fn actors(snapshot: &SourcePoseSnapshot<'_>) -> serde_json::Value {
            json!(snapshot.animation.actors().iter().enumerate().map(|(i,a)|json!({
                "name":a.name,"opacity":snapshot.actor_opacity.as_ref().map_or(f32::from(u8::from(snapshot.pose.actor_visible[i])),|o|o[i])
            })).collect::<Vec<_>>())
        }
        let high = self.high_mantle.as_ref().filter(|v| v.pose.is_some());
        let low = self.low_vault_active();
        let prone = self.prone_pose.is_some();
        let target_prone = (low || high.is_some()) && prone;
        let live = if target_prone {
            self.underlying_pose_snapshot(time, Mat4::IDENTITY)?
        } else if let Some(v) = &self.reload_presentation {
            SourcePoseSnapshot {
                animation: &self.reload_renderers[v.index].animation,
                pose: v.pose.clone(),
                root: Mat4::IDENTITY,
                actor_opacity: Some(v.opacity.clone()),
            }
        } else {
            let pose = if let Some(l) = &self.locomotion {
                l.pose().clone()
            } else {
                self.animation
                    .sample_clamped(&self.clip, self.fixed_time.unwrap_or(time as f32))
                    .map_err(|e| e.to_string())?
            };
            SourcePoseSnapshot {
                animation: &self.animation,
                pose,
                root: Mat4::IDENTITY,
                actor_opacity: None,
            }
        };
        let shown = self.source_pose_snapshot(time, Mat4::IDENTITY)?;
        let fade = if low {
            self.low_vault_return.as_ref().map(|v| &v.fade)
        } else if let Some(v) = high {
            v.fade.as_ref()
        } else if prone {
            self.prone_return_pose.as_ref()
        } else {
            None
        };
        let outgoing = fade.map(|f| {
            let (began, duration, opacity, frozen) = f.observation();
            json!({
            "began":began,"duration":duration,"weight":f.weight(time),"from_opacity":opacity,
            "frozen_pose_seconds":frozen.sample_time,"frozen_pose_crc32":crc(frozen)})
        });
        Ok(
            json!({"route":self.presentation_route(),"owners":{"high":high.is_some(),"low":low,"prone":prone},
            "high_generation":high.and_then(|v|v.generation),"low_generation":if low {self.low_vault_generation} else {None},
            "live_target":if target_prone {"prone"} else if self.reload_presentation.is_some() {"reload"} else {"base"},
            "live_target_pose_crc32":crc(&live.pose),"live_target_actors":actors(&live),
            "presented_pose_crc32":crc(&shown.pose),"presented_actors":actors(&shown),"outgoing":outgoing,
            "visual_ads":self.visual_ads_amount(),"underlying_visual_ads":self.underlying_visual_ads_amount(),
            "walk_seconds":self.walk_sample(),"walk_weight":self.walk_weight(),
            "procedural_weight":self.authored_procedural_weight(),"prone_procedural_weight":self.prone_procedural_weight(),
            "high_return_weight":self.high_mantle_return_weight(),"low_return_weight":self.low_vault_return_weight(),
            "warning":self.warning(),"renderer_failed":self.error.is_some()}),
        )
    }
    /// Distinct source and presented sample times. An outgoing pose is a live
    /// blend, so its sample_time must never be mislabeled as frozen source time.
    pub fn app_edge_high_pose_observation(&self) -> Option<serde_json::Value> {
        let visual = self.high_mantle.as_ref()?;
        let pose = visual.pose.as_ref()?;
        let source_seconds = visual
            .fade
            .as_ref()
            .map_or(pose.sample_time, |fade| fade.observation().3.sample_time);
        Some(serde_json::json!({
            "source_pose_seconds": source_seconds,
            "presented_pose_seconds": pose.sample_time,
            "mapped_target_pose_seconds": visual.mapped_target_pose_seconds,
        }))
    }
    /// Observe the actual admitted renderer/clip; never changes any motion state.
    pub fn high_candidate_observation(&self) -> Option<serde_json::Value> {
        let visual = self.high_mantle.as_ref()?;
        let renderer = self.reload_renderers.get(visual.index)?;
        let binding = self.high_mantle_binding.as_ref()?;
        Some(serde_json::json!({
            "clip": renderer.clip,
            "asset_sha256": binding.asset_sha256(),
            "receipt_sha256": binding.receipt_sha256(),
            "pose": self.app_edge_high_pose_observation(),
            "warning": renderer.warning(),
            "renderer_failed": renderer.error().is_some(),
        }))
    }
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
        if let (Some((_, renderer)), Some(pose)) = (&self.low_vault, &self.low_vault_pose) {
            return Ok(SourcePoseSnapshot {
                animation: &renderer.animation,
                pose: pose.clone(),
                root,
                actor_opacity: self.low_vault_return.as_ref().map(|v| v.opacity.clone()),
            });
        }
        if let Some(visual) = self.high_mantle.as_ref().filter(|v| v.pose.is_some()) {
            return Ok(SourcePoseSnapshot {
                animation: &self.reload_renderers[visual.index].animation,
                pose: visual.pose.as_ref().unwrap().clone(),
                root,
                actor_opacity: visual.opacity.clone(),
            });
        }
        if let (Some(index), Some(pose)) = (self.prone_index, &self.prone_pose) {
            return Ok(SourcePoseSnapshot {
                animation: &self.reload_renderers[index].animation,
                pose: pose.clone(),
                root,
                actor_opacity: self.prone_opacity.clone(),
            });
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
        Self::from_loaded(animation, skin, weapon, clip, fixed_time)
    }
    /// Construct the renderer from the exact already hash-admitted byte decode.
    fn from_loaded(
        animation: AnimationSet,
        skin: SkinnedAsset,
        weapon: vector_range::asset::WeaponAsset,
        clip: &str,
        fixed_time: Option<f32>,
    ) -> Result<Self, String> {
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
            low_vault: None,
            low_vault_pose: None,
            low_vault_return: None,
            low_vault_reload_maps: Vec::new(),
            low_vault_generation: None,
            high_mantle_binding: None,
            high_mantle: None,
            prone_index: None,
            prone_camera: None,
            prone_pose: None,
            prone_opacity: None,
            prone_return_pose: None,
            prone_reload_maps: Vec::new(),
            prone_procedural_weight: 1.,
            prone_visible_ads: 0.,
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
        let prone_error = manifest.prone_entry.as_ref().and_then(|pair| {
            model
                .install_prone(pair, &manifest.layer_anchor_actor)
                .err()
        });
        // Optional admission failure leaves all previously loaded authored paths intact.
        let high_mantle_error = manifest.high_mantle.as_ref().and_then(|reference| {
            model
                .install_high_mantle(reference, &manifest.layer_anchor_actor)
                .err()
        });
        let low_vault_error = manifest
            .low_vault
            .as_ref()
            .and_then(|reference| model.bind_low_vault(reference).err());
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
            "Authored WIP: {} clips unavailable; reload pose crossfades{}",
            missing.join(", "),
            if model.prone_index.is_some() {
                "; paired prone runtime remains opt-in WIP"
            } else {
                ""
            }
        ));
        for (route, error) in [
            ("paired prone", prone_error),
            ("low vault", low_vault_error),
            ("high mantle", high_mantle_error),
        ] {
            if let Some(error) = error {
                model.record_optional_warning(route, &error);
            }
        }
        Ok(model)
    }
    /// Stage the complete weapon/camera pair and mappings before optional admission.
    fn install_prone(
        &mut self,
        pair: &vector_range::animation_manifest::PronePairReference,
        anchor: &str,
    ) -> Result<(), String> {
        let camera = vector_range::authored_prone::ProneCameraTrack::load(
            &pair.asset,
            &pair.camera,
            &pair.receipt,
            &pair.clip,
        )?;
        let mut renderer = Self::load(
            pair.asset
                .to_str()
                .ok_or("paired prone path is not Unicode")?,
            &pair.clip,
            Some(0.),
        )?;
        let clip = renderer
            .animation
            .clips()
            .iter()
            .find(|clip| clip.name == pair.clip)
            .ok_or("missing paired prone clip")?;
        if clip.looping
            || (clip.duration() as f64 - vector_range::authored_prone::ENTRY_SECONDS).abs() > 1e-6
        {
            return Err("paired prone must be a nonlooping 68/60 second clip".into());
        }
        renderer.return_map = Some(
            PoseReturnMap::new(
                &self.animation,
                &self.skin,
                &renderer.animation,
                &renderer.skin,
                canonical_to_reload_actor_basis(),
            )
            .map_err(|e| e.to_string())?,
        );
        renderer.return_blend =
            Some(AnchoredPoseBlend::new(&renderer.animation, anchor).map_err(|e| e.to_string())?);
        let mut prone_reload_maps = Vec::new();
        // During a return this pack must be able to draw every live target actor.
        for index in self.reload_indices.into_iter().flatten() {
            if prone_reload_maps.iter().any(|(i, _)| *i == index) {
                continue;
            }
            let target = &self.reload_renderers[index];
            if target.animation.actors().iter().any(|actor| {
                !renderer
                    .animation
                    .actors()
                    .iter()
                    .any(|a| a.name == actor.name)
            }) {
                return Err("prone return pack is missing a live reload actor".into());
            }
            let map = PoseReturnMap::new(
                &target.animation,
                &target.skin,
                &renderer.animation,
                &renderer.skin,
                Mat4::IDENTITY,
            )
            .map_err(|e| e.to_string())?;
            prone_reload_maps.push((index, map));
        }
        self.prone_reload_maps = prone_reload_maps;
        self.prone_camera = Some(std::sync::Arc::new(camera));
        self.prone_index = Some(self.reload_renderers.len());
        self.reload_renderers.push(renderer);
        Ok(())
    }
    /// Complete admission and all return maps before changing any renderer state.
    fn install_high_mantle(
        &mut self,
        reference: &vector_range::animation_manifest::HighMantleReference,
        anchor: &str,
    ) -> Result<(), String> {
        let (binding, animation, skin, mesh) =
            vector_range::authored_high_mantle::HighMantleBinding::load_with_companions(
                &reference.asset,
                &reference.receipt,
                &reference.receipt_sha256,
                &reference.clip,
            )?;
        if anchor != vector_range::authored_high_mantle::ANCHOR {
            return Err("one-hand must share the live weapon anchor".into());
        }
        let mut renderer = Self::from_loaded(animation, skin, mesh, &reference.clip, Some(0.))?;
        renderer.return_map = Some(
            PoseReturnMap::new(
                &self.animation,
                &self.skin,
                &renderer.animation,
                &renderer.skin,
                canonical_to_reload_actor_basis(),
            )
            .map_err(|e| e.to_string())?,
        );
        renderer.return_blend =
            Some(AnchoredPoseBlend::new(&renderer.animation, anchor).map_err(|e| e.to_string())?);
        let mut maps = Vec::new();
        for index in self
            .reload_indices
            .into_iter()
            .flatten()
            .chain(self.prone_index)
        {
            if maps.iter().any(|(i, _)| *i == index) {
                continue;
            }
            let source = &self.reload_renderers[index];
            if source.animation.actors().iter().any(|actor| {
                !renderer
                    .animation
                    .actors()
                    .iter()
                    .any(|a| a.name == actor.name)
            }) {
                return Err("one-hand return pack is missing a live target actor".into());
            }
            maps.push((
                index,
                PoseReturnMap::new(
                    &source.animation,
                    &source.skin,
                    &renderer.animation,
                    &renderer.skin,
                    Mat4::IDENTITY,
                )
                .map_err(|e| e.to_string())?,
            ));
        }
        self.high_mantle_binding = Some(binding);
        self.high_mantle = Some(HighMantleVisual::new(self.reload_renderers.len(), maps));
        self.reload_renderers.push(renderer);
        Ok(())
    }
    pub fn bind_low_vault(
        &mut self,
        reference: &vector_range::animation_manifest::LowVaultReference,
    ) -> Result<(), String> {
        let (binding, animation, skin, weapon) =
            vector_range::authored_low_vault::LowVaultBinding::load_with_companions(
                &reference.asset,
                &reference.receipt,
                &reference.receipt_sha256,
                &reference.clip,
            )?;
        let mut renderer = Self::from_loaded(animation, skin, weapon, &reference.clip, Some(0.))?;
        let canonical_basis = if binding.uses_reload_actor_basis() {
            canonical_to_reload_actor_basis()
        } else {
            Mat4::IDENTITY
        };
        // The outgoing renderer must represent every incoming actor, including
        // reload-only props. Reject incompatible packs instead of popping them in.
        let map = |source: &Self, basis: Mat4| -> Result<PoseReturnMap, String> {
            if !source
                .animation
                .actors()
                .iter()
                .any(|actor| actor.name == binding.anchor_actor())
                || source.animation.actors().iter().any(|actor| {
                    !renderer
                        .animation
                        .actors()
                        .iter()
                        .any(|low| low.name == actor.name)
                })
            {
                return Err(
                    "low-vault return requires the shared anchor and all incoming actors".into(),
                );
            }
            PoseReturnMap::new(
                &source.animation,
                &source.skin,
                &renderer.animation,
                &renderer.skin,
                basis,
            )
            .map_err(|e| e.to_string())
        };
        let from_base = map(self, canonical_basis)?;
        let mut reload_maps = Vec::new();
        for (index, source) in self.reload_renderers.iter().enumerate() {
            reload_maps.push(
                if self.reload_indices.contains(&Some(index)) || self.prone_index == Some(index) {
                    Some(map(
                        source,
                        canonical_to_reload_actor_basis().inverse() * canonical_basis,
                    )?)
                } else {
                    None
                },
            );
        }
        renderer.return_blend = Some(
            AnchoredPoseBlend::new(&renderer.animation, binding.anchor_actor())
                .map_err(|e| e.to_string())?,
        );
        renderer.return_map = Some(from_base);
        self.low_vault = Some((binding, Box::new(renderer)));
        self.low_vault_reload_maps = reload_maps;
        self.low_vault_pose = None;
        self.low_vault_return = None;
        self.low_vault_generation = None;
        Ok(())
    }
    /// Compatibility entry point; synchronization never advances any clock.
    #[allow(dead_code)]
    pub fn synchronize_low_vault(&mut self, simulation: &vector_range::sim::Simulation) {
        self.synchronize_traversal_presentation(simulation);
    }
    fn clear_low_vault_visual(&mut self) {
        self.low_vault_pose = None;
        self.low_vault_return = None;
        self.low_vault_generation = None;
    }
    fn record_optional_warning(&mut self, route: &str, error: &str) {
        let warning = self.warning.get_or_insert_with(String::new);
        if !warning.is_empty() {
            warning.push_str("; ");
        }
        warning.push_str(&format!("{route} inactive: {error}"));
    }
    /// Remove failed optional admissions before another input can accept native
    /// traversal. Called before simulation ticks and after each observer commit.
    pub fn reconcile_simulation_bindings(&self, simulation: &mut vector_range::sim::Simulation) {
        if self.low_vault_binding().is_none() && simulation.low_vault_binding().is_some() {
            let _ = simulation.set_low_vault_binding(None);
        }
        if self.high_mantle_binding().is_none() && simulation.high_mantle_binding().is_some() {
            simulation.set_high_mantle_binding(None);
        }
        if self.prone_camera_track().is_none() {
            simulation.set_prone_camera_track(None);
        }
    }
    /// Reconcile pause, cancellation, death, reset and binding changes without
    /// render delta. Returns only target the live prone/reload/base layers.
    pub fn synchronize_traversal_presentation(
        &mut self,
        simulation: &vector_range::sim::Simulation,
    ) {
        if self.error.is_some() || simulation.player.dead() {
            self.clear_low_vault_visual();
            if let Some(visual) = &mut self.high_mantle {
                visual.clear();
            }
            let _ = self.update_prone_pose(None);
            return;
        }
        if let Err(error) = self.update_prone_presentation(simulation) {
            self.record_optional_warning("paired prone", &error);
            self.prone_camera = None;
            self.prone_index = None;
            let _ = self.update_prone_pose(None);
        }
        if let Err(error) = self.update_high_mantle_presentation(simulation) {
            self.record_optional_warning("high mantle", &error);
            self.high_mantle_binding = None;
            self.high_mantle = None;
        }
        if let Err(error) = self.update_low_vault(simulation) {
            self.record_optional_warning("low vault", &error);
            self.clear_low_vault_visual();
            self.low_vault = None;
        }
    }
    fn update_low_vault(
        &mut self,
        simulation: &vector_range::sim::Simulation,
    ) -> Result<(), String> {
        if self.low_vault_generation != Some(simulation.low_vault_generation()) {
            self.clear_low_vault_visual();
            self.low_vault_generation = Some(simulation.low_vault_generation());
        }
        if simulation.high_mantle_presentation().is_some() {
            self.clear_low_vault_visual();
            return Ok(());
        }
        if self.low_vault.is_some() && simulation.low_vault_binding() != self.low_vault_binding() {
            self.clear_low_vault_visual();
            // Explicit disable or replacement must not create a stale outgoing pose.
            if simulation.low_vault_binding().is_none() {
                return Ok(());
            }
            return Err("low-vault simulation/renderer binding mismatch".into());
        }
        if let Some(sample) = simulation.low_vault_sample() {
            let (binding, renderer) = self
                .low_vault
                .as_ref()
                .filter(|(binding, _)| simulation.low_vault_binding() == Some(binding))
                .ok_or("low-vault simulation/renderer binding mismatch")?;
            self.low_vault_pose = Some(
                renderer
                    .animation
                    .sample_clamped(binding.clip(), sample.seconds as f32)
                    .map_err(|e| e.to_string())?,
            );
            self.low_vault_return = None;
            return Ok(());
        }
        let Some(previous) = self.low_vault_pose.as_ref() else {
            return Ok(());
        };
        let (binding, renderer) = self
            .low_vault
            .as_ref()
            .ok_or("missing low-vault renderer")?;
        let underlying = self.underlying_pose_snapshot(simulation.time, Mat4::IDENTITY)?;
        let paired_index = self.prone_index.filter(|_| self.prone_pose.is_some());
        let target_index =
            paired_index.or_else(|| self.reload_presentation.as_ref().map(|v| v.index));
        let map = if let Some(index) = target_index {
            self.low_vault_reload_maps
                .get(index)
                .and_then(Option::as_ref)
                .ok_or("missing low-vault live return map")?
        } else {
            renderer
                .return_map
                .as_ref()
                .ok_or("missing low-vault base return map")?
        };
        let target = map
            .pose(
                underlying.animation,
                &renderer.animation,
                &underlying.pose,
                previous,
            )
            .map_err(|e| e.to_string())?;
        let target_opacity: Vec<f32> =
            renderer
                .animation
                .actors()
                .iter()
                .map(|actor| {
                    underlying
                        .animation
                        .actors()
                        .iter()
                        .position(|from| from.name == actor.name)
                        .map_or(0., |i| {
                            underlying.actor_opacity.as_ref().map_or(
                                f32::from(u8::from(underlying.pose.actor_visible[i])),
                                |v| v[i],
                            )
                        })
                })
                .collect();
        let visual = self.low_vault_return.get_or_insert(LowVaultReturn {
            fade: PoseReturn::with_duration(
                previous.clone(),
                previous
                    .actor_visible
                    .iter()
                    .map(|&v| f32::from(u8::from(v)))
                    .collect(),
                simulation.time,
                binding.return_seconds(),
            )
            .map_err(|e| e.to_string())?,
            weight: 0.,
            opacity: Vec::new(),
        });
        let (pose, opacity) = visual
            .fade
            .pose_with_opacity_at_weight(
                &renderer.animation,
                renderer
                    .return_blend
                    .as_ref()
                    .ok_or("missing low-vault blend")?,
                &target,
                &target_opacity,
                visual.fade.weight(simulation.time),
            )
            .map_err(|e| e.to_string())?;
        visual.weight = visual.fade.weight(simulation.time);
        visual.opacity = opacity;
        if visual.weight == 1. {
            self.low_vault_pose = None;
            self.low_vault_return = None;
        } else {
            self.low_vault_pose = Some(pose);
        }
        Ok(())
    }
    /// Procedural layers/cant return with the same committed blend weight.
    pub fn low_vault_underlying_weight(&self) -> f32 {
        if self.low_vault_active() {
            self.low_vault_return_weight().unwrap_or(0.)
        } else {
            1.
        }
    }
    pub fn low_vault_return_weight(&self) -> Option<f32> {
        self.low_vault_return.as_ref().map(|v| v.weight)
    }
    pub fn low_vault_binding(&self) -> Option<&vector_range::authored_low_vault::LowVaultBinding> {
        if self.error.is_some() {
            None
        } else {
            self.low_vault.as_ref().map(|(binding, _)| binding)
        }
    }
    pub fn low_vault_active(&self) -> bool {
        self.error.is_none() && self.low_vault_pose.is_some()
    }
    fn underlying_pose_snapshot(
        &self,
        simulation_time: f64,
        root: Mat4,
    ) -> Result<SourcePoseSnapshot<'_>, String> {
        if let (Some(index), Some(pose)) = (self.prone_index, &self.prone_pose) {
            return Ok(SourcePoseSnapshot {
                animation: &self.reload_renderers[index].animation,
                pose: pose.clone(),
                root,
                actor_opacity: self.prone_opacity.clone(),
            });
        }
        if let Some(visual) = &self.reload_presentation {
            return Ok(SourcePoseSnapshot {
                animation: &self.reload_renderers[visual.index].animation,
                pose: visual.pose.clone(),
                root,
                actor_opacity: Some(visual.opacity.clone()),
            });
        }
        let pose = if let Some(layers) = &self.locomotion {
            layers.pose().clone()
        } else {
            self.animation
                .sample_clamped(
                    &self.clip,
                    self.fixed_time.unwrap_or(simulation_time as f32),
                )
                .map_err(|e| e.to_string())?
        };
        Ok(SourcePoseSnapshot {
            animation: &self.animation,
            pose,
            root,
            actor_opacity: None,
        })
    }
    pub fn jump_sample(&self) -> Option<vector_range::authored_jump::JumpSample> {
        self.locomotion
            .as_ref()
            .and_then(LayeredLocomotion::jump_sample)
    }
    pub fn high_mantle_binding(
        &self,
    ) -> Option<vector_range::authored_high_mantle::HighMantleBinding> {
        if self.error.is_some() {
            None
        } else {
            self.high_mantle_binding.clone()
        }
    }
    pub fn prone_camera_track(
        &self,
    ) -> Option<std::sync::Arc<vector_range::authored_prone::ProneCameraTrack>> {
        if self.error.is_some() {
            None
        } else {
            self.prone_camera.clone()
        }
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
        if self.low_vault_active() {
            return self.low_vault_underlying_weight()
                * if self.prone_pose.is_some() {
                    self.prone_visible_ads
                } else {
                    self.underlying_visual_ads_amount()
                };
        }
        if let Some(visual) = self.high_mantle.as_ref().filter(|v| v.pose.is_some()) {
            return visual.visible_ads;
        }
        if self.prone_pose.is_some() {
            return self.prone_visible_ads;
        }
        self.underlying_visual_ads_amount()
    }
    fn underlying_visual_ads_amount(&self) -> f32 {
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
        if self.low_vault_active() {
            return if self.low_vault_return.is_some() {
                "low_vault.return"
            } else {
                "low_vault.low_mantle_native_wip"
            };
        }
        if let Some(visual) = self.high_mantle.as_ref().filter(|v| v.pose.is_some()) {
            return if visual.fade.is_some() {
                "high_mantle.return"
            } else {
                "high_mantle.native"
            };
        }
        if self.prone_pose.is_some() {
            return if self.prone_return_pose.is_some() {
                "prone.return"
            } else {
                "prone.entry_hold"
            };
        }
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
    pub fn authored_procedural_weight(&self) -> f32 {
        if self.low_vault_active() {
            return self.low_vault_underlying_weight()
                * if self.prone_pose.is_some() {
                    self.prone_procedural_weight
                } else {
                    1.
                };
        }
        self.high_mantle
            .as_ref()
            .filter(|v| v.pose.is_some())
            .map_or(self.prone_procedural_weight, |v| v.procedural_weight)
    }
    #[allow(dead_code)]
    pub fn high_mantle_return_weight(&self) -> Option<f32> {
        self.high_mantle
            .as_ref()
            .filter(|v| v.fade.is_some())
            .map(|v| v.return_weight)
    }
    pub fn prone_procedural_weight(&self) -> f32 {
        self.prone_procedural_weight
    }
    fn update_prone_pose(
        &mut self,
        sample: Option<vector_range::authored_prone::ProneSample>,
    ) -> Result<(), String> {
        self.prone_pose = match (self.prone_index, sample) {
            (Some(index), Some(sample)) => {
                let renderer = &self.reload_renderers[index];
                Some(
                    renderer
                        .animation
                        .sample_clamped(&renderer.clip, sample.seconds as f32)
                        .map_err(|error| error.to_string())?,
                )
            }
            _ => None,
        };
        self.prone_opacity = None;
        self.prone_return_pose = None;
        self.prone_procedural_weight = if self.prone_pose.is_some() { 0. } else { 1. };
        self.prone_visible_ads = 0.;
        Ok(())
    }
    fn update_prone_presentation(
        &mut self,
        simulation: &vector_range::sim::Simulation,
    ) -> Result<(), String> {
        if simulation.player.dead() {
            return self.update_prone_pose(None);
        }
        if let Some(sample) = simulation.prone_sample() {
            return self.update_prone_pose(Some(sample));
        }
        let (Some(index), Some(clock)) = (self.prone_index, simulation.prone_return()) else {
            return self.update_prone_pose(None);
        };
        self.update_prone_return(index, clock, simulation.time)
    }
    fn update_prone_return(
        &mut self,
        index: usize,
        clock: vector_range::authored_prone::ProneReturn,
        time: f64,
    ) -> Result<(), String> {
        if self.prone_return_pose.is_none() {
            if self.prone_pose.is_none() {
                self.update_prone_pose(Some(clock.sample))?;
            }
            let pose = self
                .prone_pose
                .as_ref()
                .ok_or("missing outgoing prone pose")?
                .clone();
            let opacity = self.prone_opacity.clone().unwrap_or_else(|| {
                pose.actor_visible
                    .iter()
                    .map(|&v| f32::from(u8::from(v)))
                    .collect()
            });
            self.prone_return_pose = Some(PoseReturn::new(pose, opacity, clock.began));
        }
        let renderer = &self.reload_renderers[index];
        let template = self
            .prone_pose
            .as_ref()
            .ok_or("missing prone return template")?;
        let (target, opacity) = if let Some(visual) = &self.reload_presentation {
            let source = &self.reload_renderers[visual.index];
            let map = &self
                .prone_reload_maps
                .iter()
                .find(|(i, _)| *i == visual.index)
                .ok_or("missing live reload to prone return map")?
                .1;
            let target = map
                .pose(
                    &source.animation,
                    &renderer.animation,
                    &visual.pose,
                    template,
                )
                .map_err(|e| e.to_string())?;
            let opacity = renderer
                .animation
                .actors()
                .iter()
                .map(|actor| {
                    source
                        .animation
                        .actors()
                        .iter()
                        .position(|a| a.name == actor.name)
                        .map_or(0., |i| visual.opacity[i])
                })
                .collect::<Vec<_>>();
            (target, opacity)
        } else {
            let live = self
                .locomotion
                .as_ref()
                .ok_or("missing live prone return target")?
                .pose();
            let target = renderer
                .return_map
                .as_ref()
                .ok_or("missing prone return map")?
                .pose(&self.animation, &renderer.animation, live, template)
                .map_err(|e| e.to_string())?;
            let opacity = target
                .actor_visible
                .iter()
                .map(|&v| f32::from(u8::from(v)))
                .collect();
            (target, opacity)
        };
        let weight = clock.weight(time);
        let (pose, opacity) = self
            .prone_return_pose
            .as_ref()
            .unwrap()
            .pose_with_opacity_at_weight(
                &renderer.animation,
                renderer
                    .return_blend
                    .as_ref()
                    .ok_or("missing prone anchor blend")?,
                &target,
                &opacity,
                weight,
            )
            .map_err(|e| e.to_string())?;
        self.prone_pose = Some(pose);
        self.prone_opacity = Some(opacity);
        self.prone_procedural_weight = weight;
        self.prone_visible_ads = self.underlying_visual_ads_amount() * weight;
        Ok(())
    }
    fn update_high_mantle_presentation(
        &mut self,
        simulation: &vector_range::sim::Simulation,
    ) -> Result<(), String> {
        let Some(mut visual) = self.high_mantle.take() else {
            return Ok(());
        };
        let result = if simulation.player.dead() || simulation.high_mantle_presentation().is_none()
        {
            visual.clear();
            Ok(())
        } else if self.high_mantle_binding.as_ref() != simulation.high_mantle_binding() {
            visual.clear();
            Err("one-hand simulation/renderer binding changed".into())
        } else {
            self.update_high_mantle_visual(
                &mut visual,
                simulation.high_mantle_presentation().unwrap(),
                simulation.time,
            )
        };
        if result.is_err() {
            visual.clear();
        }
        self.high_mantle = Some(visual);
        result
    }
    fn update_high_mantle_visual(
        &self,
        visual: &mut HighMantleVisual,
        presentation: vector_range::authored_high_mantle::HighMantlePresentation,
        time: f64,
    ) -> Result<(), String> {
        if visual.generation != Some(presentation.generation) {
            visual.clear();
            visual.generation = Some(presentation.generation);
        }
        let renderer = &self.reload_renderers[visual.index];
        let sample = || {
            renderer
                .animation
                .sample_clamped(&renderer.clip, presentation.sample.seconds as f32)
                .map_err(|e| e.to_string())
        };
        let Some(clock) = presentation.outgoing else {
            visual.pose = Some(sample()?);
            visual.opacity = None;
            visual.fade = None;
            visual.return_began = None;
            visual.mapped_target_pose_seconds = None;
            visual.return_weight = 0.;
            visual.procedural_weight = 0.;
            visual.visible_ads = 0.;
            return Ok(());
        };
        if visual.fade.is_none() || visual.return_began != Some(clock.began) {
            // A completed source must expose the native endpoint before return.
            // On cancellation preserve the last complete displayed pose once.
            if clock.completed || visual.pose.is_none() {
                visual.pose = Some(sample()?);
                visual.opacity = None;
            }
            let pose = visual.pose.as_ref().unwrap().clone();
            let opacity = visual.opacity.clone().unwrap_or_else(|| {
                pose.actor_visible
                    .iter()
                    .map(|&v| f32::from(u8::from(v)))
                    .collect()
            });
            visual.fade = Some(PoseReturn::new(pose, opacity, clock.began));
            visual.return_began = Some(clock.began);
        }
        let template = visual
            .pose
            .as_ref()
            .ok_or("missing one-hand return template")?;
        // Select the same live underlying route that drawing would expose when
        // this return is absent, including paired prone during a long return.
        let paired = self.prone_index.zip(self.prone_pose.as_ref());
        let live_target = paired
            .map(|(index, pose)| (index, pose, self.prone_opacity.as_deref()))
            .or_else(|| {
                self.reload_presentation
                    .as_ref()
                    .map(|live| (live.index, &live.pose, Some(live.opacity.as_slice())))
            });
        let (target, target_opacity) = if let Some((index, pose, opacity)) = live_target {
            let source = &self.reload_renderers[index];
            let map = &visual
                .target_maps
                .iter()
                .find(|(i, _)| *i == index)
                .ok_or("missing one-hand live target mapping")?
                .1;
            let target = map
                .pose(&source.animation, &renderer.animation, pose, template)
                .map_err(|e| e.to_string())?;
            let opacity = renderer
                .animation
                .actors()
                .iter()
                .map(|actor| {
                    source
                        .animation
                        .actors()
                        .iter()
                        .position(|a| a.name == actor.name)
                        .map_or(0., |i| {
                            opacity.map_or(f32::from(u8::from(pose.actor_visible[i])), |values| {
                                values[i]
                            })
                        })
                })
                .collect::<Vec<_>>();
            (target, opacity)
        } else {
            let live = self
                .locomotion
                .as_ref()
                .ok_or("missing live one-hand return target")?
                .pose();
            let target = renderer
                .return_map
                .as_ref()
                .ok_or("missing one-hand return mapping")?
                .pose(&self.animation, &renderer.animation, live, template)
                .map_err(|e| e.to_string())?;
            let opacity = target
                .actor_visible
                .iter()
                .map(|&v| f32::from(u8::from(v)))
                .collect();
            (target, opacity)
        };
        // Observe the existing mapped result; do not substitute or resample it.
        visual.mapped_target_pose_seconds = Some(target.sample_time);
        let weight = clock.weight(time);
        let (pose, opacity) = visual
            .fade
            .as_ref()
            .unwrap()
            .pose_with_opacity_at_weight(
                &renderer.animation,
                renderer
                    .return_blend
                    .as_ref()
                    .ok_or("missing one-hand return anchor")?,
                &target,
                &target_opacity,
                weight,
            )
            .map_err(|e| e.to_string())?;
        visual.pose = Some(pose);
        visual.opacity = Some(opacity);
        visual.return_weight = weight;
        visual.procedural_weight = weight
            * if paired.is_some() {
                self.prone_procedural_weight
            } else {
                1.
            };
        visual.visible_ads = weight
            * if paired.is_some() {
                self.prone_visible_ads
            } else {
                self.underlying_visual_ads_amount()
            };
        Ok(())
    }
    /// Exactly one committed observer, shared by real keyboard and replay input.
    pub fn committed_step(&mut self, start: f64, simulation: &vector_range::sim::Simulation) {
        if self.error.is_some() {
            return;
        }
        let previous_pose = self.locomotion.as_ref().map(|layers| layers.pose().clone());
        let previous_ads = self.underlying_visual_ads_amount();
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
        // Commit live targets first, then synchronize the exclusive traversal layer.
        self.synchronize_traversal_presentation(simulation);
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
        let (set, pose) =
            if let (Some((_, renderer)), Some(pose)) = (&self.low_vault, &self.low_vault_pose) {
                (&renderer.animation, pose)
            } else if let Some(visual) = self.high_mantle.as_ref().filter(|v| v.pose.is_some()) {
                (
                    &self.reload_renderers[visual.index].animation,
                    visual.pose.as_ref().unwrap(),
                )
            } else if let (Some(index), Some(pose)) = (self.prone_index, &self.prone_pose) {
                (&self.reload_renderers[index].animation, pose)
            } else if let Some(visual) = &self.reload_presentation {
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
        self.clear_low_vault_visual();
        if let Some(visual) = &mut self.high_mantle {
            visual.clear();
        }
        self.prone_pose = None;
        self.prone_opacity = None;
        self.prone_return_pose = None;
        self.prone_procedural_weight = 1.;
        self.prone_visible_ads = 0.;
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
            if self.low_vault_active() {
                self.record_optional_warning("low vault", &error);
                self.clear_low_vault_visual();
                self.low_vault = None;
            } else if self.high_mantle.as_ref().is_some_and(|v| v.pose.is_some()) {
                self.record_optional_warning("high mantle", &error);
                self.high_mantle = None;
                self.high_mantle_binding = None;
            } else if self.prone_pose.is_some() {
                self.record_optional_warning("paired prone", &error);
                self.prone_index = None;
                self.prone_camera = None;
                let _ = self.update_prone_pose(None);
            } else {
                eprintln!("Authored viewmodel playback failed: {error}");
                self.error = Some(error);
            }
        }
    }
    fn draw_checked(
        &mut self,
        simulation_time: f64,
        lighting: SceneLighting,
        root: Mat4,
    ) -> Result<(), String> {
        let procedural_weight = self.authored_procedural_weight();
        if let (Some((_, renderer)), Some(pose)) = (&mut self.low_vault, &self.low_vault_pose) {
            renderer.cant = self.cant * procedural_weight;
            return renderer.draw_pose_opacity(
                pose,
                lighting,
                root,
                self.low_vault_return.as_ref().map(|v| v.opacity.as_slice()),
            );
        }
        if let Some(visual) = self.high_mantle.as_ref().filter(|v| v.pose.is_some()) {
            let renderer = &mut self.reload_renderers[visual.index];
            renderer.cant = self.cant * visual.procedural_weight;
            return renderer.draw_pose_opacity(
                visual.pose.as_ref().unwrap(),
                lighting,
                root,
                visual.opacity.as_deref(),
            );
        }
        if let (Some(index), Some(pose)) = (self.prone_index, &self.prone_pose) {
            let pose = pose.clone();
            let renderer = &mut self.reload_renderers[index];
            renderer.cant = self.cant * self.prone_procedural_weight;
            return renderer.draw_pose_opacity(
                &pose,
                lighting,
                root,
                self.prone_opacity.as_deref(),
            );
        }
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
#[allow(dead_code)]
pub(crate) fn combined_replay_sim(
    binding: vector_range::authored_high_mantle::HighMantleBinding,
) -> vector_range::sim::Simulation {
    tests::combined_replay_sim(binding)
}

// The library-only admitted fixture calls this helper. The binary also
// compiles this module for tests, but cannot construct that library test binding.
#[cfg(test)]
#[allow(dead_code)]
pub(crate) fn assert_combined_admitted_sync(
    binding: vector_range::authored_high_mantle::HighMantleBinding,
) {
    tests::assert_combined_admitted_sync(binding);
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
        contact_fixture_frames(false)
    }

    fn contact_fixture_frames(animated: bool) -> AuthoredViewmodel {
        contact_fixture_duration(animated, vector_range::authored_prone::ENTRY_SECONDS)
    }

    fn contact_fixture_duration(animated: bool, duration: f64) -> AuthoredViewmodel {
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
        words(&mut payload, &[7]);
        name(&mut payload, "contact");
        let frames = if animated {
            vec![(0., 2.), (duration as f32, 3.)]
        } else {
            vec![(0., 3.)]
        };
        words(&mut payload, &[0, frames.len() as u32]); // Non-looping.
        for (time, x) in frames {
            floats(&mut payload, &[time]);
            for _ in 0..2 {
                floats(&mut payload, &[x, 0., 0., 0., 0., 0., 1., 1., 1., 1.]);
            }
            payload.push(1); // Visible actor.
        }
        for (clip, looping) in [
            ("run_in", false),
            ("run", true),
            ("bridge0", false),
            ("bridge1", false),
            ("run_out", false),
            ("settle", false),
        ] {
            name(&mut payload, clip);
            words(&mut payload, &[u32::from(looping), 2]);
            for time in [0., 0.1] {
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
            low_vault: None,
            low_vault_pose: None,
            low_vault_return: None,
            low_vault_reload_maps: Vec::new(),
            low_vault_generation: None,
            high_mantle_binding: None,
            high_mantle: None,
            prone_index: None,
            prone_camera: None,
            prone_pose: None,
            prone_opacity: None,
            prone_return_pose: None,
            prone_reload_maps: Vec::new(),
            prone_procedural_weight: 1.,
            prone_visible_ads: 0.,
            return_map: None,
            return_blend: None,
            reload_presentation: None,
            cant: 0.,
        }
    }

    #[test]
    fn candidate_observation_is_absent_without_an_admitted_binding() {
        let model = contact_fixture();
        assert!(model.high_candidate_observation().is_none());
        let (mut model, visual) = high_mantle_fixture();
        model.high_mantle = Some(visual);
        assert!(model.high_candidate_observation().is_none());
    }

    #[test]
    fn prone_outgoing_tracks_live_reload_opacity_then_live_base_without_contact_reset() {
        use vector_range::authored_locomotion_path::AuthoredLocomotionPathConfig;
        use vector_range::authored_prone::{ProneReturn, ProneSample, PRONE_EYE_HEIGHT};
        let mut model = contact_fixture();
        model.locomotion = Some(
            LayeredLocomotion::new(
                LayerSources {
                    locomotion: &model.animation,
                    walk: None,
                    ads: None,
                    jump: None,
                },
                AuthoredLocomotionPathConfig {
                    ready_clip: "contact".into(),
                    entry_clip: "run_in".into(),
                    loop_clip: "run".into(),
                    exit_bridge_clips: vec!["bridge0".into(), "bridge1".into()],
                    exit_clip: "run_out".into(),
                    settle_clip: "settle".into(),
                    rate_response_seconds: 0.05,
                    residual_decay_seconds: 0.03,
                },
                None,
                None,
                "fixture_prop",
            )
            .unwrap(),
        );
        let target = contact_fixture();
        let mut paired = contact_fixture_frames(true);
        paired.return_map = Some(
            PoseReturnMap::new(
                &model.animation,
                &model.skin,
                &paired.animation,
                &paired.skin,
                Mat4::IDENTITY,
            )
            .unwrap(),
        );
        paired.return_blend =
            Some(AnchoredPoseBlend::new(&paired.animation, "fixture_prop").unwrap());
        let map = PoseReturnMap::new(
            &target.animation,
            &target.skin,
            &paired.animation,
            &paired.skin,
            Mat4::IDENTITY,
        )
        .unwrap();
        model.reload_renderers.push(target);
        model.reload_renderers.push(paired);
        model.prone_index = Some(1);
        model.prone_reload_maps.push((0, map));
        let source = ProneSample {
            seconds: 0.3,
            frame: 19.,
            eye_height: PRONE_EYE_HEIGHT,
            orientation: Quat::from_rotation_z(0.1),
        };
        let clock = ProneReturn {
            sample: source,
            began: 4.,
            duration: 0.2,
        };
        model.update_prone_pose(Some(source)).unwrap();
        let frozen = model.prone_pose.clone().unwrap();
        let from_x = frozen.actor_globals[0].translation.x;
        for (time, x, alpha) in [(4., 5., 0.4), (4.05, 6., 0.3), (4.1, 7., 0.25)] {
            let mut target = model.reload_renderers[0]
                .animation
                .sample_clamped("contact", 0.)
                .unwrap();
            target.actor_globals[0].translation.x = x;
            target.bone_locals[0].translation.x = x;
            model.reload_presentation = Some(ReloadPresentation {
                index: 0,
                pose: target,
                opacity: vec![alpha],
                fade: None,
                outgoing: true,
                from_ads: 0.8,
                visible_ads: 0.8,
                weight: 0.2,
            });
            model.update_prone_return(1, clock, time).unwrap();
            let w = clock.weight(time);
            let snapshot = model.source_pose_snapshot(99., Mat4::IDENTITY).unwrap();
            assert!(
                (snapshot.pose.actor_globals[0].translation.x - (from_x + (x - from_x) * w)).abs()
                    < 1e-5
            );
            assert_eq!(snapshot.pose.bone_locals[0], snapshot.pose.actor_globals[0]);
            assert!((snapshot.actor_opacity.unwrap()[0] - (1. + (alpha - 1.) * w)).abs() < 1e-6);
            assert!((model.visual_ads_amount() - 0.8 * w).abs() < 1e-6);
            assert_eq!(model.prone_procedural_weight(), w);
            assert_eq!(model.presentation_route(), "prone.return");
            let before = model.prone_pose.clone();
            model.update_prone_return(1, clock, time).unwrap();
            assert_eq!(
                model.prone_pose, before,
                "pause must not advance or refreeze the source"
            );
        }
        model.reload_presentation = None;
        model.update_prone_return(1, clock, 4.15).unwrap();
        let w = clock.weight(4.15);
        assert!(
            (model.prone_pose.as_ref().unwrap().actor_globals[0]
                .translation
                .x
                - (from_x + (3. - from_x) * w))
                .abs()
                < 1e-5
        );
        model.update_prone_return(1, clock, 4.2).unwrap();
        let returned = model.prone_pose.clone().unwrap();
        assert_eq!(
            returned.bone_locals,
            model.locomotion.as_ref().unwrap().pose().bone_locals
        );
        assert_eq!(
            returned.actor_globals,
            model.locomotion.as_ref().unwrap().pose().actor_globals
        );
        model.update_prone_pose(None).unwrap();
        let live = model.source_pose_snapshot(4.2, Mat4::IDENTITY).unwrap();
        assert_eq!(live.pose.actor_globals, returned.actor_globals);
        assert_eq!(model.prone_procedural_weight(), 1.);
        model.reset(0.);
        assert!(model.prone_return_pose.is_none());
        assert!(model.prone_opacity.is_none());
    }

    #[test]
    fn fractional_pose_return_validates_opacity_and_preserves_hidden_actor_transform() {
        let model = contact_fixture();
        let mut from = model.animation.sample_clamped("contact", 0.).unwrap();
        from.actor_globals[0].translation.x = 8.;
        from.bone_locals[0].translation.x = 8.;
        let blend = AnchoredPoseBlend::new(&model.animation, "fixture_prop").unwrap();
        let fade = PoseReturn::new(from.clone(), vec![0.8], 0.);
        let mut target = model.animation.sample_clamped("contact", 0.).unwrap();
        target.actor_visible[0] = false;
        let (pose, opacity) = fade
            .pose_with_opacity_at_weight(&model.animation, &blend, &target, &[0.], 0.5)
            .unwrap();
        assert_eq!(pose.actor_globals[0], from.actor_globals[0]);
        assert!((opacity[0] - 0.4).abs() < 1e-6);
        for invalid in [vec![], vec![f32::NAN], vec![1.1], vec![-0.1], vec![0.2]] {
            assert!(fade
                .pose_with_opacity_at_weight(&model.animation, &blend, &target, &invalid, 0.5)
                .is_err());
        }
        for w in [-0.1, 1.1, f32::NAN] {
            assert!(fade
                .pose_with_opacity_at_weight(&model.animation, &blend, &target, &[0.], w)
                .is_err());
        }
    }

    #[test]
    fn paired_prone_renderer_uses_exact_committed_phase_without_entry_blend() {
        use vector_range::authored_prone::{ProneSample, ENTRY_SECONDS, PRONE_EYE_HEIGHT};
        let mut model = contact_fixture();
        model.prone_index = Some(0);
        model.reload_renderers.push(contact_fixture_frames(true));
        for frame in [1., 1.5, 2., 5., 11., 35., 69.] {
            let seconds = (frame - 1.) / 60.;
            model
                .update_prone_pose(Some(ProneSample {
                    seconds,
                    frame,
                    eye_height: PRONE_EYE_HEIGHT,
                    orientation: Quat::IDENTITY,
                }))
                .unwrap();
            let expected_x = 2. + seconds as f32 / ENTRY_SECONDS as f32;
            for render_time in [0., 10., 200.] {
                let snapshot = model
                    .source_pose_snapshot(render_time, Mat4::IDENTITY)
                    .unwrap();
                assert!((snapshot.pose.sample_time - seconds as f32).abs() < 1e-6);
                assert!((snapshot.pose.bone_locals[0].translation.x - expected_x).abs() < 1e-6);
                assert_eq!(snapshot.pose.bone_locals[0], snapshot.pose.actor_globals[0]);
                assert_eq!(snapshot.pose.actor_visible, [true]);
            }
            begin_frame(640, 480, 1.).unwrap();
            model
                .draw_checked(500., SceneLighting::range(), Mat4::IDENTITY)
                .unwrap();
            let list = take_draw_list().unwrap();
            let mesh_count = list
                .commands
                .iter()
                .filter(|command| matches!(command, Command::Mesh { .. }))
                .count();
            assert_eq!(mesh_count, 2, "one paired skin and one paired rigid actor");
        }
        model.update_prone_pose(None).unwrap();
        assert!(model.prone_pose.is_none());
        model.reset(0.);
        assert!(model.prone_pose.is_none());
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
    fn high_mantle_fixture() -> (AuthoredViewmodel, HighMantleVisual) {
        let mut model = layered_contact_fixture();
        let target = contact_fixture();
        let mut native =
            contact_fixture_duration(true, vector_range::authored_high_mantle::NATIVE_SECONDS);
        native.return_map = Some(
            PoseReturnMap::new(
                &model.animation,
                &model.skin,
                &native.animation,
                &native.skin,
                Mat4::IDENTITY,
            )
            .unwrap(),
        );
        native.return_blend =
            Some(AnchoredPoseBlend::new(&native.animation, "fixture_prop").unwrap());
        let map = PoseReturnMap::new(
            &target.animation,
            &target.skin,
            &native.animation,
            &native.skin,
            Mat4::IDENTITY,
        )
        .unwrap();
        model.reload_renderers.push(target);
        model.reload_renderers.push(native);
        (model, HighMantleVisual::new(1, vec![(0, map)]))
    }
    fn high_clock(seconds: f64) -> vector_range::authored_high_mantle::HighMantlePresentation {
        use vector_range::authored_high_mantle::{HighMantlePresentation, HighMantleSample};
        HighMantlePresentation {
            generation: 1,
            sample: HighMantleSample {
                seconds,
                source_frame: 1. + seconds * 60.,
                reference_frame: 7787. + seconds * 60.,
            },
            outgoing: None,
        }
    }
    #[test]
    fn app_edge_distinguishes_frozen_source_and_live_blend_time() {
        let (mut model, mut visual) = high_mantle_fixture();
        let mut clock = high_clock(0.45);
        model
            .update_high_mantle_visual(&mut visual, clock, 4.)
            .unwrap();
        model.high_mantle = Some(visual);
        let native = model.app_edge_high_pose_observation().unwrap();
        assert_eq!(
            native["source_pose_seconds"],
            native["presented_pose_seconds"]
        );
        assert!(native["mapped_target_pose_seconds"].is_null());
        visual = model.high_mantle.take().unwrap();
        let target = model.reload_renderers[0]
            .animation
            .sample_clamped("contact", 0.2)
            .unwrap();
        let target_seconds = target.sample_time;
        model.reload_presentation = Some(ReloadPresentation {
            index: 0,
            pose: target,
            opacity: vec![1.],
            fade: None,
            outgoing: false,
            from_ads: 0.,
            visible_ads: 0.,
            weight: 0.,
        });
        clock.outgoing = Some(vector_range::authored_high_mantle::HighMantleReturn {
            sample: clock.sample,
            began: 4.,
            duration: 0.20,
            completed: false,
        });
        let time = 4.05;
        model
            .update_high_mantle_visual(&mut visual, clock, time)
            .unwrap();
        let weight = clock.outgoing.unwrap().weight(time);
        let expected = 0.45_f32 * (1. - weight) + target_seconds * weight;
        model.high_mantle = Some(visual);
        let observed = model.app_edge_high_pose_observation().unwrap();
        assert_eq!(
            observed["source_pose_seconds"].as_f64().unwrap() as f32,
            0.45
        );
        assert_eq!(
            observed["mapped_target_pose_seconds"].as_f64().unwrap() as f32,
            target_seconds
        );
        assert_eq!(
            observed["presented_pose_seconds"].as_f64().unwrap() as f32,
            expected
        );
        assert_ne!(
            observed["source_pose_seconds"],
            observed["presented_pose_seconds"]
        );
        model.reset(0.);
        assert!(model.app_edge_high_pose_observation().is_none());
    }

    #[test]
    fn high_mantle_return_tracks_live_pose_opacity_ads_and_resets() {
        let (mut model, mut visual) = high_mantle_fixture();
        let mut clock = high_clock(0.3);
        model
            .update_high_mantle_visual(&mut visual, clock, 4.)
            .unwrap();
        let frozen = visual.pose.clone().unwrap();
        let from_x = frozen.actor_globals[0].translation.x;
        clock.outgoing = Some(vector_range::authored_high_mantle::HighMantleReturn {
            sample: clock.sample,
            began: 4.,
            duration: 0.4,
            completed: false,
        });
        for (time, x, alpha) in [(4., 5., 0.4), (4.1, 6., 0.3), (4.2, 7., 0.25)] {
            let mut target = model.reload_renderers[0]
                .animation
                .sample_clamped("contact", 0.)
                .unwrap();
            target.actor_globals[0].translation.x = x;
            target.bone_locals[0].translation.x = x;
            model.reload_presentation = Some(ReloadPresentation {
                index: 0,
                pose: target,
                opacity: vec![alpha],
                fade: None,
                outgoing: true,
                from_ads: 0.8,
                visible_ads: 0.8,
                weight: 0.2,
            });
            model
                .update_high_mantle_visual(&mut visual, clock, time)
                .unwrap();
            let w = clock.outgoing.unwrap().weight(time);
            let pose = visual.pose.as_ref().unwrap();
            assert!(
                (pose.actor_globals[0].translation.x - (from_x + (x - from_x) * w)).abs() < 1e-5
            );
            assert_eq!(pose.bone_locals[0], pose.actor_globals[0]);
            assert!((visual.opacity.as_ref().unwrap()[0] - (1. + (alpha - 1.) * w)).abs() < 1e-6);
            assert_eq!(visual.procedural_weight, w);
            assert!((visual.visible_ads - 0.8 * w).abs() < 1e-6);
            let before = visual.pose.clone();
            model
                .update_high_mantle_visual(&mut visual, clock, time)
                .unwrap();
            assert_eq!(
                before, visual.pose,
                "same committed time cannot refreeze or advance"
            );
        }
        model.reload_presentation = None;
        model
            .update_high_mantle_visual(&mut visual, clock, 4.3)
            .unwrap();
        let w = clock.outgoing.unwrap().weight(4.3);
        assert!(
            (visual.pose.as_ref().unwrap().actor_globals[0].translation.x
                - (from_x + (3. - from_x) * w))
                .abs()
                < 1e-5
        );
        model
            .update_high_mantle_visual(&mut visual, clock, 4.4)
            .unwrap();
        assert_eq!(
            visual.pose.as_ref().unwrap().bone_locals,
            model.locomotion.as_ref().unwrap().pose().bone_locals
        );
        model.high_mantle = Some(visual);
        model.reset(0.);
        let visual = model.high_mantle.as_ref().unwrap();
        assert!(visual.pose.is_none());
        assert!(visual.fade.is_none());
    }
    #[test]
    fn high_mantle_final_sample_is_retained_before_return_even_if_render_skipped() {
        let (mut model, mut visual) = high_mantle_fixture();
        model
            .update_high_mantle_visual(&mut visual, high_clock(0.1), 0.1)
            .unwrap();
        let mut completed = high_clock(vector_range::authored_high_mantle::NATIVE_SECONDS);
        completed.outgoing = Some(vector_range::authored_high_mantle::HighMantleReturn {
            sample: completed.sample,
            began: 2.,
            duration: 0.2,
            completed: true,
        });
        model
            .update_high_mantle_visual(&mut visual, completed, 2.)
            .unwrap();
        let expected = model.reload_renderers[1]
            .animation
            .sample_clamped("contact", completed.sample.seconds as f32)
            .unwrap();
        assert_eq!(
            visual.pose.as_ref().unwrap().bone_locals,
            expected.bone_locals
        );
        assert_eq!(
            visual.pose.as_ref().unwrap().actor_globals,
            expected.actor_globals
        );
        assert_eq!(visual.procedural_weight, 0.);
        model.high_mantle = Some(visual);
        let before = model.high_mantle.as_ref().unwrap().pose.clone();
        let lighting = SceneLighting {
            direction_to_light: Vec3::Y,
            ambient: 0.5,
            diffuse: 0.5,
        };
        for render_time in [2., 2., 20., 0.] {
            begin_frame(640, 480, 1.).unwrap();
            model
                .draw_checked(render_time, lighting, Mat4::IDENTITY)
                .unwrap();
            let _ = take_draw_list().unwrap();
            assert_eq!(
                model.high_mantle.as_ref().unwrap().pose,
                before,
                "render time must not own authored time"
            );
            assert_eq!(model.high_mantle_return_weight(), Some(0.));
        }
        let mut visual = model.high_mantle.take().unwrap();
        let mut restart = high_clock(0.);
        restart.generation = 2;
        model
            .update_high_mantle_visual(&mut visual, restart, 3.)
            .unwrap();
        assert!(visual.fade.is_none());
        assert_eq!(visual.pose.as_ref().unwrap().sample_time, 0.);
    }
    #[test]
    fn high_mantle_incompatible_return_rest_or_actor_mapping_fails_closed() {
        let (model, mut visual) = high_mantle_fixture();
        model
            .update_high_mantle_visual(&mut visual, high_clock(0.3), 1.)
            .unwrap();
        let mut incompatible = contact_fixture();
        incompatible.skin.bones[0].inverse_bind[12] += 1.;
        assert!(PoseReturnMap::new(
            &model.animation,
            &model.skin,
            &incompatible.animation,
            &incompatible.skin,
            Mat4::IDENTITY
        )
        .is_err());
        let (mut model, mut visual) = high_mantle_fixture();
        visual.target_maps.clear();
        let target = model.reload_renderers[0]
            .animation
            .sample_clamped("contact", 0.)
            .unwrap();
        model.reload_presentation = Some(ReloadPresentation {
            index: 0,
            pose: target,
            opacity: vec![1.],
            fade: None,
            outgoing: false,
            from_ads: 0.,
            visible_ads: 0.,
            weight: 0.,
        });
        let mut clock = high_clock(0.3);
        clock.outgoing = Some(vector_range::authored_high_mantle::HighMantleReturn {
            sample: clock.sample,
            began: 1.,
            duration: 0.2,
            completed: false,
        });
        assert!(model
            .update_high_mantle_visual(&mut visual, clock, 1.)
            .is_err());
    }
    #[test]
    fn high_mantle_unapproved_optional_pack_keeps_existing_renderer_intact() {
        use vector_range::animation_manifest::HighMantleReference;
        let mut model = layered_contact_fixture();
        let before = model.source_pose_snapshot(0., Mat4::IDENTITY).unwrap().pose;
        let reference = HighMantleReference {
            asset: "missing.vra".into(),
            receipt: "missing.json".into(),
            receipt_sha256: "1".repeat(64),
            clip: vector_range::authored_high_mantle::ACTION.into(),
        };
        let error = model
            .install_high_mantle(&reference, vector_range::authored_high_mantle::ANCHOR)
            .unwrap_err();
        assert!(error.starts_with("one-hand missing.vra: "));
        assert!(model.high_mantle_binding().is_none());
        assert!(model.high_mantle.is_none());
        assert!(model.error().is_none());
        assert_eq!(
            model.source_pose_snapshot(0., Mat4::IDENTITY).unwrap().pose,
            before
        );
    }
    #[test]
    fn high_mantle_long_return_tracks_live_paired_prone_and_nested_root_weight() {
        let (mut model, mut visual) = high_mantle_fixture();
        let paired = contact_fixture();
        let map = PoseReturnMap::new(
            &paired.animation,
            &paired.skin,
            &model.reload_renderers[1].animation,
            &model.reload_renderers[1].skin,
            Mat4::IDENTITY,
        )
        .unwrap();
        model.reload_renderers.push(paired);
        model.prone_index = Some(2);
        visual.target_maps.push((2, map));
        let mut clock = high_clock(0.3);
        model
            .update_high_mantle_visual(&mut visual, clock, 2.)
            .unwrap();
        let from_x = visual.pose.as_ref().unwrap().actor_globals[0].translation.x;
        clock.outgoing = Some(vector_range::authored_high_mantle::HighMantleReturn {
            sample: clock.sample,
            began: 2.,
            duration: 1.,
            completed: false,
        });
        for (time, x, root_weight, alpha) in [
            (2.25, 5., 0., 1.),
            (2.5, 6., 0., 0.8),
            (2.75, 7., 0.4, 0.6),
            (3., 8., 0.8, 0.4),
        ] {
            let mut pose = model.reload_renderers[2]
                .animation
                .sample_clamped("contact", 0.)
                .unwrap();
            pose.actor_globals[0].translation.x = x;
            pose.bone_locals[0].translation.x = x;
            model.prone_pose = Some(pose);
            model.prone_opacity = Some(vec![alpha]);
            model.prone_procedural_weight = root_weight;
            model.prone_visible_ads = 0.5 * root_weight;
            model
                .update_high_mantle_visual(&mut visual, clock, time)
                .unwrap();
            let w = clock.outgoing.unwrap().weight(time);
            assert!(
                (visual.pose.as_ref().unwrap().actor_globals[0].translation.x
                    - (from_x + (x - from_x) * w))
                    .abs()
                    < 1e-5
            );
            assert!((visual.opacity.as_ref().unwrap()[0] - (1. + (alpha - 1.) * w)).abs() < 1e-6);
            assert_eq!(visual.return_weight, w);
            assert_eq!(visual.procedural_weight, w * root_weight);
            assert_eq!(visual.visible_ads, w * model.prone_visible_ads);
        }
        assert_eq!(
            visual.pose.as_ref().unwrap().bone_locals,
            model.prone_pose.as_ref().unwrap().bone_locals
        );
        assert!(
            (visual.opacity.as_ref().unwrap()[0] - model.prone_opacity.as_ref().unwrap()[0]).abs()
                < 1e-6
        );
        model.high_mantle = Some(visual);
        let before = model.source_pose_snapshot(3., Mat4::IDENTITY).unwrap().pose;
        model.high_mantle.as_mut().unwrap().clear();
        let after = model.source_pose_snapshot(3., Mat4::IDENTITY).unwrap().pose;
        assert_eq!(before.bone_locals, after.bone_locals);
        assert_eq!(before.actor_globals, after.actor_globals);
        assert_eq!(
            model.authored_procedural_weight(),
            model.prone_procedural_weight()
        );
    }
    pub(super) fn combined_replay_sim(
        binding: vector_range::authored_high_mantle::HighMantleBinding,
    ) -> vector_range::sim::Simulation {
        let (mut model, _) = high_mantle_fixture();
        let mut sim = vector_range::sim::Simulation::new();
        sim.set_low_vault_binding(Some(combined_install_low(&mut model)))
            .unwrap();
        sim.set_high_mantle_binding(Some(binding));
        sim.set_prone_camera_track(Some(combined_prone_track()));
        sim
    }
    include!("../tests/support/combined_presentation_cases.rs");
}
