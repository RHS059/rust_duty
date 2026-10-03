//! Stable semantic animation slots. Asset revisions change this file's data, not input wiring.
use crate::authored_locomotion_path::AuthoredLocomotionPathConfig;
use std::{
    collections::BTreeMap,
    path::{Component, Path, PathBuf},
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClipReference {
    pub asset: PathBuf,
    pub clip: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DirectionalWalkClips {
    pub forward: String,
    pub backward: String,
    pub left: String,
    pub right: String,
}
impl DirectionalWalkClips {
    pub fn names(&self) -> [&str; 4] {
        [&self.forward, &self.backward, &self.left, &self.right]
    }
}
#[derive(Clone, Debug)]
pub struct AdsReference {
    pub asset: PathBuf,
    pub entry_clip: String,
    pub hold_clip: String,
    pub exit_clip: String,
}
#[derive(Clone, Debug)]
pub struct AnimationManifest {
    pub locomotion_asset: PathBuf,
    pub locomotion: AuthoredLocomotionPathConfig,
    pub tactical: ClipReference,
    pub regular_walk: Option<ClipReference>,
    pub directional_walk: Option<DirectionalWalkClips>,
    pub walk_anchor_actor: Option<String>,
    pub layer_anchor_actor: String,
    pub empty: Option<ClipReference>,
    pub ads: Option<AdsReference>,
    pub receiver_ads_wip: bool,
    pub ads_visual_transition_seconds: Option<f64>,
}
impl AnimationManifest {
    pub fn load(path: &Path) -> Result<Self, String> {
        let text = std::fs::read_to_string(path)
            .map_err(|error| format!("animation manifest {}: {error}", path.display()))?;
        Self::parse(&text, path.parent().unwrap_or(Path::new(".")))
    }
    pub fn parse(text: &str, directory: &Path) -> Result<Self, String> {
        let mut values = BTreeMap::new();
        for (line, value) in text.lines().enumerate() {
            let value = value.trim();
            if value.is_empty() || value.starts_with('#') {
                continue;
            }
            let (key, value) = value
                .split_once('=')
                .ok_or_else(|| format!("animation manifest line {} needs key=value", line + 1))?;
            if value.trim().is_empty()
                || values
                    .insert(key.trim().to_owned(), value.trim().to_owned())
                    .is_some()
            {
                return Err(format!("empty or duplicate animation slot: {}", key.trim()));
            }
        }
        fn take(values: &mut BTreeMap<String, String>, key: &str) -> Result<String, String> {
            values
                .remove(key)
                .ok_or_else(|| format!("missing required animation slot: {key}"))
        }
        fn policy(
            values: &mut BTreeMap<String, String>,
            key: &str,
            expected: &str,
        ) -> Result<(), String> {
            if take(values, key)? != expected {
                return Err(format!("{key} must be {expected}"));
            }
            Ok(())
        }
        fn asset(
            values: &mut BTreeMap<String, String>,
            key: &str,
            directory: &Path,
        ) -> Result<PathBuf, String> {
            let raw = take(values, key)?;
            let relative = Path::new(&raw);
            if relative.is_absolute()
                || raw.contains('\\')
                || raw.contains(':')
                || relative
                    .components()
                    .any(|part| !matches!(part, Component::Normal(_)))
            {
                return Err(format!("{key} must be a safe manifest-relative path"));
            }
            Ok(directory.join(relative))
        }
        fn reference(
            values: &mut BTreeMap<String, String>,
            slot: &str,
            directory: &Path,
        ) -> Result<ClipReference, String> {
            Ok(ClipReference {
                asset: asset(values, &format!("{slot}.asset"), directory)?,
                clip: take(values, &format!("{slot}.clip"))?,
            })
        }
        policy(&mut values, "schema", "rust-duty-animation-slots/v1")?;
        // Separate rigs are never blended. Native time is never scaled to weapon stats.
        policy(&mut values, "reload.route", "whole_model_cut")?;
        policy(&mut values, "reload.clock", "native_complete")?;
        for slot in ["fire", "mantle"] {
            policy(&mut values, slot, "unavailable")?;
        }
        let ads = if values.contains_key("ads") {
            policy(&mut values, "ads", "unavailable")?;
            None
        } else {
            policy(&mut values, "ads.clock", "native_reversible")?;
            Some(AdsReference {
                asset: asset(&mut values, "ads.asset", directory)?,
                entry_clip: take(&mut values, "ads.entry.clip")?,
                hold_clip: take(&mut values, "ads.hold.clip")?,
                exit_clip: take(&mut values, "ads.exit.clip")?,
            })
        };
        let receiver_ads_wip = match values.remove("layers.ads_walk").as_deref() {
            None | Some("optical_projection") => false,
            Some("receiver_v4_wip") => true,
            _ => return Err("unsupported ADS walk layer policy".into()),
        };
        let ads_visual_transition_seconds = values
            .remove("ads.visual_transition_seconds")
            .map(|value| {
                value
                    .parse::<f64>()
                    .map_err(|_| "invalid ADS visual transition duration")
            })
            .transpose()?;
        if ads_visual_transition_seconds
            .is_some_and(|value| !value.is_finite() || value <= 0. || value > 2.)
        {
            return Err("ADS visual duration outside (0,2]".into());
        }
        let locomotion_asset = asset(&mut values, "locomotion.asset", directory)?;
        let locomotion = AuthoredLocomotionPathConfig {
            ready_clip: take(&mut values, "ready.clip")?,
            entry_clip: take(&mut values, "sprint.entry.clip")?,
            loop_clip: take(&mut values, "sprint.loop.clip")?,
            exit_bridge_clips: take(&mut values, "sprint.bridges")?
                .split(',')
                .map(|name| name.trim().to_owned())
                .collect(),
            exit_clip: take(&mut values, "sprint.exit.clip")?,
            settle_clip: take(&mut values, "sprint.settle.clip")?,
            rate_response_seconds: take(&mut values, "sprint.response_seconds")?
                .parse()
                .map_err(|_| "invalid sprint.response_seconds")?,
            residual_decay_seconds: take(&mut values, "sprint.residual_seconds")?
                .parse()
                .map_err(|_| "invalid sprint.residual_seconds")?,
        };
        let regular_walk = if values.contains_key("regular_walk") {
            policy(&mut values, "regular_walk", "unavailable")?;
            None
        } else {
            Some(reference(&mut values, "regular_walk", directory)?)
        };
        let directional_walk = if values
            .keys()
            .any(|key| key.starts_with("regular_walk.direction."))
        {
            if regular_walk.is_none() {
                return Err("directional walk requires a regular walk source".into());
            }
            Some(DirectionalWalkClips {
                forward: take(&mut values, "regular_walk.direction.forward")?,
                backward: take(&mut values, "regular_walk.direction.backward")?,
                left: take(&mut values, "regular_walk.direction.left")?,
                right: take(&mut values, "regular_walk.direction.right")?,
            })
        } else {
            None
        };
        let walk_anchor_actor = if regular_walk.is_some() {
            Some(take(&mut values, "regular_walk.anchor_actor")?)
        } else {
            None
        };
        let layer_anchor_actor = values
            .remove("layers.anchor_actor")
            .or_else(|| walk_anchor_actor.clone())
            .ok_or("missing required animation slot: layers.anchor_actor")?;
        let tactical = reference(&mut values, "reload.tactical", directory)?;
        let empty = if values.contains_key("reload.empty") {
            policy(&mut values, "reload.empty", "unavailable")?;
            None
        } else {
            Some(reference(&mut values, "reload.empty", directory)?)
        };
        if !values.is_empty() {
            return Err(format!("unknown animation slots: {:?}", values.keys()));
        }
        Ok(Self {
            locomotion_asset,
            locomotion,
            tactical,
            regular_walk,
            directional_walk,
            walk_anchor_actor,
            layer_anchor_actor,
            empty,
            ads,
            receiver_ads_wip,
            ads_visual_transition_seconds,
        })
    }
}
