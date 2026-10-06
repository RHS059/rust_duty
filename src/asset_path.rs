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
    let manifest = adjacent
        .parent()
        .and_then(Path::parent)
        .unwrap_or(Path::new("."))
        .join("animations.cfg");
    if manifest.exists()
        || ["vra", "vrs", "vrm"].iter().any(|extension| {
            let path = adjacent.with_extension(extension);
            std::fs::symlink_metadata(&path).is_ok() || path.try_exists().is_err()
        })
    {
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
    use std::sync::atomic::{AtomicUsize, Ordering};

    static NEXT_TEMP_ID: AtomicUsize = AtomicUsize::new(0);

    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            Self::new_in(&std::env::temp_dir(), &NEXT_TEMP_ID)
        }

        fn new_in(root: &Path, next_id: &AtomicUsize) -> Self {
            loop {
                let path = root.join(format!(
                    "vector bundle spaces {} {}",
                    std::process::id(),
                    next_id.fetch_add(1, Ordering::Relaxed)
                ));
                // Claim a fresh directory before creating nested fixtures. An
                // existing entry may belong to another test or an earlier run.
                match std::fs::create_dir(&path) {
                    Ok(()) => {
                        let temp = Self(path);
                        std::fs::create_dir_all(temp.0.join("assets/weapons")).unwrap();
                        return temp;
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                    Err(error) => {
                        panic!("cannot create test directory {}: {error}", path.display())
                    }
                }
            }
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn temp_fixture_retries_occupied_paths_without_changing_them() {
        let root = Temp::new();
        let candidate = |id| {
            root.0
                .join(format!("vector bundle spaces {} {id}", std::process::id()))
        };
        std::fs::create_dir(candidate(0)).unwrap();
        let sentinel = candidate(0).join("owned-by-another-test");
        std::fs::write(&sentinel, b"keep directory").unwrap();
        std::fs::write(candidate(1), b"keep file").unwrap();

        let next_id = AtomicUsize::new(0);
        let temp = Temp::new_in(&root.0, &next_id);
        assert_eq!(temp.0, candidate(2));
        assert!(temp.0.join("assets/weapons").is_dir());
        drop(temp);
        assert!(!candidate(2).exists());
        assert_eq!(std::fs::read(sentinel).unwrap(), b"keep directory");
        assert_eq!(std::fs::read(candidate(1)).unwrap(), b"keep file");
    }

    #[test]
    fn temp_fixtures_are_distinct_during_parallel_allocation() {
        let root = Temp::new();
        let next_id = AtomicUsize::new(0);
        let temps = std::thread::scope(|scope| {
            let handles: Vec<_> = (0..16)
                .map(|_| scope.spawn(|| Temp::new_in(&root.0, &next_id)))
                .collect();
            handles
                .into_iter()
                .map(|handle| handle.join().unwrap())
                .collect::<Vec<_>>()
        });
        let paths: std::collections::BTreeSet<_> = temps.iter().map(|temp| &temp.0).collect();
        assert_eq!(paths.len(), 16);
        assert!(temps
            .iter()
            .all(|temp| temp.0.join("assets/weapons").is_dir()));
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
