# Isolated prone r15 source-only Windows proof

## Status and scope

The isolated Windows lane is implemented and **admitted for actual execution**.
Its source package and 48 producer/consumer/test files are pinned by admission
SHA-256 `07849c6a97b792654394ca290a7936ef51eafcfc9a449c2e7cf86a3f8619fd9c`.
Local preflight reassembled the transparent recipe and recomputed strict source
equivalence successfully. This admission does not claim native dense conversion
or Windows capture success. Missing or changed inputs fail before companion
producers, Blender, Cargo, or the game can start; workflow inputs cannot bypass it.

The adapter, portable dense export/fresh-import helper, regenerated rigid-oracle
sampler, explicit runtime-provenance route, strict source replay/comparison,
native DX12 WARP capture verification, and artifact allowlist now exist. The
original verifier route retains its exact original source/FBX/oracle/camera pins
and numerical thresholds. The regenerated route requires the separate v3 proof
contract and actual generated-source identity.

Local source extraction/replay and both witnesses were completed by the native
owner. This preparation independently reassembled the reviewed source-only shards
and recomputed exact equivalence over all 1,944 samples. The actual original
approved witness and regenerated witness match strictly. This does not establish
new dense conversion, actual Windows execution, or rendered acceptance.

This work ran Python synthetic tests, real read-only source-proof recomputation,
and syntax checks. It did not launch Blender, Cargo, a game, a workflow, or a
publication, and did not upload private source or merge anything.

## Source identities and privacy

- Approved original r15 BLEND SHA-256:
  `cbed3051bb8c4bbdb78f72a49a7a51bd585db33636ddc5312dde38b05a2a86c4`.
- Existing permitted base commit:
  `659fd15ec77a7b4df5018bc7c86a54deace5333e`.
- Existing base path:
  `assets/authoring/prone_crawl/revisions/entry_r5/halcyon_prone_crawl_r5.blend`.
- Existing base Git blob: `65e82510e83cfcd2a8e6a27ee849dc5a0f1531b8`.
- Base SHA-256:
  `67cf025fc31d9804cb0259432a91e496d7d8f84d1d4ac6be2b1914a6a98510ad`.

Existing repository provenance permits this task's consumption of the base; it
is **not** permission to upload or redistribute private source. The workflow
reads that exact existing commit with a sparse checkout and verifies both SHA-256
and Git-blob identity. It never uploads that checkout.

Each reconstructed Windows BLEND has its own measured SHA-256. Its bytes must not
be labeled with the approved original's hash. Windows and Linux serialization can
produce distinct generated hashes. Admission pins the reviewed original Action
recipe and hash-only witness, not one machine's generated BLEND hash. Exact
reconstruction and paired evaluation establish motion equivalence; serialized
byte identity stays false.

Regenerated BLEND, FBX, raw evaluated matrices/skins, process logs, runtime packs,
and other intermediate geometry live under a fresh `RUNNER_TEMP` directory
outside the source checkout. The only artifacts uploaded by this workflow are
explicit native PNGs, their bounded telemetry sidecars, and `summary.json`.
Ordinary full-game runtime packaging remains the existing authorized build route;
this lane does not add raw/intermediate files to that route.

## Activation requirements

The admission binds the following reviewed inputs and code. Any revision must
refresh the exact pins and rerun preflight before publication:

1. A successful original source-only Action delta extraction, replay, fresh
   reopen, and local source-equivalence comparison. The current source producer
   must reproduce the complete pair, preserve inherited Actions and non-Action
   data, and emit only original authored deltas or hash/reference metadata.
2. Hash-only witnesses covering the exact 1,944-time source clock, all 148 bones,
   rig, camera, three rigid actors, and all vertices of the three skin meshes.
   The native comparator retains exact float64-byte equality. Cross-platform
   differences are failures requiring diagnosis, never a tolerance fallback.
3. A reviewed regenerated-runtime producer and verifier, described below, with
   genuine generated-source identity throughout export, camera, VRA, receipts,
   and Rust binding. Tests must reject an arbitrary `passed=true`, stale witness,
   wrong original source, wrong generated source, wrong Action pair, wrong grid,
   and a modified VRA/camera payload. The original cbed admission remains strict.
