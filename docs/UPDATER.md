# Install once, then update from GitHub

Rust Duty uses one stable launcher. It checks the fixed `RHS059/rust_duty` GitHub release channel when opened, downloads in the background, uses a real copy/add delta when an exact base exists, and activates the new version after the game closes. There are no signing keys, services, administrator rights, PowerShell setup scripts, or repeated ZIP installations.

## One-time adoption on Windows

Download the standalone `RustDuty.exe` launcher and open it. If it is beside the existing `vector-range.exe`, it uses that folder. Otherwise it checks its previously saved install location; if none is available, a native Windows folder picker asks for the existing game folder. Close the game before this first setup. It never scans the disk.

You can supply the folder explicitly:

```
RustDuty.exe adopt "C:\Games\Rust Duty"
```

The selected folder becomes the persistent install root. The launcher copies only the existing game executable into a local version `0.0.0` and preserves the original executable. Models, settings, profiles, telemetry and saves stay in their original locations. A stable `RustDuty.exe` is placed in that same folder without overwriting another launcher. Open that launcher subsequently; the initially downloaded launcher also remembers the selected location.

The first network release supplies the public code baseline. Later compatible releases use retained `.rdb` bundles for smaller deltas. Neither setup nor updates copy private models into a release payload. The original direct game executable does not check for updates; use `RustDuty.exe` from then on.

For a fresh installation without an existing game, an explicit root can be used:

```
RustDuty.exe --root "C:\Games\New Rust Duty" open
```

A fresh code-only installation needs its model assets supplied separately. Existing installations keep theirs automatically.

## Controls

The launcher console accepts:

- `status`: current version and durable transfer progress
- `pause`: save the current transfer and pause it
- `resume`: continue the saved transfer or retry a stopped check
- `cancel`: discard unfinished transfer data; keep the installed game
- `play`: start the installed game once
- `restart`: wait for normal game exit and update completion, then apply and relaunch once
- `rollback`: restore the last good version while game and updater are idle
- `quit`: save/pause unfinished work and wait for the game to close normally

Opening the launcher starts the installed game once and checks for updates in the background. It never kills the running game or replaces its executable. A staged update activates after normal game exit. Type `restart` before closing the game if you want it to launch again after activation. Normal game exit alone never causes a relaunch loop. There is no polling while the launcher is closed.

Separate terminal commands support `status`, `pause`, `resume`, `cancel`, `update`, `rollback`, `config`, `configure` and `licenses`. Use the same `--root PATH` when controlling another installation. `update` checks, downloads and activates without starting the game. `run` opens the console without an automatic game launch. `licenses` displays the license texts embedded in the standalone launcher.

A network read can take up to the 30-second request timeout to return before a pause/cancel is observed. A failed connection keeps verified partial bytes for the next resume. Closing the console forcibly may leave a pending game record; close the orphaned game, then use `recover --game-closed`. There is only one launcher owner per installation.

## Private models and settings

The game runs with the persistent install folder as its working directory. Its immutable executables live under `versions/`. An absolute settings path is always passed to the game. Private models are discovered in these stable-root locations:

- Weapon: `private-assets/hk416a5.vrm`, `private-assets/weapons/hk416a5.vrm`, `assets/weapons/hk416a5.vrm`
- Arms: `private-assets/fps-arms.vrs`, `private-assets/arms/fps-arms.vrs`, `assets/arms/fps-arms.vrs`, `assets/arms/first-person.vrs`

The last arm name matches the existing private playable preview. Older mappings retain their priority. Explicit mappings and per-launch flags override discovery:

```
RustDuty.exe configure --settings="settings.cfg" --weapon-asset="assets/weapons/hk416a5.vrm" --arms-asset="assets/arms/first-person.vrs"
RustDuty.exe play -- --settings="alternate settings.cfg"
```

Mappings are stored in `launch.json`; the remembered install location is stored in the default per-user metadata folder. Relative mappings stay inside the install root. Explicit absolute mappings can refer to another user-owned location. Symlinks/reparse points are rejected. Paths containing spaces are passed as individual arguments without a shell.

Public bundle preparation excludes settings, saves, telemetry, private asset directories, launch mappings, remembered install locations and the private `fps-arms.vrs` / `first-person.vrs` filenames case-insensitively. The unpacker also rejects those paths. The release workflow should curate only the executable and required public license files; it does not need a publicly uploaded weapon model.

## Trust boundary

