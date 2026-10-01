use super::*;
use crate::{
    download::{self, Control},
    install::Store,
    manifest::{Asset, Delta, Manifest, Trust},
    source::Source,
};
use semver::Version;
use std::{
    collections::HashMap,
    fs,
    io::{BufRead, BufReader, Read, Write},
    net::{Shutdown, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::Command,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

fn trust() -> Trust {
    Trust::production().unwrap()
}
fn manifest_bytes(manifest: &Manifest) -> Vec<u8> {
    serde_json::to_vec(manifest).unwrap()
}
fn version(value: &str) -> Version {
    Version::parse(value).unwrap()
}
fn asset(name: &str, data: &[u8]) -> Asset {
    Asset {
        name: name.into(),
        size: data.len() as u64,
        sha256: bytes_hash(data),
    }
}
fn random_bytes(size: usize) -> Vec<u8> {
    let mut state = 59u64;
    (0..size)
        .map(|_| {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            state as u8
        })
        .collect()
}
fn bundle_files(files: &[(&str, u8, &[u8])]) -> Vec<u8> {
    let mut data = b"RDBND001".to_vec();
    data.extend_from_slice(&(files.len() as u32).to_le_bytes());
    for (path, mode, body) in files {
        data.extend_from_slice(&(path.len() as u16).to_le_bytes());
        data.extend_from_slice(path.as_bytes());
        data.push(*mode);
        data.extend_from_slice(&(body.len() as u64).to_le_bytes());
        data.extend_from_slice(body);
    }
    data
}
fn bundle(data: &[u8]) -> Vec<u8> {
    bundle_files(&[("data.bin", 0, data), ("game", 1, b"#!/bin/sh\nexit 0\n")])
}
fn manifest(full: &[u8]) -> Manifest {
    Manifest {
        schema: 1,
        repository: REPOSITORY.into(),
        version: version("1.1.0"),
        sequence: 2,
        target: TARGET.into(),
        entrypoint: "game".into(),
        bundle: asset("game-1.1.0.rdb", full),
        deltas: vec![],
    }
}
fn write(root: &Path, name: &str, data: &[u8]) -> PathBuf {
    let path = root.join(name);
    fs::write(&path, data).unwrap();
    path
}
fn old_store(root: &Path, base: &[u8]) -> Store {
    let store = Store::open(&root.join("install")).unwrap();
    store
        .install_local(&write(root, "base.rdb", base), version("1.0.0"), "game")
        .unwrap();
    store
}
fn make_patch(root: &Path, base: &[u8], new: &[u8]) -> Vec<u8> {
    let base = write(root, "patch-base.rdb", base);
    let new = write(root, "patch-new.rdb", new);
    let output = root.join("patch.rdd");
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../tools/release_update.py");
    let result = Command::new("python")
        .arg(script)
        .args(["delta", "--base"])
        .arg(base)
        .arg("--new")
        .arg(new)
        .arg("--output")
        .arg(&output)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    fs::read(output).unwrap()
}
#[derive(Clone, Debug)]
struct Request {
    path: String,
    start: usize,
    if_range: Option<String>,
}
#[derive(Default)]
struct Behavior {
    cut_once: Option<usize>,
    change_etag: bool,
    wrong_range: bool,
    stall_once: bool,
    delay_once: Option<Duration>,
    slow: bool,
}
struct Server {
    port: u16,
    bodies: Arc<Mutex<HashMap<String, Vec<u8>>>>,
    requests: Arc<Mutex<Vec<Request>>>,
    behavior: Arc<Mutex<Behavior>>,
    stop: Arc<AtomicBool>,
    worker: Option<thread::JoinHandle<()>>,
}
impl Server {
    fn new() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let port = listener.local_addr().unwrap().port();
        let bodies = Arc::new(Mutex::new(HashMap::new()));
        let requests = Arc::new(Mutex::new(Vec::new()));
        let behavior = Arc::new(Mutex::new(Behavior::default()));
        let stop = Arc::new(AtomicBool::new(false));
        let (b, r, h, s) = (
            bodies.clone(),
            requests.clone(),
            behavior.clone(),
            stop.clone(),
        );
        let worker = thread::spawn(move || {
            while !s.load(Ordering::Relaxed) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        let (b, r, h) = (b.clone(), r.clone(), h.clone());
                        thread::spawn(move || {
                            if let Err(error) = serve(stream, b, r, h) {
                                // Pausing, cancelling, and rejecting a response deliberately
                                // close the client connection before the server finishes.
                                if !matches!(
                                    error.kind(),
                                    std::io::ErrorKind::BrokenPipe
                                        | std::io::ErrorKind::ConnectionReset
                                        | std::io::ErrorKind::ConnectionAborted
                                ) {
                                    eprintln!("HTTP fixture handler failed: {error:?}");
                                }
                            }
                        });
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(2))
                    }
                    Err(e) => panic!("{e}"),
                }
            }
        });
        Self {
            port,
            bodies,
            requests,
            behavior,
            stop,
            worker: Some(worker),
        }
    }
    fn source(&self) -> Source {
        Source::loopback(self.port).unwrap()
    }
    fn put(&self, name: &str, body: Vec<u8>) {
        self.bodies.lock().unwrap().insert(name.into(), body);
    }
    fn logs(&self) -> Vec<Request> {
        self.requests.lock().unwrap().clone()
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            worker.join().unwrap();
        }
    }
}
fn serve(
    mut stream: TcpStream,
    bodies: Arc<Mutex<HashMap<String, Vec<u8>>>>,
    requests: Arc<Mutex<Vec<Request>>>,
    behavior: Arc<Mutex<Behavior>>,
) -> std::io::Result<()> {
    // Winsock accepts inherit the listener's nonblocking mode. The handler uses
    // blocking read_line/write_all, so explicitly normalize the accepted socket.
    // https://learn.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-accept
    stream.set_nonblocking(false)?;
    stream.set_read_timeout(Some(Duration::from_secs(3)))?;
    // Borrow the single socket instead of duplicating its Windows socket handle.
    let mut reader = BufReader::new(&mut stream);
    let mut first = String::new();
    reader.read_line(&mut first)?;
    let path = first.split_whitespace().nth(1).unwrap_or("").to_owned();
    let mut headers = HashMap::new();
    loop {
        let mut line = String::new();
        reader.read_line(&mut line)?;
        if line == "\r\n" || line.is_empty() {
            break;
        }
        if let Some((key, value)) = line.trim().split_once(':') {
            headers.insert(key.to_ascii_lowercase(), value.trim().to_owned());
        }
    }
    drop(reader);
    let name = path.rsplit('/').next().unwrap();
    let Some(body) = bodies.lock().unwrap().get(name).cloned() else {
        stream.write_all(
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        )?;
        return Ok(());
    };
    let range = headers.get("range").map(|v| {
        let (start, end) = v.trim_start_matches("bytes=").split_once('-').unwrap();
        (
            start.parse::<usize>().unwrap(),
            end.parse::<usize>().unwrap(),
        )
    });
    let (start, end) = range.unwrap_or((0, body.len() - 1));
    requests.lock().unwrap().push(Request {
        path,
        start,
        if_range: headers.get("if-range").cloned(),
    });
    let (cut, change, wrong, stall, delay, slow) = {
        let mut state = behavior.lock().unwrap();
        let cut = state.cut_once.take();
        let stall = std::mem::take(&mut state.stall_once);
        (
            cut,
            state.change_etag,
            state.wrong_range,
            stall,
            state.delay_once.take(),
            state.slow,
        )
    };
    let etag = if change {
        "\"version-two\""
    } else {
        "\"version-one\""
    };
    let (status, start, end) =
        if range.is_some() && headers.get("if-range").is_none_or(|s| s == etag) {
            (206, start, end)
        } else {
            (200, 0, body.len() - 1)
        };
    let length = end - start + 1;
    let content_range = if status == 206 {
        format!(
            "Content-Range: bytes {}-{end}/{}\r\n",
            start + usize::from(wrong),
            body.len()
        )
    } else {
        String::new()
    };
    write!(stream, "HTTP/1.1 {status} OK\r\nContent-Length: {length}\r\nETag: {etag}\r\n{content_range}Connection: close\r\n\r\n")?;
    if stall {
        thread::sleep(Duration::from_millis(1600));
        return Ok(());
    }
    if let Some(delay) = delay {
        thread::sleep(delay);
    }
    let end = cut.map_or(end + 1, |n| (start + n).min(end + 1));
    for chunk in body[start..end].chunks(16384) {
        stream.write_all(chunk)?;
        if slow {
            thread::sleep(Duration::from_millis(3));
        }
    }
    // Perform an orderly half-close and allow the client to drain queued body bytes.
    // Closing duplicate sockets with unread/pending data can surface as resets on Windows.
    stream.shutdown(Shutdown::Write)?;
    let mut remaining = [0; 256];
    while let Ok(n) = stream.read(&mut remaining) {
        if n == 0 {
            break;
        }
    }
    Ok(())
}
fn wait_for_prefix(
    store: &Store,
    worker: thread::JoinHandle<Result<PathBuf>>,
) -> thread::JoinHandle<Result<PathBuf>> {
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut last_status = String::from("not read yet");
    while Instant::now() < deadline {
        let progress = read_json::<download::Progress>(&store.root.join("status.json"));
        if progress.as_ref().is_ok_and(|p| p.bytes > 0) {
            return worker;
        }
        last_status = format!("{progress:?}");
        if worker.is_finished() {
            let result = worker.join();
            panic!(
                "downloader exited before a durable prefix was observed: {result:?}; \
                 last status read: {last_status}"
            );
        }
        thread::sleep(Duration::from_millis(2));
    }
    panic!(
        "no downloaded prefix observed; worker finished={}; last status read: {last_status}",
        worker.is_finished()
    );
}

