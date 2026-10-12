//! Local, exclusive per-session exports. No network or automatic sharing.
use serde_json::{json, Value};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

pub const CSV_HEADER: &str = "time,x,y,z,speed,grounded,crouched,sprinting,ads,recoil_pitch_deg,ammo,shots,hits,kills,render_fps\n";
const GUIDE: &str = "LOCAL PLAYTEST SESSION\n\nThis folder is saved only on this computer. Nothing is uploaded.\nKeep gameplay.csv, frames.json (when available), IDENTITY.json, CSV_STATUS.json and all GPU files together.\nframes.json contains its own complete/incomplete status; a missing or partial file is not a successful frame export.\nCPU present-return intervals are not GPU time or proof of performance, visual quality, or hardware.\ngpu.jsonl contains 1-second Windows GPU engine occupancy and memory samples when supported, on both renderers. GPU_METADATA.json explains scope, adapter identity and unavailable values. GPU_STATUS.json is written asynchronously after stopping; wait for it and inspect its state before sharing. Missing/partial status is not a completed GPU export. GPU engine occupancy is not shader occupancy or GPU frame time. Windows adapter LUIDs are not automatically bound to the renderer adapter name.\nThe compatibility telemetry.csv beside the game is overwritten on each new recording; this session folder is never overwritten.\n\nOBSERVATIONS TO ADD BEFORE SHARING\nTester/date/time zone:\nMachine/CPU/GPU/driver/OS:\nDisplay resolution/scale/refresh rate:\nScene and actions performed:\nVisible glitches or input/animation problems and when they occurred:\nAudio behavior:\nFiles missing or export errors:\n\nReview this folder before manually sharing it. Add only information you intend to share.\nAfter stopping, open telemetry-sessions beside the game in File Explorer. Zip this entire session folder and manually attach the ZIP when reporting. Keep all files together, including incomplete/error evidence.\n";

