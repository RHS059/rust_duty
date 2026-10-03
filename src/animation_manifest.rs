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
#[derive(Clone, Debug)]
pub struct AnimationManifest {
    pub locomotion_asset: PathBuf,
    pub locomotion: AuthoredLocomotionPathConfig,
    pub tactical: ClipReference,
    pub empty: Option<ClipReference>,
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
        for slot in ["ads", "fire", "mantle"] {
            policy(&mut values, slot, "unavailable")?;
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
            empty,
        })
    }
}