#[test]
fn github_manifest_rejects_malformed_fields_and_legacy_envelopes() {
    let good = manifest(&bundle(b"hello"));
    let encoded = manifest_bytes(&good);
    assert!(trust().verify(&encoded, TARGET).is_ok());
    let legacy = serde_json::json!({"payload": String::from_utf8(encoded.clone()).unwrap(), "signature": "00"});
    assert!(trust()
        .verify(&serde_json::to_vec(&legacy).unwrap(), TARGET)
        .is_err());
    assert!(trust().verify(b"not-json", TARGET).is_err());
    assert!(trust().verify(&encoded, "wrong-target").is_err());
    let mut unknown: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
    unknown["url"] = "https://other.example/payload".into();
    assert!(trust()
        .verify(&serde_json::to_vec(&unknown).unwrap(), TARGET)
        .is_err());
    let mut bad = good.clone();
    bad.bundle.name = "../../evil.exe".into();
    assert!(trust().verify(&manifest_bytes(&bad), TARGET).is_err());
    bad = good.clone();
    bad.bundle.sha256 = "0".repeat(63);
    assert!(trust().verify(&manifest_bytes(&bad), TARGET).is_err());
    bad = good.clone();
    bad.repository = "attacker/rust_duty".into();
    assert!(trust().verify(&manifest_bytes(&bad), TARGET).is_err());
    bad = good.clone();
    bad.entrypoint = "../game".into();
    assert!(trust().verify(&manifest_bytes(&bad), TARGET).is_err());
    bad = good;
    bad.version = version("1.1.0-beta.1");
    assert!(trust().verify(&manifest_bytes(&bad), TARGET).is_err());
}
#[test]
fn production_trust_needs_no_key_and_validates_raw_manifest() {
    let manifest = manifest(&bundle(b"hello"));
    assert!(Trust::production()
        .unwrap()
        .verify(&manifest_bytes(&manifest), TARGET)
        .is_ok());
}
#[test]
fn redirect_and_windows_path_restrictions() {
    for url in [
        "https://github.com/RHS059/rust_duty/releases/download/v1/x",
        "https://release-assets.githubusercontent.com/file",
    ] {
        assert!(source::redirect_allowed(url));
    }
    for url in [
        "http://github.com/RHS059/rust_duty/releases/x",
        "https://github.com/other/repo/releases/x",
        "https://github.com.evil.test/RHS059/rust_duty/releases/x",
        "https://evil.test/x",
        "https://user:pass@github.com/RHS059/rust_duty/releases/x",
    ] {
        assert!(!source::redirect_allowed(url));
    }
    for path in [
        "../x",
        "/x",
        "C:/x",
        "x\\y",
        "a//b",
        "NUL.txt",
        "COM1",
        "name.",
        "private-assets/key",
        "settings.cfg",
        "payload.rdb",
        "version.json",
    ] {
        assert!(bundle::safe_path(path).is_err(), "{path}");
    }
}
#[test]
fn bundle_rejects_traversal_special_types_duplicate_paths_and_truncation() {
    let root = tempfile::tempdir().unwrap();
    for files in [
        vec![("../game", 1, b"x".as_slice())],
        vec![("game", 2, b"x".as_slice())],
        vec![("game", 1, b"x".as_slice()), ("GAME", 1, b"y".as_slice())],
    ] {
        let destination = tempfile::tempdir_in(root.path()).unwrap();
        assert!(bundle::unpack(
            &write(root.path(), "bad.rdb", &bundle_files(&files)),
            destination.path(),
            "game"
        )
        .is_err());
    }
    let data = bundle(b"hi");
    let destination = tempfile::tempdir_in(root.path()).unwrap();
    assert!(bundle::unpack(
        &write(root.path(), "truncated.rdb", &data[..data.len() - 1]),
        destination.path(),
        "game"
    )
    .is_err());
    assert!(!root.path().join("game").exists());
}
#[test]
#[cfg(unix)]
fn refuses_symlink_install_and_bundle_targets() {
    use std::os::unix::fs::symlink;
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    symlink(outside.path(), root.path().join("install")).unwrap();
    assert!(Store::open(&root.path().join("install")).is_err());
    let destination = root.path().join("output");
    fs::create_dir(&destination).unwrap();
    symlink(outside.path().join("stolen"), destination.join("data.bin")).unwrap();
    assert!(bundle::unpack(
        &write(root.path(), "input.rdb", &bundle(b"x")),
        &destination,
        "game"
    )
    .is_err());
    assert!(!outside.path().join("stolen").exists());
}
#[test]
fn two_version_github_http_delta_is_byte_identical_and_rolls_back_atomically() {
    let root = tempfile::tempdir().unwrap();
    let bytes = random_bytes(512 * 1024);
    let base = bundle(&bytes);
    let mut changed = b"inserted new bytes".to_vec();
    changed.extend_from_slice(&bytes[..32000]);
    changed.extend_from_slice(b"replacement");
    changed.extend_from_slice(&bytes[34000..]);
    let new = bundle(&changed);
    let patch = make_patch(root.path(), &base, &new);
    println!(
        "Delta transfer: {} bytes versus {} full bundle bytes ({:.2}%)",
        patch.len(),
        new.len(),
        100.0 * patch.len() as f64 / new.len() as f64
    );
    assert!(
        patch.len() < new.len() / 10,
        "actual patch must contain copies and substantially fewer transferred bytes"
    );
    let store = old_store(root.path(), &base);
    fs::write(store.root.join("settings.cfg"), b"keep sensitivity=2.3").unwrap();
    fs::create_dir(store.root.join("private-assets")).unwrap();
    fs::write(store.root.join("private-assets/owned.bin"), b"keep private").unwrap();
    let mut manifest = manifest(&new);
    manifest.deltas.push(Delta {
        base_version: version("1.0.0"),
        base_sha256: bytes_hash(&base),
        asset: asset("changes.rdd", &patch),
    });
    let server = Server::new();
    server.put(&format!("update-{TARGET}.json"), manifest_bytes(&manifest));
    server.put("changes.rdd", patch);
    server.put(&manifest.bundle.name, new.clone());
    let verified = store.check(&server.source(), &trust(), TARGET).unwrap();
    let staged = store.stage(&server.source(), &verified).unwrap();
    assert_eq!(fs::read(store.bundle_path(&staged)).unwrap(), new);
    assert_eq!(
        fs::read(store.version_dir(&staged).join("data.bin")).unwrap(),
        changed
    );
    assert_eq!(
        store.state().unwrap().active.unwrap().version,
        version("1.0.0")
    );
    assert!(
        !server
            .logs()
            .iter()
            .any(|r| r.path.ends_with(&manifest.bundle.name)),
        "matching delta must avoid a full bundle request"
    );
    store.activate(staged.clone()).unwrap();
    assert_eq!(
        store.state().unwrap().active.unwrap().version,
        version("1.1.0")
    );
    assert!(store.check_newer(&manifest).is_err());
    let mut downgraded = manifest.clone();
    downgraded.version = version("0.9.0");
    downgraded.sequence = 3;
    assert!(store.check_newer(&downgraded).is_err());
    store.rollback().unwrap();
    assert_eq!(
        store.state().unwrap().active.unwrap().version,
        version("1.0.0")
    );
    assert!(
        store.activate(staged).is_err(),
        "rollback must not lower anti-replay high-water mark"
    );
    assert_eq!(
        fs::read(store.root.join("settings.cfg")).unwrap(),
        b"keep sensitivity=2.3"
    );
    assert_eq!(
        fs::read(store.root.join("private-assets/owned.bin")).unwrap(),
        b"keep private"
    );
    println!("Verified GitHub-style HTTPS-trust manifest over local HTTP, 1.0.0 -> 1.1.0 using a real patch; exact bytes, atomic activation, rollback and user data preservation passed");
}
#[test]
fn bad_delta_falls_back_to_full_and_wrong_base_skips_delta() {
    for bad_base in [false, true] {
        let root = tempfile::tempdir().unwrap();
        let base = bundle(&random_bytes(200000));
        let new = bundle(&random_bytes(220000));
        let store = old_store(root.path(), &base);
        let patch = b"hash-verified but malformed delta".to_vec();
        let mut manifest = manifest(&new);
        manifest.deltas.push(Delta {
            base_version: version("1.0.0"),
            base_sha256: if bad_base {
                "0".repeat(64)
            } else {
                bytes_hash(&base)
            },
            asset: asset("bad.rdd", &patch),
        });
        let server = Server::new();
        server.put("bad.rdd", patch);
        server.put(&manifest.bundle.name, new.clone());
        let staged = store.stage(&server.source(), &manifest).unwrap();
        assert_eq!(fs::read(store.bundle_path(&staged)).unwrap(), new);
        assert!(server
            .logs()
            .iter()
            .any(|r| r.path.ends_with(&manifest.bundle.name)));
        assert_eq!(
            server.logs().iter().any(|r| r.path.ends_with("bad.rdd")),
            !bad_base
        );
    }
}
#[test]
fn disconnected_download_resumes_from_verified_prefix_after_process_restart() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::open(root.path()).unwrap();
    let bytes = random_bytes(3 * 1024 * 1024);
    let asset = asset("payload.rdb", &bytes);
    let server = Server::new();
    server.put(&asset.name, bytes.clone());
    server.behavior.lock().unwrap().cut_once = Some(131072);
    assert!(matches!(
        download::download(&store.root, &server.source(), &version("1.1.0"), &asset),
        Err(Error::Network(_))
    ));
    let checkpoint = fs::metadata(
        store
            .root
            .join("cache")
            .join(format!("{}.part", asset.sha256)),
    )
    .unwrap()
    .len();
    assert!(checkpoint > 0 && checkpoint < asset.size);
    // Reopen both install and HTTP client, as a new launcher process would.
    let reopened = Store::open(root.path()).unwrap();
    let ready =
        download::download(&reopened.root, &server.source(), &version("1.1.0"), &asset).unwrap();
    assert_eq!(fs::read(ready).unwrap(), bytes);
    assert!(server.logs().iter().any(
        |r| r.start == checkpoint as usize && r.if_range.as_deref() == Some("\"version-one\"")
    ));
}
#[test]
fn changed_etag_discards_old_prefix_instead_of_appending() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::open(root.path()).unwrap();
    let bytes = random_bytes(2 * 1024 * 1024);
    let asset = asset("payload.rdb", &bytes);
    let server = Server::new();
    server.put(&asset.name, bytes.clone());
    server.behavior.lock().unwrap().cut_once = Some(131072);
    assert!(download::download(&store.root, &server.source(), &version("1.1.0"), &asset).is_err());
    server.behavior.lock().unwrap().change_etag = true;
    let ready =
        download::download(&store.root, &server.source(), &version("1.1.0"), &asset).unwrap();
    assert_eq!(fs::read(ready).unwrap(), bytes);
    let logs = server.logs();
    assert!(logs[1].start > 0);
    assert_eq!(logs[2].start, 0);
}
#[test]
fn pause_resume_and_cancel_are_persisted() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::open(root.path()).unwrap();
    let bytes = random_bytes(4 * 1024 * 1024);
    let asset = asset("payload.rdb", &bytes);
    let server = Server::new();
    server.put(&asset.name, bytes.clone());
    server.behavior.lock().unwrap().slow = true;
    let (path, source, artifact) = (store.root.clone(), server.source(), asset.clone());
    let worker =
        thread::spawn(move || download::download(&path, &source, &version("1.1.0"), &artifact));
    let worker = wait_for_prefix(&store, worker);
    download::set_control(&store.root, Control::Paused).unwrap();
    let result = worker.join().unwrap();
    assert!(
        matches!(result, Err(Error::Paused)),
        "pause result: {result:?}"
    );
    let part = store
        .root
        .join("cache")
        .join(format!("{}.part", asset.sha256));
    let checkpoint = part.metadata().unwrap().len();
    assert!(checkpoint > 0);
    assert_eq!(
        download::control(&Store::open(root.path()).unwrap().root).unwrap(),
        Control::Paused
    );
    assert!(matches!(
        download::download(&store.root, &server.source(), &version("1.1.0"), &asset),
        Err(Error::Paused)
    ));
    download::set_control(&store.root, Control::Running).unwrap();
    let ready =
        download::download(&store.root, &server.source(), &version("1.1.0"), &asset).unwrap();
    assert_eq!(fs::read(ready).unwrap(), bytes);
    assert!(server.logs().iter().any(|r| r.start == checkpoint as usize));
    // A cancelled transfer remains cancelled across restart and deletes partial checkpoints.
    fs::write(&part, b"partial").unwrap();
    download::set_control(&store.root, Control::Cancelled).unwrap();
    assert!(matches!(
        download::download(&store.root, &server.source(), &version("1.1.0"), &asset),
        Err(Error::Cancelled)
    ));
    assert!(!part.exists());
    assert_eq!(download::control(root.path()).unwrap(), Control::Cancelled);
}
#[test]
fn corrupted_prefix_restarts_and_hash_or_range_mismatch_never_installs() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::open(root.path()).unwrap();
    let bytes = random_bytes(2 * 1024 * 1024);
    let asset = asset("payload.rdb", &bytes);
    let server = Server::new();
    server.put(&asset.name, bytes.clone());
    server.behavior.lock().unwrap().cut_once = Some(65536);
    assert!(download::download(&store.root, &server.source(), &version("1.1.0"), &asset).is_err());
    let part = store
        .root
        .join("cache")
        .join(format!("{}.part", asset.sha256));
    let size = part.metadata().unwrap().len();
    fs::write(&part, vec![0; size as usize]).unwrap();
    let ready =
        download::download(&store.root, &server.source(), &version("1.1.0"), &asset).unwrap();
    assert_eq!(fs::read(&ready).unwrap(), bytes);
    assert_eq!(server.logs()[1].start, 0);
    fs::remove_file(ready).unwrap();
    server.behavior.lock().unwrap().wrong_range = true;
    assert!(download::download(&store.root, &server.source(), &version("1.1.0"), &asset).is_err());
    server.behavior.lock().unwrap().wrong_range = false;
    server.put(&asset.name, vec![0; bytes.len()]);
    assert!(download::download(&store.root, &server.source(), &version("1.1.0"), &asset).is_err());
    assert!(!part.exists());
    assert!(store.state().unwrap().active.is_none());
}
#[test]
fn stalled_server_times_out_without_losing_install() {
    let root = tempfile::tempdir().unwrap();
    let store = old_store(root.path(), &bundle(b"old"));
    let bytes = random_bytes(100000);
    let artifact = asset("new.rdb", &bytes);
    let server = Server::new();
    server.put(&artifact.name, bytes);
    server.behavior.lock().unwrap().stall_once = true;
    assert!(matches!(
        download::download(
            &store.root,
            &Source::loopback_with_timeout(server.port, Duration::from_millis(1200)).unwrap(),
            &version("1.1.0"),
            &artifact
        ),
        Err(Error::Network(_))
    ));
    assert_eq!(
        store.state().unwrap().active.unwrap().version,
        version("1.0.0")
    );
    assert!(
        download::download(&store.root, &server.source(), &version("1.1.0"), &artifact).is_ok()
    );
}
#[test]
fn failed_staging_and_game_exit_restore_last_good_without_lowering_sequence() {
    let root = tempfile::tempdir().unwrap();
    let store = old_store(root.path(), &bundle(b"old"));
    let server = Server::new();
    let malformed = bundle_files(&[("../game", 1, b"bad")]);
    let bad = manifest(&malformed);
    server.put(&bad.bundle.name, malformed);
    assert!(store.stage(&server.source(), &bad).is_err());
    assert_eq!(
        store.state().unwrap().active.unwrap().version,
        version("1.0.0")
    );
    let new = bundle(b"new");
    let manifest = manifest(&new);
    server.put(&manifest.bundle.name, new);
    let staged = store.stage(&server.source(), &manifest).unwrap();
    let mut state = store.state().unwrap();
    state.pending_launch = true;
    store.save(&state).unwrap();
    assert!(store.activate(staged.clone()).is_err());
    assert!(store.recover().is_err());
    store.finish_launch(true).unwrap();
    store.activate(staged).unwrap();
    store.finish_launch(false).unwrap();
    let state = store.state().unwrap();
    assert_eq!(state.active.unwrap().version, version("1.0.0"));
    assert_eq!(state.highest_sequence, 2);
}
#[test]
fn delta_rejects_copy_overflow_and_trailing_bytes() {
    let root = tempfile::tempdir().unwrap();
    let base = write(root.path(), "base", b"abc");
    let mut patch = b"RDDLT001".to_vec();
    patch.extend_from_slice(&3u64.to_le_bytes());
    patch.extend_from_slice(&3u64.to_le_bytes());
    patch.push(0);
    patch.extend_from_slice(&u64::MAX.to_le_bytes());
    patch.extend_from_slice(&3u64.to_le_bytes());
    patch.push(255);
    assert!(delta::apply(
        &base,
        &write(root.path(), "patch", &patch),
        &root.path().join("out"),
        3
    )
    .is_err());
    let mut patch = b"RDDLT001".to_vec();
    patch.extend_from_slice(&3u64.to_le_bytes());
    patch.extend_from_slice(&3u64.to_le_bytes());
    patch.push(1);
    patch.extend_from_slice(&3u64.to_le_bytes());
    patch.extend_from_slice(b"xyz");
    patch.extend_from_slice(&[255, 0]);
    assert!(delta::apply(
        &base,
        &write(root.path(), "patch2", &patch),
        &root.path().join("out2"),
        3
    )
    .is_err());
}
#[test]
fn only_one_launcher_can_own_an_install() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::open(root.path()).unwrap();
    let lock = store.lock().unwrap();
    assert!(store.lock().is_err());
    drop(lock);
    assert!(store.lock().is_ok());
}

