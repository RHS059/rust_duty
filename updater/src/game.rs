//! In-game updates. The renderer never downloads, hashes or copies a payload.
//! A private copy of the game performs the final replacement after all sessions close.
use crate::{
    atomic_json,
    bootstrap::GAME_FILE,
    bundle,
    download::{self, Control, Progress},
    file_hash,
    install::{Installed, Store},
    invalid, launch,
    manifest::Trust,
    read_json, reject_symlink, safe_dir,
    source::Source,
    Error, Result, TARGET,
};
use fs2::FileExt;
use semver::Version;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{mpsc, Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

const METADATA: &str = ".rust-duty-updates";
const HELPER_FLAG: &str = "--rust-duty-update-helper";
const STARTUP_PLAN: &str = "--rust-duty-update-startup=";
const STARTUP_TOKEN: &str = "--rust-duty-update-startup-token=";
const HELPER_TIMEOUT: Duration = Duration::from_secs(120);

/// Machine-readable state; UI gates must never infer success from display text.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum UpdatePhase {
    #[default]
    Checking,
    Current,
    Paused,
    Cancelled,
    Ready,
    Restarting,
    Unavailable,
}

#[derive(Debug, Clone, Default)]
pub struct UpdateSnapshot {
    pub phase: UpdatePhase,
    pub message: String,
    pub bytes: u64,
    pub total: u64,
    pub running: bool,
    pub ready: bool,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpdateAction {
    Pause,
    Resume,
    Cancel,
    Restart,
}

#[derive(Clone)]
struct Paths {
    root: PathBuf,
    executable: PathBuf,
    target: PathBuf,
    metadata: PathBuf,
}
#[derive(Clone)]
struct Prepared {
    helper: PathBuf,
    plan: PathBuf,
    token: String,
    root: PathBuf,
}
struct Pending {
    child: Child,
    prepared: Prepared,
    deadline: Instant,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Admission {
    token: String,
    helper_pid: u32,
}
#[derive(Default)]
struct Shared {
    snapshot: UpdateSnapshot,
    prepared: Option<Prepared>,
    restarting: bool,
    generation: u64,
}
enum Request {
    Pause,
    Resume,
    Cancel,
    Stop,
}

pub struct GameUpdater {
    shared: Arc<Mutex<Shared>>,
    requests: mpsc::Sender<Request>,
    // Shared for every running game; helper requires an exclusive lock.
    _session: File,
    pending: Option<Pending>,
}

impl GameUpdater {
    pub fn start(version: &str) -> Result<Self> {
        let version = stable_version(version)?;
        let executable = std::env::current_exe()?;
        let paths = locate(&executable)?;
        let args = std::env::args()
            .skip(1)
            .filter(|a| !a.starts_with(STARTUP_PLAN) && !a.starts_with(STARTUP_TOKEN))
            .collect::<Vec<_>>();
        Self::start_at(paths, version, args, None)
    }

    fn start_at(
        paths: Paths,
        version: Version,
        args: Vec<String>,
        source: Option<Source>,
    ) -> Result<Self> {
        safe_dir(&paths.metadata)?;
        hide_metadata(&paths.metadata)?;
        let session = session_file(&paths.metadata)?;
        // Do not block a frame while an already-admitted helper is installing.
        FileExt::try_lock_shared(&session)
            .map_err(|_| invalid("An update is being installed; reopen the game shortly"))?;
        let shared = Arc::new(Mutex::new(Shared {
            snapshot: UpdateSnapshot {
                message: "Checking for updates…".into(),
                running: true,
                ..Default::default()
            },
            ..Default::default()
        }));
        let (tx, rx) = mpsc::channel();
        let state = shared.clone();
        thread::Builder::new()
            .name("game-updater".into())
            .spawn(move || {
                if let Err(error) = coordinate(paths, version, args, source, rx, state.clone()) {
                    let mut state = state.lock().unwrap();
                    state.snapshot.running = false;
                    state.snapshot.ready = false;
                    state.snapshot.phase = UpdatePhase::Unavailable;
                    state.snapshot.message = format!("Update check unavailable: {error}");
                }
            })?;
        Ok(Self {
            shared,
            requests: tx,
            _session: session,
            pending: None,
        })
    }

    pub fn snapshot(&mut self) -> UpdateSnapshot {
        self.shared.lock().unwrap().snapshot.clone()
    }

