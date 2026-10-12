# Companion reuse eligibility review: GPU telemetry registration

Review date: 2026-10-06. This review refreshes source eligibility for the
existing five immutable companion artifacts. It does not generate assets,
rerun Blender/source-oracle parity, or establish a native renderer result.

## Exact identities and failure

- Previous review: `bb496492879ad42b5ce5b3707828f4281a663fd0`.
- Reviewed current main: `a2fc4734b7f1afcdc92e46d3d813a423fd1d119e`.
- Locally inspected source: `5f03245ebb5ae9811fec5cc945117a15080df55f`.
  All 61 refreshed source-file Git blobs match reviewed main. The complete
  GitHub comparison from locally available `b35e59667b56151f9bb6fb749b706d97bf842db9`
  establishes unchanged paths; direct current-main file reads establish
  `src/lib.rs`, `tools/package_game.py`, and the three new telemetry paths.
- Unchanged eligible assets tree: `67adef966a2c0db0ee1535897a9011becb6e53a9`.
- Historical origin run: `37339601251`, attempt 1, head
  `72663e2b18dda818c800dec96af1ce452dbdd4da`, tested merge
  `fbf6c33df03c155e23f75d485660b7648ee36024`.

The existing guard correctly rejects current source with
`current source Git identity mismatch: src/lib.rs`. Every original lock row
was audited: 57 of 58 match their reviewed byte count, SHA-256 and committed
Git blob. The sole mismatch is exactly the addition of
`pub mod gpu_telemetry;` and its blank line after `ui_theme`.

The current library is 1,701 bytes, SHA-256
`090d44a59fb9b4d6de1a98e6199f157afce88ed81a1930395675ee542d6217cc`,
Git blob `962e4d27791833bc516c308a54d6045979039251`. Its historical
`origin_sha256` remains
`b8be3461113a2967b93959878a744b8380cc296a1cb1b7eb770417edd0a5c551`.

## Sampler dependency review

The production asset workflow builds `sample_viewmodel_clip` with
`--locked --release --no-default-features`. The example imports
`viewmodel_animation::{game_model_root, AnimationSet}`. That module imports
the rigid `asset::WeaponAsset` parser and `skinned_asset::{crc32, Bone,
SkinnedAsset}`, plus `glam` and the standard library. The example, all three
parser/sampler files, `Cargo.toml`, `Cargo.lock`, and `build.rs` retain their
reviewed and historical bytes. Parsing, companion binding, sample timing,
interpolation, skin palettes, actor transforms, and JSON probe output have
not changed.

The newly registered telemetry module imports existing `serde_json` and
standard-library APIs. Its Windows implementation additionally binds the
inbox PDH library. The module has no startup constructor, global allocator,
exported replacement symbol, or call from the CPU sampler. File creation and
thread startup occur in the explicit `Recorder::start` call. That call's
production owner is `src/telemetry_export.rs`, wired to the game binary;
the asset sampler does not invoke it. The Windows PDH query is constructed
inside the recorder worker, not by registering the library module.

The newly compiled production modules are now pinned and mandatory:

- `src/gpu_telemetry.rs`
- `src/gpu_telemetry/counters.rs`
- `src/gpu_telemetry/windows.rs`

This binds the exact implementation supporting this registration review,
including its Windows-only dependency. All three paths were verified absent
at `origin.tested_merge`; they are marked `origin_absent: true`, with no
invented historical digest. The separately declared `gpu_telemetry/tests.rs`
is `cfg(test)` only and is not compiled into the production sampler.
These additions do not claim a complete historical Rust build-cache hit or
expand the lock into a whole-game dependency audit.

## Preserved proof boundary

All 58 historical `origin_sha256` values were checked against the actual
historical tested-merge blobs and preserved. The immutable origin object,
five artifact records including ZIP hashes and member inventories, external
Jump source identity, eligible asset tree, limits and acceptance statement
are unchanged. The 57 already matching original source rows are unchanged.