#[test]
#[cfg(unix)]
fn launcher_waits_for_child_and_failed_new_game_restores_last_good() {
    let root = tempfile::tempdir().unwrap();
    let base = bundle_files(&[("game", 1, b"#!/bin/sh\nsleep 0.1\nexit 0\n")]);
    let store = old_store(root.path(), &base);
    let new = bundle_files(&[("game", 1, b"#!/bin/sh\nexit 3\n")]);
    let release = manifest(&new);
    let server = Server::new();
    server.put(&release.bundle.name, new);
    let staged = store.stage(&server.source(), &release).unwrap();
    let mut game = store.launch(&[]).unwrap();
    assert!(game.try_wait().unwrap().is_none());
    assert!(store.activate(staged.clone()).is_err());
    store.finish_launch(game.wait().unwrap().success()).unwrap();
    store.activate(staged).unwrap();
    let mut game = store.launch(&[]).unwrap();
    store.finish_launch(game.wait().unwrap().success()).unwrap();
    assert_eq!(
        store.state().unwrap().active.unwrap().version,
        version("1.0.0")
    );
}

#[test]
fn launch_mapping_discovers_stable_root_assets_and_preserves_explicit_arguments() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::open(root.path()).unwrap();
    fs::create_dir_all(store.root.join("private-assets")).unwrap();
    fs::write(
        store.root.join("private-assets/hk416a5.vrm"),
        b"user weapon",
    )
    .unwrap();
    fs::write(store.root.join("private-assets/fps-arms.vrs"), b"user arms").unwrap();
    fs::write(store.root.join("settings.cfg"), b"user sensitivity").unwrap();
    let config = launch::LaunchConfig::default();
    let args = launch::mapped_arguments(&store.root, &config, &["--hold-controls".into()]).unwrap();
    assert!(args.contains(&"--hold-controls".into()));
    for (flag, path) in [
        ("--settings=", "settings.cfg"),
        ("--weapon-asset=", "private-assets/hk416a5.vrm"),
        ("--arms-asset=", "private-assets/fps-arms.vrs"),
    ] {
        assert!(args.contains(&format!("{flag}{}", store.root.join(path).display())));
    }
    let configured = launch::LaunchConfig {
        settings: Some("persistent/settings.cfg".into()),
        weapon_asset: Some("private-assets/saved-weapon.vrm".into()),
        arms_asset: Some("private-assets/saved-arms.vrs".into()),
        game_args: vec!["--hold-controls".into(), "--settings=saved.cfg".into()],
    };
    launch::save(&store.root, &configured).unwrap();
    assert_eq!(launch::load(&store.root).unwrap(), configured);
    let args = launch::mapped_arguments(
        &store.root,
        &configured,
        &[
            "--profile=kestrel".into(),
            "--settings=selected settings.cfg".into(),
            "--weapon-asset=private-assets/selected.vrm".into(),
        ],
    )
    .unwrap();
    assert_eq!(&args[..2], &["--hold-controls", "--profile=kestrel"]);
    assert_eq!(
        args.iter().filter(|a| a.starts_with("--settings=")).count(),
        1
    );
    assert_eq!(
        args.iter()
            .filter(|a| a.starts_with("--weapon-asset="))
            .count(),
        1
    );
    assert!(args.contains(&format!(
        "--settings={}",
        store.root.join("selected settings.cfg").display()
    )));
    assert!(args.contains(&format!(
        "--weapon-asset={}",
        store.root.join("private-assets/selected.vrm").display()
    )));
    assert!(args.contains(&format!(
        "--arms-asset={}",
        store.root.join("private-assets/saved-arms.vrs").display()
    )));
    let profile =
        launch::mapped_arguments(&store.root, &config, &["--profile=kestrel".into()]).unwrap();
    assert!(profile.contains(&format!(
        "--settings={}",
        store.root.join("profiles/kestrel.cfg").display()
    )));
    assert!(launch::mapped_arguments(
        &store.root,
        &config,
        &["--weapon-asset=../outside.vrm".into()]
    )
    .is_err());
}

