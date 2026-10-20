# Task B stage 0: measured Cedar Junction baseline

Run completed 2026-10-20 UTC. The [machine-readable summary](task-b-stage0-swiftshader-v2-summary.json)
contains exact source, asset identities, adapter, configuration and all aggregates.
The measured source is `7a493e7707e17f5b2687beb33b087f206e3b24b1`, tree
`acc6434bfcdeaadd93af05c6c50c1c4f33fe9b7a`, with a clean release build.
A publication commit with the same tree contains identical measured source.

## Actual result

720 measured frames completed after 60 excluded warmup frames, 1280×720, fixed
`cedar-junction-streets-v2` route. All 720 GPU query samples were available.
The actual adapter was **SwiftShader Device (Subzero), Vulkan, device type Cpu**,
using SwiftShader driver. This is software-renderer evidence, not hardware GPU
performance, gameplay FPS, display cadence or visual/artistic approval.

| Measured field | Mean | Nearest-rank p95 |
| --- | ---: | ---: |
| CPU recording wall span | 16.82 ms | 26.91 ms |
| CPU renderer-submit wall span | 190.34 ms | 282.55 ms |
| CPU recording + submit wall span | 207.16 ms | 310.00 ms |
| Separate host GPU fence/readback wait | 208.38 ms | 374.12 ms |
| Actual encoded-frame GPU timestamps | 187.71 ms | 354.56 ms |
| Issued draw calls per frame | 338.69 | 510 |
| Submitted triangles per frame | 1,969,971.13 | 3,048,272 |
| Uploaded payload bytes per frame | 115,807,733.63 | 179,867,368 |

Mean upload components: 103,901,394.11 vertex bytes, 11,819,826.81 index bytes,
86,512.71 transform bytes and zero texture bytes per frame. Transform alignment
bytes count; allocation padding and renderer initialization do not.

Other release builds ran on the shared host during parts of the measurement.
CPU spans and software GPU execution are therefore contention-sensitive.
Use draw/triangle/upload counts as the clean structural baseline; repeat timings
on an otherwise idle named machine before claiming an isolated timing speedup.
The explicit per-frame fence bounds in-flight uploads and changes throughput.
CPU submit/fence time is never substituted for GPU timestamp time.

The selected asset was the existing baked `lighting.bin` (54,926,812 bytes,
FNV-1a-64 `16f0809ac7865679`) with level.json (1,868,550 bytes,
`4b59159644d6f8f8`). A raw source v1/v4 geometry comparison is a different input
pair and must use its own baseline and explicit independently verified parity.

## Reproduce

At the measured source, on this cloud software-Vulkan setup:

```sh
export CARGO_HOME=/workspace/shared/cargo
export RUSTUP_HOME=/workspace/shared/rustup
export PATH=/workspace/shared/cargo/bin:$PATH
export RUST_DUTY_BENCH_REVISION="$(git rev-parse HEAD)"
export RUST_DUTY_BENCH_DIRTY=false  # only after verifying a clean tree
export RUST_DUTY_BENCH_MACHINE=dot-cloud-swiftshader-2026-10-20
export VK_ICD_FILENAMES=/usr/lib/chromium/vk_swiftshader_icd.json
export LD_LIBRARY_PATH=/usr/lib/chromium
cargo run --locked --release --no-default-features --features wgpu-runtime \
  --example cedar_benchmark -- --mode headless-gpu --renderer vulkan \
  --output stage0-swiftshader-v2-1280x720-720frames.json \
  --width 1280 --height 720 --warmup 60 --frames 720
```

Use the platform's actual adapter configuration on another machine; these ICD
paths are specific to the measured cloud host. The production level resolver
selected assets/levels/cedar_junction/level.json beside this source checkout.
Toolchain: rustc 1.99.1 (58cf8f9c3 2026-10-13), Linux 6.18.55 x86_64.

The 477,875-byte raw per-frame report is retained with the benchmark artifacts.
This compact checked-in summary binds it by SHA256:
`1fbdc45ef7d30895abf9942989413d947f2409b10b7155dc99292451c708ad47`.
The full report passed JSON Schema Draft 2020-12 and production-comparator
validation; self-comparison produced zero deltas for all observed metrics.

## Evidence and limitations

- Four benchmark tests passed on the v2 path, including every interpolated frame
  against all sixteen frozen authored building footprints, exact path repetition,
  real public CityLevel/facade recording and rejected invalid options.
- Two renderer-counter/timestamp unit tests passed. The explicit real-adapter
  counter fixture passed on SwiftShader: repeated single-triangle submissions
  each issued one draw with 120 vertex, 6 index and 64 uniform bytes. This ran on
  stage 0's original `a4842ca`; its renderer source is unchanged in `7a493e7`.
- Scoped WGPU library/example clippy with `-D warnings` passed before the path
  revision. The v2 example compiled in release and its CPU tests passed afterward.
- The comparison suite has ten passing unit tests. Its additional stage 2
  verifier-dependent CLI test is skipped where that verifier is not yet present.
  A temporary composition with the actual stage 2 verifier also passed its valid
  reordered-vertex fixture and rejected an intentionally changed candidate file.
- The superseded v1 route entered outer building footprints. Its specific run was
  interrupted (exit 130), with no complete report, and contributes no results here.

Full measurement boundaries and comparison commands:
[Cedar benchmark guide](../../performance/CEDAR_BENCHMARK.md).