4. An immutable `tools/prone_r15_windows_admission.json`, with exactly these keys:
   - `schema`: `rust-duty-prone-r15-windows-admission/v1`
   - `base_sha256` and `approved_source_sha256`: identities above
   - `inputs`: exactly `delta`, `approved_witness`, `regenerated_witness`,
     `replay_receipt`, and `source_equivalence`. Ordinary files have only `path`
     and `sha256`. A sharded `delta` has `manifest_path`, `manifest_sha256`, and
     the reassembled original delta `sha256`; no opaque encoding is accepted.
   - `code_sha256`: reviewed repository-relative source/test paths and SHA-256s
5. Input JSON paths under `assets/authoring/prone_r15_sourceproof/`; every input
   must be individually inspected for original/source-free content before
   publication. Do not copy a whole producer output folder. The code map must
   contain all `MINIMUM_CODE_PINS` plus Python and Rust rejection tests, and any
   additional producer/verifier helper the adapter uses.
6. Compute the admission JSON's real SHA-256 and bind the driver to that pin
   in the same reviewed source revision. The driver rehashes every file and recomputes
   the local source-equivalence receipt rather than accepting status fields.

Windows then independently reconstructs the source, writes an actual replay
receipt and hash-only witness, and compares that witness with the pinned approved
witness. These must pass before dense production or capture. The Windows receipt
is tied to that Windows candidate's actual bytes; Linux generated hashes are only
historical local proof evidence.

## Dense-production adapter boundary

The fixed adapter is `tools/produce_prone_r15_regenerated_runtime.py`. Its bytes
and dependencies must be pinned in the admission code map. It uses
`export_prone_r15_regenerated_dense.py`, `sample_prone_r15_regenerated_rigid.py`,
`prone_r15_regenerated_contract.py`, the shared proof-bearing camera sampler and
importer, and the explicit regenerated route in `verify_prone_r15_runtime.py`.
These are prepared implementations; their native results require separate actual
execution and verification.

The driver invokes the adapter twice with identical arguments, first `produce`
then `verify`. These modes follow the option arguments:

- `--root`: actual current checkout
- `--source`: privately regenerated Windows BLEND
- `--source-equivalence`: just-computed strict Windows equivalence receipt
- `--blender`: checksum-verified official Blender 4.3.2
- `--work`: fresh private producer work directory
- `--output`: private runtime directory
- `--runtime-sampler`: actual same-checkout Windows `sample_viewmodel_clip.exe`
- `--camera-sampler`: actual same-checkout Windows `sample_prone_camera.exe`

The adapter implements and independently verifies:

- Both original approved rig and camera Actions explicitly bound after canonical
  reset. Complete pair fingerprints and the pinned approved-motion witness
  identity must be part of the proof-bearing regenerated descriptor.
- One dense paired FBX take, including camera and all three actors, source frames
  1–69 at 60 Hz, bake step 1/64. Reset to frame 1 before export to preserve bind
  basis. No retiming, cropping, simplified curves, or source save during export.
- Fresh FBX import and parity over the retained independent 1,944 source times,
  including camera/world, camera-relative foreground, all bones and all skin
  vertices. Preserve the established error limits and report measured maxima.
- 4,353 VRA keys and paired camera samples at 3,840 Hz, native crop 0–68, source
  and imported offsets 1, exact rig/camera Actions, common motion removed once,
  canonical hierarchy/rest basis, and all three rigid actors.
- Actual current Rust CPU sampler parity at the retained 1,944 times, including
  the rigid actor check, plus actual Rust camera-track admission. Python fallback
  interpolation or a flag-only receipt is not a replacement. Actual Rust probes
  run in bounded batches of at most 256 exact time strings and 24,000 UTF-16
  command-line units; all 1,944 samples remain mandatory and in original order.
  This avoids long-path failures at the Windows command-line limit.