#[test]
fn launcher_discovers_private_preview_arms_without_overriding_existing_mappings() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::open(root.path()).unwrap();
    fs::create_dir_all(store.root.join("assets/arms")).unwrap();
    let preview = store.root.join("assets/arms/first-person.vrs");
    fs::write(&preview, b"private preview arms").unwrap();
    let config = launch::LaunchConfig::default();
    let arms_argument = |config: &launch::LaunchConfig, per_launch: &[String]| {
        launch::mapped_arguments(&store.root, config, per_launch)
            .unwrap()
            .into_iter()
            .filter(|argument| argument.starts_with("--arms-asset="))
            .collect::<Vec<_>>()
    };
    assert_eq!(
        arms_argument(&config, &[]),
        vec![format!("--arms-asset={}", preview.display())]
    );

    // Existing installations retain their prior discovery priority.
    fs::create_dir_all(store.root.join("private-assets")).unwrap();
    let existing = store.root.join("private-assets/fps-arms.vrs");
    fs::write(&existing, b"existing private arms").unwrap();
    assert_eq!(
        arms_argument(&config, &[]),
        vec![format!("--arms-asset={}", existing.display())]
    );
    let configured = launch::LaunchConfig {
        arms_asset: Some("private-assets/selected.vrs".into()),
        ..Default::default()
    };
    assert_eq!(
        arms_argument(&configured, &[]),
        vec![format!(
            "--arms-asset={}",
            store.root.join("private-assets/selected.vrs").display()
        )]
    );
    assert_eq!(
        arms_argument(
            &configured,
            &["--arms-asset=assets/arms/first-person.vrs".into()]
        ),
        vec![format!("--arms-asset={}", preview.display())]
    );
}

