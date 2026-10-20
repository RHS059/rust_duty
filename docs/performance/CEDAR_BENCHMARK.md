# Cedar Junction renderer benchmark (Task B stage 0)

This benchmark uses the production CityLevel loader, culling, draw facade and
WgpuRenderer. Its camera is a pure function of integer frame index. It never
creates or advances Simulation, consumes input, or uses elapsed time to move.
It measures the static city workload, without soldiers, weapons, HUD or gameplay.

## Reproducible runs

Use a named machine, the same release profile, adapter/driver, asset bytes,
resolution, warmup and frame count for baseline and candidate. Close unrelated
heavy workloads. Record repeated runs before interpreting small timing changes.

```sh
export RUST_DUTY_BENCH_REVISION="$(git rev-parse HEAD)"
export RUST_DUTY_BENCH_DIRTY="$(test -z "$(git status --porcelain)" && echo false || echo true)"
export RUST_DUTY_BENCH_MACHINE="my-machine-and-power-mode"
cargo run --locked --release --no-default-features --features wgpu-runtime \
  --example cedar_benchmark -- --output before.json --renderer vulkan \
  --width 1280 --height 720 --warmup 60 --frames 720
```

On Windows set the equivalent environment variables in PowerShell and choose
`--renderer dx12`; `--renderer metal` selects Metal on macOS. An explicit backend
retains existing adapter-selection behavior. `--force-fallback-adapter` requests
software rendering. Actual adapter classification and driver information are
recorded; software results must not be presented as hardware performance.

`--output` must name a new file; existing evidence is never overwritten. Failure
writes a failed report with its error, never a successful/zero result. Missing
assets, failed render validation and query/readback failures fail the run.
`--level-file path/to/level.json` (alias `--level`) selects a specific fixture.
The loader prefers adjacent lighting.bin when present. The report fingerprints
the *actual selected* mesh file and level document, with size and FNV-1a-64
content identity (not an authenticity/security digest). Do not accidentally
compare baked subdivided lighting geometry with the smaller unlit source.

The canonical v2 path stays on the authored 0/±32 m street corridors; v1 crossed
outer building footprints and must not be compared with v2. It lasts 720 frames,
with nine fixed waypoints (eight street and
raised-overview segments), 70-degree vertical field of view and the production
400 m far plane. Warmup frames are excluded from samples. Measured frame zero
always restarts path zero regardless of warmup count. Counts below 720 are
partial-path diagnostics, not a complete fly-through. Each GPU submission is
explicitly drained, so a slow/software adapter cannot accumulate city-sized
in-flight uploads. This serial diagnostic is not asynchronous gameplay FPS.

Without a GPU, execute the real production scene-recording path:

```sh
cargo run --locked --release --no-default-features --example cedar_benchmark -- \
  --mode cpu-scene --output cpu-before.json --warmup 60 --frames 720
```

CPU mode measures CityLevel::draw/culling/facade recording and exact recorded
mesh/triangle counts. It does not prepare GPU arenas, issue draws or upload
anything. Those fields, renderer-submit time and GPU duration are null.

## Measurement boundary

- `cpu_record_ns`: host monotonic duration to create the camera/draw list, run
  production culling, validate and record the visible city meshes.
- `cpu_submit_ns`: host monotonic WgpuRenderer::submit duration, including
  validation, packing/upload calls, encoding, queue submit and normal polls.
  It ends before the explicit benchmark completion fence.
- `cpu_frame_ns`: contiguous recording plus submission host span, excluding
  report/counter bookkeeping and the explicit completion/readback wait.
- `cpu_gpu_wait_ns`: separate host fence/map wait. This is **not GPU duration**.
- `gpu_timestamp_ns`: actual start/end query ticks bracketing encoded frame
  commands, scaled by Queue::get_timestamp_period. Includes clear and rendering;
  excludes CPU planning/upload calls, timestamp resolve/readback and surface
  presentation. Both required timestamp features are requested only by
  new_headless_profiled. Unsupported, missing or non-monotonic samples are null.
- `draw_calls`, `triangles`, `line_segments`: counts at actual draw_indexed
  callsites. Submitted triangles are not unique or visible triangle counts.
- `*_upload_bytes`: actual uploaded vertex, index, transform and cache-miss RGBA
  payload bytes; transform alignment bytes count. GPU allocation padding,
  renderer initialization (white pixel), readback and target clears do not.
  `upload_bytes` is the sum. Static cache hits must add zero geometry bytes;
  future cache-miss uploads must update these same counters at their callsite.

Counters are opt-in and reset per submission. Normal gameplay does not allocate
query resources, request timestamp features, or add GPU fences. Existing
frame_performance/session present-return CPU measurements are unchanged.
Do not subtract CPU spans to invent GPU time or convert these serial headless
results into displayed/gameplay FPS.

## Compare and validate

```sh
python3 scripts/compare_cedar_benchmark.py before.json after.json > comparison.json
python3 -m unittest discover -s scripts/tests -p test_compare_cedar_benchmark.py
cargo test --locked --no-default-features --example cedar_benchmark
cargo test --locked --no-default-features --features wgpu-runtime --lib render::metrics
```

The comparator rejects failed reports, malformed/missing samples, different
mode, host, adapter, path, resolution/configuration or asset identities. It
requires RUST_DUTY_BENCH_MACHINE, and preserves unavailable values as null.
It reports means, nearest-rank p50/p95, range and mean deltas. Partial/mismatched
GPU coverage is shown, but receives no performance delta. No budget or automatic
performance-pass threshold is invented.

The opt-in actual adapter test validates repeated real submissions and exact
triangle/index/vertex/uniform counters (one triangle: 120/6/64 bytes):

```sh
cargo test --locked --no-default-features --features wgpu-runtime --lib \
  render::metrics::tests::headless_metrics_count_real_issued_work_and_payloads \
  -- --ignored --nocapture
```

That test is ignored by the default CPU suite, not counted as a GPU pass. Run it
explicitly with an available native or software adapter. Optional GPU timestamp
availability is reported, not required to make the adapter test pass.

Schema: [cedar-benchmark.schema.json](cedar-benchmark.schema.json).