- Windows may regenerate a private dense oracle after strict source equality. For
  a disk-constrained local counterpart, reuse the immutable approved full private
  oracle only after equivalence passes and explicitly bind that equivalence; do
  not relabel it as a newly generated source or duplicate it unnecessarily.
- A narrow regenerated-source descriptor that ties actual generated identity to
  original approved identity, full Action pair, approved witness, and the exact
  proof contract. Keep `candidate_sha256` equal to actual generated bytes.
- Fail-closed `verify` mode independently reloads and hashes every producer
  output/evidence before capture. Its detailed numerical evidence stays private.

`produce` runs the private export, fresh import, camera sampling, optional rigid
sampling, paired conversion, and actual Rust CPU parity. `verify` reopens all
outputs and runs the actual Rust CPU probes again; it never trusts a producer's
`passed` flag alone. An original immutable private oracle can be selected with
`--reference-oracle` plus `--reference-rigid`; this avoids duplicating its 583 MB
on a disk-constrained local executor. `--skeleton-vra` selects the existing pinned
canonical runtime, and `--native-lock` must use the native owner's chosen lock.
A completed private dense export/fresh-import directory may be reused with
`--existing-dense`, together with the same reference-oracle options if applicable.
The adapter rechecks actual FBX/proof/recipe/oracle/evidence hashes and complete
fresh-import metrics before adoption; it does not export twice. Both modes must
receive the same adopted directory. The pinned clock is written as exact LF
bytes; source-index row/skin paths use POSIX separators on every platform.
The command must still be queued with that owner; a file lock cannot discover
unrelated native processes.

The regenerated sidecar schema is `prone-entry-r15-camera-motion/v2`; its pair
receipt schema is `rust-duty-prone-camera-pair/v3`. Both embed identical
`source_equivalence` descriptors. The Rust binding telemetry preserves that
descriptor. The template is `tools/prone_r15_equivalence_contract.json`, embedded
at Rust build time and also read by Python. It is not an extra private runtime
companion. The original sidecar v1 and receipt v2 retain original-only admission.

The five runtime files consumed by this driver are `asset.vra`, `asset.vrs`,
`asset.vrm`, `asset.prone-camera.json`, and `asset.prone-pair.json`. The latter must
bind actual generated-source, VRA, and camera hashes. Any extra sidecar required
by the final Rust contract needs an explicit allowlist update; it must never be
silently dropped or copied recursively.

## Capture and source inspection

The driver constructs a separate diagnostic animation manifest from the current
validated runtime companions, adds the prone pair, and keeps the default manifest
unchanged. It starts the current Windows game twice, in order 60 Hz then 30 Hz:

`--renderer=dx12 --force-fallback-adapter --no-update --level=range --capture --capture-native-window --capture-sequence=gameplay-prone`

The capture identity binds run/attempt/commit, frozen binaries/source pins,
isolated runtime inventory, actual generated source, and source equivalence.
There must be 283 native-window frames at 60 Hz and 142 at 30 Hz, exactly named,
with every PNG and four sidecars present. Each image must report Dx12, requested
`dx12`, Microsoft Basic Render Driver, native window, and 1440×900. Rendered frame
witness pixels and PNG validity/coverage are checked, followed by the existing
strict prone frame/sequence/gameplay/time checks and exact shared-timestamp state
comparison. Native process success alone is insufficient.

Static inspection of the PR71 source found the expected DX12 route:

- `src/main.rs`: wgpu and legacy both execute `app::run`.
- `src/sim.rs` near 1270: prone track replaces eye height during the clip.
- `src/app.rs` near 1251: prone camera axes feed the world camera.
- `src/capture.rs` near 95: native-window capture uses no offscreen target and
  derives metadata from the active renderer.
- `src/draw/facade.rs` near 763: rendered witness commands precede capture.
- `src/render/frame.rs` near 151 and 83: ordered GPU copy, then completed readback.
- `src/render/runtime.rs` near 125: readback/submission failures propagate.
- `src/platform/window.rs` near 332: final-frame submission occurs even when the
  application future resolves, preventing a missing final PNG from appearing as
  successful completion.

