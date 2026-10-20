# Task B stage 3: measured conservative visibility

Completed 2026-10-20 UTC. The canonical street route shows a very small
structural reduction after conservative interior visibility, while CPU recording
and submission increased. Observed software GPU time decreased. These results
are **not a net performance pass**.

The [checked-in evidence](task-b-stage3-raw-comparison.json) contains source and
binary identities, full-report hashes, all metric distributions/deltas, adapter,
configuration and measured asset identities.

## Matched measured runs

- Baseline: clean release `0d2e71ba789d622912b87bf7eef3b4dce0ee99c1`, tree
  `cd903dfe34045dd154a10ca2e3a96e6bc758e1ac`, stage 2 per-instance rendering.
- Candidate: clean release `ba686b6cddb49e9915430b8a0e02263083d264da`, tree
  `4e5519125150ad48463d1f6b462d5e4516bfd558`, stage 3 including portal boundary
  validation. Built from `6f96ddf` plus `c27dcb7` and stage 2 evidence `a37fad5`.
- Both: 1280×720, 60 excluded warmup frames, 720 measured frames, fixed
  `cedar-junction-streets-v2` path, explicit per-frame completion fence, same
  `dot-cloud-swiftshader-2026-10-20` host and SwiftShader Vulkan CPU adapter.
- Both use identical `stage3-1f01f6c` fixture bytes. The strict comparator passed
  without any geometry-parity exception. No lighting.bin was present.

| Metric, mean per frame | Stage 2 | Stage 3 | Change |
| --- | ---: | ---: | ---: |
| Issued draws | 3,562.47 | 3,560.23 | -0.063% |
| Submitted triangles | 797,538.48 | 797,227.79 | -0.039% |
| Uploaded payload bytes | 1,086,585.73 | 1,086,011.51 | -0.053% |
| CPU recording wall span | 0.7500 ms | 0.8675 ms | +15.67% |
| CPU submit wall span | 7.8939 ms | 9.7809 ms | +23.90% |
| CPU recording + submit | 8.6440 ms | 10.6486 ms | +23.19% |
| Actual encoded-frame GPU timestamps | 121.8649 ms | 110.1998 ms | -9.57% |

Only 83 of 720 frames issued fewer draws, with a maximum reduction of 88 draws
and 11,928 triangles in one frame. No frame issued more draws. Draw p95 remained
6,387 and triangle p95 remained 1,349,944. Both runs include three first-use
geometry-upload frames after warmup. GPU p95 decreased from 203.4105 to 188.5203 ms;
all 720 GPU timestamp samples were available in both runs.

The deterministic work reduction is small on this exterior street path. The
CPU increase remains visible rather than being hidden behind the lower software
GPU timing. Shared-host CPU contention affects both host-wall spans and
SwiftShader; one run per source cannot establish an isolated GPU speedup.
These results do not establish physical GPU performance, display cadence,
gameplay FPS, or the visibility benefit for all interior viewpoints. Portal
correctness tests and visual review remain separate evidence.

## Input and artifact identities

Unchanged final fixture:

- level.json: 2,057,352 bytes, SHA256
  `adf33ccdcf9b3d08281a02498231726844576eb0cf8031ba92e1b65ff561c618`
- meshes.bin: 38,459,157 bytes, SHA256
  `5ac00d08df6d87283fbf486cf3d87e829f3585897fccf094a27e223f77e99653`

Candidate raw report SHA256:
`3fbcda46464e45a736bdc7b6d16a513aaa2547f5b626efc45cb8299201994cd4`.
The complete report schema and ordered 720-sample sequence validated. All eleven
comparator tests passed on the measured checkout. No renderer or visibility
changes were made after measurement; this commit only records evidence.

## Reproduce and compare

Build at the candidate source above; verify a clean tree before setting the
dirty receipt to false. Use the Rust and named machine/adapter environment in
the [stage 0 baseline](TASK_B_STAGE0_BASELINE.md). CITY_V4 must name the unchanged
fixture directory with the hashes above.

```sh
export RUST_DUTY_BENCH_REVISION="$(git rev-parse HEAD)"
export RUST_DUTY_BENCH_DIRTY=false
cargo run --locked --release --no-default-features --features wgpu-runtime \
  --example cedar_benchmark -- --mode headless-gpu --renderer vulkan \
  --level-file "$CITY_V4/level.json" --output stage3-raw.json \
  --width 1280 --height 720 --warmup 60 --frames 720
python3 scripts/compare_cedar_benchmark.py stage2-raw.json stage3-raw.json
```
