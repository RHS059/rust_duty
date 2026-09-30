//! Fail-closed updater. The production trust root is deliberately unconfigured.
pub mod bundle;
pub mod delta;
pub mod download;
pub mod install;
pub mod launch;
pub mod manifest;
pub mod signing;
pub mod source;

use serde::{de::DeserializeOwned, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File},
    io::{Read, Write},
    path::Path,
};

pub const REPOSITORY: &str = "RHS059/rust_duty";
pub const TARGET: &str = env!("UPDATER_TARGET");
pub const MAX_ASSET: u64 = 2 * 1024 * 1024 * 1024;
pub const MAX_MANIFEST: u64 = 1024 * 1024;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error("production update trust is UNCONFIGURED; install a reviewed launcher with the release signing public key pinned at build time")]
    Unconfigured,
    #[error("download paused; use resume to continue")]
    Paused,
    #[error("download cancelled")]
    Cancelled,
    #[error("network stalled: {0}; partial download saved, resume to retry")]
    Network(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
pub type Result<T> = std::result::Result<T, Error>;
pub fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}

pub fn file_hash(path: &Path) -> Result<String> {
    let mut f = File::open(path)?;
    let mut hash = Sha256::new();
    let mut buf = [0; 65536];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hash.update(&buf[..n]);
    }
    Ok(hex::encode(hash.finalize()))
}
pub fn bytes_hash(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
pub fn read_json<T: DeserializeOwned>(path: &Path) -> Result<T> {
    reject_symlink(path)?;
    let f = File::open(path)?;
    if f.metadata()?.len() > MAX_MANIFEST {
        return Err(invalid("oversized state file"));
    }
    Ok(serde_json::from_reader(f)?)
}
/// Same-directory tempfile replacement is atomic on Windows and Unix. Sync data before replacement.
pub fn atomic_bytes(path: &Path, data: &[u8]) -> Result<()> {
    reject_symlink(path)?;
    let parent = path
        .parent()
        .ok_or_else(|| invalid("missing parent directory"))?;
    reject_symlink(parent)?;
    let mut f = tempfile::NamedTempFile::new_in(parent)?;
    f.write_all(data)?;
    f.as_file().sync_all()?;
    f.persist(path).map_err(|e| e.error)?;
    sync_dir(parent)?;
    Ok(())
}
pub fn atomic_json<T: Serialize>(path: &Path, data: &T) -> Result<()> {
    atomic_bytes(path, &serde_json::to_vec_pretty(data)?)
}
pub fn sync_dir(path: &Path) -> Result<()> {
    #[cfg(unix)]
    File::open(path)?.sync_all()?;
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}
pub fn reject_symlink(path: &Path) -> Result<()> {
    for ancestor in path.ancestors() {
        match fs::symlink_metadata(ancestor) {
            Ok(m) if is_link_or_reparse(&m) => {
                return Err(invalid("symlinks are not allowed in the installation path"))
            }
            Ok(_) => (),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.into()),
        }
    }
    Ok(())
}
pub fn safe_dir(path: &Path) -> Result<()> {
    reject_symlink(path)?;
    fs::create_dir_all(path)?;
    Ok(())
}

#[cfg(test)]
mod tests;

fn is_link_or_reparse(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        metadata.file_type().is_symlink()
    }
}
