use crate::{
    atomic_bytes, atomic_json, bundle, delta,
    download::{self, Control},
    file_hash, invalid,
    manifest::{Manifest, Trust},
    read_json,
    source::Source,
    Error, Result,
};
use fs2::FileExt;
use semver::Version;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
    process::{Child, Command},
};

#[derive(Clone)]
pub struct Store {
    pub root: PathBuf,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Installed {
    pub version: Version,
    pub sequence: u64,
    pub bundle_sha256: String,
    pub entrypoint: String,
}
impl Installed {
    pub fn directory(&self) -> String {
        format!("{}-{}", self.sequence, self.version)
    }
}
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub active: Option<Installed>,
    pub previous: Option<Installed>,
    pub last_good: Option<Installed>,
    pub highest_sequence: u64,
    pub pending_launch: bool,
}

fn content_delta<'a>(
    manifest: &'a Manifest,
    version: &Version,
    sha: &str,
) -> Option<&'a crate::manifest::Delta> {
    manifest.deltas.iter().find(|delta| {
        delta.base_version == *version
            && delta.base_sha256 == sha
            && delta.asset.size < manifest.bundle.size
    })
}
/// Capture an optional optimization. A changing/unreadable source cannot block
/// the verified full transfer, but unsafe paths remain fatal.
pub(crate) fn optional_executable_baseline(
    name: &str,
    source: &mut impl std::io::Read,
    size: u64,
    output: &mut impl std::io::Write,
) -> Result<bool> {
    bundle::safe_path(name)?;
    if size == 0 || size > crate::MAX_ASSET - 1024 {
        return Ok(false);
    }
    match bundle::write_single_executable(name, source, size, output) {
        Ok(()) => Ok(true),
        Err(Error::Io(_)) => Ok(false),
        Err(Error::Invalid(message))
            if message == "running executable changed during baseline capture" =>
        {
            Ok(false)
        }
        Err(error) => Err(error),
    }
}

impl Store {
    pub fn open(root: &Path) -> Result<Self> {
        crate::safe_dir(root)?;
        let root = root.canonicalize()?;
        crate::safe_dir(&root.join("versions"))?;
        crate::safe_dir(&root.join("cache"))?;
        Ok(Self { root })
    }
    pub fn lock(&self) -> Result<File> {
        let path = self.root.join("launcher.lock");
        crate::reject_symlink(&path)?;
        let file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(path)?;
        file.try_lock_exclusive().map_err(|_| {
            invalid(
                "another launcher owns this install; use status/pause/resume/cancel to control it",
            )
        })?;
        Ok(file)
    }
    pub fn state(&self) -> Result<State> {
        let path = self.root.join("install.json");
        crate::reject_symlink(&path)?;
        if !path.exists() {
            return Ok(State::default());
        }
        let state: State = read_json(&path)?;
        for installed in [&state.active, &state.previous, &state.last_good]
            .into_iter()
            .flatten()
        {
            bundle::safe_path(&installed.entrypoint)?;
            if !installed.version.pre.is_empty()
                || !installed.version.build.is_empty()
                || !crate::manifest::valid_hash(&installed.bundle_sha256)
            {
                return Err(invalid("invalid installed version record"));
            }
        }
        Ok(state)
    }
    pub fn save(&self, state: &State) -> Result<()> {
        atomic_json(&self.root.join("install.json"), state)
    }
    pub fn version_dir(&self, installed: &Installed) -> PathBuf {
        self.root.join("versions").join(installed.directory())
    }
    pub fn bundle_path(&self, installed: &Installed) -> PathBuf {
        self.version_dir(installed).join("payload.rdb")
    }
    pub fn check(&self, source: &Source, trust: &Trust, target: &str) -> Result<Manifest> {
        let cache = self.root.join("manifest.cache.json");
        let bytes = match source.latest(target) {
            Ok(bytes) => {
                trust.verify(&bytes, target)?;
                atomic_bytes(&cache, &bytes)?;
                bytes
            }
            Err(network_error) if cache.exists() => {
                crate::reject_symlink(&cache)?;
                if cache.metadata()?.len() > crate::MAX_MANIFEST {
                    return Err(invalid("oversized cached manifest"));
                }
                eprintln!("{network_error}; checking the last verified manifest instead");
                fs::read(&cache)?
            }
            Err(e) => return Err(e),
        };
        let manifest = trust.verify(&bytes, target)?;
        self.check_newer(&manifest)?;
        Ok(manifest)
    }
    pub fn check_newer(&self, manifest: &Manifest) -> Result<()> {
        let state = self.state()?;
        if state.active.as_ref().is_some_and(|active| {
            manifest.version == active.version
                && manifest.sequence == state.highest_sequence
                && manifest.bundle.sha256 == active.bundle_sha256
        }) {
            return Err(Error::UpToDate);
        }
        if manifest.sequence <= state.highest_sequence
            || state
                .active
                .as_ref()
                .is_some_and(|a| manifest.version <= a.version)
        {
            return Err(invalid(
                "no newer permitted release (same version, downgrade, or replay rejected)",
            ));
        }
        Ok(())
    }

