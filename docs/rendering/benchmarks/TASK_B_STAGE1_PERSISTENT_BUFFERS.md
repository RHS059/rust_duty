# Task B stage 1: persistent static buffers, measured comparison

Run completed 2026-10-20 UTC. The [compact comparison summary](task-b-stage1-swiftshader-v2-comparison-summary.json)
binds the raw reports and full comparison with SHA256 and records all aggregates.
Baseline source: `7a493e7707e17f5b2687beb33b087f206e3b24b1`.
Candidate source: `28b8d9f5cdf0570f21c62a166eb582eac60da70c`, tree
`a14a9edd59a10b6a16f9a7aab86c01e4de6d3365`. Both were clean release builds.

## Matched workload and structural result

Both runs completed 720 measured frames after 60 excluded warmup frames at
1280×720 on `cedar-junction-streets-v2`. The production comparator accepted the
same configuration, camera samples, machine, adapter and selected asset bytes.
Every one of the 720 frames has **exactly equal issued draw and triangle counts**.
Means remain 338.6903 draws and 1,969,971.1347 triangles per frame.

Stage 1 uploaded new static geometry in three measured frames as previously
unseen chunks entered the route. The other **717 frames uploaded matrices only**.
Those first-use uploads are included in the averages, never excluded as outliers.

| Measured field | Baseline mean | Stage 1 mean | Mean change |
| --- | ---: | ---: | ---: |
| Vertex payload bytes/frame | 103,901,394.11 | 148,826.44 | −99.857% |
| Index payload bytes/frame | 11,819,826.81 | 32,200.50 | −99.728% |
| Transform payload bytes/frame | 86,512.71 | 86,512.71 | 0% |
| Total uploaded payload bytes/frame | 115,807,733.63 | 267,539.66 | −99.769% |
| CPU recording wall span | 16.817 ms | 0.047 ms | −99.719% |
| CPU renderer-submit wall span | 190.338 ms | 1.061 ms | −99.443% |
| CPU recording + submit wall span | 207.156 ms | 1.108 ms | −99.465% |
| Separate host GPU fence/readback wait | 208.384 ms | 196.645 ms | −5.633% |
| Actual encoded-frame GPU timestamp span | 187.712 ms | 196.354 ms | **+4.604%** |

No texture payload was uploaded in either measured run. Transform alignment
bytes count; allocation padding and initialization do not. Nearest-rank p95 CPU
recording + submit was 310.002 ms → 1.764 ms; GPU timestamp p95 was
354.562 ms → 331.331 ms. All 720 GPU timestamp samples were available in each run.

## Interpretation and limits

This is **SwiftShader Device (Subzero), Vulkan, device type Cpu**, on
`dot-cloud-swiftshader-2026-10-20`, Linux 6.18.55 x86_64, rustc 1.99.1.
Benchmark GPU workloads ran sequentially. Other release builds ran on the shared
host during parts of the measurements: CPU spans and software GPU execution are
contention-sensitive. Draw/triangle/upload counts establish the structural
change; repeat timings on an otherwise idle named machine before claiming an
isolated timing speedup.

The GPU mean increased 4.604%; these measurements do **not** establish a GPU
speedup. Nor do they establish hardware GPU performance, gameplay FPS, display
cadence, a performance-budget pass, or visual/artistic approval. CPU submit and
fence duration are never substituted for GPU timestamps. The explicit per-frame
completion fence changes throughput and bounds in-flight work.

Both reports selected the existing baked `lighting.bin` (54,926,812 bytes,
FNV-1a-64 `16f0809ac7865679`) and `level.json` (1,868,550 bytes,
`4b59159644d6f8f8`). A raw v1/v4 geometry comparison requires its own raw stage 1
baseline and explicit geometry/placement parity; it must not reuse this baked
pair as if the inputs were interchangeable.

## Reproduce and audit

Build each exact source with a verified clean tree:

```sh
RUST_DUTY_BENCH_REVISION="$(git rev-parse HEAD)" RUST_DUTY_BENCH_DIRTY=false \
  cargo build --locked --release --no-default-features --features wgpu-runtime \
  --example cedar_benchmark
```

Preserve each resulting executable before switching source. Run sequentially on
the same machine and with the same original shipped level/lighting files:

```sh
RUST_DUTY_BENCH_MACHINE=dot-cloud-swiftshader-2026-10-20 \
VK_ICD_FILENAMES=/usr/lib/chromium/vk_swiftshader_icd.json \
LD_LIBRARY_PATH=/usr/lib/chromium \
  ./cedar_benchmark --mode headless-gpu --renderer vulkan \
  --level /absolute/path/to/unchanged/cedar_junction/level.json \
  --output NEW_REPORT.json --width 1280 --height 720 --warmup 60 --frames 720
python scripts/compare_cedar_benchmark.py BASELINE.json CANDIDATE.json
```

The ICD and library paths above are specific to this software-Vulkan host; use
the actual platform adapter setup elsewhere. Raw reports and executables are
retained separately; this commit includes only compact summary/interpretation.
The comparator rejects different selected assets without a separately supported
and verified parity procedure. The bound raw report SHA256 values are:

- Baseline: `1fbdc45ef7d30895abf9942989413d947f2409b10b7155dc99292451c708ad47`
- Stage 1: `e74226ca70d1dcbcea9e83c8fb8bd20327c34add06cfa85adb83b661f8cc0db9`
- Full comparison: `58d023ee90956e7ccd94cdc46d4c1f61683724cb24004501cb2fec3e10bfa255`