Every `revalidate_reused_companions.py` function, including `verify_source`,
is unchanged. The only executable change extends the mandatory source-path
inventory to the three telemetry files. Expected checkout commit, assets
tree, exact HEAD blob, exact worktree bytes, external Jump source, complete
ZIP inventory and digest, validator success, and post-validation input
immutability are still required. No normalization or allow-on-mismatch path
is introduced.

All functions in current `package_game.py` have the same AST as the
historical producer version. Its previously reviewed difference remains
limited to the `RUNTIME_FILES` documentation/theme list. Exporters and other
asset validators retain their existing pinned bytes. This review found no
source-oracle behavior change requiring fresh generation.

## Executed evidence and remaining work

- Passed: audit of all 58 old source rows, all 58 historical digests, and
  current-main identity for all 61 new rows and the complete assets tree.
- Passed: old lock reproduces the exact `src/lib.rs` rejection through the
  real source verifier; refreshed lock passes against clean local commit
  `5f03245`, with hash-checked external Jump bytes from its pinned commit.
- Passed: 38 scoped Python tests across `test_revalidate_reused_companions`,
  `test_fetch_source_bound_companions`, and `test_windows_recovery_workflow`.
  New real-Git fixtures cover a stale registration pin, its narrow refresh,
  worktree edits, and committed edits with restored worktree bytes. Each of
  the library, all three telemetry paths, and sampler is tested. Missing
  telemetry lock rows fail validation. New paths do not claim origin hashes.
- Passed: fresh extraction, immutable ZIP digest/inventory verification,
  and current structural/source validators for the locally available
  original walk, ADS, directional and Jump packs. The staged input snapshot
  is unchanged after validation. Historical parity reports were read as
  historical evidence, not regenerated.
- Not run locally: complete five-pack revalidation and aggregate generated
  verification, because the complete original reload ZIP is unavailable
  in this executor. No partial or synthesized reload ZIP was substituted.
- Not run: fresh generation, fresh source-oracle parity, Rust compilation,
  or native Windows/DX12 execution as part of this lock-only review.

The full Windows recovery path must still download all five exact original
ZIPs, pass the unchanged current-source and structural checks, then complete
its separately required build and native checks. A pin refresh or four-pack
local check is not a five-pack acceptance receipt or gameplay approval.

## Static calibration asset eligibility addendum (2026-10-06)

The separately approved untextured legacy HK416 is restored as one runtime file,
`assets/weapons/hk416a5.vrm`, for the documented static calibration fixture.
Source base is main `3e64a7dbd64802df2cb4f393e5e6afffd8988640`. The asset is
3,901,244 bytes, SHA-256
`082b8302a39c8fd3218f3c732f8c3a06c1af1fb40f703f8d64f581b38b32d4aa`, Git blob
`f3743fbe7c9ec1e65c70ee1a7ce8cd620aa5dcea`. Strict VRMESH01 inspection verifies
CRC `fc786964`, 30 mesh parts, zero textures and zero texture bytes.

The only assets-tree difference from
`67adef966a2c0db0ee1535897a9011becb6e53a9` is this added path. Every pre-existing
asset blob is unchanged. The reviewed new assets tree is
`a691466f735dee7861b3476d700572255ed2cae5`. Only `eligible_assets_tree` is updated
in the reuse lock; all 61 source rows, all 58 historical origin hashes, the
five immutable ZIP identities, origin record and acceptance boundary are unchanged.

The CPU companion sampler and generators do not load this optional static weapon.
The new native presentation fixture selects it explicitly and suppresses automatic
authored loading; ordinary authored validation keeps every existing companion and
replay. This audit permits the exact additive tree, not arbitrary future asset
changes, and does not claim new generation/source-oracle parity or native success.

## Graphics-device registration eligibility addendum (2026-10-06)

