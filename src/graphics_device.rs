//! Persisted, best-effort GPU identity. Never identify an adapter by list order or substring.
//! Driver versions are deliberately excluded: a driver update should not reset the choice.
use crate::{draw::BackendInfo, platform::launch::LaunchOptions};
use serde_json::{json, Value};
use std::{
    cell::RefCell,
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Fingerprint {
    pub backend: String,
    pub name: String,
    pub vendor: u32,
    pub device: u32,
    pub device_type: String,
}
impl Fingerprint {
    pub fn label(&self) -> String {
        format!("{} ({})", self.name, self.backend)
    }
    pub fn json(&self) -> Value {
        json!({"backend": self.backend, "name": self.name, "vendor_id": self.vendor,
            "device_id": self.device, "device_type": self.device_type})
    }
    fn parse(value: &Value) -> Result<Self, String> {
        let text = |key: &str| {
            value[key]
                .as_str()
                .filter(|s| !s.is_empty() && s.len() <= 512 && !s.chars().any(char::is_control))
                .map(str::to_owned)
                .ok_or_else(|| format!("invalid graphics fingerprint {key}"))
        };
        let number = |key: &str| {
            value[key]
                .as_u64()
                .and_then(|v| u32::try_from(v).ok())
                .ok_or_else(|| format!("invalid graphics fingerprint {key}"))
        };
        let result = Self {
            backend: text("backend")?,
            name: text("name")?,
            vendor: number("vendor_id")?,
            device: number("device_id")?,
            device_type: text("device_type")?,
        };
        if !matches!(result.backend.as_str(), "dx12" | "vulkan" | "metal") {
            return Err("unsupported graphics fingerprint backend".into());
        }
        Ok(result)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub enum Preference {
    #[default]
    Auto,
    Adapter(Fingerprint),
}
impl Preference {
    pub fn label(&self) -> String {
        match self {
            Self::Auto => "Auto (default launch behavior)".into(),
            Self::Adapter(id) => id.label(),
        }
    }
    pub fn json(&self) -> Value {
        match self {
            Self::Auto => Value::Null,
            Self::Adapter(id) => id.json(),
        }
    }
    pub fn load(path: &Path) -> Result<Self, String> {
        let file = match fs::File::open(path) {
            Ok(file) => file,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Self::Auto),
            Err(e) => return Err(format!("read graphics preference: {e}")),
        };
        let mut bytes = Vec::new();
        file.take(16 * 1024 + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| e.to_string())?;
        if bytes.len() > 16 * 1024 {
            return Err("graphics preference exceeds 16 KiB".into());
        }
        let value: Value = serde_json::from_slice(&bytes)
            .map_err(|e| format!("invalid graphics preference: {e}"))?;
        if value["schema"] != "rust-duty-graphics-device/v1" || value.get("adapter").is_none() {
            return Err("unsupported graphics preference schema".into());
        }
        if value["adapter"].is_null() {
            Ok(Self::Auto)
        } else {
            Ok(Self::Adapter(Fingerprint::parse(&value["adapter"])?))
        }
    }
    pub fn save(&self, path: &Path) -> Result<(), String> {
        // Prepare beside the destination; a failed write must not truncate a working preference.
        let parent = path.parent().unwrap_or(Path::new("."));
        let name = path
            .file_name()
            .ok_or("graphics preference needs a filename")?
            .to_string_lossy();
        static SEQUENCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let sequence = SEQUENCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let temporary = parent.join(format!(".{name}.{}.{sequence}.tmp", std::process::id()));
        let bytes = serde_json::to_vec_pretty(
            &json!({"schema":"rust-duty-graphics-device/v1", "adapter":self.json()}),
        )
        .map_err(|e| e.to_string())?;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|e| format!("save graphics preference: {e}"))?;
        let result = file.write_all(&bytes).and_then(|_| file.sync_all());
        drop(file);
        let result = result.and_then(|_| fs::rename(&temporary, path));
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        result.map_err(|e| format!("save graphics preference: {e}"))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Candidate {
    pub id: Fingerprint,
    pub surface_supported: bool,
}

/// Require exactly one full fingerprint, including across incompatible surfaces.
/// PCI IDs and names alone cannot distinguish two identical physical cards.
pub fn exact_match(wanted: &Fingerprint, available: &[Candidate]) -> Result<usize, String> {
    let matches: Vec<_> = available
        .iter()
        .enumerate()
        .filter(|(_, c)| c.id == *wanted)
        .collect();
    match matches.as_slice() {
        [] => Err(format!("Selected graphics device {} is missing. No fallback was used. Start with --graphics-device=auto to choose again.", wanted.label())),
        [(index, candidate)] if candidate.surface_supported => Ok(*index),
        [_] => Err(format!("Selected graphics device {} cannot present to this window. No fallback was used. Start with --graphics-device=auto to choose again.", wanted.label())),
        _ => Err(format!("Selected graphics device {} is ambiguous ({} identical fingerprints). No fallback was used. Start with --graphics-device=auto to choose again.", wanted.label(), matches.len())),
    }
}

#[derive(Clone, Debug, Default)]
pub struct Session {
    pub path: PathBuf,
    pub preference: Preference,
    pub startup_preference: Preference,
    pub candidates: Vec<Candidate>,
    pub actual: Option<BackendInfo>,
    pub evidence: Value,
    pub forced_fallback: bool,
    pub renderer_override: Option<String>,
    pub catalog_ready: bool,
    pub catalog_error: Option<String>,
}
thread_local! { static SESSION: RefCell<Session> = RefCell::new(Session::default()); }
pub fn snapshot() -> Session {
    SESSION.with(|s| s.borrow().clone())
}
pub fn initialize(session: Session) {
    SESSION.with(|s| *s.borrow_mut() = session);
}
/// Diagnostic rendering must not inherit a user's interactive adapter choice.
#[cfg(any(feature = "wgpu-runtime", test))]
pub(crate) fn device_preference(windowed: bool, force_fallback: bool) -> Preference {
    if windowed && !force_fallback {
        snapshot().startup_preference
    } else {
        Preference::Auto
    }
}

pub fn update_actual(info: BackendInfo, evidence: Value) {
    SESSION.with(|s| {
        let mut s = s.borrow_mut();
        s.actual = Some(info);
        s.evidence = evidence;
    });
}
pub fn update_catalog(candidates: Vec<Candidate>) {
    SESSION.with(|s| {
        let mut s = s.borrow_mut();
        s.candidates = candidates;
        s.catalog_ready = true;
    });
}
pub fn save_choice(preference: Preference) -> Result<(), String> {
    SESSION.with(|s| {
        let mut s = s.borrow_mut();
        if s.forced_fallback {
            return Err("Forced software validation ignores saved device choices".into());
        }
        if s.path.as_os_str().is_empty() {
            return Err("Graphics preference is unavailable in this runtime".into());
        }
        if let Preference::Adapter(id) = &preference {
            exact_match(id, &s.candidates)?;
        }
        preference.save(&s.path)?;
        s.preference = preference;
        Ok(())
    })
}

/// Parse device options separately so diagnostic renderer flags keep their existing semantics.
/// An explicit Auto is also the recovery route for a missing or malformed saved choice.
pub fn prepare_launch(args: &[String], options: &mut LaunchOptions) -> Result<Session, String> {
    let mut path = PathBuf::from("graphics-device.json");
    let mut path_set = false;
    let mut reset = false;
    let mut args = args.iter();
    while let Some(arg) = args.next() {
        if arg == "--graphics-device" || arg.starts_with("--graphics-device=") {
            let value = if arg == "--graphics-device" {
                args.next()
                    .map(String::as_str)
                    .ok_or("--graphics-device requires auto")?
            } else {
                arg.strip_prefix("--graphics-device=").unwrap()
            };
            if reset || value != "auto" {
                return Err("--graphics-device accepts auto, once; use the Graphics device menu for an exact GPU choice".into());
            }
            reset = true;
        } else if arg == "--graphics-settings" || arg.starts_with("--graphics-settings=") {
            let value = if arg == "--graphics-settings" {
                args.next()
                    .map(String::as_str)
                    .ok_or("--graphics-settings requires a path")?
            } else {
                arg.strip_prefix("--graphics-settings=").unwrap()
            };
            if path_set || value.is_empty() || value.starts_with("--") {
                return Err("--graphics-settings requires one nonempty path".into());
            }
            path = value.into();
            path_set = true;
        }
    }
    // Do not even read user preferences in forced software tests, including malformed files.
    let preference = if reset || options.force_fallback_adapter {
        Preference::Auto
    } else {
        Preference::load(&path)
            .map_err(|e| format!("{e}. Start with --graphics-device=auto to choose again."))?
    };
    let renderer_override = options.renderer.clone();
    if let Preference::Adapter(id) = &preference {
        if let Some(renderer) = &options.renderer {
            if renderer != "auto" && renderer != &id.backend {
                return Err(format!("Saved graphics device uses {}, conflicting with --renderer={renderer}. No fallback was used. Use --graphics-device=auto to honor this renderer without the saved device.", id.backend));
            }
        } else {
            // Only an explicit saved device opts into its native runtime. Auto leaves defaults unchanged.
            options.renderer = Some(id.backend.clone());
        }
    }
    Ok(Session {
        path,
        startup_preference: preference.clone(),
        preference,
        forced_fallback: options.force_fallback_adapter,
        renderer_override,
        ..Default::default()
    })
}

/// Native catalogs are already surface-checked. Legacy discovery is lazy so it cannot
/// change default startup timing or diagnostic captures, and validates presentation on restart.
pub fn ensure_catalog() {
    let state = snapshot();
    if state.catalog_ready {
        return;
    }
    if state.path.as_os_str().is_empty() {
        SESSION.with(|s| {
            let mut s = s.borrow_mut();
            s.catalog_ready = true;
            s.catalog_error =
                Some("Graphics selection is unavailable in this diagnostic runtime".into());
        });
        return;
    }
    #[cfg(feature = "wgpu-runtime")]
    {
        let state = snapshot();
        if state.renderer_override.as_deref() == Some("gl") || state.forced_fallback {
            SESSION.with(|s| {
                let mut s = s.borrow_mut();
                s.catalog_ready = true;
                s.catalog_error = Some(
                    "Explicit GL/software launch: restart without that flag to choose a GPU".into(),
                );
            });
            return;
        }
        let candidates = pollster::block_on(crate::render::device::menu_candidates());
        update_catalog(candidates);
    }
    #[cfg(not(feature = "wgpu-runtime"))]
    SESSION.with(|s| {
        let mut s = s.borrow_mut();
        s.catalog_ready = true;
        s.catalog_error =
            Some("GPU selection requires a build with the native wgpu renderer".into());
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    fn id(name: &str) -> Fingerprint {
        Fingerprint {
            backend: "dx12".into(),
            name: name.into(),
            vendor: 0x10de,
            device: 0x2208,
            device_type: "DiscreteGpu".into(),
        }
    }
    fn candidate(name: &str, supported: bool) -> Candidate {
        Candidate {
            id: id(name),
            surface_supported: supported,
        }
    }
    fn temp(name: &str) -> PathBuf {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        std::env::temp_dir().join(format!(
            "graphics-{name}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ))
    }
    #[test]
    fn device_policy_ignores_interactive_choice_for_headless_or_forced_fallback() {
        let previous = snapshot();
        let selected = Preference::Adapter(id("NVIDIA GeForce RTX 3080 Ti"));
        initialize(Session {
            startup_preference: selected.clone(),
            ..Default::default()
        });
        assert_eq!(device_preference(true, false), selected);
        for (windowed, forced) in [(false, false), (false, true), (true, true)] {
            assert_eq!(device_preference(windowed, forced), Preference::Auto);
        }
        initialize(previous);
    }
    #[test]
    fn invalid_saved_schema_or_identity_is_an_error_instead_of_auto() {
        let path = temp("invalid");
        for value in [
            json!({"schema":"rust-duty-graphics-device/v2","adapter":null}),
            json!({"schema":"rust-duty-graphics-device/v1"}),
            json!({"schema":"rust-duty-graphics-device/v1","adapter":{"backend":"dx12","name":"RTX 3080 Ti"}}),
        ] {
            fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
            assert!(Preference::load(&path).is_err());
        }
        fs::remove_file(path).unwrap();
    }
    #[test]
    fn exact_selection_rejects_substrings_missing_ambiguous_and_incompatible() {
        let wanted = id("NVIDIA GeForce RTX 3080 Ti");
        let mut candidates = vec![
            candidate("NVIDIA GeForce RTX 3080", true),
            candidate(&wanted.name, true),
        ];
        assert_eq!(exact_match(&wanted, &candidates), Ok(1));
        assert!(exact_match(&id("RTX 3080 Ti"), &candidates)
            .unwrap_err()
            .contains("missing"));
        candidates[1].surface_supported = false;
        assert!(exact_match(&wanted, &candidates)
            .unwrap_err()
            .contains("cannot present"));
        candidates.push(candidate(&wanted.name, true));
        assert!(exact_match(&wanted, &candidates)
            .unwrap_err()
            .contains("ambiguous"));
    }
    #[test]
    fn preference_round_trip_and_replacement_preserve_full_identity() {
        let path = temp("roundtrip");
        assert_eq!(Preference::load(&path).unwrap(), Preference::Auto);
        let preference = Preference::Adapter(id("NVIDIA GeForce RTX 3080 Ti"));
        preference.save(&path).unwrap();
        assert_eq!(Preference::load(&path).unwrap(), preference);
        Preference::Auto.save(&path).unwrap();
        assert_eq!(Preference::load(&path).unwrap(), Preference::Auto);
        fs::remove_file(path).unwrap();
    }
    #[test]
    fn malformed_choice_fails_closed_but_force_fallback_and_explicit_auto_ignore_it() {
        let path = temp("malformed");
        fs::write(&path, b"{bad}").unwrap();
        let args = vec![format!("--graphics-settings={}", path.display())];
        assert!(prepare_launch(&args, &mut LaunchOptions::default()).is_err());
        let mut options = LaunchOptions {
            renderer: Some("dx12".into()),
            force_fallback_adapter: true,
            ..Default::default()
        };
        let state = prepare_launch(&args, &mut options).unwrap();
        assert_eq!(state.preference, Preference::Auto);
        assert!(state.forced_fallback);
        let mut recovery = args;
        recovery.push("--graphics-device=auto".into());
        assert_eq!(
            prepare_launch(&recovery, &mut LaunchOptions::default())
                .unwrap()
                .preference,
            Preference::Auto
        );
        assert_eq!(fs::read(&path).unwrap(), b"{bad}");
        fs::remove_file(path).unwrap();
    }
    #[test]
    fn stored_gpu_opts_in_but_auto_and_renderer_overrides_preserve_launch_contract() {
        let path = temp("launch");
        let args = vec![format!("--graphics-settings={}", path.display())];
        let mut options = LaunchOptions::default();
        prepare_launch(&args, &mut options).unwrap();
        assert_eq!(
            options.runtime(true, true).unwrap(),
            crate::platform::launch::RuntimeChoice::Legacy
        );
        Preference::Adapter(id("RTX 3080 Ti")).save(&path).unwrap();
        prepare_launch(&args, &mut options).unwrap();
        assert_eq!(options.renderer.as_deref(), Some("dx12"));
        for renderer in ["vulkan", "gl"] {
            let mut conflicting = LaunchOptions {
                renderer: Some(renderer.into()),
                ..Default::default()
            };
            assert!(prepare_launch(&args, &mut conflicting)
                .unwrap_err()
                .contains("conflicting"));
            assert_eq!(conflicting.renderer.as_deref(), Some(renderer));
        }
        let mut explicit_auto = LaunchOptions {
            renderer: Some("auto".into()),
            ..Default::default()
        };
        assert!(matches!(
            prepare_launch(&args, &mut explicit_auto)
                .unwrap()
                .preference,
            Preference::Adapter(_)
        ));
        assert_eq!(explicit_auto.renderer.as_deref(), Some("auto"));
        fs::remove_file(path).unwrap();
    }
}
