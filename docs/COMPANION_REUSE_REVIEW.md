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