    /// Prefer the stored bundle. If that is a fuller package, also try the
    /// one-file image of its entrypoint: that is the executable already on disk,
    /// so a content patch can COPY it instead of downloading another copy.
    fn delta_base<'a>(
        &self,
        base: &Installed,
        manifest: &'a Manifest,
    ) -> Result<Option<(PathBuf, &'a crate::manifest::Delta)>> {
        if !manifest.deltas.iter().any(|patch| {
            patch.base_version == base.version && patch.asset.size < manifest.bundle.size
        }) {
            return Ok(None);
        }
        let stored = self.bundle_path(base);
        crate::reject_symlink(&stored)?;
        if stored.is_file() && file_hash(&stored).is_ok_and(|sha| sha == base.bundle_sha256) {
            if let Some(patch) = content_delta(manifest, &base.version, &base.bundle_sha256) {
                return Ok(Some((stored, patch)));
            }
        }
        let executable = self.version_dir(base).join(&base.entrypoint);
        crate::reject_symlink(&executable)?;
        if !executable.is_file() {
            return Ok(None);
        }
        let Ok(mut input) = File::open(&executable) else {
            return Ok(None);
        };
        let Ok(metadata) = input.metadata() else {
            return Ok(None);
        };
        let size = metadata.len();
        // A damaged optional delta base must not prevent a verified full update.
        if size == 0 || size > crate::MAX_ASSET - 1024 {
            return Ok(None);
        }
        let mut temporary = tempfile::NamedTempFile::new_in(self.root.join("cache"))?;
        if !optional_executable_baseline(
            &base.entrypoint,
            &mut input,
            size,
            temporary.as_file_mut(),
        )? {
            return Ok(None);
        }
        temporary.as_file().sync_all()?;
        let sha = file_hash(temporary.path())?;
        let Some(patch) = content_delta(manifest, &base.version, &sha) else {
            return Ok(None);
        };
        let path = self
            .root
            .join("cache")
            .join(format!("running-executable-{sha}.rdb"));
        crate::reject_symlink(&path)?;
        if !(path.is_file() && file_hash(&path)? == sha) {
            if path.exists() {
                fs::remove_file(&path)?;
            }
            temporary.persist(&path).map_err(|error| error.error)?;
        }
        Ok(Some((path, patch)))
    }

    /// Downloads and extracts into a new version directory. It never changes the active pointer.
    pub fn stage(&self, source: &Source, manifest: &Manifest) -> Result<Installed> {
        self.check_newer(manifest)?;
        let installed = Installed {
            version: manifest.version.clone(),
            sequence: manifest.sequence,
            bundle_sha256: manifest.bundle.sha256.clone(),
            entrypoint: manifest.entrypoint.clone(),
        };
        let mut bundle_path = None;
        if let Some(base) = self.state()?.active {
            // Staging never activates. The version switch still waits until the
            // game process has exited and the helper can take the install lock.
            if let Some((base_path, patch)) = self.delta_base(&base, manifest)? {
                download::report(
                    &self.root,
                    "delta",
                    Some(&patch.asset),
                    0,
                    "Matching base verified; fetching a copy/add delta",
                )?;
                let downloaded =
                    download::download(&self.root, source, &manifest.version, &patch.asset);
                match downloaded {
                    Err(e @ (Error::Paused | Error::Cancelled | Error::Network(_))) => {
                        return Err(e)
                    }
                    Err(e) => eprintln!(
                        "Delta transfer rejected ({e}); falling back to full verified bundle"
                    ),
                    Ok(patch_path) => {
                        let output = self
                            .root
                            .join("cache")
                            .join(format!("{}.reconstructed", manifest.bundle.sha256));
                        crate::reject_symlink(&output)?;
                        if output.exists() {
                            fs::remove_file(&output)?;
                        }
                        let applied =
                            delta::apply(&base_path, &patch_path, &output, manifest.bundle.size)
                                .and_then(|_| {
                                    if file_hash(&output)? == manifest.bundle.sha256 {
                                        Ok(())
                                    } else {
                                        Err(invalid("reconstructed bundle hash mismatch"))
                                    }
                                });
                        match applied {
                            Ok(()) => bundle_path = Some(output),
                            Err(e) => {
                                if output.exists() {
                                    fs::remove_file(output)?;
                                }
                                eprintln!(
                                    "Delta rejected ({e}); falling back to full verified bundle"
                                );
                            }
                        }
                    }
                }
            }
        }
        let bundle_path = match bundle_path {
            Some(path) => path,
            None => download::download(&self.root, source, &manifest.version, &manifest.bundle)?,
        };
        match download::control(&self.root)? {
            Control::Paused => return Err(Error::Paused),
            Control::Cancelled => return Err(Error::Cancelled),
            Control::Running => (),
        }
        download::report(
            &self.root,
            "staging",
            None,
            0,
            "Verifying and extracting into an isolated version directory",
        )?;
        self.extract(&bundle_path, &installed)?;
        download::report(
            &self.root,
            "ready",
            None,
            0,
            "Update staged; switches only when the game is closed",
        )?;
        Ok(installed)
    }
    fn extract(&self, bundle_path: &Path, installed: &Installed) -> Result<()> {
        if file_hash(bundle_path)? != installed.bundle_sha256 {
            return Err(invalid("bundle hash changed before extraction"));
        }
        let directory = self.version_dir(installed);
        crate::reject_symlink(&directory)?;
        if directory.exists() {
            // Re-extract rather than trusting an interrupted or locally modified staging directory.
            if self
                .state()?
                .active
                .is_some_and(|a| a.directory() == installed.directory())
            {
                return Err(invalid("cannot overwrite active version"));
            }
            fs::remove_dir_all(&directory)?;
        }
        let stage = tempfile::Builder::new()
            .prefix(".stage-")
            .tempdir_in(self.root.join("versions"))?;
        bundle::unpack(bundle_path, stage.path(), &installed.entrypoint)?;
        fs::copy(bundle_path, stage.path().join("payload.rdb"))?;
        OpenOptions::new()
            .write(true)
            .open(stage.path().join("payload.rdb"))?
            .sync_all()?;
        atomic_json(&stage.path().join("version.json"), installed)?;
        crate::sync_dir(stage.path())?;
        fs::rename(stage.path(), &directory)?;
        crate::sync_dir(&self.root.join("versions"))?;
        Ok(())
    }
    /// Initial local install is explicit, offline, and trusts the user-provided initial bundle.
    /// Network updates use the fixed GitHub HTTPS channel and verified hashes.
    pub fn install_local(&self, path: &Path, version: Version, entrypoint: &str) -> Result<()> {
        if self.state()?.active.is_some() {
            return Err(invalid("initial install already exists"));
        }
        if !version.pre.is_empty() || !version.build.is_empty() {
            return Err(invalid("stable version required"));
        }
        let installed = Installed {
            version,
            sequence: 0,
            bundle_sha256: file_hash(path)?,
            entrypoint: entrypoint.into(),
        };
        self.extract(path, &installed)?;
        self.save(&State {
            active: Some(installed.clone()),
            last_good: Some(installed),
            ..State::default()
        })
    }
    /// Caller owns launcher lock and must wait for its child to exit before activating.
    pub fn activate(&self, installed: Installed) -> Result<()> {
        let mut state = self.state()?;
        if state.pending_launch {
            return Err(invalid(
                "game is running or previous launch needs recovery; refusing version switch",
            ));
        }
        if installed.sequence <= state.highest_sequence
            || state
                .active
                .as_ref()
                .is_some_and(|a| installed.version <= a.version)
        {
            return Err(invalid("activation downgrade/replay refused"));
        }
        let bundle = self.bundle_path(&installed);
        if !bundle.is_file() || file_hash(&bundle)? != installed.bundle_sha256 {
            return Err(invalid("staged bundle failed activation verification"));
        }
        if !self
            .version_dir(&installed)
            .join(&installed.entrypoint)
            .is_file()
        {
            return Err(invalid("staged executable missing"));
        }
        state.previous = state.last_good.clone();
        state.highest_sequence = installed.sequence;
        state.active = Some(installed);
        self.save(&state)?;
        download::report(
            &self.root,
            "installed",
            None,
            0,
            "Version switch committed atomically; previous version retained",
        )
    }
    pub fn launch(&self, args: &[String]) -> Result<Child> {
        let mut state = self.state()?;
        if state.pending_launch {
            return Err(invalid(
                "launch already pending; recover the previous launch first",
            ));
        }
        let installed = state
            .active
            .clone()
            .ok_or_else(|| invalid("no local game installed; run install-local once"))?;
        let executable = self.version_dir(&installed).join(&installed.entrypoint);
        crate::reject_symlink(&executable)?;
        let launch_config = crate::launch::load(&self.root)?;
        let args = crate::launch::mapped_arguments(&self.root, &launch_config, args)?;
        state.pending_launch = true;
        self.save(&state)?;
        match Command::new(executable)
            .current_dir(&self.root)
            .args(&args)
            .spawn()
        {
            Ok(child) => Ok(child),
            Err(e) => {
                self.finish_launch(false)?;
                Err(e.into())
            }
        }
    }
    pub fn finish_launch(&self, success: bool) -> Result<()> {
        let mut state = self.state()?;
        state.pending_launch = false;
        if success {
            state.last_good = state.active.clone();
        }
        if !success {
            if let Some(previous) = state.previous.take() {
                state.active = Some(previous);
            }
        }
        self.save(&state)
    }
    pub fn recover(&self) -> Result<()> {
        if self.state()?.pending_launch {
            return Err(invalid("previous launcher ended during a game session; close that game, then run recover to restore the last good version"));
        }
        Ok(())
    }
    pub fn rollback(&self) -> Result<()> {
        let mut state = self.state()?;
        if state.pending_launch {
            return Err(invalid("close the game before rollback"));
        }
        state.active = Some(
            state
                .previous
                .take()
                .ok_or_else(|| invalid("no previous version retained"))?,
        );
        self.save(&state)
    }
}
