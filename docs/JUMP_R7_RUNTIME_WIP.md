# Common Jump r7 runtime WIP — candidate 0.1.9

Base: `d4d9b622d42ce0aa45896f06ac338a6ae7a0be14`. The separate 0.1.8
release remains unchanged. This lane adds the common jump to stable semantic
bindings, the existing authored viewmodel, packaging, and same-run CI exports.
It does not modify simulation physics, controls, persisted settings, or source
Actions. Delta updater work from unrelated branches is not claimed here.

The immutable source is `assets/authoring/jump/halcyon_jump.blend` at Hal's
`e9317f90ea171976306e2f17c111325d948ea357`, SHA256
`a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`.
CI reads that existing source directly; it is not duplicated or replaced. The
three r7 Actions export as `jump_takeoff`, `jump_air`, `jump_land`, respectively
11/60, 23/60, 28/60 seconds. All are non-looping. The original 44 canonical
walking records and exact VRS/VRM companions remain byte-identical.

An accepted simulation launch starts takeoff. The air transition runs at native
time then clamps its endpoint until actual ground contact. Contact starts the
landing clock, with a bounded 60 ms blend from the prior visible composed pose;
it never waits for or forces the reference flight deadline. Reload and mantle
suppress and consume jump presentation. Source HIP motion uses the existing
weapon-space layering primitive, retaining ADS articulation and optical-axis
constraints. Walking XYZ gains and v9 directional retargeting do not scale the
jump source. Transition blends are presentation, not source curve edits.

Hal reported fixed-view qualitative pass at `b303f99`; Elara's paired review is
still pending. This is authorized useful WIP, with no numeric reference-match
score, new Eevee render, or artistic approval claim.

## Current evidence

- Blender 4.3.2 (`32f5fdce0a0a`), official archive SHA256
  `4da1c956673c0485e63054e563ee69198cc8f80d8157dd7592dffc8a6a5592e6`.
  Source auto-execution disabled; evaluation/export only, no rendering.
- Actual source → evaluated FBX → named take conversion → Rust CPU sampler:
  25 native/off-key samples per clip, all 75 passed the existing 1 mm geometry
  threshold with matching visibility. Full reports live in
  `verification/jump_r7_runtime/`. They describe the local exact export hash,
  not a later regenerated CI artifact.
- Five Rust endpoint/air-hold checks passed, including takeoff/air and air/land
  seams. These establish sampled position continuity, not continuous velocity
  or artistic similarity.
- Rust 1.99: 36 focused contracts passed; all-target Clippy and formatting checks passed. Controller, manifest, shared-layer contracts include native time,
  early/late contact, air hold, pause/reset, ADS/reload ownership, real accepted
  held-input launch, Space-to-stand and mantle suppression. `sim.rs` unchanged.
- Packaging revalidates source identity, r7 Action names, exact crop, dense
  sample counts, canonical clip bytes, companion hashes, parity, seam reports,
  gzip transports and safe manifest bindings. Tests reject stale evidence,
  altered source/crops, invalid timing and corrupted transports.
- Native capture route `gameplay-jump` exercises HIP and ADS jumps plus reload
  interruption. Its gate has synthetic positive/negative fixtures. Actual
  native capture, complete Windows/Linux packaging, and live publication remain
  CI/release work; a successful source export is not a rendered gameplay pass.

## Reproduce

Materialize the immutable BLEND from the pinned source commit into a source
folder, then run:

```sh
cargo build --locked --no-default-features --example sample_viewmodel_clip
python tools/build_jump_assets.py --source-dir /path/to/jump-source \
  --blender /path/to/blender-4.3.2 \
  --sampler target/debug/examples/sample_viewmodel_clip \
  --work build-jump/work --output build-jump/runtime
python tools/check_generated_assets.py --kind jump --directory build-jump/runtime
```

Both work/output paths must be fresh. The build workflow consumes the same-run
verified output, materializes and stages all three companions, then records
`native-gameplay-jump-evidence`. Existing ADS/reload/directional capture gates
remain active. A failed Jump export or native gate blocks the complete build.