Reviewed source is main `5f5de8c008fdcfc0bdd6f6b0d84a5c14ad6a9707`.
Windows preview run `37494031701` stopped at the source guard before game
compilation. Auditing **all 61 existing source rows** found exactly one mismatch:
`src/lib.rs` gained only `pub mod graphics_device;` in
`ebf4bcb7f489766e3c7ec188c35db9bb4146c62b`. The old lock reproduces
`current source Git identity mismatch: src/lib.rs` through `verify_source`.
The other 60 rows and eligible assets tree are unchanged.

The narrow refresh binds these exact current identities:

| Path | Bytes | SHA-256 | Git blob |
| --- | ---: | --- | --- |
| `src/lib.rs` | 1,726 | `d99219a4e4fcc06d73d3841b0b6d6fa40edcb4ac2aa5e1882cd5f66cda7284b1` | `b2873bf2dbe7f8785402dab7b7e078920357231f` |
| `src/graphics_device.rs` | 18,112 | `731d3ad664ed8b8cc358e19f7ec321646af8fbe50872ccf63322128264418e8b` | `7e8d180025a490b7b0d280b1eaca563d9243cb05` |

The new module imports `draw::BackendInfo`, `platform::launch::LaunchOptions`,
the already locked `serde_json`, and the standard library. Its session is a
lazy `thread_local!` initialized only on explicit access. The default session
does not read settings or create a device. File reads/writes are explicit
`Preference::load`, `Preference::save`, launch, and menu operations; callers
are the game entry point, pause menu, application diagnostics and renderer.
Native adapter enumeration in `ensure_catalog` is guarded by `wgpu-runtime`,
which the production `--no-default-features` sampler build does not enable.
There is no startup constructor, global allocator, replacement symbol, new
external dependency, or sampler call into this module.

The complete CPU probe call path remains the reviewed example into
`viewmodel_animation`, `asset`, and `skinned_asset`, using `glam` and standard
library operations. Those four files, `Cargo.toml`, `Cargo.lock`, and `build.rs`
retain their exact pins. The GPU/CPU feature commit's other game, UI, and
renderer edits do not enter that call path. This establishes source eligibility
for these reused companions, not whole-game build equivalence or acceptance
of the new graphics-device behavior.

The [complete historical tree](https://api.github.com/repos/RHS059/rust_duty/git/trees/fbf6c33df03c155e23f75d485660b7648ee36024?recursive=1)
was checked with `truncated: false`: `src/graphics_device.rs` is absent, so its
new row has `origin_absent: true` and no invented `origin_sha256`. All 58
historical origin digests were rechecked against origin Git blobs: 56 match
unchanged local bytes, and the historical library and package tool were read
at the exact tested merge. All 58 historical values remain unchanged.

The lock now contains 62 source rows. Only the existing library's current
identity/review note, the new current-only graphics module, and the reviewed
source commit change. The origin object, five exact ZIP digests and complete
member inventories, external Jump identity, eligible assets tree, limits,
and acceptance statement are byte-for-byte equivalent JSON values. The
validator adds mandatory library and graphics-module paths; every validator
function AST remains unchanged, including both early and late source checks.

Executed on this exact source plus the four-file eligibility patch:

- Passed: all 62 current committed blob, worktree byte-count and SHA-256 pins;
  all preserved historical identities and immutable lock sections.
- Passed: 47 Python tests in `test_revalidate_reused_companions`,
  `test_fetch_source_bound_companions`, `test_windows_recovery_workflow`, and
  `test_windows_migration_preview_workflow`; temporary fixtures used the workspace.
  Real-Git cases cover the stale registration, exact refresh, worktree edits,
  committed edits with restored worktree bytes, and a graphics-module edit
  after validators finish that must not publish a success receipt. Omitting
  either the library or graphics-module lock row fails validation.
- Passed: `git diff --check` and comparison proving the registration is the
  only library change and all source-verifier functions are unchanged.
- Not run: full five-ZIP extraction/revalidation, external Jump byte validation,
  asset generation, fresh source-oracle parity, Rust compilation, or native
  Windows execution. Original ZIPs and the external Jump file are not available
  in this checkout. The Windows workflow must still validate those exact inputs
  and perform its separate build and native checks before claiming success.
