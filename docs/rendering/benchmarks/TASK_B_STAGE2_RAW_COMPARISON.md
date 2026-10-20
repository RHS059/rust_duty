# Task B stage 2: measured per-instance trade-off

Completed 2026-10-20 UTC. Stage 2 submits fewer triangles, but substantially more
draws and upload bytes than the original-geometry stage 1 baseline. CPU recording
and submission also increased. This result is **not a net performance pass**.

The [checked-in evidence](task-b-stage2-raw-comparison.json) contains both source
identities, full-report hashes, all metric distributions/deltas, actual adapter,
configuration, measured asset identities and independently recomputed parity.

## Matched measured runs

- Baseline: clean release `28b8d9f5cdf0570f21c62a166eb582eac60da70c`, tree
  `a14a9edd59a10b6a16f9a7aab86c01e4de6d3365`, original RDCITY01 source geometry.
- Candidate: clean release `0d2e71ba789d622912b87bf7eef3b4dce0ee99c1`, tree
  `cd903dfe34045dd154a10ca2e3a96e6bc758e1ac`, stage 2 per-instance rendering.
- Both: 1280×720, 60 excluded warmup frames, 720 measured frames, fixed
  `cedar-junction-streets-v2` camera path, explicit per-frame completion fence,
  same `dot-cloud-swiftshader-2026-10-20` host and SwiftShader Vulkan CPU adapter.
- Candidate uses the final `stage3-1f01f6c` fixture unchanged. Its extra visibility
  metadata is ignored by this stage 2 binary. Later stages can use identical
  input bytes for strict comparisons.

| Metric, mean per frame | Raw stage 1 | Stage 2 | Change |
| --- | ---: | ---: | ---: |
| Issued draws | 104.23 | 3,562.47 | +3,317.74% |
| Submitted triangles | 1,150,023.22 | 797,538.48 | -30.65% |
| Uploaded payload bytes | 163,711.18 | 1,086,585.73 | +563.72% |
| CPU recording wall span | 0.0247 ms | 0.7500 ms | +2,938.78% |
| CPU submit wall span | 0.5961 ms | 7.8939 ms | +1,224.21% |
| CPU recording + submit | 0.6209 ms | 8.6440 ms | +1,292.15% |
| Actual encoded-frame GPU timestamps | 119.5920 ms | 121.8649 ms | +1.90% |

GPU p95 increased from 173.6505 to 203.4105 ms. All 720 GPU timestamp samples
were available in both runs. Draw p95 increased from 152 to 6,387; upload p95
increased from 38,720 to 1,638,976 bytes. Means include legitimate first-use
geometry uploads after warmup; these are not replaced by assumed steady-state
zero values.

The finer submission granularity reduces coarse-frustum excess triangles while
adding many draw calls and transform uploads. The deterministic counter changes
are clear. Other CPU compilation/work occurred on the shared host, so these
software GPU and CPU-wall timings remain contention-sensitive. No physical GPU,
display cadence, gameplay FPS or isolated hardware speedup is claimed.

## Geometry and placement proof

This is a raw-v1/raw-v4 comparison, not baked-lighting versus source geometry.
Both input directories contain measured level.json and meshes.bin; neither
selected lighting.bin.

- Original mesh SHA256:
  `7f64d0c429e6e41577e555c514bcae08a33b1de62f9741ff848d45bec2717967`
- Candidate mesh SHA256:
  `5ac00d08df6d87283fbf486cf3d87e829f3585897fccf094a27e223f77e99653`
- Candidate level.json SHA256:
  `adf33ccdcf9b3d08281a02498231726844576eb0cf8031ba92e1b65ff561c618`

The independent verifier compared all 2,740,498 source triangles, preserving
ordered triangle positions, normals, RGBA, winding and multiplicity. The sorted
triangle-hash multiset SHA256 is
`f434d7bcaf38b6e70b47cb4193c5a590191be6e5ba8c2a0609b123fc75f35cf8`.
Original level/layout placement fields also matched.

The fixture's bundled v4→v4 proof was correctly rejected for this comparison
because its baseline mesh SHA did not bind the measured raw-v1 input. A new
proof was generated from the exact measured directories. The comparator then
matched both benchmark FNV/size identities and mesh SHA256s, reran the independent
verifier, and required exact equality with that fresh report. This checks source
geometry/placement; it is not a rendered-pixel or artistic approval.

## Reproduce and compare

Build at the candidate source above; verify a clean tree before setting the
dirty receipt to false. Use the named machine and adapter environment documented
in the [stage 0 baseline](TASK_B_STAGE0_BASELINE.md). Set CITY_V4 to the immutable
fixture directory with the candidate hashes above and RAW_V1 to the original
source-geometry directory including its original layout.json.

```sh
export RUST_DUTY_BENCH_REVISION="$(git rev-parse HEAD)"
export RUST_DUTY_BENCH_DIRTY=false
cargo run --locked --release --no-default-features --features wgpu-runtime \
  --example cedar_benchmark -- --mode headless-gpu --renderer vulkan \
  --level-file "$CITY_V4/level.json" --output stage2-raw.json \
  --width 1280 --height 720 --warmup 60 --frames 720
python3 tools/verify_city_geometry.py "$RAW_V1" "$CITY_V4" \
  --report measured-pair-parity.json
python3 scripts/compare_cedar_benchmark.py stage1-raw.json stage2-raw.json \
  --geometry-parity measured-pair-parity.json \
  --baseline-city "$RAW_V1" --candidate-city "$CITY_V4"
```

The raw candidate report SHA256 is
`015c3903d19ffdd97d60bf792ef97c9aa7d43ebfc94e34861f24a022d3fb7ad5`.
Its schema and complete sample sequence validated. All eleven comparator tests
passed in the stage 2 checkout, including the actual verifier-dependent CLI
positive fixture and stale-byte rejection. Only this documentation/evidence was
changed after measuring; no stage 2 renderer fixes are included in this result.