#[test]
fn public_bundles_reject_private_assets_and_launch_configuration() {
    let root = tempfile::tempdir().unwrap();
    for path in [
        "launch.json",
        "launcher-location.json",
        "private-assets/hk416a5.vrm",
        "assets/private-assets/hk416a5.vrm",
        "fps-arms.vrs",
        "assets/arms/fps-arms.vrs",
        "first-person.vrs",
        "assets/arms/first-person.vrs",
        "assets/arms/FIRST-PERSON.VRS",
    ] {
        assert!(bundle::safe_path(path).is_err(), "{path}");
        let destination = tempfile::tempdir_in(root.path()).unwrap();
        let untrusted_bundle = bundle_files(&[
            ("game", 1, b"game"),
            (path, 0, b"private fixture must never be extracted"),
        ]);
        assert!(bundle::unpack(
            &write(root.path(), "private.rdb", &untrusted_bundle),
            destination.path(),
            "game"
        )
        .is_err());
        assert!(!destination.path().join(path).exists(), "{path}");
    }
}

#[test]
fn child_receives_absolute_stable_paths_after_version_switch_without_copying_private_data() {
    let root = tempfile::tempdir().unwrap();
    let source = write(root.path(), "child_fixture.rs", br#"
fn main() {
    std::fs::write("received-args.txt", std::env::args().skip(1).collect::<Vec<_>>().join("\n")).unwrap();
}
"#);
    let binary = root.path().join(bootstrap::GAME_FILE);
    let compiled = Command::new("rustc")
        .args(["--edition=2021", "--crate-name", "updater_child_fixture"])
        .arg(&source)
        .arg("-o")
        .arg(&binary)
        .output()
        .unwrap();
    assert!(
        compiled.status.success(),
        "{}",
        String::from_utf8_lossy(&compiled.stderr)
    );
    let executable = fs::read(binary).unwrap();
    let base = bundle_files(&[(bootstrap::GAME_FILE, 1, &executable)]);
    let store = Store::open(&root.path().join("install")).unwrap();
    store
        .install_local(
            &write(root.path(), "base.rdb", &base),
            version("1.0.0"),
            bootstrap::GAME_FILE,
        )
        .unwrap();
    fs::create_dir_all(store.root.join("private-assets")).unwrap();
    fs::write(store.root.join("settings.cfg"), b"keep settings").unwrap();
    fs::write(
        store.root.join("private-assets/hk416a5.vrm"),
        b"keep weapon",
    )
    .unwrap();
    fs::create_dir_all(store.root.join("assets/arms")).unwrap();
    let preview_arms = store.root.join("assets/arms/first-person.vrs");
    fs::write(&preview_arms, b"keep arms").unwrap();
    let config = launch::LaunchConfig {
        game_args: vec!["--hold-controls".into()],
        ..Default::default()
    };
    launch::save(&store.root, &config).unwrap();
    let per_launch = vec!["--profile=kestrel".into(), "--settings=settings.cfg".into()];
    let expected = launch::mapped_arguments(&store.root, &config, &per_launch).unwrap();
    assert!(expected.contains(&format!("--arms-asset={}", preview_arms.display())));
    let mut game = store.launch(&per_launch).unwrap();
    store.finish_launch(game.wait().unwrap().success()).unwrap();
    assert_eq!(
        fs::read_to_string(store.root.join("received-args.txt"))
            .unwrap()
            .lines()
            .map(str::to_owned)
            .collect::<Vec<_>>(),
        expected
    );
    let new = bundle_files(&[
        (bootstrap::GAME_FILE, 1, &executable),
        ("public.txt", 0, b"new version"),
    ]);
    let mut release = manifest(&new);
    release.entrypoint = bootstrap::GAME_FILE.into();
    let server = Server::new();
    server.put(&release.bundle.name, new);
    let staged = store.stage(&server.source(), &release).unwrap();
    let version_dir = store.version_dir(&staged);
    store.activate(staged).unwrap();
    let mut game = store.launch(&per_launch).unwrap();
    store.finish_launch(game.wait().unwrap().success()).unwrap();
    assert_eq!(
        fs::read_to_string(store.root.join("received-args.txt"))
            .unwrap()
            .lines()
            .map(str::to_owned)
            .collect::<Vec<_>>(),
        expected
    );
    assert!(!version_dir.join("private-assets").exists());
    assert!(!version_dir.join("assets/arms/first-person.vrs").exists());
    assert!(!version_dir.join("settings.cfg").exists());
    assert!(!version_dir.join("launch.json").exists());
    assert_eq!(
        fs::read(store.root.join("settings.cfg")).unwrap(),
        b"keep settings"
    );
    assert_eq!(
        fs::read(store.root.join("private-assets/hk416a5.vrm")).unwrap(),
        b"keep weapon"
    );
    assert_eq!(fs::read(preview_arms).unwrap(), b"keep arms");
    assert_eq!(launch::load(&store.root).unwrap(), config);
}

#[test]
fn automatic_launch_occurs_once_only_after_an_install_is_available() {
    let mut auto = launch::AutoPlayOnce::new(true);
    assert!(!auto.take_if_installed(false));
    assert!(!auto.take_if_installed(false));
    assert!(auto.take_if_installed(true));
    assert!(
        !auto.take_if_installed(true),
        "a child exit must not trigger a relaunch loop"
    );
    assert!(!auto.take_if_installed(false));
    let mut manual = launch::AutoPlayOnce::new(false);
    assert!(!manual.take_if_installed(true));
    let mut cancelled = launch::AutoPlayOnce::new(true);
    cancelled.cancel();
    assert!(!cancelled.take_if_installed(true));
}

#[test]
fn ordinary_transfer_can_wait_longer_than_the_intentional_stall_budget() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::open(root.path()).unwrap();
    let body = random_bytes(64 * 1024);
    let artifact = asset("delayed.rdb", &body);
    let server = Server::new();
    server.put(&artifact.name, body.clone());
    server.behavior.lock().unwrap().delay_once = Some(Duration::from_millis(1600));
    let ready =
        download::download(&store.root, &server.source(), &version("1.1.0"), &artifact).unwrap();
    assert_eq!(fs::read(ready).unwrap(), body);
}

