use crate::{
    atomic_json, bytes_hash, file_hash, invalid, manifest::Asset, read_json, source::Source, Error,
    Result,
};
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};
const CHUNK: u64 = 1024 * 1024;

#[derive(Debug, Copy, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "snake_case")]
pub enum Control {
    #[default]
    Running,
    Paused,
    Cancelled,
}
pub fn control(root: &Path) -> Result<Control> {
    let path = root.join("control.json");
    if !path.exists() {
        return Ok(Control::Running);
    }
    read_json(&path)
}
pub fn set_control(root: &Path, value: Control) -> Result<()> {
    atomic_json(&root.join("control.json"), &value)
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Progress {
    pub phase: String,
    pub asset: Option<String>,
    pub bytes: u64,
    pub total: u64,
    pub message: String,
}
pub fn report(
    root: &Path,
    phase: &str,
    asset: Option<&Asset>,
    bytes: u64,
    message: &str,
) -> Result<()> {
    atomic_json(
        &root.join("status.json"),
        &Progress {
            phase: phase.into(),
            asset: asset.map(|a| a.name.clone()),
            bytes,
            total: asset.map_or(0, |a| a.size),
            message: message.into(),
        },
    )
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Transfer {
    asset: Asset,
    etag: Option<String>,
    bytes: u64,
    prefix_sha256: String,
}
fn strong_etag(tag: Option<&str>) -> Option<String> {
    tag.filter(|t| {
        t.len() >= 2 && t.starts_with('"') && t.ends_with('"') && !t.contains(['\r', '\n'])
    })
    .map(str::to_owned)
}
fn clear(path: &Path) -> Result<()> {
    if path.exists() {
        crate::reject_symlink(path)?;
        fs::remove_file(path)?;
    }
    Ok(())
}
pub fn cancel_partial(root: &Path) -> Result<()> {
    for item in fs::read_dir(root.join("cache"))? {
        let item = item?;
        let path = item.path();
        if matches!(
            path.extension().and_then(|s| s.to_str()),
            Some("part" | "json")
        ) {
            clear(&path)?;
        }
    }
    report(
        root,
        "cancelled",
        None,
        0,
        "Partial downloads removed; installed game unchanged",
    )
}
fn check_control(root: &Path, asset: &Asset, bytes: u64) -> Result<()> {
    match control(root)? {
        Control::Running => Ok(()),
        Control::Paused => {
            report(
                root,
                "paused",
                Some(asset),
                bytes,
                "Progress saved; resume continues from the verified checkpoint",
            )?;
            Err(Error::Paused)
        }
        Control::Cancelled => {
            cancel_partial(root)?;
            Err(Error::Cancelled)
        }
    }
}
/// A checkpoint contains the hash of the durable prefix. A torn write is truncated to that checkpoint.
/// A mismatching prefix, ETag, Content-Range, or final hash can never be used as installed content.
pub fn download(root: &Path, source: &Source, version: &Version, asset: &Asset) -> Result<PathBuf> {
    asset.validate()?;
    let cache = root.join("cache");
    crate::safe_dir(&cache)?;
    let part = cache.join(format!("{}.part", asset.sha256));
    let meta = cache.join(format!("{}.json", asset.sha256));
    let ready = cache.join(format!("{}.ready", asset.sha256));
    for path in [&part, &meta, &ready] {
        crate::reject_symlink(path)?;
    }
    check_control(root, asset, 0)?;
    if ready.exists() {
        if ready.metadata()?.len() == asset.size && file_hash(&ready)? == asset.sha256 {
            return Ok(ready);
        }
        clear(&ready)?;
    }
    let mut transfer = Transfer {
        asset: asset.clone(),
        etag: None,
        bytes: 0,
        prefix_sha256: bytes_hash(&[]),
    };
    if part.exists() && meta.exists() {
        if let Ok(saved) = read_json::<Transfer>(&meta) {
            if saved.asset == *asset
                && saved.bytes <= asset.size
                && part.metadata()?.len() >= saved.bytes
            {
                OpenOptions::new()
                    .write(true)
                    .open(&part)?
                    .set_len(saved.bytes)?;
                if file_hash(&part)? == saved.prefix_sha256
                    && (saved.bytes == 0 || saved.etag.is_some())
                {
                    transfer = saved;
                }
            }
        }
    }
    if transfer.bytes == 0 {
        clear(&part)?;
        clear(&meta)?;
    }
    let mut hash = Sha256::new();
    if transfer.bytes > 0 {
        let mut prefix = File::open(&part)?;
        let mut buf = [0; 65536];
        loop {
            let n = prefix.read(&mut buf)?;
            if n == 0 {
                break;
            }
            hash.update(&buf[..n]);
        }
    }
    let mut resets = 0;
    while transfer.bytes < asset.size {
        check_control(root, asset, transfer.bytes)?;
        report(
            root,
            "downloading",
            Some(asset),
            transfer.bytes,
            "Downloading with durable checkpoints",
        )?;
        let offset = transfer.bytes;
        let end = (offset + CHUNK - 1).min(asset.size - 1);
        let mut response = source.asset(version, asset, offset, end, transfer.etag.as_deref())?;
        let tag = strong_etag(response.headers().get("etag").and_then(|v| v.to_str().ok()));
        let status = response.status().as_u16();
        // If-Range returns 200 when the object changed. Never append that response to an old prefix.
        if offset > 0 && (status == 200 || tag != transfer.etag) {
            resets += 1;
            if resets > 2 {
                return Err(Error::Network("remote object keeps changing".into()));
            }
            clear(&part)?;
            clear(&meta)?;
            transfer.bytes = 0;
            transfer.etag = None;
            hash = Sha256::new();
            continue;
        }
        let response_size = match status {
            206 => {
                let expected = format!("bytes {offset}-{end}/{}", asset.size);
                if response
                    .headers()
                    .get("content-range")
                    .and_then(|v| v.to_str().ok())
                    != Some(expected.as_str())
                {
                    return Err(invalid("invalid Content-Range; refusing to append bytes"));
                }
                if tag.is_none() {
                    return Err(invalid(
                        "server omitted a strong ETag required for safe ranged downloads",
                    ));
                }
                end - offset + 1
            }
            200 if offset == 0 => asset.size,
            _ => return Err(Error::Network(format!("asset HTTP {status}"))),
        };
        if response
            .headers()
            .get("content-encoding")
            .is_some_and(|v| v != "identity")
        {
            return Err(invalid("encoded response cannot be resumed"));
        }
        if let Some(length) = response.content_length() {
            if length != response_size {
                return Err(invalid("response length differs from signed asset range"));
            }
        }
        transfer.etag = tag;
        // Persist the entity validator before receiving any bytes.
        atomic_json(&meta, &transfer)?;
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&part)
            .map_err(|e| crate::io_at("open partial download", &part, e))?;
        let mut remaining = response_size;
        let mut buf = [0; 65536];
        while remaining > 0 {
            check_control(root, asset, transfer.bytes)?;
            let count = (remaining as usize).min(buf.len());
            let n = response
                .read(&mut buf[..count])
                .map_err(|e| Error::Network(e.to_string()))?;
            if n == 0 {
                return Err(Error::Network(
                    "connection ended before the requested bytes arrived".into(),
                ));
            }
            file.write_all(&buf[..n])
                .map_err(|e| crate::io_at("write partial download", &part, e))?;
            file.sync_data()
                .map_err(|e| crate::io_at("sync partial download", &part, e))?;
            hash.update(&buf[..n]);
            transfer.bytes += n as u64;
            remaining -= n as u64;
            transfer.prefix_sha256 = hex::encode(hash.clone().finalize());
            atomic_json(&meta, &transfer)?;
            report(
                root,
                "downloading",
                Some(asset),
                transfer.bytes,
                "Progress saved",
            )?;
        }
        let mut tail = [0];
        if response
            .read(&mut tail)
            .map_err(|e| Error::Network(e.to_string()))?
            != 0
        {
            return Err(invalid("response has extra bytes"));
        }
    }
    check_control(root, asset, transfer.bytes)?;
    if file_hash(&part)? != asset.sha256 {
        clear(&part)?;
        clear(&meta)?;
        return Err(invalid(
            "download SHA-256 mismatch; corrupt bytes discarded",
        ));
    }
    fs::rename(&part, &ready)?;
    crate::sync_dir(&cache)?;
    clear(&meta)?;
    Ok(ready)
}
