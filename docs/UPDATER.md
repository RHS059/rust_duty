# Updates inside the game

Open `vector-range.exe` normally. The game checks the fixed `RHS059/rust_duty` GitHub release channel on launch and downloads available updates in the background. It uses a real copy/add delta when its retained baseline matches; otherwise it downloads the verified full payload. Offline startup and ordinary play do not wait for the network.

## In-game controls

The title/pause screen displays update status, transfer progress, and buttons to pause, resume, or cancel. Once the verified update is staged, **Restart & apply** closes the game normally, replaces its executable through a hidden helper, and reopens it. A small in-play notice tells you when an update is ready. There is no separate launcher to open and no recurring ZIP installation.

The helper is a temporary copy of the game's own executable. It runs without a game window and exists only to replace a Windows executable after its running process releases it. It does not install a service, require administrator rights, or terminate the playing process. The original game path remains the path you launch next time.

An older build without this feature needs the integrated game executable once. Merely downloading a separate updater does not add a launch check to that older executable. The public release channel contains code only; existing licensed models remain local.

Pause and cancel are observed at durable transfer checkpoints; an in-flight network request can take up to its 30-second timeout to return. Resume uses validated partial bytes where the server supports it. Cancellation keeps the installed game. `--no-update` disables checking for an explicitly offline run; deterministic capture/demo runs disable it automatically.

## Models, settings, and recovery

The update worker keeps its cache, verified version bundles, transfer checkpoints and rollback state in `.rust-duty-updates` beside the persistent game installation. Only the validated executable is replaced. Model folders, settings, profiles, telemetry and saves are never copied into a public payload or overwritten during activation.

Existing launch mappings and explicit asset/settings arguments are retained. The private preview's `assets/arms/first-person.vrs` and `assets/weapons/hk416a5.vrm` continue to resolve from the persistent game folder, including installations previously adopted by the old launcher. Paths with spaces are passed as individual arguments without a shell.

Public packing and unpacking reject private model locations, settings and saves. The release workflow curates original code and license files only. A successful code update does not depend on publishing either licensed model.

The `updater/` command-line program remains a developer/diagnostic tool for release testing. It is not the normal player entry point.

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

There is no runtime URL override. HTTPS redirects are restricted to that repository's release paths and GitHub's `release-assets.githubusercontent.com` / `objects.githubusercontent.com` hosts, with a bounded redirect count. No GitHub login, token or cookie is used by the game updater.

The manifest is plain JSON with exactly `schema`, `repository`, `version`, `sequence`, `target`, `entrypoint`, `bundle`, and `deltas`. Unknown fields and legacy signature envelopes are rejected. Both stable semantic version and monotonic sequence must advance. Repeated equal metadata for the installed version is reported as up to date; downgrades, changed same-version payloads and sequence replay are refused. Rollback never lowers the highest activated sequence.

## Transfers, deltas and activation

HTTP downloads use identity encoding, bounded 1 MiB ranges, a 30-second request timeout, and strong ETags for resumable ranged replies. Range bounds and lengths must match exactly. Durable checkpoints record synced bytes, ETag and prefix SHA-256. A corrupted prefix, changed ETag, or resumed full response causes a safe restart. A full response without a strong ETag can complete, but cannot safely resume after interruption.

Every completed patch/full bundle must match the manifest size and SHA-256. A patch is selected only when the installed version and actual retained bundle hash match its base and the patch is smaller than the full bundle. Pause, cancellation and network failure keep their transfer semantics. A malformed patch or invalid reconstruction falls back to the full verified bundle.

`RDDLT001` patches contain old/new sizes, copy(offset,length) operations, literal byte operations and an end marker. A rolling checksum finds 4096-byte base blocks; SHA-256 confirms matches. Application streams into a new file and verifies the reconstructed full bundle. This is a real binary delta, not another archive download.

`RDBND001` full bundles are deterministic uncompressed regular-file archives. They reject path traversal, special files, Windows device names, duplicate/case-colliding paths and protected user data. Limits are 2 GiB and 50,000 files. They extract into fresh same-volume version directories. The game stages a verified version while play continues. Restart launches a hidden copy of the game in helper mode; after the running game exits, it atomically replaces the normal game executable and relaunches that same path. The previous executable and verified bundle are retained for rollback. Running game processes are never overwritten. Historical caches/versions are not yet automatically garbage-collected.

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