#[test]
fn http_fixture_restores_blocking_mode_for_inherited_nonblocking_sockets() {
    use std::sync::mpsc;

    // Winsock accept inherits the listener's nonblocking mode. Force that state
    // on every platform, and delay the request so a nonblocking read must fail.
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let body = random_bytes(512 * 1024);
    let bodies = Arc::new(Mutex::new(HashMap::from([(
        "fixture.rdb".into(),
        body.clone(),
    )])));
    let (accepted_tx, accepted_rx) = mpsc::channel();
    let (done_tx, done_rx) = mpsc::channel();
    let worker = thread::spawn(move || {
        let (stream, _) = listener.accept().unwrap();
        stream.set_nonblocking(true).unwrap();
        accepted_tx.send(()).unwrap();
        let result = serve(
            stream,
            bodies,
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Behavior::default())),
        );
        done_tx.send(result).unwrap();
    });
    let mut client = TcpStream::connect(address).unwrap();
    client
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    accepted_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    match done_rx.recv_timeout(Duration::from_millis(100)) {
        Err(mpsc::RecvTimeoutError::Timeout) => (),
        other => panic!("handler must wait for request bytes, not exit: {other:?}"),
    }
    client
        .write_all(b"GET /fixture.rdb HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        .unwrap();
    client.shutdown(Shutdown::Write).unwrap();
    let mut response = Vec::new();
    client.read_to_end(&mut response).unwrap();
    done_rx
        .recv_timeout(Duration::from_secs(5))
        .unwrap()
        .unwrap();
    worker.join().unwrap();
    let split = response
        .windows(4)
        .position(|bytes| bytes == b"\r\n\r\n")
        .unwrap()
        + 4;
    assert_eq!(&response[split..], body);
}

fn synced_test_tempfile(root: &Path, bytes: &[u8]) -> tempfile::NamedTempFile {
    let mut file = tempfile::NamedTempFile::new_in(root).unwrap();
    file.write_all(bytes).unwrap();
    file.as_file().sync_all().unwrap();
    file
}

