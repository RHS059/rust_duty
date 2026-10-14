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
accepted commit owns frame 1 and freezes the actual entry eye height. The camera
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

- 21 new Python paired matrix/identity/grid/rest tests passed.
- 12 existing importer tests passed.
- Python compilation/CLI checks and actual immutable sidecar validation passed.
- 32 new source-free Rust contracts are included; Rust formatting completed.
  Rust contract execution was initially
  blocked before game compilation by the shared filesystem running out of space.
  Only the new disposable build cache was removed. This is not a Rust test pass.
- No private Blender/FBX conversion, Eevee capture, native runtime visual pass,
  artistic pass, packaged build or ship claim.

The existing Cargo/Python suites remain the test route; no new CI workflow is
introduced. Source changes are based on main 601b7fc416d7feaf677b002354f7130b0f8a8c8f
and preserve its approved Jump r8 integration.