These are source findings, not evidence that Windows capture has executed.
Deterministic 30/60 Hz sampling does not establish sustained display FPS or
arbitrary continuous-time parity. Capture telemetry and witnesses do not replace
source/CPU equivalence or independent image review.

## Official Blender toolchain gate

The reviewed historical Windows ZIP pin is
`933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6`,
405,138,423 bytes. Previous work had secondary historical Scoop-manifest
corroboration while the official checksum line was inaccessible. This preparation
does **not** claim fresh vendor verification.

At execution the workflow must fetch
`https://download.blender.org/release/Blender4.3/blender-4.3.2.sha256`, find exactly
one line for `blender-4.3.2-windows-x64.zip`, and require it to match that pin. It
then downloads the official ZIP, verifies size/hash, checks Blender's version,
and writes a receipt binding the actual executable and archive. Unavailable or
mismatched vendor evidence stops the lane; no secondary-source fallback exists.
No Blender rendering is requested by this workflow or adapter contract.

## Branch and aggregate isolation

Do not move PR71's active branch to publish this preparation. Create a dedicated
`aella/prone-r15-sourceproof-*` branch containing the code lineage:

- main baseline `c04706de2e559a08532be78e4bd37c989f62938e`
- PR71 original r15 runtime head `b9d07be18aa0b4fd383516ca0786e7f5f792d0d8`
- source verification checkpoint
  `32a34a415b1858343653cc77b0354701a1309d21` (parent b9d07be)
- source producer revisions, real proof/admission, regenerated consumer changes,
  and this workflow on top, as available and reviewed

Only `pull_request` and explicit `workflow_dispatch` trigger the isolated proof;
there is no base-branch filter, so a stacked PR is supported. Omitting a push
trigger avoids a duplicate long proof when opening the draft.

Use a draft stacked PR. Do not push the local verification snapshot's synthetic
Git history. The dedicated branch prevents ordinary `build.yml`'s
`game-${branch}` concurrency from replacing PR71's active aggregate. This workflow
has its own `prone-r15-sourceproof-${branch}` group and `cancel-in-progress: false`.
Its same-run reload/walk/ADS/directional/jump producers wait for admission; no
cross-run artifact substitution is allowed. The main aggregate still executes
normally for the new branch/PR and retains its existing full-game build route.
This lane has contents-read permission only and performs no deployment or merge.

## Preparation checks

- `python -m unittest discover -s tools -p test_prone_r15_windows_sourceproof.py -v`
- `python -m unittest discover -s tools -p test_prone_r15_regenerated_runtime.py -v`
- `python -m unittest discover -s tools -p test_verify_prone_r15_runtime.py -v`
- `python -m py_compile tools/run_prone_r15_windows_sourceproof.py tools/test_prone_r15_windows_sourceproof.py tools/produce_prone_r15_regenerated_runtime.py tools/export_prone_r15_regenerated_dense.py tools/sample_prone_r15_regenerated_rigid.py tools/prone_r15_regenerated_contract.py tools/verify_prone_r15_runtime.py`
- Parse `.github/workflows/prone-r15-windows-sourceproof.yml` with a YAML parser
  and check trigger/job inventory.
- `python tools/run_prone_r15_windows_sourceproof.py preflight --root .` passed
  against the exact committed-source inputs. It still rejects absent/stale pins.
- Synthetic suites passed: 20 orchestration, 17 regenerated adapter/provenance,
  and 24 unchanged original runtime regressions. These are not native results.


## Follow-on full-game packaging hook

After actual Windows proof passes, the minimal separate integration is an
explicit validated-runtime handoff into the existing game build: package only
`asset.vra`, `asset.vrs`, `asset.vrm`, `asset.prone-camera.json`, and
`asset.prone-pair.json`, plus a bounded validation receipt binding their hashes to
the proof commit/run. `package_game.py` must verify that receipt and require the
identical five-file set before materialization; `build.yml` must consume only its
own dependency run's artifact. Keep the ordinary default manifest unchanged until
that integration is reviewed. No BLEND, FBX, source oracle, intermediate geometry,
or raw process logs belong in this handoff. This follow-on is documented only;
the isolated lane's artifact allowlist remains unchanged.
