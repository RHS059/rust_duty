//! GitHub HTTPS updater with SHA-256 verified bundles and resumable copy/add deltas.
pub mod bootstrap;
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
    io::{BufReader, Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};

pub const REPOSITORY: &str = "RHS059/rust_duty";
pub const TARGET: &str = env!("UPDATER_TARGET");
pub const MAX_ASSET: u64 = 2 * 1024 * 1024 * 1024;
pub const MAX_MANIFEST: u64 = 1024 * 1024;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error("already up to date")]
    UpToDate,
    #[error("download paused; use resume to continue")]
    Paused,
    #[error("download cancelled")]
    Cancelled,
    #[error("network stalled: {0}; partial download saved, resume to retry")]
    Network(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error("{operation} at {path}: {source}")]
    Filesystem {
        operation: &'static str,
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
pub type Result<T> = std::result::Result<T, Error>;
pub fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}

pub(crate) fn io_at(operation: &'static str, path: &Path, source: std::io::Error) -> Error {
    Error::Filesystem {
        operation,
        path: path.to_owned(),
        source,
    }
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
    let f = File::open(path).map_err(|e| io_at("open state for reading", path, e))?;
    if f.metadata()
        .map_err(|e| io_at("inspect state", path, e))?
        .len()
        > MAX_MANIFEST
    {
        return Err(invalid("oversized state file"));
    }
    // serde_json reads individual bytes; buffering avoids keeping a Windows state
    // handle open across hundreds of tiny system calls during concurrent updates.
    Ok(serde_json::from_reader(BufReader::new(f))?)
}

const REPLACE_RETRIES: usize = 100;
const REPLACE_RETRY_DELAY: Duration = Duration::from_millis(10);

fn windows_replace_contention(error: &Error) -> bool {
    match error {
        Error::Io(error) | Error::Filesystem { source: error, .. } => {
            // ERROR_ACCESS_DENIED can be a transient delete-pending race;
            // ERROR_SHARING_VIOLATION can be a reader or virus scanner's handle.
            matches!(error.raw_os_error(), Some(5 | 32))
        }
        _ => false,
    }
}

// The platform flag and injected operations are private so tests can exercise
// Windows retry/error paths deterministically on every build host.
fn persist_with_retry<P, W>(
    mut file: tempfile::NamedTempFile,
    path: &Path,
    windows: bool,
    mut persist: P,
    mut wait: W,
) -> Result<()>
where
    P: FnMut(tempfile::NamedTempFile, &Path) -> std::result::Result<File, tempfile::PersistError>,
    W: FnMut(Duration),
{
    for attempt in 0..=REPLACE_RETRIES {
        // Recheck the destination, temporary file, and all ancestors on EVERY
        // attempt. Invalid paths never become eligible by waiting or retrying.
        let checked = reject_symlink(path).and_then(|()| reject_symlink(file.path()));
        let error = if let Err(error) = checked {
            error
        } else {
            match persist(file, path) {
                Ok(_) => return Ok(()),
                Err(failure) => {
                    file = failure.file; // retain the SAME synced tempfile
                    io_at("atomically replace state", path, failure.error)
                }
            }
        };
        if !windows || !windows_replace_contention(&error) || attempt == REPLACE_RETRIES {
            return Err(error);
        }
        wait(REPLACE_RETRY_DELAY);
    }
    unreachable!("the final attempt returns its error")
}

/// Same-directory replacement preserves the previous complete file until success.
/// Only Windows access/sharing contention is retried, at most 100 times (10 ms each).
/// A permanent denial still fails closed: never delete the old file or change ACLs.
pub fn atomic_bytes(path: &Path, data: &[u8]) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("missing parent directory"))?;
    reject_symlink(parent)?;
    let mut f = tempfile::NamedTempFile::new_in(parent)
        .map_err(|e| io_at("create state tempfile", parent, e))?;
    f.write_all(data)
        .map_err(|e| io_at("write state tempfile", path, e))?;
    f.as_file()
        .sync_all()
        .map_err(|e| io_at("sync state tempfile", path, e))?;
    persist_with_retry(
        f,
        path,
        cfg!(windows),
        |file, path| file.persist(path),
        std::thread::sleep,
    )?;
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
            Err(e) => return Err(io_at("validate path metadata", ancestor, e)),
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
