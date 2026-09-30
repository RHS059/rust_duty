# Signed, resumable app updates

## Current status

The updater library, console launcher, real copy/add delta generator and local HTTP tests are implemented. **There is no live update channel yet.** `RHS059/rust_duty` needs reviewed, signed release assets before network updates can work. Production signing trust is deliberately **UNCONFIGURED** in the default build. No production signing keys, credentials, repository settings, GitHub releases or upload permissions were created. The owner-run setup is documented in [SIGNING_SETUP.md](SIGNING_SETUP.md); its sensitive steps must be run personally on the owner's Windows computer.

Once an approved public key is pinned and the channel is published, the user installs the launcher and game once. Opening the launcher checks/downloads a newer signed release automatically. Interrupted downloads continue from verified saved bytes; a matching delta avoids fetching the full bundle. The launcher does not poll when closed.

Opening/double-clicking the launcher starts the installed game once and checks/downloads updates in the background. A first verified installation starts once when ready. Closing the game does not trigger an automatic relaunch loop. Explicit `run` keeps manual control. The initial UI is a clear console with `status`, `pause`, `resume`, `cancel`, `play`, `rollback` and `quit`. It is not yet a graphical Windows installer. Native Windows runtime testing remains required before distribution; the local verification in this environment runs on Linux. The stable bootstrap executable is not overwritten or silently replaced by its child. Updating the bootstrap itself or rotating its pinned key requires a reviewed replacement installer.

## Build and one-time installation

From the repository root:

```sh
cargo build --manifest-path updater/Cargo.toml --locked --release --bins
cargo test --manifest-path updater/Cargo.toml --locked
cargo clippy --manifest-path updater/Cargo.toml --locked --all-targets -- -D warnings
python -m unittest discover -s tools -p 'test_release_update.py' -v
```

The launcher binary is `updater/target/release/rust-duty-launcher` (or `.exe`). The release-owner helper is `rust-duty-release-sign` (or `.exe`), separate from normal game launch/update behavior. The independent crate and lockfile do not change the game's dependencies. It uses the same native target as its game payload, baked into the binary at compile time.

Prepare a clean initial payload directory containing the game executable and redistributable runtime files. For the current game, include the approved `assets/weapons/hk416a5.vrm` sidecar in that same relative layout when using it. Keep private source assets out of that directory. The packer rejects symlinks and automatically excludes top-level settings, telemetry, private assets, saves and updater-state paths.

```sh
python tools/release_update.py pack --input /path/to/initial-payload \
  --entrypoint vector-range --output /path/to/initial-1.0.0.rdb
updater/target/release/rust-duty-launcher --root /path/to/my-install \
  install-local /path/to/initial-1.0.0.rdb 1.0.0 vector-range
updater/target/release/rust-duty-launcher --root /path/to/my-install play
```

On Windows, use `vector-range.exe` as the entrypoint and `rust-duty-launcher.exe`. Run everything as the normal user. Default installs are `%LOCALAPPDATA%\RustDuty`, `$XDG_DATA_HOME/rust-duty`, or `~/.local/share/rust-duty`. No administrator rights, service or scheduled job is needed.

`install-local` is an explicit, one-time trust decision for the supplied local bundle. It is not a network-signature bypass and refuses to replace an existing installation. For the first version use the actual stable game release number; the initial sequence is zero. The game runs with the install root as its working directory. Existing `settings.cfg`, `profiles/`, `private-assets/`, telemetry and saves in that root stay outside version switching. Put any desired initial settings there once, or pass the game's explicit `--settings=` argument after `--`:

```sh
rust-duty-launcher --root /path/to/my-install play -- --settings=/path/to/settings.cfg
```

No licensed assets are imported or redistributed by the updater. The release owner must ensure every file in the payload is authorized for distribution. Public runtime resources belong in the version payload; game resource lookup must explicitly use its executable/version directory if it needs non-embedded files. The current game's user-config lookup uses the install working directory.

## Persistent launch mappings and private assets

Every game process receives an absolute `--settings=...` path anchored in the stable install root, independently of its version directory. The default is `<install>/settings.cfg`; `--profile=kestrel` keeps the game's `<install>/profiles/kestrel.cfg` default unless a settings mapping or explicit flag overrides it.

The launcher also discovers existing stable-root asset files in this order:

- Weapon: `private-assets/hk416a5.vrm`, `private-assets/weapons/hk416a5.vrm`, then `assets/weapons/hk416a5.vrm`
- Arms: `private-assets/fps-arms.vrs`, `private-assets/arms/fps-arms.vrs`, then `assets/arms/fps-arms.vrs`

When found, these are passed as absolute `--weapon-asset=` and `--arms-asset=` flags. If no stable weapon asset is mapped/found, the game can load its public version-local `assets/weapons/hk416a5.vrm` sidecar or embedded fallback normally. Arms require a game build supporting `--arms-asset=`. No private file is copied into the new version or an update bundle.

Save other local locations and persistent game options while the launcher is closed:

```sh
rust-duty-launcher --root /path/to/my-install configure \
  --settings="settings.cfg" \
  --weapon-asset="private-assets/final-hk416a5.vrm" \
  --arms-asset="private-assets/fps-arms.vrs" \
  --game-arg="--hold-controls"
rust-duty-launcher --root /path/to/my-install config
```

Mappings are saved in `<install>/launch.json`, outside all release version directories. Relative paths resolve from the install root and cannot traverse above it. Explicit absolute paths can point to another user-owned data location. Symlink/reparse-point paths are rejected. Spaces in paths are passed as a single argument; no shell is involved. Settings files need not exist yet. Explicit missing asset mappings are still sent to the game so its asset-error handling can identify them rather than silently substituting a different asset.

Per-launch path arguments after `--` override the saved mappings and saved game arguments. The launcher emits each recognized path flag once, normalized to an absolute path. Other game arguments keep their text and order:

```sh
rust-duty-launcher --root /path/to/my-install play -- \
  --settings="alternate settings.cfg" --weapon-asset="private-assets/another.vrm"
```

`configure --clear-settings --clear-weapon-asset --clear-arms-asset` restores automatic mapping/discovery. `--clear-game-args` clears saved extra arguments. Configuration and private files survive updates and rollback. `launch.json`, any `private-assets` directory, and the private `fps-arms.vrs` filename are excluded/rejected by the release packer and rejected by the bundle unpacker. The disabled workflow copies only the explicitly named approved HK416 sidecar; it never imports a private directory by glob.

## Controls and restart behavior

- `open` (default): launch the installed game once, or the first verified install when ready; check/download in the background
- `run`: manual interactive launcher; starts one check/download attempt
- `play`: starts the installed game while an update can download/stage in the background
- `config` / `configure`: inspect or save persistent settings/private-asset paths and game arguments
- `status`: installed version, current phase, durable byte count, transfer control and signing configuration
- `pause`: persist pause; the in-flight read can take up to the 30-second request timeout to return
- `resume`: continue the saved transfer; open an interactive launcher if one is not already running
- `cancel`: persist cancellation and discard partial download/checkpoint files; the installed game stays usable
- `update`: check/download/stage/activate once, then exit
- `rollback`: restore the retained last-good version while the game and updater are idle
- `quit`: save/pause an active transfer and wait for the game to exit normally; never kill it
- `recover --game-closed`: after an abnormal launcher termination, explicitly confirm the orphaned game has been closed, then restore the last-good version if available

The interactive window accepts the same controls. A second terminal can issue status/pause/resume/cancel against the same `--root`. An advisory OS lock permits only one launcher to own an installation. Transfers, control state and progress are persistent. When the network stalls, an error is shown and the checkpoint remains; use resume or reopen the launcher. There is no cloud polling, automatic purchase, permission elevation or forced game shutdown.

Closing the console forcibly may leave `pending_launch` set. Startup then fails closed and requests the explicit recovery command rather than assuming the game has exited. A normal Quit waits for the child. Downloaded/staged versions never overwrite the running game executable, including on Windows. Native Windows process/antivirus behavior still needs platform testing.

Cancel removes unverified partial transfers. Already verified cache files and staged version directories may remain for safe reuse, and the last-good bundle is retained as a delta base. This first implementation does not automatically garbage-collect every historical cache/version directory; consider disk space when preparing large releases.

## Authenticity, origin and rollback protection

An update envelope contains two fields: `payload` (the exact UTF-8 manifest JSON string) and `signature` (a 64-byte Ed25519 signature encoded as lowercase hex). `verify_strict` checks the signature before deserializing trusted content. Manifests reject unknown fields, wrong schema/repository/target, invalid paths/hashes, oversized assets, unstable versions and repeated delta bases.