Publisher identity is the exact `RHS059/rust_duty` repository delivered over GitHub HTTPS. The launcher deliberately trusts that GitHub account and release channel. Someone who controls that account/channel can publish a new accepted release. SHA-256 detects damaged or mismatched payloads; it is not an independent publisher signature. No public/private signing key, signing secret or signing setup is required.

The only discovery URL is:

```
https://github.com/RHS059/rust_duty/releases/latest/download/update-<target>.json
```

Assets are fetched from:

```
https://github.com/RHS059/rust_duty/releases/download/v<version>/<asset-name>
```

There is no runtime URL override. HTTPS redirects are restricted to that repository's release paths and GitHub's `release-assets.githubusercontent.com` / `objects.githubusercontent.com` hosts, with a bounded redirect count. No GitHub login, token or cookie is used by the public launcher.

The manifest is plain JSON with exactly `schema`, `repository`, `version`, `sequence`, `target`, `entrypoint`, `bundle`, and `deltas`. Unknown fields and legacy signature envelopes are rejected. Both stable semantic version and monotonic sequence must advance. Repeated equal metadata for the installed version is reported as up to date; downgrades, changed same-version payloads and sequence replay are refused. Rollback never lowers the highest activated sequence.

## Transfers, deltas and activation

HTTP downloads use identity encoding, bounded 1 MiB ranges, a 30-second request timeout, and strong ETags for resumable ranged replies. Range bounds and lengths must match exactly. Durable checkpoints record synced bytes, ETag and prefix SHA-256. A corrupted prefix, changed ETag, or resumed full response causes a safe restart. A full response without a strong ETag can complete, but cannot safely resume after interruption.

Every completed patch/full bundle must match the manifest size and SHA-256. A patch is selected only when the installed version and actual retained bundle hash match its base and the patch is smaller than the full bundle. Pause, cancellation and network failure keep their transfer semantics. A malformed patch or invalid reconstruction falls back to the full verified bundle.

`RDDLT001` patches contain old/new sizes, copy(offset,length) operations, literal byte operations and an end marker. A rolling checksum finds 4096-byte base blocks; SHA-256 confirms matches. Application streams into a new file and verifies the reconstructed full bundle. This is a real binary delta, not another archive download.

`RDBND001` full bundles are deterministic uncompressed regular-file archives. They reject path traversal, special files, Windows device names, duplicate/case-colliding paths and protected user data. Limits are 2 GiB and 50,000 files. They extract into fresh same-volume version directories. Activation atomically replaces a small `install.json` pointer and retains the last successful version for rollback. Running game processes are never overwritten. Historical caches/versions are not yet automatically garbage-collected.

## Release tooling

```
python tools/release_update.py prepare --input curated-code-only --output release-assets --version 1.1.0 --sequence 2 --target x86_64-pc-windows-msvc --entrypoint vector-range.exe --previous retained-1.0.0.rdb --previous-version 1.0.0
python tools/release_update.py verify --manifest release-assets/update-x86_64-pc-windows-msvc.json --assets-dir release-assets --version 1.1.0 --target x86_64-pc-windows-msvc
```

The first release omits `--previous` and `--previous-version`. Preparation emits a plain manifest, full `.rdb` and an optional `.rdd`. The manifest advertises a delta only when smaller than its full target. Keep previous full bundles available. Only stable `v<version>` GitHub releases marked latest are discovered. Never replace published version assets or reset the sequence. The bootstrap target must match the game target.

Build the standalone launcher with generated dependency notices:

```
cargo fetch --manifest-path updater/Cargo.toml --locked
python tools/collect_updater_licenses.py
cargo build --manifest-path updater/Cargo.toml --locked --release --bin rust-duty-launcher
```

`trust-status` reports `GITHUB_HTTPS_SHA256 RHS059/rust_duty`. Bootstrap self-replacement is separate from game updates; this implementation does not overwrite its running launcher.

## Verification

Local tests exercise ordinary production manifest parsing over a loopback HTTP source, adoption of a simulated existing install, a first full release followed by a smaller real delta, byte-identical reconstruction, interrupted/resumed/cancelled downloads, corrupted prefixes, bad hashes/ranges, ETag changes, replay rejection, atomic activation, rollback and private-data preservation. The second full bundle is omitted in the adoption test so its delta success cannot be disguised as a full download.

A native child fixture verifies absolute settings/private-arm arguments before and after version switching on Windows and Linux. Public packing and unpacking both test the delivered private-arm filename and case variants. These fixture tests do not establish a live GitHub channel or interactive Windows gameplay by themselves. Verify the published A→B channel and native Windows migration/launch before reporting live delivery complete.