    /// First call starts the helper; poll until true confirms validated helper admission.
    pub fn action(&mut self, action: UpdateAction) -> Result<bool> {
        if action == UpdateAction::Restart {
            if let Some(pending) = self.pending.as_mut() {
                match poll_admission(pending) {
                    Ok(true) => {
                        self.pending.take();
                        return Ok(true);
                    }
                    Ok(false) => return Ok(false),
                    Err(error) => {
                        let mut pending = self.pending.take().unwrap();
                        let _ = pending.child.kill();
                        let _ = pending.child.wait();
                        let mut state = self.shared.lock().unwrap();
                        state.prepared = Some(pending.prepared);
                        state.restarting = false;
                        state.snapshot.ready = true;
                        state.snapshot.phase = UpdatePhase::Ready;
                        state.snapshot.message = format!("Restart not admitted: {error}");
                        return Err(error);
                    }
                }
            }
            let prepared = {
                let mut state = self.shared.lock().unwrap();
                if state.restarting {
                    return Ok(false);
                }
                let prepared = state
                    .prepared
                    .take()
                    .ok_or_else(|| invalid("No verified update is ready to restart"))?;
                state.restarting = true;
                state.snapshot.ready = false;
                state.snapshot.phase = UpdatePhase::Restarting;
                state.snapshot.message = "Restarting to install the verified update…".into();
                prepared
            };
            let mut command = Command::new(&prepared.helper);
            command
                .arg(HELPER_FLAG)
                .arg(format!("--update-plan={}", prepared.plan.display()))
                .arg(format!("--update-token={}", prepared.token))
                .current_dir(&prepared.root)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            hide_process(&mut command);
            match command.spawn() {
                Ok(child) => {
                    self.pending = Some(Pending {
                        child,
                        prepared,
                        deadline: Instant::now() + Duration::from_secs(30),
                    });
                    return Ok(false);
                }
                Err(error) => {
                    let mut state = self.shared.lock().unwrap();
                    state.prepared = Some(prepared);
                    state.restarting = false;
                    state.snapshot.ready = true;
                    state.snapshot.phase = UpdatePhase::Ready;
                    state.snapshot.message = format!("Could not start update helper: {error}");
                    return Err(error.into());
                }
            }
        }
        if action == UpdateAction::Cancel {
            if let Some(mut pending) = self.pending.take() {
                let _ = pending.child.kill();
                let _ = pending.child.wait();
            }
            let mut state = self.shared.lock().unwrap();
            state.generation += 1;
            state.prepared = None;
            state.restarting = false;
            state.snapshot.ready = false;
            state.snapshot.phase = UpdatePhase::Cancelled;
            state.snapshot.message = "Cancelling update…".into();
        }
        let request = match action {
            UpdateAction::Pause => Request::Pause,
            UpdateAction::Resume => Request::Resume,
            UpdateAction::Cancel => Request::Cancel,
            UpdateAction::Restart => unreachable!(),
        };
        self.requests
            .send(request)
            .map_err(|_| invalid("Update worker has stopped"))?;
        Ok(false)
    }
}
impl Drop for GameUpdater {
    fn drop(&mut self) {
        let _ = self.requests.send(Request::Stop);
    }
}

fn poll_admission(pending: &mut Pending) -> Result<bool> {
    if let Some(status) = pending.child.try_wait()? {
        let detail =
            read_json::<String>(&pending.prepared.plan.parent().unwrap().join("result.json"))
                .unwrap_or_else(|_| format!("helper exited before admission: {status}"));
        return Err(invalid(detail));
    }
    let ack = pending
        .prepared
        .plan
        .parent()
        .unwrap()
        .join("admitted.json");
    if ack.exists() {
        let admission: Admission = read_json(&ack)?;
        if admission.token != pending.prepared.token {
            return Err(invalid("helper acknowledgement token mismatch"));
        }
        if admission.helper_pid == pending.child.id() {
            return Ok(true);
        }
        // A retried helper must write its own acknowledgement, not reuse an old PID.
    }
    if Instant::now() >= pending.deadline {
        return Err(invalid("helper admission timed out"));
    }
    Ok(false)
}
fn preflight(plan: &Plan) -> Result<()> {
    let store = Store::open(&plan.root.join(METADATA))?;
    let bundle = store.bundle_path(&plan.installed);
    let candidate = store.version_dir(&plan.installed).join(GAME_FILE);
    reject_symlink(&bundle)?;
    reject_symlink(&candidate)?;
    let state = store.state()?;
    if plan.installed.sequence <= state.highest_sequence
        || state
            .active
            .as_ref()
            .is_some_and(|v| plan.installed.version <= v.version)
    {
        return Err(invalid(
            "staged update was superseded; restart is not admitted",
        ));
    }
    if file_hash(&bundle)? != plan.installed.bundle_sha256
        || file_hash(&candidate)? != plan.new_sha256
    {
        return Err(invalid("staged update changed before helper admission"));
    }
    verify_old(plan)
}

/// Headless smoke driver for the SAME controller, called before a graphical window.
/// --update-headless [--update-apply] [--update-timeout-seconds=120]
pub fn dispatch_headless(version: &str) -> Option<i32> {
    let args = std::env::args().collect::<Vec<_>>();
    if !args.iter().any(|a| a == "--update-headless") {
        return None;
    }
    let apply = args.iter().any(|a| a == "--update-apply");
    let mut terminal = "error";
    let result = (|| {
        let timeout = args
            .iter()
            .find_map(|a| a.strip_prefix("--update-timeout-seconds="))
            .map(|v| {
                v.parse::<u64>()
                    .map_err(|_| invalid("invalid update timeout"))
            })
            .transpose()?
            .unwrap_or(120);
        if !(1..=600).contains(&timeout) {
            return Err(invalid("update timeout must be1..600seconds"));
        }
        let mut updater = GameUpdater::start(version)?;
        mark_ready_sync(version)?;
        let until = Instant::now() + Duration::from_secs(timeout);
        let mut previous = String::new();
        let mut restarting = false;
        loop {
            let snapshot = updater.snapshot();
            let line = serde_json::json!({"running_version":version,"message":snapshot.message,
                "bytes":snapshot.bytes,"total":snapshot.total,"running":snapshot.running,"ready":snapshot.ready}).to_string();
            if line != previous {
                println!("{line}");
                previous = line;
            }
            if apply && (snapshot.ready || restarting) {
                restarting = true;
                if updater.action(UpdateAction::Restart)? {
                    println!(
                        "{}",
                        serde_json::json!({"running_version":version,"helper_admitted":true})
                    );
                    terminal = "helper_admitted";
                    return Ok(());
                }
            } else if !snapshot.running {
                if snapshot.ready || snapshot.phase == UpdatePhase::Current {
                    terminal = if snapshot.ready { "ready" } else { "current" };
                    return Ok(());
                }
                return Err(invalid(snapshot.message));
            }
            if Instant::now() >= until {
                return Err(invalid("headless update timed out; partial bytes retained"));
            }
            thread::sleep(Duration::from_millis(40));
        }
    })();
    let code = if result.is_ok() { 0 } else { 1 };
    if let Ok(executable) = std::env::current_exe() {
        if let Ok(paths) = locate(&executable) {
            let _ = safe_dir(&paths.metadata);
            let proof = serde_json::json!({"version":version,"pid":std::process::id(),"status":terminal,"exit_code":code,
                "executable":executable,"sha256":file_hash(&executable).ok(),"message":result.as_ref().err().map(ToString::to_string)});
            let _ = atomic_json(&paths.metadata.join("headless-result.json"), &proof);
        }
    }
    match result {
        Ok(()) => Some(0),
        Err(error) => {
            eprintln!("{error}");
            Some(1)
        }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StartupReady {
    token: String,
    pid: u32,
    executable: PathBuf,
    sha256: String,
    version: Version,
}

/// Call only after successful graphical/asset initialization. Hashing and acknowledgement
/// writing happen off the render thread. Normal launches without a startup token are a no-op.
pub fn mark_ready(version: &str) -> Result<()> {
    if !std::env::args().any(|a| a.starts_with(STARTUP_PLAN)) {
        return Ok(());
    }
    let version = version.to_owned();
    thread::Builder::new()
        .name("update-startup-ack".into())
        .spawn(move || {
            if let Err(error) = mark_ready_sync(&version) {
                eprintln!("Update startup acknowledgement failed: {error}");
            }
        })?;
    Ok(())
}
fn mark_ready_sync(version: &str) -> Result<()> {
    let args = std::env::args().collect::<Vec<_>>();
    let plans = args
        .iter()
        .filter_map(|a| a.strip_prefix(STARTUP_PLAN))
        .collect::<Vec<_>>();
    let tokens = args
        .iter()
        .filter_map(|a| a.strip_prefix(STARTUP_TOKEN))
        .collect::<Vec<_>>();
    if plans.is_empty() && tokens.is_empty() {
        return Ok(());
    }
    if plans.len() != 1 || tokens.len() != 1 {
        return Err(invalid("invalid update startup arguments"));
    }
    let path = Path::new(plans[0]);
    let plan: Plan = read_json(path)?;
    validate_plan(&plan, path, &plan.helper, tokens[0])?;
    let executable = std::env::current_exe()?.canonicalize()?;
    let version = stable_version(version)?;
    let sha256 = file_hash(&executable)?;
    validate_startup_identity(&plan, &executable, &version, &sha256)?;
    atomic_json(
        &job_dir(&plan).join("startup-ready.json"),
        &StartupReady {
            token: plan.token,
            pid: std::process::id(),
            executable,
            sha256,
            version,
        },
    )
}

fn validate_startup_identity(
    plan: &Plan,
    executable: &Path,
    version: &Version,
    sha256: &str,
) -> Result<()> {
    // Windows current_exe may omit the extended-length prefix that canonicalize adds.
    // Resolve both absolute paths instead of weakening identity to a filename/string test.
    reject_symlink(executable)?;
    reject_symlink(&plan.target)?;
    if !executable.is_absolute()
        || executable.canonicalize()? != plan.target.canonicalize()?
        || *version != plan.installed.version
        || sha256 != plan.new_sha256
    {
        return Err(invalid(
            "replacement startup identity/version/hash mismatch",
        ));
    }
    Ok(())
}

fn validate_startup_ack(plan: &Plan, ack: &StartupReady, child_pid: u32) -> Result<bool> {
    if ack.pid != child_pid {
        return Ok(false);
    }
    if ack.token != plan.token {
        return Err(invalid(
            "replacement startup acknowledgement token mismatch",
        ));
    }
    validate_startup_identity(plan, &ack.executable, &ack.version, &ack.sha256)?;
    Ok(true)
}

fn stable_version(value: &str) -> Result<Version> {
    let version =
        Version::parse(value).map_err(|e| invalid(format!("invalid running game version: {e}")))?;
    if !version.pre.is_empty() || !version.build.is_empty() {
        return Err(invalid("stable game version required"));
    }
    Ok(version)
}

fn locate(executable: &Path) -> Result<Paths> {
    reject_symlink(executable)?;
    let executable = executable.canonicalize()?;
    let parent = executable
        .parent()
        .ok_or_else(|| invalid("game has no parent directory"))?;
    // Recognize a legacy launcher version only by its validated version record.
    // Never infer a persistent root merely from a folder named `versions`.
    for directory in parent.ancestors().take(5) {
        let Some(versions) = directory.parent() else {
            continue;
        };
        if versions.file_name().and_then(|x| x.to_str()) != Some("versions") {
            continue;
        }
        let record = directory.join("version.json");
        if !record.is_file() {
            continue;
        }
        let installed: Installed = read_json(&record)?;
        bundle::safe_path(&installed.entrypoint)?;
        if directory.file_name().and_then(|x| x.to_str()) != Some(installed.directory().as_str())
            || directory.join(&installed.entrypoint).canonicalize()? != executable
        {
            continue;
        }
        let store_root = versions
            .parent()
            .ok_or_else(|| invalid("invalid version root"))?;
        let root = if store_root.file_name().and_then(|x| x.to_str()) == Some(METADATA) {
            store_root
                .parent()
                .ok_or_else(|| invalid("invalid update root"))?
        } else {
            store_root
        };
        reject_symlink(root)?;
        let root = root.canonicalize()?;
        return Ok(Paths {
            target: root.join(GAME_FILE),
            metadata: root.join(METADATA),
            root,
            executable,
        });
    }
    Ok(Paths {
        root: parent.to_owned(),
        target: executable.clone(),
        metadata: parent.join(METADATA),
        executable,
    })
}

fn session_file(metadata: &Path) -> Result<File> {
    let path = metadata.join("session.lock");
    reject_symlink(&path)?;
    Ok(OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)?)
}

fn coordinate(
    paths: Paths,
    running: Version,
    args: Vec<String>,
    source: Option<Source>,
    requests: mpsc::Receiver<Request>,
    shared: Arc<Mutex<Shared>>,
) -> Result<()> {
    let store = Store::open(&paths.metadata)?;
    let engine_lease = Arc::new(store.lock()?);
    ensure_baseline(&store, &paths.executable, &running)?;
    let source = source.map(Ok).unwrap_or_else(Source::github)?;
    let preference_path = store.root.join("user-control.json");
    let mut preference: Control = if preference_path.is_file() {
        read_json(&preference_path)?
    } else {
        Control::Running
    };
    download::set_control(&store.root, preference)?;
    if preference == Control::Cancelled {
        download::cancel_partial(&store.root)?;
    }
    if preference != Control::Running {
        let mut s = shared.lock().unwrap();
        s.snapshot.running = false;
        s.snapshot.phase = if preference == Control::Paused {
            UpdatePhase::Paused
        } else {
            UpdatePhase::Cancelled
        };
        s.snapshot.message = if preference == Control::Paused {
            "Download paused. Resume to continue."
        } else {
            "Updates cancelled. Resume to check again."
        }
        .into();
    }
    let (done_tx, done_rx) = mpsc::channel::<(u64, Result<Prepared>)>();
    let mut active = false;
    let mut requested = preference == Control::Running;
    let mut cancelled = preference == Control::Cancelled;
    loop {
        match requests.recv_timeout(Duration::from_millis(80)) {
            Ok(Request::Stop) | Err(mpsc::RecvTimeoutError::Disconnected) => {
                let stop = if preference == Control::Cancelled {
                    Control::Cancelled
                } else {
                    Control::Paused
                };
                let _ = download::set_control(&store.root, stop);
                return Ok(());
            }
            Ok(Request::Pause) => {
                requested = false;
                preference = Control::Paused;
                atomic_json(&preference_path, &preference)?;
                download::set_control(&store.root, preference)?;
                let mut s = shared.lock().unwrap();
                s.snapshot.phase = UpdatePhase::Paused;
                s.snapshot.message = "Pausing download…".into();
                if !active {
                    s.snapshot.running = false;
                }
            }
            Ok(Request::Resume) => {
                cancelled = false;
                preference = Control::Running;
                atomic_json(&preference_path, &preference)?;
                download::set_control(&store.root, preference)?;
                if shared.lock().unwrap().prepared.is_none() {
                    requested = true;
                }
            }
            Ok(Request::Cancel) => {
                requested = false;
                cancelled = true;
                preference = Control::Cancelled;
                atomic_json(&preference_path, &preference)?;
                download::set_control(&store.root, preference)?;
                let mut s = shared.lock().unwrap();
                s.prepared = None;
                s.snapshot.ready = false;
                s.snapshot.phase = UpdatePhase::Cancelled;
                s.snapshot.message = "Cancelling update; current game is unchanged…".into();
                if !active {
                    s.snapshot.running = false;
                }
                if !active {
                    download::cancel_partial(&store.root)?;
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => (),
        }
        if let Ok((completed_generation, result)) = done_rx.try_recv() {
            active = false;
            let mut s = shared.lock().unwrap();
            s.snapshot.running = false;
            if cancelled || completed_generation != s.generation {
                s.prepared = None;
                s.snapshot.ready = false;
                s.snapshot.phase = UpdatePhase::Cancelled;
                s.snapshot.message = "Update cancelled; current game is unchanged".into();
                download::cancel_partial(&store.root)?;
            } else {
                match result {
                    Ok(prepared) => {
                        s.prepared = Some(prepared);
                        s.snapshot.ready = true;
                        s.snapshot.phase = UpdatePhase::Ready;
                        s.snapshot.message = "Update ready. Restart to install it.".into();
                        requested = false;
                    }
                    Err(Error::UpToDate) => {
                        s.snapshot.phase = UpdatePhase::Current;
                        s.snapshot.message =
                            format!("Version {running} is current; no newer update")
                    }
                    Err(Error::Paused) => {
                        s.snapshot.phase = UpdatePhase::Paused;
                        s.snapshot.message =
                            "Download paused. Resume continues the verified download.".into()
                    }
                    Err(Error::Cancelled) => {
                        s.snapshot.phase = UpdatePhase::Cancelled;
                        s.snapshot.message = "Update cancelled; current game is unchanged".into()
                    }
                    Err(error) => {
                        s.snapshot.phase = UpdatePhase::Unavailable;
                        s.snapshot.message =
                            format!("Update unavailable: {error}. Resume to retry.")
                    }
                }
            }
        }
        if active {
            if let Ok(progress) = read_json::<Progress>(&store.root.join("status.json")) {
                let mut s = shared.lock().unwrap();
                s.snapshot.bytes = progress.bytes;
                s.snapshot.total = progress.total;
                s.snapshot.message = progress.message;
            }
        }
        if requested && !active {
            requested = false;
            active = true;
            {
                let mut s = shared.lock().unwrap();
                s.snapshot.running = true;
                s.snapshot.phase = UpdatePhase::Checking;
                s.snapshot.bytes = 0;
                s.snapshot.total = 0;
                s.snapshot.ready = false;
                s.snapshot.message = "Checking for a newer release…".into();
            }
            let generation = shared.lock().unwrap().generation;
            let (store, source, paths, running, args, tx) = (
                store.clone(),
                source.clone(),
                paths.clone(),
                running.clone(),
                args.clone(),
                done_tx.clone(),
            );
            let lease = engine_lease.clone();
            thread::Builder::new()
                .name("game-update-transfer".into())
                .spawn(move || {
                    let _lease = lease;
                    let result = check_and_prepare(&store, &source, &paths, &running, &args);
                    let _ = tx.send((generation, result));
                })?;
        }
    }
}

fn ensure_baseline(store: &Store, executable: &Path, running: &Version) -> Result<()> {
    if store.state()?.active.is_some() {
        return Ok(());
    }
    reject_symlink(executable)?;
    let mut source = File::open(executable)?;
    let size = source.metadata()?.len();
    if size == 0 || size > crate::MAX_ASSET - 1024 {
        return Err(invalid("invalid running executable size"));
    }
    let mut baseline = tempfile::NamedTempFile::new_in(store.root.join("cache"))?;
    baseline.write_all(bundle::MAGIC)?;
    baseline.write_all(&1u32.to_le_bytes())?;
    baseline.write_all(&(GAME_FILE.len() as u16).to_le_bytes())?;
    baseline.write_all(GAME_FILE.as_bytes())?;
    baseline.write_all(&[1])?;
    baseline.write_all(&size.to_le_bytes())?;
    if std::io::copy(&mut source, &mut baseline)? != size {
        return Err(invalid(
            "running executable changed during baseline capture",
        ));
    }
    baseline.as_file().sync_all()?;
    store.install_local(baseline.path(), running.clone(), GAME_FILE)
}

fn check_and_prepare(
    store: &Store,
    source: &Source,
    paths: &Paths,
    running: &Version,
    args: &[String],
) -> Result<Prepared> {
    let cache = store.root.join("manifest.cache.json");
    let (bytes, discovery_error) = match source.latest(TARGET) {
        Ok(bytes) => {
            Trust::production()?.verify(&bytes, TARGET)?;
            crate::atomic_bytes(&cache, &bytes)?;
            (bytes, None)
        }
        Err(error) if cache.is_file() => {
            reject_symlink(&cache)?;
            if cache.metadata()?.len() > crate::MAX_MANIFEST {
                return Err(invalid("oversized cached manifest"));
            }
            (fs::read(&cache)?, Some(error))
        }
        Err(error) => return Err(error),
    };
    let manifest = Trust::production()?.verify(&bytes, TARGET)?;
    // This gate precedes persisted Store state, including manually installed builds.
    if manifest.version <= *running {
        // Cached metadata may safely identify a newer candidate, but it cannot
        // prove that the installed build is current when discovery is offline.
        return Err(discovery_error.unwrap_or(Error::UpToDate));
    }
    store.check_newer(&manifest).map_err(|error| match error {
        Error::UpToDate => invalid("A newer build is recorded locally; reopen the updated game"),
        error => error,
    })?;
    if manifest.entrypoint != GAME_FILE {
        return Err(invalid(
            "update must contain the game executable as its entrypoint",
        ));
    }
    let installed = store.stage(source, &manifest)?;
    match download::control(&store.root)? {
        Control::Paused => return Err(Error::Paused),
        Control::Cancelled => return Err(Error::Cancelled),
        Control::Running => (),
    }
    prepare_restart(paths, store, running, installed, args, std::process::id())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Plan {
    schema: u32,
    token: String,
    root: PathBuf,
    target: PathBuf,
    helper: PathBuf,
    parent_pid: u32,
    running_version: Version,
    installed: Installed,
    helper_sha256: String,
    old_sha256: Option<String>,
    new_sha256: String,
    args: Vec<String>,
}
fn job_dir(plan: &Plan) -> PathBuf {
    plan.root.join(METADATA).join("jobs").join(&plan.token)
}
fn token() -> Result<String> {
    let mut bytes = [0u8; 16];
    getrandom::getrandom(&mut bytes)
        .map_err(|e| invalid(format!("random token unavailable: {e}")))?;
    Ok(hex::encode(bytes))
}
fn prepare_restart(
    paths: &Paths,
    store: &Store,
    running: &Version,
    installed: Installed,
    args: &[String],
    parent_pid: u32,
) -> Result<Prepared> {
    let token = token()?;
    let jobs = paths.metadata.join("jobs");
    safe_dir(&jobs)?;
    let directory = jobs.join(&token);
    reject_symlink(&directory)?;
    fs::create_dir(&directory)?;
    let helper = directory.join(if cfg!(windows) {
        "helper.exe"
    } else {
        "helper"
    });
    copy_new(&paths.executable, &helper)?;
    let staged = store.version_dir(&installed).join(&installed.entrypoint);
    reject_symlink(&staged)?;
    reject_symlink(&paths.target)?;
    let args = launch::mapped_arguments(&paths.root, &launch::load(&paths.root)?, args)?;
    let plan = Plan {
        schema: 1,
        token: token.clone(),
        root: paths.root.clone(),
        target: paths.target.clone(),
        helper: helper.clone(),
        parent_pid,
        running_version: running.clone(),
        installed,
        helper_sha256: file_hash(&helper)?,
        old_sha256: if paths.target.exists() {
            Some(file_hash(&paths.target)?)
        } else {
            None
        },
        new_sha256: file_hash(&staged)?,
        args,
    };
    let plan_path = directory.join("plan.json");
    atomic_json(&plan_path, &plan)?;
    validate_plan(&plan, &plan_path, &helper, &token)?;
    Ok(Prepared {
        helper,
        plan: plan_path,
        token,
        root: paths.root.clone(),
    })
}

fn validate_plan(
    plan: &Plan,
    plan_path: &Path,
    executable: &Path,
    supplied_token: &str,
) -> Result<()> {
    if plan.schema != 1
        || plan.token != supplied_token
        || plan.token.len() != 32
        || !plan
            .token
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        || plan.parent_pid == 0
        || plan.installed.version <= plan.running_version
        || plan.installed.sequence == 0
        || plan.installed.entrypoint != GAME_FILE
        || !crate::manifest::valid_hash(&plan.new_sha256)
        || !crate::manifest::valid_hash(&plan.helper_sha256)
        || plan
            .old_sha256
            .as_ref()
            .is_some_and(|h| !crate::manifest::valid_hash(h))
        || !crate::manifest::valid_hash(&plan.installed.bundle_sha256)
        || !plan.installed.version.pre.is_empty()
        || !plan.installed.version.build.is_empty()
    {
        return Err(invalid("invalid update helper plan"));
    }
    for path in [
        &plan.root,
        &plan.target,
        &plan.helper,
        plan_path,
        executable,
    ] {
        reject_symlink(path)?;
    }
    if !plan.root.is_absolute()
        || plan.root.canonicalize()? != plan.root
        || plan.target.parent() != Some(plan.root.as_path())
        || !plan
            .target
            .file_name()
            .and_then(|s| s.to_str())
            .is_some_and(crate::manifest::safe_name)
        || plan_path != job_dir(plan).join("plan.json")
        || plan.helper
            != job_dir(plan).join(if cfg!(windows) {
                "helper.exe"
            } else {
                "helper"
            })
        || executable.canonicalize()? != plan.helper.canonicalize()?
        || file_hash(executable)? != plan.helper_sha256
    {
        return Err(invalid(
            "update helper path or executable validation failed",
        ));
    }
    // Revalidate already-absolute user paths and portable command-line bounds.
    let remapped =
        launch::mapped_arguments(&plan.root, &launch::LaunchConfig::default(), &plan.args)?;
    if remapped != plan.args {
        return Err(invalid(
            "restart arguments are not stable absolute mappings",
        ));
    }
    Ok(())
}

/// Call before window initialization. A normal game launch returns None.
pub fn dispatch_helper() -> Option<i32> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if !args.iter().any(|a| a == HELPER_FLAG) {
        return None;
    }
    let result = (|| {
        if args.len() != 3 {
            return Err(invalid("invalid helper arguments"));
        }
        let path = args
            .iter()
            .find_map(|a| a.strip_prefix("--update-plan="))
            .ok_or_else(|| invalid("missing helper plan"))?;
        let token = args
            .iter()
            .find_map(|a| a.strip_prefix("--update-token="))
            .ok_or_else(|| invalid("missing helper token"))?;
        run_helper(Path::new(path), token, &std::env::current_exe()?)
    })();
    match result {
        Ok(()) => Some(0),
        Err(e) => {
            eprintln!("Update helper failed: {e}");
            Some(1)
        }
    }
}

fn run_helper(path: &Path, token: &str, executable: &Path) -> Result<()> {
    let plan: Plan = read_json(path)?;
    validate_plan(&plan, path, executable, token)?;
    let mut parent_closed = false;
    let result = (|| {
        preflight(&plan)?;
        atomic_json(
            &job_dir(&plan).join("admitted.json"),
            &Admission {
                token: plan.token.clone(),
                helper_pid: std::process::id(),
            },
        )?;
        wait_parent(plan.parent_pid, HELPER_TIMEOUT)?;
        parent_closed = true;
        let session = session_file(&plan.root.join(METADATA))?;
        wait_exclusive(&session, HELPER_TIMEOUT)?;
        apply_and_launch(&plan, session)
    })();
    if result.is_err() && parent_closed && plan.old_sha256.is_some() && verify_old(&plan).is_ok() {
        let mut old = Command::new(&plan.target);
        old.current_dir(&plan.root).args(
            plan.args
                .iter()
                .filter(|arg| arg.as_str() != "--update-apply"),
        );
        hide_process(&mut old);
        let _ = old.spawn();
    }
    let message = match &result {
        Ok(()) => "Update installed and replacement startup acknowledged".to_string(),
        Err(e) => format!("Update failed: {e}; previous executable retained or restored"),
    };
    let _ = atomic_json(&job_dir(&plan).join("result.json"), &message);
    result
}

fn apply_and_launch(plan: &Plan, session: File) -> Result<()> {
    let store = Store::open(&plan.root.join(METADATA))?;
    let engine_lock = store.lock()?;
    let before = store.state()?;
    if plan.installed.sequence <= before.highest_sequence
        || before
            .active
            .as_ref()
            .is_some_and(|a| plan.installed.version <= a.version)
    {
        return Err(invalid("staged update was superseded; refusing replay"));
    }
    let payload = store.bundle_path(&plan.installed);
    reject_symlink(&payload)?;
    if file_hash(&payload)? != plan.installed.bundle_sha256 {
        return Err(invalid("staged bundle hash changed"));
    }
    let verified = tempfile::Builder::new()
        .prefix("verified-")
        .tempdir_in(job_dir(plan))?;
    bundle::unpack(&payload, verified.path(), GAME_FILE)?;
    let candidate = verified.path().join(GAME_FILE);
    if file_hash(&candidate)? != plan.new_sha256 {
        return Err(invalid(
            "staged executable does not match the verified bundle",
        ));
    }
    verify_old(plan)?;
    let backup = job_dir(plan).join("previous.exe");
    if let Some(expected) = &plan.old_sha256 {
        if backup.exists() {
            reject_symlink(&backup)?;
            if file_hash(&backup)? != *expected {
                return Err(invalid("backup changed before replacement"));
            }
        } else {
            copy_new(&plan.target, &backup)?;
        }
    }
    atomic_json(&job_dir(plan).join("previous-state.json"), &before)?;
    replace_executable(&candidate, &plan.target, &plan.new_sha256)?;
    let mut after = before.clone();
    after.previous = before.active.clone();
    after.last_good = Some(plan.installed.clone());
    after.active = Some(plan.installed.clone());
    after.highest_sequence = plan.installed.sequence;
    after.pending_launch = false;
    if let Err(error) = store.save(&after) {
        rollback_file(plan, &backup)?;
        let mut restored = before.clone();
        restored.highest_sequence = restored.highest_sequence.max(plan.installed.sequence);
        store.save(&restored)?;
        return Err(error);
    }
    // New game needs both locks. Its startup must not contend with this helper.
    drop(engine_lock);
    drop(session);
    let launched = launch_replacement(plan);
    if let Err(error) = launched {
        let session = session_file(&store.root)?;
        wait_exclusive(&session, Duration::from_secs(5))?;
        let _engine_lock = store.lock()?;
        if file_hash(&plan.target)? != plan.new_sha256 {
            return Err(invalid("replacement changed; refusing unsafe rollback"));
        }
        rollback_file(plan, &backup)?;
        let mut restored = before.clone();
        restored.highest_sequence = restored.highest_sequence.max(plan.installed.sequence);
        store.save(&restored)?;
        return Err(error);
    }
    Ok(())
}
fn verify_old(plan: &Plan) -> Result<()> {
    reject_symlink(&plan.target)?;
    match (&plan.old_sha256, plan.target.exists()) {
        (Some(expected), true) if file_hash(&plan.target)? == *expected => Ok(()),
        (None, false) => Ok(()),
        _ => Err(invalid("game executable changed since update preparation")),
    }
}
fn rollback_file(plan: &Plan, backup: &Path) -> Result<()> {
    if let Some(hash) = &plan.old_sha256 {
        replace_executable(backup, &plan.target, hash)
    } else {
        reject_symlink(&plan.target)?;
        if file_hash(&plan.target)? != plan.new_sha256 {
            return Err(invalid("refusing to remove an unexpected executable"));
        }
        fs::remove_file(&plan.target)?;
        crate::sync_dir(&plan.root)
    }
}
fn launch_replacement(plan: &Plan) -> Result<()> {
    let mut command = Command::new(&plan.target);
    command
        .current_dir(&plan.root)
        .args(&plan.args)
        .arg(format!(
            "{STARTUP_PLAN}{}",
            job_dir(plan).join("plan.json").display()
        ))
        .arg(format!("{STARTUP_TOKEN}{}", plan.token));
    hide_process(&mut command);
    let mut child = command.spawn()?;
    let until = Instant::now() + Duration::from_secs(60);
    let ack_path = job_dir(plan).join("startup-ready.json");
    let headless = plan.args.iter().any(|arg| arg == "--update-headless");
    let mut acknowledged = false;
    let result = (|| {
        loop {
            if ack_path.is_file() {
                let ack: StartupReady = read_json(&ack_path)?;
                if validate_startup_ack(plan, &ack, child.id())? {
                    acknowledged = true;
                    if !headless {
                        return Ok(());
                    }
                }
            }
            if let Some(status) = child.try_wait()? {
                return if status.success() && acknowledged {
                    Ok(())
                } else {
                    Err(invalid(format!(
                        "replacement exited without a healthy startup acknowledgement: {status}"
                    )))
                };
            }
            if Instant::now() >= until {
                // Only our own unacknowledged replacement process is stopped, never another game.
                return Err(invalid(
                    "replacement did not acknowledge startup within60seconds",
                ));
            }
            thread::sleep(Duration::from_millis(40));
        }
    })();
    if result.is_err() {
        let _ = child.kill();
        let _ = child.wait();
    }
    result
}

fn copy_new(source: &Path, destination: &Path) -> Result<()> {
    reject_symlink(source)?;
    reject_symlink(destination)?;
    let mut input = File::open(source)?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)?;
    std::io::copy(&mut input, &mut output)?;
    output.sync_all()?;
    fs::set_permissions(destination, input.metadata()?.permissions())?;
    if file_hash(source)? != file_hash(destination)? {
        return Err(invalid("copy hash mismatch"));
    }
    Ok(())
}
fn replace_executable(source: &Path, destination: &Path, expected_hash: &str) -> Result<()> {
    reject_symlink(source)?;
    reject_symlink(destination)?;
    let parent = destination
        .parent()
        .ok_or_else(|| invalid("missing game directory"))?;
    let mut input = File::open(source)?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent)?;
    std::io::copy(&mut input, &mut temporary)?;
    temporary.as_file().sync_all()?;
    temporary
        .as_file()
        .set_permissions(input.metadata()?.permissions())?;
    if file_hash(temporary.path())? != expected_hash {
        return Err(invalid("replacement hash mismatch"));
    }
    crate::persist_with_retry(
        temporary,
        destination,
        cfg!(windows),
        |f, p| f.persist(p),
        thread::sleep,
    )?;
    crate::sync_dir(parent)
}
fn wait_exclusive(file: &File, timeout: Duration) -> Result<()> {
    let until = Instant::now() + timeout;
    loop {
        match file.try_lock_exclusive() {
            Ok(()) => return Ok(()),
            Err(e)
                if e.kind() == std::io::ErrorKind::WouldBlock
                    || matches!(e.raw_os_error(), Some(32 | 33)) => {}
            Err(e) => return Err(e.into()),
        }
        if Instant::now() >= until {
            return Err(invalid(
                "other game sessions are still open; update was not applied",
            ));
        }
        thread::sleep(Duration::from_millis(50));
    }
}
#[cfg(windows)]
fn wait_parent(pid: u32, timeout: Duration) -> Result<()> {
    use windows_sys::Win32::{
        Foundation::{CloseHandle, WAIT_OBJECT_0},
        System::Threading::{OpenProcess, WaitForSingleObject},
    };
    unsafe {
        let handle = OpenProcess(0x00100000, 0, pid);
        if handle.is_null() {
            let error = std::io::Error::last_os_error();
            return if error.raw_os_error() == Some(87) {
                Ok(())
            } else {
                Err(error.into())
            };
        }
        let result = WaitForSingleObject(handle, timeout.as_millis().min(u32::MAX as u128) as u32);
        CloseHandle(handle);
        if result == WAIT_OBJECT_0 {
            Ok(())
        } else {
            Err(invalid(
                "game process did not close; update was not applied",
            ))
        }
    }
}
#[cfg(unix)]
fn wait_parent(pid: u32, timeout: Duration) -> Result<()> {
    let until = Instant::now() + timeout;
    loop {
        let exists = unsafe { libc::kill(pid as i32, 0) } == 0;
        if !exists {
            let error = std::io::Error::last_os_error();
            if error.raw_os_error() == Some(libc::ESRCH) {
                return Ok(());
            }
            return Err(error.into());
        }
        if Instant::now() >= until {
            return Err(invalid(
                "game process did not close; update was not applied",
            ));
        }
        thread::sleep(Duration::from_millis(50));
    }
}
#[cfg(not(any(unix, windows)))]
fn wait_parent(_: u32, _: Duration) -> Result<()> {
    Err(invalid(
        "in-game replacement is unsupported on this platform",
    ))
}
#[cfg(windows)]
fn hide_process(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(0x08000000);
}
#[cfg(not(windows))]
fn hide_process(_: &mut Command) {}
#[cfg(windows)]
fn hide_metadata(path: &Path) -> Result<()> {
    use std::os::windows::{ffi::OsStrExt, fs::MetadataExt};
    use windows_sys::Win32::Storage::FileSystem::SetFileAttributesW;
    let wide = path
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let attrs = fs::metadata(path)?.file_attributes();
    if unsafe { SetFileAttributesW(wide.as_ptr(), attrs | 2) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}
#[cfg(not(windows))]
fn hide_metadata(_: &Path) -> Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        bytes_hash,
        manifest::{Asset, Manifest},
        tests::Server,
    };

    fn archive(bytes: &[u8]) -> Vec<u8> {
        let mut out = bundle::MAGIC.to_vec();
        out.extend(1u32.to_le_bytes());
        out.extend((GAME_FILE.len() as u16).to_le_bytes());
        out.extend(GAME_FILE.as_bytes());
        out.push(1);
        out.extend((bytes.len() as u64).to_le_bytes());
        out.extend(bytes);
        out
    }
    fn fixture_paths(root: &Path) -> Paths {
        let root = root.canonicalize().unwrap();
        let exe = root.join(GAME_FILE);
        fs::write(&exe, b"synthetic running game").unwrap();
        Paths {
            executable: exe.clone(),
            target: exe,
            metadata: root.join(METADATA),
            root,
        }
    }
    fn publish(server: &Server, version: &str, size: usize) -> Manifest {
        let bytes = archive(&vec![b'B'; size]);
        let manifest = Manifest {
            schema: 1,
            repository: crate::REPOSITORY.into(),
            version: stable_version(version).unwrap(),
            sequence: 2,
            target: TARGET.into(),
            entrypoint: GAME_FILE.into(),
            bundle: Asset {
                name: "game.rdb".into(),
                size: bytes.len() as u64,
                sha256: bytes_hash(&bytes),
            },
            deltas: vec![],
        };
        server.put("game.rdb", bytes);
        server.put(
            &format!("update-{TARGET}.json"),
            serde_json::to_vec(&manifest).unwrap(),
        );
        manifest
    }
    fn await_snapshot(
        updater: &mut GameUpdater,
        predicate: impl Fn(&UpdateSnapshot) -> bool,
    ) -> UpdateSnapshot {
        let until = Instant::now() + Duration::from_secs(25);
        loop {
            let s = updater.snapshot();
            if predicate(&s) {
                return s;
            }
            assert!(Instant::now() < until, "timed out: {s:?}");
            thread::sleep(Duration::from_millis(10));
        }
    }
    fn wait_engine(root: &Path) {
        let store = Store::open(root).unwrap();
        let until = Instant::now() + Duration::from_secs(10);
        loop {
            if store.lock().is_ok() {
                return;
            }
            assert!(Instant::now() < until);
            thread::sleep(Duration::from_millis(10));
        }
    }

    #[test]
    fn newer_running_build_is_current_and_never_fetches_older_executable() {
        let root = tempfile::tempdir().unwrap();
        let paths = fixture_paths(root.path());
        let server = Server::new();
        publish(&server, "0.1.1", 4096);
        let mut updater = GameUpdater::start_at(
            paths.clone(),
            stable_version("0.1.2").unwrap(),
            vec![],
            Some(server.source()),
        )
        .unwrap();
        let state = await_snapshot(&mut updater, |s| !s.running);
        assert!(state.message.contains("is current"), "{state:?}");
        assert_eq!(state.phase, UpdatePhase::Current);
        assert!(!state.ready);
        assert_eq!(server.request_count(), 1);
        assert_eq!(fs::read(paths.target).unwrap(), b"synthetic running game");
    }

    #[test]
    fn newer_store_record_does_not_make_an_old_running_binary_current() {
        let root = tempfile::tempdir().unwrap();
        let paths = fixture_paths(root.path());
        let server = Server::new();
        let manifest = publish(&server, "1.1.0", 4096);
        let store = Store::open(&paths.metadata).unwrap();
        let installed = Installed {
            version: manifest.version,
            sequence: manifest.sequence,
            bundle_sha256: manifest.bundle.sha256,
            entrypoint: manifest.entrypoint,
        };
        store
            .save(&crate::install::State {
                active: Some(installed),
                highest_sequence: manifest.sequence,
                ..Default::default()
            })
            .unwrap();
        let mut updater = GameUpdater::start_at(
            paths,
            stable_version("1.0.0").unwrap(),
            vec![],
            Some(server.source()),
        )
        .unwrap();
        let state = await_snapshot(&mut updater, |s| !s.running);
        assert_eq!(state.phase, UpdatePhase::Unavailable);
        assert!(!state.ready);
        assert!(!state.message.contains("is current"));
    }

    #[test]
    fn stale_cached_manifest_cannot_report_current_while_offline() {
        let root = tempfile::tempdir().unwrap();
        let paths = fixture_paths(root.path());
        let server = Server::new();
        let manifest = publish(&server, "1.0.0", 4096);
        let source = server.source();
        drop(server);
        let store = Store::open(&paths.metadata).unwrap();
        atomic_json(&store.root.join("manifest.cache.json"), &manifest).unwrap();
        let mut updater = GameUpdater::start_at(
            paths,
            stable_version("1.0.0").unwrap(),
            vec![],
            Some(source),
        )
        .unwrap();
        let state = await_snapshot(&mut updater, |s| !s.running);
        assert_eq!(state.phase, UpdatePhase::Unavailable);
        assert!(!state.ready);
        assert!(!state.message.contains("is current"));
    }

    #[test]
    fn explicit_pause_survives_restart_and_resume_finishes_the_same_download() {
        let root = tempfile::tempdir().unwrap();
        let paths = fixture_paths(root.path());
        let server = Server::new();
        server.slow_transfers();
        let manifest = publish(&server, "1.1.0", 5 * 1024 * 1024);
        let mut updater = GameUpdater::start_at(
            paths.clone(),
            stable_version("1.0.0").unwrap(),
            vec![],
            Some(server.source()),
        )
        .unwrap();
        await_snapshot(&mut updater, |s| s.bytes > 0 && s.running);
        updater.action(UpdateAction::Pause).unwrap();
        await_snapshot(&mut updater, |s| !s.running && s.message.contains("paused"));
        let partial = paths
            .metadata
            .join("cache")
            .join(format!("{}.part", manifest.bundle.sha256));
        let prefix = partial.metadata().unwrap().len();
        assert!(prefix > 0 && prefix < manifest.bundle.size);
        let before = server.request_count();
        drop(updater);
        wait_engine(&paths.metadata);
        let mut reopened = GameUpdater::start_at(
            paths.clone(),
            stable_version("1.0.0").unwrap(),
            vec![],
            Some(server.source()),
        )
        .unwrap();
        await_snapshot(&mut reopened, |s| {
            !s.running && s.message.contains("paused")
        });
        assert_eq!(server.request_count(), before);
        assert_eq!(partial.metadata().unwrap().len(), prefix);
        reopened.action(UpdateAction::Resume).unwrap();
        await_snapshot(&mut reopened, |s| s.ready);
        assert_eq!(fs::read(paths.target).unwrap(), b"synthetic running game");
    }

    #[test]
    fn cancel_invalidates_queued_completion_and_stays_cancelled_across_restart() {
        let root = tempfile::tempdir().unwrap();
        let paths = fixture_paths(root.path());
        let server = Server::new();
        server.slow_transfers();
        publish(&server, "1.1.0", 2 * 1024 * 1024);
        let mut updater = GameUpdater::start_at(
            paths.clone(),
            stable_version("1.0.0").unwrap(),
            vec![],
            Some(server.source()),
        )
        .unwrap();
        await_snapshot(&mut updater, |s| s.bytes > 0 && s.running);
        updater.action(UpdateAction::Cancel).unwrap();
        assert!(!updater.snapshot().ready);
        assert!(updater.action(UpdateAction::Restart).is_err());
        await_snapshot(&mut updater, |s| {
            !s.running && s.message.contains("cancelled")
        });
        thread::sleep(Duration::from_millis(150));
        assert!(!updater.snapshot().ready);
        drop(updater);
        wait_engine(&paths.metadata);
        let count = server.request_count();
        let mut reopened = GameUpdater::start_at(
            paths.clone(),
            stable_version("1.0.0").unwrap(),
            vec![],
            Some(server.source()),
        )
        .unwrap();
        await_snapshot(&mut reopened, |s| {
            !s.running && s.message.contains("cancelled")
        });
        assert_eq!(server.request_count(), count);
        reopened.action(UpdateAction::Resume).unwrap();
        await_snapshot(&mut reopened, |s| s.ready);
        // Also cover Cancel after completion was queued/published but before apply.
        reopened.action(UpdateAction::Cancel).unwrap();
        assert!(!reopened.snapshot().ready);
        assert!(reopened.action(UpdateAction::Restart).is_err());
    }

    #[test]
    fn pause_resume_and_cancel_resume_races_do_not_publish_stale_ready() {
        let root = tempfile::tempdir().unwrap();
        let paths = fixture_paths(root.path());
        let server = Server::new();
        server.slow_transfers();
        publish(&server, "1.1.0", 3 * 1024 * 1024);
        let mut updater = GameUpdater::start_at(
            paths.clone(),
            stable_version("1.0.0").unwrap(),
            vec![],
            Some(server.source()),
        )
        .unwrap();
        await_snapshot(&mut updater, |s| s.bytes > 0 && s.running);
        updater.action(UpdateAction::Pause).unwrap();
        updater.action(UpdateAction::Resume).unwrap();
        updater.action(UpdateAction::Cancel).unwrap();
        updater.action(UpdateAction::Resume).unwrap();
        await_snapshot(&mut updater, |s| s.ready);
        assert_eq!(fs::read(paths.target).unwrap(), b"synthetic running game");
        assert_eq!(updater.shared.lock().unwrap().generation, 1);
    }

    #[test]
    fn closing_controller_is_nonblocking_and_transfer_retains_engine_lease() {
        let root = tempfile::tempdir().unwrap();
        let paths = fixture_paths(root.path());
        let server = Server::new();
        server.slow_transfers();
        publish(&server, "1.1.0", 5 * 1024 * 1024);
        let mut updater = GameUpdater::start_at(
            paths.clone(),
            stable_version("1.0.0").unwrap(),
            vec![],
            Some(server.source()),
        )
        .unwrap();
        await_snapshot(&mut updater, |s| s.bytes > 0 && s.running);
        let start = Instant::now();
        drop(updater);
        assert!(start.elapsed() < Duration::from_millis(200));
        wait_engine(&paths.metadata);
        assert_eq!(
            read_json::<Control>(&paths.metadata.join("user-control.json")).unwrap_or_default(),
            Control::Running
        );
        assert!(fs::read_dir(paths.metadata.join("cache"))
            .unwrap()
            .any(|p| p.unwrap().path().extension().is_some_and(|x| x == "part")));
    }

    fn compile_game(root: &Path) -> PathBuf {
        let source = root.join("fixture.rs");
        fs::write(&source, r#"fn main() {
            let args: Vec<String> = std::env::args().skip(1).collect();
            if args.iter().any(|a| a == "--parent-fixture") {
                std::fs::write(std::env::var_os("RD_PARENT_READY").unwrap(), b"ready").unwrap();
                std::thread::sleep(std::time::Duration::from_millis(800)); return;
            }
            let exe=std::env::current_exe().unwrap();
            if args.iter().any(|a| a == "--fail-on-b") && std::fs::read(&exe).unwrap().ends_with(b"VERSION_B") {
                std::thread::sleep(std::time::Duration::from_millis(800)); std::process::exit(17);
            }
            if let Some(path)=args.iter().find_map(|a| a.strip_prefix("--rust-duty-update-startup=")) {
                let token=args.iter().find_map(|a|a.strip_prefix("--rust-duty-update-startup-token=")).unwrap();
                let hash=std::env::var("RD_NEW_HASH").unwrap();
                let ack=format!("{{\"token\":{:?},\"pid\":{},\"executable\":{:?},\"sha256\":{:?},\"version\":\"1.1.0\"}}",token,std::process::id(),exe.to_str().unwrap(),hash);
                let dest=std::path::Path::new(path).parent().unwrap().join("startup-ready.json");
                std::fs::write(dest.with_extension("tmp"),ack).unwrap();std::fs::rename(dest.with_extension("tmp"),dest).unwrap();
            }
            if args.iter().any(|a|a == "--update-headless") { std::thread::sleep(std::time::Duration::from_millis(350)); }
            let text=format!("{}\n{}\n{}",exe.display(),std::env::current_dir().unwrap().display(),args.join("\n"));
            std::fs::write(std::env::var_os("RD_RECEIVED").unwrap(), text).unwrap();
        }"#).unwrap();
        let target = root.join(if cfg!(windows) {
            "fixture.exe"
        } else {
            "fixture"
        });
        let output = Command::new("rustc")
            .args(["--edition=2021", "--crate-name", "game_update_fixture"])
            .arg(&source)
            .arg("-o")
            .arg(&target)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        target
    }
    fn write_bundle(root: &Path, name: &str, data: &[u8]) -> PathBuf {
        let path = root.join(name);
        fs::write(&path, archive(data)).unwrap();
        path
    }
    fn staged(store: &Store, data: &[u8]) -> Installed {
        let payload = write_bundle(&store.root, "next.rdb", data);
        let installed = Installed {
            version: stable_version("1.1.0").unwrap(),
            sequence: 2,
            bundle_sha256: file_hash(&payload).unwrap(),
            entrypoint: GAME_FILE.into(),
        };
        let directory = store.version_dir(&installed);
        safe_dir(&directory).unwrap();
        bundle::unpack(&payload, &directory, GAME_FILE).unwrap();
        fs::copy(payload, directory.join("payload.rdb")).unwrap();
        atomic_json(&directory.join("version.json"), &installed).unwrap();
        installed
    }
    fn wait_file(path: &Path) {
        let until = Instant::now() + Duration::from_secs(15);
        while !path.is_file() {
            assert!(Instant::now() < until, "missing {}", path.display());
            thread::sleep(Duration::from_millis(10));
        }
    }

    // This same test runs natively on Windows, including locked running EXEs.
    fn process_case(fail: bool, headless: bool) {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().canonicalize().unwrap();
        let fixture = compile_game(&root);
        let old_bytes = fs::read(&fixture).unwrap();
        let old_bundle = write_bundle(&root, "base.rdb", &old_bytes);
        let legacy = Store::open(&root).unwrap();
        legacy
            .install_local(&old_bundle, stable_version("1.0.0").unwrap(), GAME_FILE)
            .unwrap();
        let old_install = legacy.state().unwrap().active.unwrap();
        let versioned_exe = legacy.version_dir(&old_install).join(GAME_FILE);
        let mut root_bytes = old_bytes.clone();
        root_bytes.extend(b"OLD_ROOT");
        fs::write(root.join(GAME_FILE), &root_bytes).unwrap();
        fs::set_permissions(
            root.join(GAME_FILE),
            fs::metadata(&fixture).unwrap().permissions(),
        )
        .unwrap();
        fs::write(root.join("settings.cfg"), b"private settings").unwrap();
        safe_dir(&root.join("private-assets")).unwrap();
        fs::write(root.join("private-assets/fps-arms.vrs"), b"private arms").unwrap();
        let paths = locate(&versioned_exe).unwrap();
        assert_eq!(paths.root, root);
        assert_eq!(paths.target, root.join(GAME_FILE));
        let store = Store::open(&paths.metadata).unwrap();
        ensure_baseline(&store, &paths.executable, &stable_version("1.0.0").unwrap()).unwrap();
        let mut new_bytes = old_bytes.clone();
        new_bytes.extend(b"VERSION_B");
        let installed = staged(&store, &new_bytes);
        let parent_ready = root.join("parent.ready");
        let received = root.join("received.txt");
        let mut parent = Command::new(&versioned_exe)
            .arg("--parent-fixture")
            .env("RD_PARENT_READY", &parent_ready)
            .spawn()
            .unwrap();
        wait_file(&parent_ready);
        let args = vec![
            "--replacement-fixture".into(),
            "--literal=two words".into(),
            "--settings=settings.cfg".into(),
            "--arms-asset=private-assets/fps-arms.vrs".into(),
        ];
        let mut args = args;
        if fail {
            args.push("--fail-on-b".into());
        }
        if headless {
            args.push("--update-headless".into());
        }
        let prepared = prepare_restart(
            &paths,
            &store,
            &stable_version("1.0.0").unwrap(),
            installed.clone(),
            &args,
            parent.id(),
        )
        .unwrap();
        // The test harness supplies the real helper code; the game fixtures are tiny executables.
        fs::copy(std::env::current_exe().unwrap(), &prepared.helper).unwrap();
        let mut plan: Plan = read_json(&prepared.plan).unwrap();
        plan.helper_sha256 = file_hash(&prepared.helper).unwrap();
        atomic_json(&prepared.plan, &plan).unwrap();
        let other_session = session_file(&paths.metadata).unwrap();
        FileExt::lock_shared(&other_session).unwrap();
        let child = Command::new(&prepared.helper)
            .args([
                "--exact",
                "game::tests::helper_process_entry",
                "--ignored",
                "--nocapture",
            ])
            .env("RD_HELPER_PLAN", &prepared.plan)
            .env("RD_HELPER_TOKEN", &prepared.token)
            .env("RD_RECEIVED", &received)
            .env("RD_NEW_HASH", &plan.new_sha256)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let mut pending = Pending {
            child,
            prepared: prepared.clone(),
            deadline: Instant::now() + Duration::from_secs(20),
        };
        while !poll_admission(&mut pending).unwrap() {
            thread::sleep(Duration::from_millis(10));
        }
        assert_eq!(
            fs::read(&paths.target).unwrap(),
            root_bytes,
            "admission must not replace a running game"
        );
        assert!(parent.wait().unwrap().success());
        thread::sleep(Duration::from_millis(100));
        assert_eq!(
            fs::read(&paths.target).unwrap(),
            root_bytes,
            "other session still owns a shared lock"
        );
        drop(other_session);
        let output = pending.child.wait_with_output().unwrap();
        assert_eq!(
            output.status.success(),
            !fail,
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        if headless && !fail {
            assert!(
                received.exists(),
                "helper must wait for headless completion after startup ack"
            );
        }
        wait_file(&received);
        let receipt = fs::read_to_string(&received).unwrap();
        let mut receipt_lines = receipt.lines();
        assert_eq!(
            Path::new(receipt_lines.next().unwrap())
                .canonicalize()
                .unwrap(),
            paths.target.canonicalize().unwrap()
        );
        assert_eq!(
            Path::new(receipt_lines.next().unwrap())
                .canonicalize()
                .unwrap(),
            root
        );
        assert!(receipt.contains("--literal=two words"));
        assert!(receipt.contains(&format!(
            "--settings={}",
            root.join("settings.cfg").display()
        )));
        assert!(receipt.contains(&format!(
            "--arms-asset={}",
            root.join("private-assets/fps-arms.vrs").display()
        )));
        assert_eq!(
            fs::read(&paths.target).unwrap(),
            if fail { root_bytes } else { new_bytes }
        );
        assert_eq!(fs::read(&versioned_exe).unwrap(), old_bytes);
        assert_eq!(
            fs::read(root.join("settings.cfg")).unwrap(),
            b"private settings"
        );
        assert_eq!(
            fs::read(root.join("private-assets/fps-arms.vrs")).unwrap(),
            b"private arms"
        );
        let state = store.state().unwrap();
        assert_eq!(state.highest_sequence, 2);
        assert_eq!(
            state.active.unwrap().version,
            stable_version(if fail { "1.0.0" } else { "1.1.0" }).unwrap()
        );
    }
    #[test]
    fn helper_replaces_persistent_root_after_versioned_parent_and_other_sessions_exit() {
        process_case(false, false);
    }
    #[test]
    fn helper_rolls_back_delayed_startup_failure_without_lowering_sequence_or_touching_private_files(
    ) {
        process_case(true, false);
    }
    #[test]
    fn helper_waits_for_headless_terminal_exit_after_startup_ack() {
        process_case(false, true);
    }

    #[test]
    fn startup_ack_accepts_equivalent_absolute_paths_but_keeps_all_identity_checks() {
        let temp = tempfile::tempdir().unwrap();
        let paths = fixture_paths(temp.path());
        let store = Store::open(&paths.metadata).unwrap();
        ensure_baseline(&store, &paths.executable, &stable_version("1.0.0").unwrap()).unwrap();
        let installed = staged(&store, b"next executable");
        let prepared = prepare_restart(
            &paths,
            &store,
            &stable_version("1.0.0").unwrap(),
            installed,
            &[],
            std::process::id(),
        )
        .unwrap();
        let plan: Plan = read_json(&prepared.plan).unwrap();
        let mut ack = StartupReady {
            token: plan.token.clone(),
            pid: 123,
            // TempDir's native spelling differs from the canonical extended path on Windows.
            executable: temp.path().join(GAME_FILE),
            sha256: plan.new_sha256.clone(),
            version: plan.installed.version.clone(),
        };
        assert!(validate_startup_ack(&plan, &ack, 123).unwrap());
        assert!(!validate_startup_ack(&plan, &ack, 124).unwrap());
        ack.token = "b".repeat(32);
        assert!(validate_startup_ack(&plan, &ack, 123).is_err());
        ack.token = plan.token.clone();
        ack.sha256 = "0".repeat(64);
        assert!(validate_startup_ack(&plan, &ack, 123).is_err());
        ack.sha256 = plan.new_sha256.clone();
        ack.version = stable_version("1.0.0").unwrap();
        assert!(validate_startup_ack(&plan, &ack, 123).is_err());
        ack.version = plan.installed.version.clone();
        ack.executable = PathBuf::from(GAME_FILE);
        assert!(validate_startup_ack(&plan, &ack, 123).is_err());
        ack.executable = temp.path().join("different-game.exe");
        fs::copy(&plan.target, &ack.executable).unwrap();
        assert!(validate_startup_ack(&plan, &ack, 123).is_err());
        #[cfg(unix)]
        {
            ack.executable = temp.path().join("linked-game");
            std::os::unix::fs::symlink(&plan.target, &ack.executable).unwrap();
            assert!(validate_startup_ack(&plan, &ack, 123).is_err());
        }
    }

    #[test]
    #[ignore]
    fn helper_process_entry() {
        let path = PathBuf::from(std::env::var_os("RD_HELPER_PLAN").unwrap());
        let token = std::env::var("RD_HELPER_TOKEN").unwrap();
        run_helper(&path, &token, &std::env::current_exe().unwrap()).unwrap();
    }

    #[test]
    fn cancel_kills_only_pending_helper_and_stale_ack_is_not_admission() {
        let temp = tempfile::tempdir().unwrap();
        let paths = fixture_paths(temp.path());
        safe_dir(&paths.metadata).unwrap();
        let fixture = compile_game(temp.path());
        let marker = temp.path().join("parent.ready");
        let child = Command::new(fixture)
            .arg("--parent-fixture")
            .env("RD_PARENT_READY", marker)
            .spawn()
            .unwrap();
        let prepared = Prepared {
            helper: PathBuf::new(),
            plan: paths.metadata.join("plan.json"),
            token: "a".repeat(32),
            root: paths.root.clone(),
        };
        atomic_json(
            &paths.metadata.join("admitted.json"),
            &Admission {
                token: prepared.token.clone(),
                helper_pid: child.id() + 1,
            },
        )
        .unwrap();
        let mut pending = Pending {
            child,
            prepared,
            deadline: Instant::now() + Duration::from_secs(5),
        };
        assert!(!poll_admission(&mut pending).unwrap());
        let (tx, rx) = mpsc::channel();
        let shared = Arc::new(Mutex::new(Shared {
            restarting: true,
            ..Default::default()
        }));
        let mut updater = GameUpdater {
            shared: shared.clone(),
            requests: tx,
            _session: session_file(&paths.metadata).unwrap(),
            pending: Some(pending),
        };
        updater.action(UpdateAction::Cancel).unwrap();
        assert!(updater.pending.is_none());
        assert!(!shared.lock().unwrap().restarting);
        assert!(matches!(rx.recv().unwrap(), Request::Cancel));
        assert!(!updater.snapshot().ready);
        assert_eq!(fs::read(paths.target).unwrap(), b"synthetic running game");
    }

    #[test]
    fn altered_plan_or_staged_payload_is_rejected_before_admission() {
        let temp = tempfile::tempdir().unwrap();
        let paths = fixture_paths(temp.path());
        let store = Store::open(&paths.metadata).unwrap();
        ensure_baseline(&store, &paths.executable, &stable_version("1.0.0").unwrap()).unwrap();
        let installed = staged(&store, b"next executable");
        let prepared = prepare_restart(
            &paths,
            &store,
            &stable_version("1.0.0").unwrap(),
            installed,
            &[],
            std::process::id(),
        )
        .unwrap();
        let plan: Plan = read_json(&prepared.plan).unwrap();
        let mut changed = plan.clone();
        changed.target = temp.path().join("elsewhere").join(GAME_FILE);
        assert!(
            validate_plan(&changed, &prepared.plan, &prepared.helper, &prepared.token).is_err()
        );
        changed = plan.clone();
        changed.installed.version = stable_version("0.9.0").unwrap();
        assert!(
            validate_plan(&changed, &prepared.plan, &prepared.helper, &prepared.token).is_err()
        );
        fs::write(
            store.version_dir(&plan.installed).join(GAME_FILE),
            b"tampered",
        )
        .unwrap();
        assert!(preflight(&plan).is_err());
        assert!(!job_dir(&plan).join("admitted.json").exists());
    }
}