fn write_new(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

/// Only whitelisted source fields from metadata bound to the actual executable
/// hash and embedded label are retained. Arbitrary paths/CLI/user data are not.
pub fn packaged_source(executable: &Path, label: &str, sha256: Option<&str>) -> Value {
    let result = (|| -> io::Result<Value> {
        let path = executable
            .parent()
            .unwrap_or(Path::new("."))
            .join("BUILD_IDENTITY.json");
        let meta = fs::symlink_metadata(&path)?;
        if !meta.is_file() || meta.file_type().is_symlink() || meta.len() > 16 * 1024 {
            return Err(io::Error::other("unsafe or oversized BUILD_IDENTITY.json"));
        }
        let mut bytes = Vec::new();
        File::open(path)?
            .take(16 * 1024 + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() > 16 * 1024 {
            return Err(io::Error::other("oversized BUILD_IDENTITY.json"));
        }
        let row: Value = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if row["schema"] != "rust-duty-build-identity/v1"
            || row["display_version"] != label
            || sha256.is_none()
            || row["executable"]["sha256"].as_str() != sha256
        {
            return Err(io::Error::other(
                "packaged identity does not match this executable",
            ));
        }
        let source = &row["source"];
        let commit = source["commit"].as_str().unwrap_or("");
        if commit.len() != 40 || !commit.bytes().all(|c| c.is_ascii_hexdigit()) {
            return Err(io::Error::other(
                "packaged source commit is missing or invalid",
            ));
        }
        Ok(
            json!({"state":"bound_to_executable_hash_and_label", "commit":commit,
            "branch":source["branch"].as_str(), "run_id":source["run_id"].as_u64(),
            "run_attempt":source["run_attempt"].as_u64(), "run_url":source["run_url"].as_str()}),
        )
    })();
    result.unwrap_or_else(|error| json!({"state":"unavailable", "error":error.to_string()}))
}

pub struct LocalExport {
    pub directory: PathBuf,
    csv: File,
    compatibility: File,
    failure: Option<String>,
    finalized: bool,
    gpu: Option<vector_range::gpu_telemetry::Recorder>,
    gpu_start_error: Option<String>,
}
impl LocalExport {
    pub fn start(parent: &Path, compatibility: &Path, identity: &Value) -> io::Result<Self> {
        if fs::symlink_metadata(compatibility).is_ok_and(|m| m.file_type().is_symlink()) {
            return Err(io::Error::other("telemetry.csv must not be a symlink"));
        }
        match fs::symlink_metadata(parent) {
            Ok(meta) if !meta.is_dir() || meta.file_type().is_symlink() => {
                return Err(io::Error::other(
                    "session output root must be a real directory",
                ));
            }
            Ok(_) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => fs::create_dir(parent)?,
            Err(error) => return Err(error),
        }
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let epoch = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_millis();
        let mut selected = None;
        for _ in 0..1024 {
            let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
            let path = parent.join(format!("session-{epoch}-{}-{sequence}", std::process::id()));
            match fs::create_dir(&path) {
                Ok(()) => {
                    selected = Some(path);
                    break;
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(error),
            }
        }
        let directory = selected.ok_or_else(|| io::Error::other("no unused session directory"))?;
        write_new(
            &directory.join("IDENTITY.json"),
            &serde_json::to_vec_pretty(identity).map_err(io::Error::other)?,
        )?;
        write_new(&directory.join("OBSERVATIONS.txt"), GUIDE.as_bytes())?;
        let mut csv = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join("gameplay.csv"))?;
        csv.write_all(CSV_HEADER.as_bytes())?;
        let mut compatibility = File::create(compatibility)?;
        compatibility.write_all(CSV_HEADER.as_bytes())?;
        let (gpu, gpu_start_error) = match vector_range::gpu_telemetry::Recorder::start(
            &directory,
            identity["runtime_observed"].clone(),
        ) {
            Ok(recorder) => (Some(recorder), None),
            Err(error) => {
                let error = error.to_string();
                eprintln!("GPU telemetry could not start: {error}");
                (None, Some(error))
            }
        };
        Ok(Self {
            directory,
            csv,
            compatibility,
            failure: None,
            finalized: false,
            gpu,
            gpu_start_error,
        })
    }
    pub fn frame_path(&self) -> PathBuf {
        self.directory.join("frames.json")
    }
    pub fn error(&self) -> Option<&str> {
        self.failure.as_deref()
    }
    fn status(&self, state: &str) -> io::Result<()> {
        write_new(&self.directory.join("CSV_STATUS.json"), &serde_json::to_vec_pretty(
            &json!({"schema":"rust-duty-local-csv-status/v1", "state":state,
                "error":self.failure, "gpu_start_error":self.gpu_start_error,
                "gpu_trace":"Check GPU_STATUS.json independently; GPU sampling stops asynchronously. Missing/partial status is not completion.", "frame_trace":"Check frames.json independently; CSV status is not frame completion."})
        ).map_err(io::Error::other)?)
    }
    pub fn finish(mut self) -> Result<PathBuf, String> {
        if let Some(gpu) = &mut self.gpu {
            gpu.stop();
        }
        if let Err(error) = self.flush() {
            self.failure.get_or_insert_with(|| error.to_string());
        }
        let state = if self.failure.is_some() {
            "incomplete"
        } else {
            "stopped"
        };
        let status = self.status(state);
        self.finalized = true;
        status.map_err(|error| {
            format!(
                "{}: could not save CSV status: {error}",
                self.directory.display()
            )
        })?;
        if let Some(error) = &self.failure {
            return Err(format!(
                "{}: incomplete CSV export: {error}",
                self.directory.display()
            ));
        }
        Ok(self.directory.clone())
    }
}
impl Write for LocalExport {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if let Some(error) = &self.failure {
            return Err(io::Error::other(error.clone()));
        }
        if let Err(error) = self
            .csv
            .write_all(bytes)
            .and_then(|()| self.compatibility.write_all(bytes))
        {
            self.failure = Some(error.to_string());
            return Err(error);
        }
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        self.csv.flush()?;
        self.compatibility.flush()?;
        self.csv.sync_all()?;
        self.compatibility.sync_all()
    }
}
impl Drop for LocalExport {
    fn drop(&mut self) {
        if !self.finalized {
            if let Err(error) = self.flush() {
                self.failure.get_or_insert_with(|| error.to_string());
            }
            if let Err(error) = self.status("interrupted") {
                eprintln!(
                    "Could not save interrupted telemetry status in {}: {error}",
                    self.directory.display()
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn root() -> PathBuf {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "local-export-tests-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        root
    }
    fn wait_for_gpu_exports(root: &Path) {
        let parent = root.join("sessions");
        let Ok(entries) = fs::read_dir(parent) else {
            return;
        };
        for entry in entries {
            let directory = entry.unwrap().path();
            if !directory.join("GPU_METADATA.json").is_file() {
                continue;
            }
            let started = std::time::Instant::now();
            loop {
                if fs::read(directory.join("GPU_STATUS.json"))
                    .ok()
                    .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
                    .is_some()
                {
                    break;
                }
                assert!(
                    started.elapsed() < std::time::Duration::from_secs(10),
                    "GPU telemetry export did not finish"
                );
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
        }
    }
    #[test]
    fn repeats_keep_every_session_and_compatibility_csv_schema() {
        let root = root();
        let parent = root.join("sessions");
        let compatibility = root.join("telemetry.csv");
        let mut first =
            LocalExport::start(&parent, &compatibility, &json!({"synthetic":true})).unwrap();
        first.write_all(b"first row\n").unwrap();
        let one = first.finish().unwrap();
        let original = fs::read(one.join("gameplay.csv")).unwrap();
        let mut second =
            LocalExport::start(&parent, &compatibility, &json!({"synthetic":true})).unwrap();
        second.write_all(b"second row\n").unwrap();
        let two = second.finish().unwrap();
        assert_ne!(one, two);
        assert_eq!(fs::read(one.join("gameplay.csv")).unwrap(), original);
        assert_eq!(
            fs::read(two.join("gameplay.csv")).unwrap(),
            fs::read(compatibility).unwrap()
        );
        assert!(original.starts_with(CSV_HEADER.as_bytes()));
        assert!(one.join("OBSERVATIONS.txt").is_file());
        wait_for_gpu_exports(&root);
        for directory in [&one, &two] {
            let gpu: Value =
                serde_json::from_slice(&fs::read(directory.join("GPU_STATUS.json")).unwrap())
                    .unwrap();
            assert_eq!(gpu["state"], "stopped");
            assert!(directory.join("gpu.jsonl").is_file());
            assert!(directory.join("GPU_METADATA.json").is_file());
        }
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn unfinished_session_is_explicitly_interrupted() {
        let root = root();
        let export = LocalExport::start(
            &root.join("sessions"),
            &root.join("telemetry.csv"),
            &json!({}),
        )
        .unwrap();
        let directory = export.directory.clone();
        drop(export);
        let status: Value =
            serde_json::from_slice(&fs::read(directory.join("CSV_STATUS.json")).unwrap()).unwrap();
        assert_eq!(status["state"], "interrupted");
        assert!(!directory.join("frames.json").exists());
        wait_for_gpu_exports(&root);
        let gpu: Value =
            serde_json::from_slice(&fs::read(directory.join("GPU_STATUS.json")).unwrap()).unwrap();
        assert_eq!(gpu["state"], "interrupted");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn existing_status_is_not_overwritten_or_called_success() {
        let root = root();
        let export = LocalExport::start(
            &root.join("sessions"),
            &root.join("telemetry.csv"),
            &json!({}),
        )
        .unwrap();
        let status = export.directory.join("CSV_STATUS.json");
        fs::write(&status, b"sentinel").unwrap();
        assert!(export.finish().is_err());
        assert_eq!(fs::read(status).unwrap(), b"sentinel");
        wait_for_gpu_exports(&root);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn actual_csv_write_failure_latches_and_exports_incomplete_status() {
        let root = root();
        let mut export = LocalExport::start(
            &root.join("sessions"),
            &root.join("telemetry.csv"),
            &json!({}),
        )
        .unwrap();
        let directory = export.directory.clone();
        // A read-only descriptor is an actual failing Write target, without
        // modifying process permissions or depending on a special OS device.
        export.compatibility = File::open(root.join("telemetry.csv")).unwrap();
        assert!(export.write_all(b"row\n").is_err());
        assert!(export.error().is_some());
        assert!(export.write_all(b"later row\n").is_err());
        assert!(export.finish().is_err());
        let status: Value =
            serde_json::from_slice(&fs::read(directory.join("CSV_STATUS.json")).unwrap()).unwrap();
        assert_eq!(status["state"], "incomplete");
        assert!(status["error"]
            .as_str()
            .is_some_and(|text| !text.is_empty()));
        wait_for_gpu_exports(&root);
        fs::remove_dir_all(root).unwrap();
    }
    #[cfg(unix)]
    #[test]
    fn symlink_roots_and_compatibility_files_do_not_redirect_writes() {
        use std::os::unix::fs::symlink;
        let root = root();
        let outside = root.join("outside");
        fs::create_dir(&outside).unwrap();
        symlink(&outside, root.join("sessions")).unwrap();
        assert!(LocalExport::start(
            &root.join("sessions"),
            &root.join("telemetry.csv"),
            &json!({})
        )
        .is_err());
        assert_eq!(fs::read_dir(&outside).unwrap().count(), 0);
        fs::remove_file(root.join("sessions")).unwrap();
        fs::write(outside.join("sentinel"), b"keep").unwrap();
        symlink(outside.join("sentinel"), root.join("telemetry.csv")).unwrap();
        assert!(LocalExport::start(
            &root.join("sessions"),
            &root.join("telemetry.csv"),
            &json!({})
        )
        .is_err());
        assert_eq!(fs::read(outside.join("sentinel")).unwrap(), b"keep");
        wait_for_gpu_exports(&root);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn source_identity_mismatch_cannot_claim_a_commit() {
        let root = root();
        let exe = root.join("vector-range.exe");
        let metadata = root.join("BUILD_IDENTITY.json");
        fs::write(&metadata,serde_json::to_vec(&json!({"schema":"rust-duty-build-identity/v1","display_version":"version",
            "executable":{"sha256":"a"},"source":{"commit":"1".repeat(40),"private":"must not copy"}})).unwrap()).unwrap();
        assert_eq!(
            packaged_source(&exe, "version", Some("a"))["commit"],
            "1".repeat(40)
        );
        assert!(packaged_source(&exe, "version", Some("a"))
            .get("private")
            .is_none());
        assert!(packaged_source(&exe, "version", Some("b"))
            .get("commit")
            .is_none());
        wait_for_gpu_exports(&root);
        fs::remove_dir_all(root).unwrap();
    }
}
