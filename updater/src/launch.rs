//! Persistent per-user settings and private assets are separate from immutable release versions.
use crate::{atomic_json, invalid, read_json, Result};
use serde::{Deserialize, Serialize};
use std::path::{Component, Path, PathBuf};

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default, deny_unknown_fields)]
pub struct LaunchConfig {
    pub settings: Option<String>,
    pub weapon_asset: Option<String>,
    pub arms_asset: Option<String>,
    pub game_args: Vec<String>,
}

pub fn load(root: &Path) -> Result<LaunchConfig> {
    let path = root.join("launch.json");
    if path.exists() {
        read_json(&path)
    } else {
        Ok(LaunchConfig::default())
    }
}

pub fn save(root: &Path, config: &LaunchConfig) -> Result<()> {
    // Resolve first so malformed mappings never replace a working configuration.
    mapped_arguments(root, config, &[])?;
    atomic_json(&root.join("launch.json"), config)
}

fn absolute_data_path(root: &Path, value: &str) -> Result<PathBuf> {
    if value.is_empty() || value.contains('\0') {
        return Err(invalid("empty or invalid persistent data path"));
    }
    let input = Path::new(value);
    if !input.is_absolute()
        && input
            .components()
            .any(|c| matches!(c, Component::ParentDir | Component::Prefix(_)))
    {
        return Err(invalid("relative data mappings must stay within the install root; use an explicit absolute path for external user data"));
    }
    let resolved = if input.is_absolute() {
        input.to_path_buf()
    } else {
        root.join(input)
    };
    crate::reject_symlink(&resolved)?;
    Ok(resolved)
}

fn discover(root: &Path, candidates: &[&str]) -> Result<Option<String>> {
    for candidate in candidates {
        let path = root.join(candidate);
        if std::fs::symlink_metadata(&path).is_ok() {
            crate::reject_symlink(&path)?;
            return Ok(Some((*candidate).into()));
        }
    }
    Ok(None)
}

/// Path flags appear exactly once, as absolute paths. Per-launch path flags override
/// saved game arguments, which override named configuration mappings. Other arguments
/// retain their order and text. No user data is copied into a version or a release.
pub fn mapped_arguments(
    root: &Path,
    config: &LaunchConfig,
    per_launch: &[String],
) -> Result<Vec<String>> {
    if !root.is_absolute() {
        return Err(invalid(
            "install root must be absolute when resolving game paths",
        ));
    }
    if config.game_args.len() + per_launch.len() > 256 {
        return Err(invalid("too many game arguments"));
    }
    let mut settings = config.settings.clone();
    let mut weapon = config.weapon_asset.clone();
    let mut arms = config.arms_asset.clone();
    let mut args = Vec::new();
    for arg in config.game_args.iter().chain(per_launch) {
        if arg.len() > 32768 || arg.contains('\0') {
            return Err(invalid("invalid game argument"));
        }
        if let Some(path) = arg.strip_prefix("--settings=") {
            settings = Some(path.into());
        } else if let Some(path) = arg.strip_prefix("--weapon-asset=") {
            weapon = Some(path.into());
        } else if let Some(path) = arg.strip_prefix("--arms-asset=") {
            arms = Some(path.into());
        } else {
            args.push(arg.clone());
        }
    }
    if settings.is_none() {
        let kestrel = args
            .iter()
            .find_map(|a| a.strip_prefix("--profile="))
            .is_some_and(|p| p == "kestrel");
        settings = Some(
            if kestrel {
                "profiles/kestrel.cfg"
            } else {
                "settings.cfg"
            }
            .into(),
        );
    }
    if weapon.is_none() {
        weapon = discover(
            root,
            &[
                "private-assets/hk416a5.vrm",
                "private-assets/weapons/hk416a5.vrm",
                "assets/weapons/hk416a5.vrm",
            ],
        )?;
    }
    if arms.is_none() {
        arms = discover(
            root,
            &[
                "private-assets/fps-arms.vrs",
                "private-assets/arms/fps-arms.vrs",
                "assets/arms/fps-arms.vrs",
                // Private playable previews use this executable-relative name.
                // Keep it anchored in the stable root after adopting the launcher.
                "assets/arms/first-person.vrs",
            ],
        )?;
    }
    for (flag, value) in [
        ("--settings=", settings),
        ("--weapon-asset=", weapon),
        ("--arms-asset=", arms),
    ] {
        if let Some(value) = value {
            let resolved = absolute_data_path(root, &value)?;
            let path = resolved
                .to_str()
                .ok_or_else(|| invalid("game data path is not UTF-8"))?;
            args.push(format!("{flag}{path}"));
        }
    }
    if args.iter().map(|a| a.len() + 3).sum::<usize>() > 30_000 {
        return Err(invalid(
            "resolved game command line exceeds the portable size limit",
        ));
    }
    Ok(args)
}

/// One automatic launch per open, including a verified first installation.
/// A game exit or failed spawn cannot accidentally create an automatic relaunch loop.
#[derive(Debug)]
pub struct AutoPlayOnce {
    pending: bool,
}
impl AutoPlayOnce {
    pub fn new(requested: bool) -> Self {
        Self { pending: requested }
    }
    pub fn take_if_installed(&mut self, installed: bool) -> bool {
        if installed && self.pending {
            self.pending = false;
            true
        } else {
            false
        }
    }
    pub fn cancel(&mut self) {
        self.pending = false;
    }
}
