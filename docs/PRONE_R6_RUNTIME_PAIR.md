# Prone r6 paired runtime binding (opt-in WIP)

This change adds original runtime/importer code and source-free tests. It does
not enable an asset in the default manifest, publish private soldier assets,
merge the authoring branch, or approve the motion. Hal's immutable authoring
contract is [PR34 at 659fd15e](https://github.com/RHS059/rust_duty/tree/659fd15ec77a7b4df5018bc7c86a54deace5333e/assets/authoring/prone_crawl/revisions/entry_r6).
The authored wrist-guard residual remains 0.763097 degrees against the 0.08-degree
strict diagnostic. Artistic approval, a real paired private FBX conversion, and
native game presentation evidence remain pending.

## Runtime opt-in

Only a complete local pair can load. Add all five manifest entries together:

    prone_entry.policy=paired_r6_wip
    prone_entry.asset=prone/asset.vra
    prone_entry.clip=prone_crawl_enter_r6
    prone_entry.camera=prone/asset.prone-camera.json
    prone_entry.receipt=prone/asset.prone-pair.json

The matching VRS/VRM companions are still checked by the existing VRA loader.
The import receipt binds the actual VRA bytes, exact camera-sidecar bytes,
candidate source hash, both source Action fingerprints, complete native frame
mapping, and the one-time common-motion-removal policy. Missing halves or
mismatched fingerprints fail the authored-model load. No format change to
VRANIM01 is made. Source metadata is bounded, every camera/delta matrix must be
finite, rigid and right-handed, and all 545 clock samples must be present.

The simulation starts one paired clock only when the ordinary stance controller
accepts entry into prone. A standing request still passes through crouch. The
accepted commit owns frame 1 and freezes the actual visible entry eye height,
absorbing any residual landing kick once so it cannot add another height track.
The camera
height replaces generic stance easing while the pair owns presentation:

    height = entry_height + depth_fraction * (0.2794 - entry_height)
    source_frame = 1 + 60 * elapsed_seconds

The 68/60-second key span is unchanged; frame 69 is held while prone owns the
pair. The normalized impact trough may exceed 1 (about 1.031746); it is not
clamped to the endpoint. Existing low-ceiling safety still caps actual eye
height. At frame 69 the endpoint is exactly the ordinary 0.2794-m prone target.

Camera orientation is expressed relative to the initial authored camera,
in camera-local +X-right/+Y-up/-Z-forward axes. Only the rendered world-camera
axes use that quaternion. Gameplay aim, recoil logic, capsule shape, firing
decisions and traversal retain their existing owners.

The weapon samples the same committed seconds, with no 60-ms entry crossfade.
The paired pose is exclusive of run/walk/reload/cant and procedural sway/action
layers; static user viewmodel offset is preserved. ADS, reload, airborne,
traversal, stance exit, death and reset release ownership. Ordinary height easing
resumes from the current height, not a stale pre-entry height. Pause does not
advance the simulation. Renderer failure releases the camera half as well.

## Importer boundary

Use the existing FBX importer with explicit paired options. For native crop
0..68, use --fps 60 --subdivisions 8 --pair-candidate-frame-offset 1 and
--name prone_crawl_enter_r6. The explicit --take is the actual FBX stack name,
which may differ from the source Action name. Existing required FBX, source,
actor and skeleton arguments remain required.

Additional pins:

- --pair-sidecar: immutable camera_motion_samples.json
- --pair-sidecar-sha256: d87a195fff6e65ab78961b6ec8afaecd78e65fd22d0bff892afbb05c004abe2b
- --pair-candidate-source: private candidate BLEND path (hashed only, not opened)
- --pair-rig-action-fingerprint: 2a860a55decb8f0fa06226f55a2ace85e9629a21b54ff827cb275b244da8d41f
- --pair-camera-action-fingerprint: 7006eeec2a3a9c83ca6eec27290692db81554ecb219afc656f8da413aa311c82

The importer removes D(t) = C(t) * inverse(C0) from evaluated global bones and
rigid actors exactly once, before its existing Blender-to-glTF basis conversion.
It restores canonical initial armature/skin object worlds before freezing rest
geometry. Bone rest matrices, skin bindings and existing hidden-actor semantics
remain checked. The default unpaired path is unchanged.

Paired input must carry the declared common motion in the armature object track.
A fixed/already-normalized armature or an exporter that folds object motion into
root bones fails closed; adapt only after inspecting that actual export.
Resampling is limited to timestamps present in the 480-Hz sidecar. No camera
curve is inferred at arbitrary extra FBX samples. Successful conversion emits
asset.prone-pair.json and the exact bytes of asset.prone-camera.json.

## Evidence at this checkpoint

- 20 new source-free export-adapter tests passed, including success/error
  restoration of temporary bindings. The existing tools discovery suite passed
  all 53 focused local Python tests after this adapter revision.
- 21 new Python paired matrix/identity/grid/rest tests passed.
- 12 existing importer tests passed.
- Python compilation/CLI checks and actual immutable sidecar validation passed.
- At 6afba2da812aba19c862c97189b9ca1cfce50640, the existing
  [runtime contracts CI](https://github.com/RHS059/rust_duty/actions/runs/38518527667/job/115702686273)
  passed all-target Clippy with warnings denied and the complete
  cargo test --locked --no-default-features suite: 913 passed, zero failed,
  two existing ignored. This includes all 33 new prone contracts and the direct
  paired-renderer phase/draw test in source_triangle_completeness.
- The [existing sampler CI](https://github.com/RHS059/rust_duty/actions/runs/38518527676/job/115702686530)
  passed at the same source head. Broader CI built the game and passed its
  existing source-conversion, GL/DX12 UI, renderer and same-platform return
  checks. A Windows dependency-notice provenance failure belongs to the separate
  release repair; it does not establish paired-prone native presentation.
- At 0f4bedbbff5e808b86bd71be048570cca6495255, the updated-base
  [runtime contracts CI](https://github.com/RHS059/rust_duty/actions/runs/38530583133/job/115741240520)
  passed all-target no-default-feature Clippy and all 917 Rust tests, with zero
  failures and two existing ignored. All 33 prone contracts passed again.
- At 966c22cec58d819a50085e6a3db2300ed0b69dd5, the generic
  [actual DX12 WARP gameplay capture](https://github.com/RHS059/rust_duty/actions/runs/38531454092/job/115746216645)
  passed; subsequent notice verification failed on inherited stale inventory.
  That run also exposed newer-main formatting/iterator failures. Calibrated
  OpenGL HIP/ADS captures passed, while both DX12 calibrated captures timed out.
  These results do not validate the opt-in prone pair or waive the DX12 failures.
- The source-only paired-export adapter below is a later revision. Its source-free
  checks do not constitute an actual Blender/FBX export result.
- The initial local Rust build stopped before game compilation because the shared
  filesystem ran out of space. Only its newly generated disposable cache was
  removed; subsequent verification used the existing remote CI.
- No private Blender/FBX conversion, Eevee capture, native runtime visual pass,
  artistic pass, packaged build or ship claim.

The existing Cargo/Python suites remain the test route; no new CI workflow is
introduced. Source changes started from main 601b7fc416d7feaf677b002354f7130b0f8a8c8f.
The branch now incorporates main 5b1d6d400f14ddaa60f27c4766cb3b3078424973,
preserving approved Jump r8, the city picker and new level/weapon lighting.
The refreshed-base revision requires fresh CI; earlier green evidence remains source-specific.

A separate semantics-preserving city test initializer fix is included solely to
unblock the existing all-target Clippy suite. Its first failure was in unchanged
tests/city_level_contract.rs, not a prone-specific compilation failure.

## Explicit paired export adapter

The historical PR34 five-take exporter remains untouched, including its frozen
r1 source snapshot, actions and hash. Use tools/export_prone_pair.py with the
separate tools/prone_pair_r6_export.json for this pair. The config pins exact
candidate bytes, both Action fingerprints, the camera sidecar, action count,
object selection and the complete native clock. It is intentionally diagnostic.

The adapter binds both Actions concurrently and checks evaluated camera matrices
and common rig-object motion at every one of the 545 sidecar times. It emits a
single global-scene FBX stack; NLA-strip and all-Action export are disabled.
The camera stays bound but is excluded from the ARMATURE/MESH FBX selection.
Common motion is retained in the FBX for the importer to remove exactly once.
Rigid actors with Armature modifiers are rejected because that FBX route would
omit their object animation. Source files are never saved, existing output
locations are refused, and temporary bindings are restored even on failure.

This timing choice follows Blender 4.3.2's
[global-scene bake implementation](https://github.com/blender/blender/blob/v4.3.2/scripts/addons_core/io_scene_fbx/export_fbx_bin.py):
it retains absolute frame times and names the stack after the scene. The adapter
sets that temporary scene name to prone_crawl_enter_r6. With the existing
importer's explicit anim_offset=0, source frames 1..69 map to native crop 0..68
using --imported-frame-offset 1. This must not be replaced by the historical
zero-based NLA timing convention.

When the native capture resource window is free, the remaining actual export
step is to run a fresh private Blender 4.3.2 process, without rendering:

    blender --background --factory-startup --disable-autoexec /private/candidate.blend \
      --python-exit-code 1 --python tools/export_prone_pair.py -- \
      --config tools/prone_pair_r6_export.json \
      --sidecar /private/entry_r6/camera_motion_samples.json \
      --output-dir /private/new-paired-export

That produces a private FBX, exact sidecar/config copies, a normalized evaluated
bone/actor source oracle, and export_receipt.json. The receipt is written only
after all identity/evaluated checks, export and source-byte/Action preservation
checks pass. It records no artistic approval or runtime-import claim.

Then run the existing import_fbx_viewmodel.py in another clean Blender process,
with --take prone_crawl_enter_r6 --name prone_crawl_enter_r6 --fps 60
--native-start 0 --native-end 68 --subdivisions 8 --imported-frame-offset 1,
the actual emitted FBX hash, the existing canonical skeleton VRA and rigid actors,
and every --pair-* pin listed above. Use a new output directory. Reimported rig
object motion must match the sidecar at every time; no fallback normalizes a
fixed rig or folds a missing object track into root bones. Actual source/FBX
witness comparison and paired native presentation remain required for this new
export/runtime boundary. The default manifest stays off until a complete pair
is available.

For a revised source, create a separate explicit config and matching sidecar
with the revised source hash, both fingerprints, exact Action count and source
contract commit. Do not replace the checked-in r6 config or weaken any historical
pin. This adapter currently accepts the r6-compatible Action names, sidecar
schema and native timing only. Renamed Actions or another timing/coordinate
contract need an explicit reviewed adapter/runtime revision, not an alias.
Hal's wrist correction and genuine paired Eevee/art review remain separate
outstanding authoring work.

## Draft-only inherited build repairs

To test this branch against the current main, it reuses coordinated original
build repairs from PR65 at 4d2e37d035f9aeef2fe4ee9fe4d1bf9eb4e50d15:

- Copied app test-block removal and equivalent private frame-trace capture tuple
  with an exact JSON regression.
- Equivalent range/lighting iterator and test-module ordering fixes, plus
  rustfmt-only capture/frame/world-draw changes.
- The identical city Settings initializer.
- The unchanged license collector's refreshed Cargo.lock provenance inventory.
- Preview default-feature assertions scoped to the actual game-build step, with
  two negative probes; mandatory lighting files in packaging test fixtures and
  the preview inventory.

The current source blobs and complete main tree were checked before draft reuse.
The new main lighting code, baked assets, picker and approved Jump packaging are
preserved. No authored pose was modified. PR65 remains separately owned; this
draft reuse does not mark it ready or merge it. Current-base checks must run again
for this exact branch, and the unresolved calibrated DX12 timeouts remain failures.
