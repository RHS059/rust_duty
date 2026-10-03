//! Resolve packaged assets relative to the executable, never to an incidental CWD.
use crate::asset::{AssetError, WeaponAsset};
use std::path::{Path, PathBuf};
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WeaponSource {
    Procedural,
    External(PathBuf),
    Embedded,
    Missing(PathBuf),
}
pub fn resolve_weapon(
    executable: &Path,
    explicit: Option<&Path>,
    procedural: bool,
    embedded: bool,
) -> WeaponSource {
    if procedural {
        return WeaponSource::Procedural;
    }
    if let Some(path) = explicit {
        return WeaponSource::External(path.to_owned());
    }
    let adjacent = executable
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("assets/weapons/hk416a5.vrm");
    // A malformed/inaccessible entry is not treated as an absent model: loading
    // it must produce an actionable error rather than silently hiding corruption.
    if std::fs::symlink_metadata(&adjacent).is_ok() || adjacent.try_exists().is_err() {
        WeaponSource::External(adjacent)
    } else if embedded {
        WeaponSource::Embedded
    } else {
        WeaponSource::Missing(adjacent)
    }
}
/// Prefer an explicitly selected viewmodel; otherwise discover the private
/// locomotion pack beside the game. An incomplete pack is selected too so the
/// loader reports the missing companion instead of silently using the old rig.
pub fn resolve_viewmodel(
    executable: &Path,
    explicit: Option<&Path>,
    explicit_legacy: bool,
) -> Option<PathBuf> {
    if let Some(path) = explicit {
        return Some(path.to_owned());
    }
    if explicit_legacy {
        return None;
    }
    let adjacent = executable
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("assets/locomotion/asset.vra");
    let manifest = adjacent.parent().and_then(Path::parent).unwrap_or(Path::new(".")).join("animations.cfg");
    if manifest.exists() || ["vra", "vrs", "vrm"].iter().any(|extension| {
        let path = adjacent.with_extension(extension);
        std::fs::symlink_metadata(&path).is_ok() || path.try_exists().is_err()
    }) {
        Some(adjacent)
    } else {
        None
    }
}

pub fn load_weapon(
    source: &WeaponSource,
    embedded: Option<&[u8]>,
) -> Result<Option<WeaponAsset>, AssetError> {
    match source {
        WeaponSource::Procedural | WeaponSource::Missing(_) => Ok(None),
        WeaponSource::External(path) => WeaponAsset::load(path).map(Some),
        WeaponSource::Embedded => WeaponAsset::decode(
            embedded.ok_or_else(|| AssetError("Embedded model is unavailable".into()))?,
        )
        .map(Some),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "vector bundle spaces {} {}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            std::fs::create_dir_all(path.join("assets/weapons")).unwrap();
            Self(path)
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    #[test]
    fn locomotion_pack_is_discovered_next_to_executable() {
        let temp = Temp::new();
        let model = temp.0.join("assets/locomotion/asset.vra");
        std::fs::create_dir_all(model.parent().unwrap()).unwrap();
        let exe = temp.0.join("vector-range.exe");
        assert_eq!(resolve_viewmodel(&exe, None, false), None);
        // A partial installation must be reported by the loader, not hidden.
        std::fs::write(model.with_extension("vrs"), b"fixture").unwrap();
        assert_eq!(resolve_viewmodel(&exe, None, false), Some(model.clone()));
        std::fs::write(&model, b"fixture").unwrap();
        std::fs::write(model.with_extension("vrm"), b"fixture").unwrap();
        assert_eq!(resolve_viewmodel(&exe, None, false), Some(model));
        assert_eq!(resolve_viewmodel(&exe, None, true), None);
        let explicit = Path::new("custom/view.vra");
        assert_eq!(
            resolve_viewmodel(&exe, Some(explicit), true),
            Some(explicit.to_owned())
        );
    }

    #[test]
    fn finds_model_next_to_exe_even_with_spaces_and_unrelated_working_directory() {
        let temp = Temp::new();
        let model = temp.0.join("assets/weapons/hk416a5.vrm");
        std::fs::write(&model, include_bytes!("../tests/fixtures/triangle.vrm")).unwrap();
        let source = resolve_weapon(&temp.0.join("vector-range.exe"), None, false, false);
        assert_eq!(source, WeaponSource::External(model));
        assert_eq!(load_weapon(&source, None).unwrap().unwrap().meshes.len(), 1);
    }
    #[test]
    fn bundled_model_wins_over_embedded_model() {
        let temp = Temp::new();
        let p = temp.0.join("assets/weapons/hk416a5.vrm");
        std::fs::write(&p, b"bad").unwrap();
        assert_eq!(
            resolve_weapon(&temp.0.join("game.exe"), None, false, true),
            WeaponSource::External(p)
        );
    }
    #[test]
    fn corrupt_packaged_model_is_an_error_not_silent_fallback() {
        let temp = Temp::new();
        let p = temp.0.join("assets/weapons/hk416a5.vrm");
        std::fs::write(&p, b"bad").unwrap();
        let source = resolve_weapon(&temp.0.join("game.exe"), None, false, true);
        assert!(load_weapon(
            &source,
            Some(include_bytes!("../tests/fixtures/triangle.vrm"))
        )
        .is_err());
    }
    #[test]
    fn missing_asset_reports_expected_path() {
        let temp = Temp::new();
        assert_eq!(
            resolve_weapon(&temp.0.join("game.exe"), None, false, false),
            WeaponSource::Missing(temp.0.join("assets/weapons/hk416a5.vrm"))
        );
    }
    #[test]
    fn embedded_used_when_no_sidecar() {
        let temp = Temp::new();
        assert_eq!(
            resolve_weapon(&temp.0.join("game.exe"), None, false, true),
            WeaponSource::Embedded
        );
    }
    #[test]
    fn explicit_override_and_procedural_switch_are_respected() {
        let exe = Path::new("some/game.exe");
        let p = Path::new("my/model.vrm");
        assert_eq!(
            resolve_weapon(exe, Some(p), false, true),
            WeaponSource::External(p.into())
        );
        assert_eq!(
            resolve_weapon(exe, Some(p), true, true),
            WeaponSource::Procedural
        );
    }
    #[test]
    fn a_directory_in_place_of_asset_is_reported_as_invalid() {
        let temp = Temp::new();
        let p = temp.0.join("assets/weapons/hk416a5.vrm");
        std::fs::create_dir(&p).unwrap();
        let s = resolve_weapon(&temp.0.join("game.exe"), None, false, false);
        assert!(load_weapon(&s, None).is_err());
    }
}