The public verification key is compiled in using `RUST_DUTY_UPDATE_PUBLIC_KEY` (64 hexadecimal characters). There is no runtime public-key override, insecure mode or arbitrary update URL. Do not create real signing keys or grant signing/publishing credentials without the owner's explicit approval. Deterministic test keys exist only in Rust `#[cfg(test)]` code and must never be used as production trust.

After the release owner has approved an existing signing process and its public key, build a reviewed launcher with that public key supplied at build time. The normal unconfigured build refuses all network update checks before making requests; it can still install/play an explicitly trusted initial local bundle.

The only production discovery URL is:

```
https://github.com/RHS059/rust_duty/releases/latest/download/update-<target>.json
```

Asset URLs are constructed from the verified version/name:

```
https://github.com/RHS059/rust_duty/releases/download/v<version>/<asset-name>
```

Manifest-provided arbitrary URLs are not supported. HTTPS redirects are limited to that exact repository's release paths and GitHub's `release-assets.githubusercontent.com` / `objects.githubusercontent.com` asset hosts. Redirect count is bounded. No cookies, GitHub tokens or saved credentials are required for public releases.

Both the semantic version and a strictly increasing release `sequence` must advance. The durable highest activated sequence is never lowered during rollback. A failed release cannot be replayed automatically after rollback: publish a corrected higher version and sequence. SHA-256 protects the full bundle, patch, reconstructed bundle and durable partial prefix. Cryptographic signatures provide authenticity; hashes alone are not accepted as publisher identity.

## Resumable transfer design

Artifacts are downloaded into the install's `cache/` directory. HTTP requests use identity encoding, bounded 1 MiB byte ranges and a 30-second timeout. A strong ETag is required for ranged replies. Every response must have the exact expected `Content-Range` and length. Later ranges include `If-Range` with the previously saved ETag.

Each received block is synced before its byte count and prefix SHA-256 checkpoint are atomically replaced. On restart, any bytes beyond that checkpoint are truncated and the saved prefix hash is recomputed. A corrupted prefix is discarded. A changed ETag or `200` response to a resumed range causes a safe restart from zero rather than appending incompatible bytes. A full `200` response without a strong ETag can complete in one attempt, but cannot be safely resumed after interruption; the launcher will restart that transfer. Servers returning malformed ranges are rejected.

After the final SHA-256 matches the signed asset metadata, the `.part` file is renamed to verified cache storage. Patch transfer failures caused by pause, cancellation or network stalls preserve state and wait for continuation. A structurally invalid/corrupt patch or reconstructed-bundle hash failure triggers a full verified bundle fallback. A patch is considered only if installed base version and actual bundle hash both match and the patch is smaller than the full bundle.

## Real delta format

`tools/release_update.py delta` uses a rolling weak checksum and SHA-256-confirmed matching against 4096-byte blocks from the old bundle. It scans new content byte by byte, so an insertion does not destroy all later block alignment. Adjacent copies coalesce. It emits only unchanged byte-range references and new literal bytes; it does not disguise another ZIP as a delta.

`RDDLT001` binary layout:

- 8-byte magic `RDDLT001`
- old bundle size, new bundle size: little-endian u64 each
- operation `0`: copy offset and length (u64, u64) from the old bundle
- operation `1`: literal length (u64), followed by those bytes
- operation `255`: end; trailing data is rejected

Copy ranges, output size, operation count and total asset size are bounded. Application streams through a 64 KiB buffer into a new file, then verifies the complete target hash. Release generation uses memory-mapped inputs. It intentionally does not compress before delta generation: an opaque compressed archive can destroy reuse. The full fallback bundle is uncompressed too; this trades a larger exceptional/full initial transfer for simple, testable byte-identical patching. A production compression layer is a separate optimization.

## Safe staging and activation

`RDBND001` bundles contain only regular files: magic, u32 file count, then for each file a u16 ASCII path length, path, one-byte mode (0 regular / 1 executable), u64 byte length and content. The unpacker rejects absolute paths, `..`, backslashes, drive names, Windows device names, duplicate/case-colliding names, special modes/symlinks and protected user/install paths. Paths are ASCII and at most 240 bytes; bundles are limited to 2 GiB and 50,000 files.

Extraction happens in a fresh same-volume temporary directory under `versions/`. The verified bundle and version metadata are copied into it; only a completed directory is renamed into place. Activation atomically replaces the small `install.json` pointer, retaining the last successfully exited version. Sync-before-replace protects normal process interruption. Filesystem/device power-loss guarantees still depend on the host OS and storage; no updater can promise against every hardware failure. The implementation syncs directories on Unix; Windows replacement relies on the platform's atomic file replacement behavior.

