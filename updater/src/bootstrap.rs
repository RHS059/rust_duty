//! One-time adoption of an existing game folder. Private data stays in that folder.
use crate::{bundle, file_hash, install::Store, invalid, reject_symlink, Result};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::{Path, PathBuf},
};

pub const GAME_FILE: &str = if cfg!(windows) {
    "vector-range.exe"
} else {
    "vector-range"
};
pub const LAUNCHER_FILE: &str = if cfg!(windows) {
    "RustDuty.exe"
} else {
    "rust-duty-launcher"
};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Location {
    root: PathBuf,
}

fn usable_root(root: &Path) -> Result<bool> {
    reject_symlink(root)?;
    for name in ["install.json", GAME_FILE] {
        let path = root.join(name);
        reject_symlink(&path)?;
        if path.is_file() {
            return Ok(true);
        }
    }
    Ok(false)
}

/// Inspect only the executable's folder and one previously saved location.
pub fn find_root(executable: &Path, metadata_root: &Path) -> Result<Option<PathBuf>> {
    if let Some(parent) = executable.parent() {
        if usable_root(parent)? {
            return Ok(Some(parent.to_path_buf()));
        }
    }
    let location = metadata_root.join("launcher-location.json");
    reject_symlink(&location)?;
    if location.is_file() {
        let location: Location = crate::read_json(&location)?;
        if !location.root.is_absolute() {
            return Err(invalid("saved game location must be absolute"));
        }
        if usable_root(&location.root)? {
            return Ok(Some(location.root));
        }
    }
    if usable_root(metadata_root)? {
        return Ok(Some(metadata_root.to_path_buf()));
    }
    Ok(None)
}

pub fn remember_root(metadata_root: &Path, root: &Path) -> Result<()> {
    crate::safe_dir(metadata_root)?;
    crate::atomic_json(
        &metadata_root.join("launcher-location.json"),
        &Location {
            root: root.canonicalize()?,
        },
    )
}

/// Build an exact one-file baseline; never enumerate or import the asset folder.
pub fn adopt(root: &Path) -> Result<Store> {
    reject_symlink(root)?;
    let source = root.join(GAME_FILE);
    reject_symlink(&source)?;
    if !source.is_file() {
        return Err(invalid(format!(
            "Select the existing game folder containing {GAME_FILE}"
        )));
    }
    let store = Store::open(root)?;
    let _lock = store.lock()?;
    if store.state()?.active.is_some() {
        return Ok(store.clone());
    }
    let mut executable = fs::File::open(&source)?;
    let size = executable.metadata()?.len();
    let mut baseline = tempfile::NamedTempFile::new_in(store.root.join("cache"))?;
    bundle::write_single_executable(GAME_FILE, &mut executable, size, baseline.as_file_mut()).map_err(|error| {
        if matches!(error, crate::Error::Invalid(ref message) if message.contains("changed during baseline")) {
            invalid("existing game changed during adoption; close it and retry")
        } else if matches!(error, crate::Error::Invalid(ref message) if message.contains("invalid running executable")) {
            invalid("existing game executable has an invalid size")
        } else {
            error
        }
    })?;
    baseline.as_file().sync_all()?;
    store.install_local(baseline.path(), semver::Version::new(0, 0, 0), GAME_FILE)?;
    Ok(store.clone())
}

/// Install a stable launcher copy without overwriting an existing executable.
pub fn install_launcher(executable: &Path, root: &Path) -> Result<PathBuf> {
    reject_symlink(executable)?;
    let destination = root.join(LAUNCHER_FILE);
    reject_symlink(&destination)?;
    if destination.exists() {
        if executable.canonicalize()? == destination.canonicalize()?
            || file_hash(executable)? == file_hash(&destination)?
        {
            return Ok(destination);
        }
        return Err(invalid(format!("An existing launcher is already at {}. Open that launcher; bootstrap replacement is a separate action.", destination.display())));
    }
    let mut temporary = tempfile::NamedTempFile::new_in(root)?;
    let mut source = fs::File::open(executable)?;
    std::io::copy(&mut source, &mut temporary)?;
    temporary.as_file().sync_all()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        temporary
            .as_file()
            .set_permissions(fs::Permissions::from_mode(0o755))?;
    }
    temporary
        .persist_noclobber(&destination)
        .map_err(|error| error.error)?;
    crate::sync_dir(root)?;
    Ok(destination)
}

#[cfg(not(windows))]
pub fn choose_existing_root() -> Result<PathBuf> {
    Err(invalid(format!("Choose your existing game folder with: rust-duty-launcher adopt /path/to/game (containing {GAME_FILE}). For a new install use --root /path/to/install open.")))
}

#[cfg(windows)]
pub fn choose_existing_root() -> Result<PathBuf> {
    use std::{ffi::OsString, os::windows::ffi::OsStringExt, ptr};
    use windows_sys::Win32::{
        System::Com::{CoInitializeEx, CoTaskMemFree, CoUninitialize, COINIT_APARTMENTTHREADED},
        UI::Shell::{
            SHBrowseForFolderW, SHGetPathFromIDListEx, BIF_NEWDIALOGSTYLE, BIF_RETURNONLYFSDIRS,
            BROWSEINFOW,
        },
    };
    // All pointers stay valid through the blocking native dialog. The shell PIDL
    // is freed by its matching COM allocator before the apartment is released.
    unsafe {
        let initialized = CoInitializeEx(ptr::null(), COINIT_APARTMENTTHREADED as u32);
        if initialized < 0 {
            return Err(invalid(
                "Windows folder picker could not start; use RustDuty.exe adopt PATH",
            ));
        }
        let title: Vec<u16> = "Select your existing Rust Duty folder (contains vector-range.exe). Close the game first.\0".encode_utf16().collect();
        let mut display = [0u16; 260];
        let info = BROWSEINFOW {
            pszDisplayName: display.as_mut_ptr(),
            lpszTitle: title.as_ptr(),
            ulFlags: BIF_NEWDIALOGSTYLE | BIF_RETURNONLYFSDIRS,
            ..Default::default()
        };
        let selected = SHBrowseForFolderW(&info);
        if selected.is_null() {
            CoUninitialize();
            return Err(crate::Error::Cancelled);
        }
        let mut path = vec![0u16; 32768];
        let valid = SHGetPathFromIDListEx(selected, path.as_mut_ptr(), path.len() as u32, 0);
        CoTaskMemFree(selected.cast());
        CoUninitialize();
        if valid == 0 {
            return Err(invalid("Choose a normal local game folder"));
        }
        let length = path
            .iter()
            .position(|value| *value == 0)
            .ok_or_else(|| invalid("invalid selected path"))?;
        Ok(PathBuf::from(OsString::from_wide(&path[..length])))
    }
}
