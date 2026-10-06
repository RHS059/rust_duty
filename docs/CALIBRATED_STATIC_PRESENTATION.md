# Calibrated static presentation fixture (WIP, native applicability pending)

This exercises the reference-presentation path documented by
`docs/VISUAL_REFERENCE_MATCH.md`, using the exact approved untextured static
HK416. It does not replace, shorten, change or approve any authored gameplay
replay, telemetry equality check, contact test or human review.

## Inputs and command

Use the already-built dual-runtime `vector-range.exe` from this exact source
revision and the already-staged pinned app-local Mesa directory. No additional
game build is performed by this runner. Only Pillow and the repository's existing
stdlib/Pillow tools are needed; NumPy is not a runner/validator dependency.

    python tools/run_calibrated_presentation.py --executable target/debug/vector-range.exe --root . --runtime evidence/game-ui-gl-runtime --evidence evidence/calibrated-static

The coordinator can add `--bin vector-range` to the existing GL UI job's
`cargo build --locked --no-default-features --features legacy-macroquad,wgpu-runtime --example game_ui_contract`
command and run this step after GL UI verification. Always retain the separate
`evidence/calibrated-static/` packet, including failed native captures. A failing
fixture returns nonzero. All existing authored shards/aggregate remain required.

Source must contain `assets/weapons/hk416a5.vrm`, SHA256
`082b8302a39c8fd3218f3c732f8c3a06c1af1fb40f703f8d64f581b38b32d4aa`.
Its validated format is VRMESH01/v1, CRCfc786964,30 meshes,84,926 vertices,
98,522 triangles, zero textures and zero texture bytes. It contains neither an
FBX/GLB container nor skinned arm data. The coordinator owns publication of this
single specifically authorized weapon; this proposal does not include its bytes.

## Exact presentation route

The runner invokes `--weapon-asset` and omits `--animation-manifest`,
`--viewmodel-asset`, `--arms-asset`, `--procedural-weapon` and gameplay sequences.
Those omissions are essential: a manifest could reselect authored loading,
while `--procedural-weapon` would select the block-rifle fallback.

It deliberately uses production `ViewmodelFraming::from_args` defaults without
framing overrides. A separate additive Rust test calls the actual constructor
and pins HFOV76, hip (0.05930,-0.04831,-0.30806), ADS (0,-0.03794,-0.2322),
hip YXZ angles (0.04118,-0.01252,0) and identity ADS rotation. A later default
change must fail that ordinary Cargo contract, not silently pass a forced pose.
The capture validator also requires emitted HFOV76 and exact ADS0/1 metadata.

`--profile=kestrel` selects `Settings::default`. The generated, hash-bound settings
file explicitly sets all three extra viewmodel offsets to zero. Kestrel's world
FOV does not control the fixed viewmodel camera. `--capture-lighting` freezes
simulation time at zero and supplies a checked lighting record; no moving,
reloading, sprinting or firing input is used. The staged executable directory
contains only the pinned runtime and executable, so no adjacent private arm pack
is discovered. One reference and one diagnostic world checkpoint are retained
per invocation. The generic process counter reports1 for its explicit output
file; the validator separately requires both PNGs and all three sidecars.

## Measured pixels and feature identity

`calibrated_sight_contours.py` scans the complete unscaled960x540 image, excluding
only the independently validated64x22 frame-witness rectangle. It localizes
bounded background contours and a unique near/far sight constellation without
consulting target pixel coordinates. The original calibration comparison occurs
only after measurement: rear aperture ADS(480,270), front guard hip(526,280),
both axes inclusive±4px including zero. Missing or ambiguous contours fail.

`static-sight-geometry.json` records independent fits to actual recovered static
asset vertices: near sight mesh27 and far guard mesh29, concentric inner/outer
rims on both depth faces,21 vertices per fitted rim, residuals below72nm.
The validator projects that source geometry with the documented unchanged camera
and framing to check near/far depth and approximate opening scale. The projected
center is explicitly labeled projection evidence; it never becomes the measured
center or a target-centered search region. Native raw contours still need first-
run inspection to establish the detector's applicability to the real raster.
The copied contour helper retains its prototype labeling for that reason.

Reports retain threshold6/8/10 sensitivity and uniqueness, and explicitly label
0.5px as quantization only, not total uncertainty. Detector morphology/scale
filters are identity assumptions, not a relaxed calibration tolerance. Raw PNGs,
logs, exact invocation, EXE/asset/settings hashes, per-pose invocation-derived
witnesses and measured coordinates are retained even when calibration fails.

Four measurements are required: hip/ADS on Windows OpenGl/llvmpipe and
Dx12/WARP/Fxc, using the same executable and settings. Original absolute results
and GL-to-DX12 deltas are separate. Exact backend agreement cannot waive an
absolute calibration failure. Human visual/hardware gates remain open.

## Same-attempt aggregation helper

`verify_calibrated_presentation.verify_evidence(evidence, expected_binding)` can
recheck the transported packet against the caller's independently verified
source/run/attempt/EXE binding, reseal checks, decode raw witnesses and remeasure.
Its CLI accepts `--evidence` plus the existing authored `--input-manifest`.
This helper is delivered for follow-on aggregate wiring; its full transported
packet path has not yet been executed natively. Do not treat its presence as a
completed authored aggregate or a successful Windows fixture.

## Checks actually run

- Twelve synthetic Python tests passed: inclusive0/4, displaced matched backends,
  stale witness, wrong pose/HFOV/time, missing evidence, ambiguous/wrong features,
  exact static CLI, process receipt, platform/output guards, source-projection
  target independence and independently recomputed source-rim residuals.
- One bounded component test compiled the exact production constructor body with
  the cached pinned glam library and passed. This is not a fresh full Cargo lane;
  the additive Rust test must run in normal production Cargo checks after apply.
- `git apply --check` accepted the additive Rust patch against local a5a4e729.
- Actual local rendering was blocked before game startup because Xorg could not
  establish local/Unix listening sockets. No insecure transport fallback,
  installation or expensive game rebuild was attempted. No GL or Windows pixel
  result is claimed.

## Fresh compact inspection output

A renderer-only feedback caller reuses the existing native renderer workflow.
It does not run the source-bound recovery/distribution or complete main workflow,
and its independent non-canceling queue does not interrupt their active checks.
Each execution performs new captures; it does not read or repackage any historical
artifact. The complete calibration packet is always retained. A second artifact
contains only captures, logs, source/input summary and frozen settings, after
checking a 24 MiB uncompressed transfer budget. Missing or excessive compact
output is reported; it does not erase the full packet or waive a failed check.

The first full-packet transfer returned HTTP403. Its cause is unestablished; no
alternate route or retry was used. The compact output is a new resource from a
fresh native run, whose actual transfer outcome must be checked independently.
