# Finite WARP corroboration

This fixture supplements the preserved ADS diagnostic packet. It never reads original captured pixels, modifies an original report, changes required/possible masks or thresholds, or asserts that the entire GPU arithmetic profile is proven. Its report keeps `acceptance_verdict: null` and explicitly identifies later corroboration.

The fixed scope is the 50 already-selected visible fallback frame IDs in `FINITE_FRAMES`. The 160 empty fallback cases and omitted source triangles need their separate reviewed source-separation evidence. These are not a full scenario rerender.

## Build and input binding

Build fresh on Windows with pinned Rust 1.99.0 and the original locked dependency graph:

```text
cargo build --locked --release --no-default-features --features legacy-macroquad,wgpu-runtime --example finite_warp_probe
```

Native mode rejects a debug build, a build without both original renderer features, and any actual adapter other than DX12 CPU Microsoft Basic Render Driver. The caller must preserve a build receipt binding the actual compiler `rustc -Vv`, build command, source files, and resulting executable SHA-256. The report does not infer its build compiler from a separately installed runtime compiler.

Generate the input geometry trace natively from the original SHA-bound source and companions using `source_visibility_geometry_probe`. Do not present an existing Linux trace or old executable as Windows execution. The caller must bind the reviewed trace producer, complete source inventory and omitted-triangle separation evidence, and verify native replay against the original source records.

```text
target/release/examples/finite_warp_probe.exe --native --trace TRACE_JSONL --original-jsonl ORIGINAL_FRAMES_DX12_JSONL --source-receipt ORIGINAL_SOURCE_RECEIPT_JSON --source-root SOURCE_ROOT --output-dir NEW_OUTPUT_DIRECTORY
```

`SOURCE_ROOT` contains `assets/locomotion/asset.vrm` and `assets/reload/asset.vrm`. Their exact before/after SHA-256 identities are checked against the pinned original receipt. Source indices and position bits must match those original meshes; UV and normal bits come directly from them. Matrices and CPU-lit colors are supplied by the source-bound geometry replay. Each isolated triangle is repacked through production `FrameArena` as three source vertices with indices `[0, 1, 2]`. This diagnostic remapping is recorded explicitly; it is not a claim to have observed original native draw buffers.

Before rendering each state, the fixture recomputes outward interval-edge support from the source trace. Its required/possible masks must exactly reproduce that state's pinned original source masks. Unsafe-color possible support must be excluded from required support. Both original receipt and DX12 JSONL have fixed expected SHA-256 constants. Production shader, upload, device, target, draw layout, Cargo metadata, and the original portion of mesh.rs must match original receipt bytes. All inputs are checked again after execution.

`--plan-only` replaces `--native` to validate source inputs and report cost without creating a GPU. A plan can never emit a native pass.

## Three finite checks

1. Every traced triangle uses the production vertex module, 40-byte input layout, production uploaded matrix, full 960×540 viewport, no culling and single-sample RGBA8 UNORM target. A diagnostic fragment shader discards exactly its independently allowed sample support, plus the explicitly excluded 64×22 frame-witness region. The allowed mask uses integer textureLoad with an exact absolute pixel-coordinate mapping. Depth and blending are disabled for this support guard. DX12 binary occlusion must remain zero for every draw. This establishes per-triangle support containment; global union containment alone would not justify filtering individual color probes.
2. A coverage-only fragment shader renders the complete triangle union. Every required sample must be covered and every covered non-witness sample must lie within the original possible mask. The diagnostic fragment stages do not modify vertex positions. They have no early-depth annotation. Coverage-only PS always survives; the original color PS has no discard, depth write, sample mask or alpha-to-coverage behavior that would change geometric support.
3. Every triangle whose independently allowed support intersects required support is isolated with coverage-only, unblended original `fs_straight`, and production `BlendMode::Alpha` passes over opaque black and opaque white destination colors. Only a predeclared sample rectangle is copied, preserving the full viewport and production VS/input layout. At every required sample covered by that triangle, each resulting UNORM target must have stored alpha 255 and each RGB channel must lie in that source triangle's vertex-color convex envelope ±3 bytes. Stored alpha 255 alone is not treated as proof of exact preblend float alpha 1. The production blend endpoint results bound every representable destination channel through the fixed blend equation. All candidate textures are immutable white. Every possible winner is checked; no untested support is silently retained. Any failure stops the run, without shrinking required support or widening the possible mask.

The support guard is the reason cropped color readbacks are sufficient: no candidate triangle may escape its own independently computed support into a sample that was skipped. Diagnostic depth/blend removal observes all candidates independent of original depth ordering; it does not claim to reproduce the original native pipeline state. The exact union of checked required sample IDs must equal the original required mask, so overlapping checks cannot hide a missing sample. At retained samples every possible winner preserves the source contrast even under production alpha blending across both destination endpoints, so depth selection cannot select an unchecked contributor.

## Evidence and negative controls

`report.json` uses `rust-duty-finite-warp-corroboration/v1`. It records source/trace/executable/implementation digests, actual adapter type/vendor/device/driver, hashes of already-loaded D3D12, WARP, DXGI and FXC runtime DLLs, shader translation path, target/sample configuration and all 50 states. Compiled DXBC bytes are not exposed by the production wgpu API, so `compiled_shader_hash` remains null with that exact reason. Source WGSL and the pinned translation/compiler path are recorded instead.

Each frame directory contains production-packed per-draw vertex/index/matrix/color digests, a coverage PNG, compact raw readbacks with coverage, unblended-source, alpha-over-black, and alpha-over-white planes, and an observation JSONL identifying every expected color draw and its buffer offsets/digests. Query guards are checked synchronously; a missing/extra isolated draw receipt fails independently of overlap in the union.

Native controls run for every state: omit all native draws; shrink possible support; enlarge required support; inject nonopaque alpha and an error beyond three byte levels into an actual fragment readback; omit a triangle receipt; and remove one actually covered sample from a triangle's guard mask. The last control must produce nonzero native binary occlusion. The altered controls never redefine the accepted source masks. CPU tests also reject wrong matrix/vertex/index upload bytes and wrong attribute stride/offset/format, and validate exact mask-coordinate mapping and both diagnostic WGSL modules.

No native pass has been claimed merely because the fixture compiles or its CPU plan passes. A successful native report remains later, finite corroboration and must be joined with the original checks, complete source/input binding, separate omitted/empty geometry proofs, build receipt, and runtime-identity comparison before a coordinator changes an acceptance decision.
