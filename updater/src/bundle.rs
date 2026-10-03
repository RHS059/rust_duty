//! RDBND001 is a deterministic, uncompressed regular-file-only archive.
use crate::{invalid, Result, MAX_ASSET};
use std::{
    collections::HashSet,
    fs::{File, OpenOptions},
    io::Read,
    path::{Path, PathBuf},
};
pub const MAGIC: &[u8; 8] = b"RDBND001";
pub fn safe_path(value: &str) -> Result<PathBuf> {
    if value.len() > 240 || value.is_empty() || !value.is_ascii() || value.contains('\\') {
        return Err(invalid("unsafe bundle path"));
    }
    for component in value.split('/') {
        if component.is_empty()
            || component == "."
            || component == ".."
            || component.ends_with('.')
            || component.ends_with(' ')
            || !component
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._- ".contains(&b))
        {
            return Err(invalid("unsafe bundle path"));
        }
        let stem = component.split('.').next().unwrap().to_ascii_uppercase();
        if matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
            || (stem.len() == 4
                && (stem.starts_with("COM") || stem.starts_with("LPT"))
                && stem.as_bytes()[3].is_ascii_digit())
        {
            return Err(invalid("Windows device name in bundle"));
        }
    }
    if value.split('/').any(|part| {
        part.eq_ignore_ascii_case("private-assets")
            || part.eq_ignore_ascii_case(".rust-duty-updates")
            || part.eq_ignore_ascii_case("fps-arms.vrs")
            || part.eq_ignore_ascii_case("first-person.vrs")
    }) {
        return Err(invalid(
            "private asset and updater-state paths are forbidden in public update bundles",
        ));
    }
    let first = value.split('/').next().unwrap().to_ascii_lowercase();
    if matches!(
        first.as_str(),
        "settings.cfg"
            | ".rust-duty-updates"
            | "telemetry.csv"
            | "private-assets"
            | "user"
            | "userdata"
            | "saves"
            | "cache"
            | "versions"
            | "install.json"
            | "control.json"
            | "payload.rdb"
            | "version.json"
            | "launcher.lock"
            | "manifest.cache.json"
            | "status.json"
            | "launch.json"
            | "launcher-location.json"
    ) {
        return Err(invalid("bundle contains protected user/install data"));
    }
    Ok(PathBuf::from(value))
}
pub fn unpack(bundle: &Path, destination: &Path, entrypoint: &str) -> Result<()> {
    crate::reject_symlink(destination)?;
    let mut input = File::open(bundle)?;
    let length = input.metadata()?.len();
    if length > MAX_ASSET {
        return Err(invalid("oversized bundle"));
    }
    let mut magic = [0; 8];
    input.read_exact(&mut magic)?;
    if &magic != MAGIC {
        return Err(invalid("invalid bundle magic"));
    }
    let mut n = [0; 4];
    input.read_exact(&mut n)?;
    let count = u32::from_le_bytes(n);
    if count == 0 || count > 50_000 {
        return Err(invalid("invalid bundle file count"));
    }
    let mut seen = HashSet::new();
    let mut total = 0u64;
    let mut buffer = [0; 65536];
    let mut has_entry = false;
    for _ in 0..count {
        let mut n = [0; 2];
        input.read_exact(&mut n)?;
        let n = u16::from_le_bytes(n) as usize;
        if n == 0 || n > 240 {
            return Err(invalid("unsafe path length"));
        }
        let mut path = vec![0; n];
        input.read_exact(&mut path)?;
        let path = String::from_utf8(path).map_err(|_| invalid("non-UTF8 bundle path"))?;
        let relative = safe_path(&path)?;
        if !seen.insert(path.to_ascii_lowercase()) {
            return Err(invalid("duplicate/case-colliding bundle paths"));
        }
        let mut mode = [0];
        input.read_exact(&mut mode)?;
        if mode[0] > 1 {
            return Err(invalid("unsupported bundle file type/mode"));
        }
        let mut size = [0; 8];
        input.read_exact(&mut size)?;
        let size = u64::from_le_bytes(size);
        total = total
            .checked_add(size)
            .ok_or_else(|| invalid("bundle overflow"))?;
        if total > length {
            return Err(invalid("bundle declared size overflow"));
        }
        let target = destination.join(relative);
        crate::safe_dir(target.parent().unwrap())?;
        crate::reject_symlink(&target)?;
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&target)?;
        crate::delta::copy_exact(&mut input, &mut output, size, &mut buffer)?;
        output.sync_all()?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(
                &target,
                std::fs::Permissions::from_mode(if mode[0] == 1 { 0o755 } else { 0o644 }),
            )?;
        }
        if path == entrypoint {
            has_entry = true;
            if mode[0] != 1 {
                return Err(invalid("entrypoint must be executable"));
            }
        }
    }
    let mut tail = [0];
    if !has_entry || input.read(&mut tail)? != 0 {
        return Err(invalid("missing entrypoint or trailing bundle data"));
    }
    crate::sync_dir(destination)?;
    Ok(())
}