#[test]
fn atomic_replace_retries_only_windows_contention_and_retains_the_same_tempfile() {
    let root = tempfile::tempdir().unwrap();
    let path = write(root.path(), "state.json", b"old complete state");
    let file = synced_test_tempfile(root.path(), b"new complete state");
    let temporary_path = file.path().to_owned();
    let mut attempts = 0;
    let mut waits = Vec::new();
    persist_with_retry(
        file,
        &path,
        true,
        |file, destination| {
            attempts += 1;
            assert_eq!(file.path(), temporary_path);
            assert_eq!(fs::read(file.path()).unwrap(), b"new complete state");
            assert_eq!(fs::read(destination).unwrap(), b"old complete state");
            if attempts <= 2 {
                Err(tempfile::PersistError {
                    file,
                    error: std::io::Error::from_raw_os_error(if attempts == 1 { 5 } else { 32 }),
                })
            } else {
                file.persist(destination)
            }
        },
        |delay| waits.push(delay),
    )
    .unwrap();
    assert_eq!(attempts, 3);
    assert_eq!(waits, vec![REPLACE_RETRY_DELAY; 2]);
    assert_eq!(fs::read(&path).unwrap(), b"new complete state");
    assert!(!temporary_path.exists());
}

#[test]
fn atomic_replace_exhaustion_and_nonretry_errors_preserve_last_good_state() {
    // The Windows classifier is tested through injection on every platform.
    for (windows, code, expected_attempts) in [
        (true, 5, REPLACE_RETRIES + 1),
        (true, 32, REPLACE_RETRIES + 1),
        (true, 2, 1),
        (true, 112, 1), // ERROR_DISK_FULL is not transient sharing contention.
        (false, 5, 1),  // Never interpret Unix errno as a Windows error code.
        (false, 32, 1),
    ] {
        let root = tempfile::tempdir().unwrap();
        let path = write(root.path(), "state.json", b"last good state");
        let file = synced_test_tempfile(root.path(), b"replacement");
        let temporary_path = file.path().to_owned();
        let mut attempts = 0;
        let mut waits = 0;
        let result = persist_with_retry(
            file,
            &path,
            windows,
            |file, destination| {
                attempts += 1;
                assert_eq!(file.path(), temporary_path);
                assert_eq!(fs::read(destination).unwrap(), b"last good state");
                Err(tempfile::PersistError {
                    file,
                    error: std::io::Error::from_raw_os_error(code),
                })
            },
            |_| waits += 1,
        );
        match result.unwrap_err() {
            Error::Filesystem {
                operation,
                path: failed_path,
                source,
            } => {
                assert_eq!(operation, "atomically replace state");
                assert_eq!(failed_path, path);
                assert_eq!(source.raw_os_error(), Some(code));
            }
            other => panic!("expected contextual filesystem error, got {other:?}"),
        }
        assert_eq!(attempts, expected_attempts);
        assert_eq!(waits, expected_attempts - 1);
        assert_eq!(fs::read(path).unwrap(), b"last good state");
        assert!(
            !temporary_path.exists(),
            "failed tempfiles must not accumulate"
        );
    }
}

#[cfg(unix)]
#[test]
fn atomic_replace_rechecks_symlinks_after_contention_before_trying_again() {
    let root = tempfile::tempdir().unwrap();
    let path = write(root.path(), "state.json", b"old state");
    let elsewhere = write(root.path(), "elsewhere.json", b"must remain unchanged");
    let file = synced_test_tempfile(root.path(), b"new state");
    let mut attempts = 0;
    let result = persist_with_retry(
        file,
        &path,
        true,
        |file, _| {
            attempts += 1;
            Err(tempfile::PersistError {
                file,
                error: std::io::Error::from_raw_os_error(32),
            })
        },
        |_| {
            fs::remove_file(&path).unwrap();
            std::os::unix::fs::symlink(&elsewhere, &path).unwrap();
        },
    );
    assert!(matches!(result, Err(Error::Invalid(_))));
    assert_eq!(
        attempts, 1,
        "the symlink must prevent a second persist call"
    );
    assert_eq!(fs::read(elsewhere).unwrap(), b"must remain unchanged");
}

#[test]
fn concurrent_status_readers_and_atomic_writers_observe_complete_snapshots() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("status.json");
    let snapshot = |generation| serde_json::json!({"generation": generation, "mirror": generation, "padding": "x".repeat(512)});
    atomic_json(&path, &snapshot(0)).unwrap();
    let stop = Arc::new(AtomicBool::new(false));
    let start = Arc::new(std::sync::Barrier::new(3));
    let readers: Vec<_> = (0..2)
        .map(|_| {
            let (path, stop, start) = (path.clone(), stop.clone(), start.clone());
            thread::spawn(move || -> Result<usize> {
                let mut reads = 0;
                start.wait();
                while !stop.load(Ordering::Acquire) {
                    let value: serde_json::Value = read_json(&path)?;
                    assert_eq!(value["generation"], value["mirror"]);
                    assert_eq!(value["padding"].as_str().unwrap(), "x".repeat(512));
                    reads += 1;
                    thread::yield_now();
                }
                Ok(reads)
            })
        })
        .collect();
    start.wait();
    let result = (1..=200).try_for_each(|generation| atomic_json(&path, &snapshot(generation)));
    stop.store(true, Ordering::Release);
    for reader in readers {
        assert!(reader.join().unwrap().unwrap() > 0);
    }
    result.unwrap();
    let final_state: serde_json::Value = read_json(&path).unwrap();
    assert_eq!(final_state, snapshot(200));
}

#[cfg(windows)]
#[test]
fn atomic_replace_handles_native_windows_reader_contention() {
    use std::os::windows::fs::OpenOptionsExt;

    let root = tempfile::tempdir().unwrap();
    let path = write(root.path(), "status.json", b"old complete state");
    // Deliberately model an external reader that does not allow delete/rename.
    // This changes this test handle's sharing mode, never file permissions.
    let reader = fs::OpenOptions::new()
        .read(true)
        .share_mode(1 | 2)
        .open(&path)
        .unwrap();
    let file = synced_test_tempfile(root.path(), b"new complete state");
    let failure = file.persist(&path).unwrap_err();
    assert!(
        matches!(failure.error.raw_os_error(), Some(5 | 32)),
        "{failure:?}"
    );
    assert_eq!(fs::read(&path).unwrap(), b"old complete state");
    drop(failure);
    let release = thread::spawn(move || {
        thread::sleep(Duration::from_millis(150));
        drop(reader);
    });
    let result = atomic_bytes(&path, b"new complete state");
    release.join().unwrap();
    result.unwrap();
    assert_eq!(fs::read(&path).unwrap(), b"new complete state");

    // A holder that never releases within the retry budget must fail safely.
    let _reader = fs::OpenOptions::new()
        .read(true)
        .share_mode(1 | 2)
        .open(&path)
        .unwrap();
    let result = atomic_bytes(&path, b"must not replace while denied");
    assert!(
        matches!(
            result,
            Err(Error::Filesystem {
                operation: "atomically replace state",
                ..
            })
        ),
        "{result:?}"
    );
    assert_eq!(fs::read(&path).unwrap(), b"new complete state");
}