The launcher alone owns the game child process. While `pending_launch` is true, activation and rollback are refused. On normal game exit it clears that flag; a successful exit marks the current release as last-good. Launch failure/nonzero exit restores last-good when available. Settings/private assets are outside immutable versions and untouched by this switch. The bootstrap itself is intentionally stable, so no running launcher executable is replaced.

## Prepare releases without publishing

Create unsigned local release assets:

```sh
python tools/release_update.py prepare \
  --input /path/to/curated-payload --output /path/to/release-assets \
  --version 1.1.0 --sequence 2 --target x86_64-pc-windows-msvc \
  --entrypoint vector-range.exe \
  --previous /path/to/retained-1.0.0.rdb --previous-version 1.0.0
```

This produces a deterministic full `.rdb`, a true `.rdd` patch, and `update-<target>.payload.json`. The patch is advertised only if smaller than the full bundle. Keep previous full bundles available to the release preparer; clients retain their installed base bundle automatically. To serve several older bases, prepare corresponding patches and include each accurate base version/hash in the payload before signing (at most 32). Never alter signed payload bytes afterward.

An approved external/offline signer or the personally configured `rust-duty-release-sign` helper must sign the exact payload bytes. The Python release preparer does not accept private keys or generate credentials. After signing, verify/seal using the approved public key:

```sh
python tools/release_update.py seal \
  --payload release-assets/update-x86_64-pc-windows-msvc.payload.json \
  --signature approved-signature.bin --public-key approved-public-key.hex \
  --output release-assets/update-x86_64-pc-windows-msvc.json
```

`seal` uses the Python `cryptography` package only for public signature verification. It does not contact GitHub. Do not upload/publish anything until separately approved. A future release must use the tag `v<version>` and exact manifest/asset names. That release must become the repository's latest stable release for discovery. The release target must match the launcher target, e.g. GNU and MSVC builds have different target strings.

`.github/workflow-drafts/prepare-updates.yml.disabled` is a **disabled preparation-only draft**, outside the active workflows directory. Even if copied/approved later, it has only manual dispatch and `contents: read`, prepares unsigned build artifacts and does not create releases, generate keys, grant persistent permissions or sign anything.

## Validation performed

The local harness uses a real loopback HTTP server, a deterministic local-only Ed25519 test key and the same Python patch generator used for releases. It installs version 1.0.0, verifies a signed version 1.1.0 manifest, transfers the smaller patch, reconstructs the exact new bundle, extracts exact target files, activates atomically and rolls back. It asserts that no full-bundle HTTP request occurred in the valid-delta case.

Rust tests also cover malformed/signature-tampered manifests, wrong repository/target, path traversal, symlinks, Windows device names, special archive modes, duplicate paths, truncated bundles, malicious patch ranges, concurrent launchers, full fallback, mismatched base, connection drop plus process/client restart, partial-prefix corruption, strong ETag changes, malformed range/size/hash, persisted pause/resume/cancel, stalled responses, anti-downgrade/sequence replay, staging failure, child-exit gating, last-good rollback, and actual child command-line preservation of absolute settings/private-asset paths across a version switch. Python tests cover delta insert/delete/replace round trips, small/unrelated inputs, deterministic bundles, protected-file exclusion and symlink rejection.

Still required before a production launch: approved key/bootstrap trust, real signed GitHub releases, Windows-native launch/update/recovery tests, real release-to-release patch size/performance measurement, installer/shortcut packaging, and a deliberate publisher procedure for preserving sequence monotonicity and old base bundles.

## Bootstrap CI and dependency notices

`.github/workflows/updater.yml` runs Windows/Linux updater tests, lint, builds and bootstrap artifact packaging with only `contents: read`. It does not use secrets, create keys, sign manifests, publish releases or enable the disabled production workflow. Windows CI parses the owner-run PowerShell scripts without executing them. Setup artifacts are clearly marked UNCONFIGURED.

`tools/collect_updater_licenses.py` resolves actual Cargo dependency graphs for Windows MSVC and Linux GNU and copies packaged registry LICENSE/NOTICE files without inventing copyright text. `updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt` and `UPDATER_DEPENDENCIES.json` are included with both binaries, alongside the project license. Run `cargo fetch --manifest-path updater/Cargo.toml --locked` and regenerate notices after dependency changes. These updater notices are separate from the game's existing third-party notice file.