#[test]
fn existing_install_adoption_then_two_github_updates_preserve_private_data() {
    let workspace = tempfile::tempdir().unwrap();
    let root = workspace.path().join("existing game with spaces");
    fs::create_dir_all(root.join("assets/arms")).unwrap();
    fs::create_dir_all(root.join("assets/weapons")).unwrap();
    let base_exe = random_bytes(256 * 1024);
    fs::write(root.join(bootstrap::GAME_FILE), &base_exe).unwrap();
    fs::write(
        root.join("assets/arms/first-person.vrs"),
        b"PRIVATE ARM FIXTURE",
    )
    .unwrap();
    fs::write(
        root.join("assets/weapons/hk416a5.vrm"),
        b"PRIVATE WEAPON FIXTURE",
    )
    .unwrap();
    fs::write(root.join("settings.cfg"), b"MY SETTINGS").unwrap();
    let store = bootstrap::adopt(&root).unwrap();
    let adopted = store.state().unwrap().active.unwrap();
    assert_eq!(adopted.version, version("0.0.0"));
    assert_eq!(
        fs::read(store.version_dir(&adopted).join(bootstrap::GAME_FILE)).unwrap(),
        base_exe
    );
    let original_bundle = fs::read(store.bundle_path(&adopted)).unwrap();
    assert!(!original_bundle
        .windows(b"PRIVATE".len())
        .any(|w| w == b"PRIVATE"));
    assert!(!store.version_dir(&adopted).join("assets").exists());
    assert!(!store.version_dir(&adopted).join("settings.cfg").exists());
    // Repeated adoption is idempotent and does not discard installation state.
    assert_eq!(
        bootstrap::adopt(&root)
            .unwrap()
            .state()
            .unwrap()
            .active
            .unwrap()
            .version,
        version("0.0.0")
    );
    let metadata = workspace.path().join("launcher metadata");
    bootstrap::remember_root(&metadata, &root).unwrap();
    assert_eq!(
        bootstrap::find_root(&workspace.path().join("Downloads/RustDuty.exe"), &metadata).unwrap(),
        Some(store.root.clone())
    );
    let expected_paths =
        launch::mapped_arguments(&store.root, &launch::LaunchConfig::default(), &[]).unwrap();
    assert!(expected_paths.contains(&format!(
        "--arms-asset={}",
        store.root.join("assets/arms/first-person.vrs").display()
    )));
    assert!(expected_paths.contains(&format!(
        "--weapon-asset={}",
        store.root.join("assets/weapons/hk416a5.vrm").display()
    )));

    let server = Server::new();
    let first_bundle = bundle_files(&[(bootstrap::GAME_FILE, 1, &base_exe)]);
    let mut first = manifest(&first_bundle);
    first.version = version("1.0.0");
    first.sequence = 1;
    first.entrypoint = bootstrap::GAME_FILE.into();
    first.bundle = asset("game-1.0.0.rdb", &first_bundle);
    server.put(&format!("update-{TARGET}.json"), manifest_bytes(&first));
    server.put(&first.bundle.name, first_bundle.clone());
    let checked = store
        .check(&server.source(), &Trust::production().unwrap(), TARGET)
        .unwrap();
    let staged = store.stage(&server.source(), &checked).unwrap();
    store.activate(staged).unwrap();
    store.finish_launch(true).unwrap();

    let mut updated_exe = base_exe.clone();
    updated_exe.splice(10000..10020, b"NEW VERSION BYTES".iter().copied());
    let second_bundle = bundle_files(&[(bootstrap::GAME_FILE, 1, &updated_exe)]);
    let patch = make_patch(workspace.path(), &first_bundle, &second_bundle);
    assert!(patch.len() < second_bundle.len() / 10);
    let mut second = manifest(&second_bundle);
    second.entrypoint = bootstrap::GAME_FILE.into();
    second.deltas.push(Delta {
        base_version: version("1.0.0"),
        base_sha256: bytes_hash(&first_bundle),
        asset: asset("game-1.0.0-to-1.1.0.rdd", &patch),
    });
    server.put(&format!("update-{TARGET}.json"), manifest_bytes(&second));
    server.put(&second.deltas[0].asset.name, patch);
    // Deliberately omit the full second bundle: delta must succeed independently.
    let checked = store
        .check(&server.source(), &Trust::production().unwrap(), TARGET)
        .unwrap();
    let staged = store.stage(&server.source(), &checked).unwrap();
    assert_eq!(fs::read(store.bundle_path(&staged)).unwrap(), second_bundle);
    store.activate(staged.clone()).unwrap();
    assert_eq!(
        fs::read(store.version_dir(&staged).join(bootstrap::GAME_FILE)).unwrap(),
        updated_exe
    );
    assert_eq!(
        launch::mapped_arguments(&store.root, &launch::LaunchConfig::default(), &[]).unwrap(),
        expected_paths
    );
    assert!(!store.version_dir(&staged).join("assets").exists());
    assert_eq!(
        fs::read(root.join("assets/arms/first-person.vrs")).unwrap(),
        b"PRIVATE ARM FIXTURE"
    );
    assert_eq!(
        fs::read(root.join("assets/weapons/hk416a5.vrm")).unwrap(),
        b"PRIVATE WEAPON FIXTURE"
    );
    assert_eq!(fs::read(root.join("settings.cfg")).unwrap(), b"MY SETTINGS");
    assert!(!server
        .logs()
        .iter()
        .any(|request| request.path.ends_with(&second.bundle.name)));
    store.rollback().unwrap();
    assert_eq!(
        store.state().unwrap().active.unwrap().version,
        version("1.0.0")
    );
    assert_eq!(store.state().unwrap().highest_sequence, 2);
}

#[test]
fn bootstrap_does_not_scan_or_overwrite_existing_launcher() {
    let workspace = tempfile::tempdir().unwrap();
    let missing = workspace.path().join("missing");
    assert!(bootstrap::adopt(&missing).is_err());
    assert!(!missing.exists());
    let root = workspace.path().join("game");
    fs::create_dir(&root).unwrap();
    let source = write(workspace.path(), "bootstrap", b"launcher fixture");
    let installed = bootstrap::install_launcher(&source, &root).unwrap();
    assert_eq!(fs::read(&installed).unwrap(), b"launcher fixture");
    assert_eq!(
        bootstrap::install_launcher(&source, &root).unwrap(),
        installed
    );
    fs::write(&source, b"different executable").unwrap();
    assert!(bootstrap::install_launcher(&source, &root).is_err());
    assert_eq!(fs::read(&installed).unwrap(), b"launcher fixture");
    // An unrelated sibling game folder is never searched.
    fs::write(root.join(bootstrap::GAME_FILE), b"game").unwrap();
    assert_eq!(
        bootstrap::find_root(
            &workspace.path().join("Downloads/bootstrap"),
            &workspace.path().join("metadata")
        )
        .unwrap(),
        None
    );
}
