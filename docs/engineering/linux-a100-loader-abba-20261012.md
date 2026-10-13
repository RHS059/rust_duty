# Authored loader comparison on Linux A100 / Vulkan

Captured 2026-10-12, 08:27–08:30 UTC. Independent replay completed; A100 runtime shutdown verified at 08:33:55 UTC.

## Result

The exact two-file loader deduplication reduced observed frame intervals in both candidate runs of this single ABBA block. Baseline medians were 30.7965 and 30.7122 ms; candidate medians were 18.2504 and 18.1158 ms. This hardware result supports retaining the loader change and pursuing the remaining CPU work. It does not meet the 60 FPS minimum in this authored test, and it does not establish the Windows DX12 / RTX 3080 Ti target. The current game's optimization target remains 140–200+ FPS at physical 1920×1080.

No resident-mesh/shader offload or new staging-pool implementation is present in these captures. Existing destination-buffer reuse and vertex serialization are enabled on both sides.

## Exact comparison

- Candidate origin: `c111eba1bbd67b9988aeada4fbf9b2b528d43b65`, tree `02d3969b2f79e22571736a3651ee239b4b5e0d75`.
- Baseline: the same materialized source, with only `src/authored_viewmodel.rs` and `src/weapon_model.rs` restored byte-for-byte from `adc270635ee2faa24fe66ee0dfaa85b0b617ba5c`. This is an explicit counterfactual, not a claim that the complete baseline is that old commit.
- Both retained 131-file source inventories match their Git sources. The complete 122-input production inventories differ only in those two files.
- Fresh Linux release builds use the same Rust 1.99.0 compiler, `--locked --no-default-features --features wgpu-runtime --release --bin vector-range`. Candidate was built first; the same-host baseline was built afterward. Build labels differ and are retained.
- NVIDIA A100-SXM4-40GB, Vulkan, NVIDIA driver 580.82.07, explicit adapter fingerprint, Immediate presentation, physical client 1920×1080, Ubuntu 24.04.4 / Xvfb.
- Both variants load the same 77-file public authored companion set from the verified v0.1.9 Linux release plus the current animations manifest. This is not claimed identical to later Windows-generated assets. No private soldier assets were used.
- GPU timestamps enabled on both sides. Observed WGPU descriptor bits are 32: application debug assertions off, DEBUG/VALIDATION/GBV off, indirect-call validation on.
- Order: baseline, candidate, candidate, baseline. Each run starts with a fresh process, waits for positive authored loading, enters gameplay, records approximately 31.2 seconds around 30 one-second hardware observations, and exits normally via F10. Stationary input, no movement or mouse replay.

## Per-run measurements

All values below are milliseconds. Percentiles use nearest-rank selection. Rows are independent run distributions, not averages of percentiles.

| Run | Variant | Eligible intervals | Frame p50 | Frame p95 | Frame p99 | Recording p50 | Renderer-submit p50 | Frame-plan p50 | Upload p50 | GPU-command p50 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | baseline | 1011 | 30.796537 | 31.881567 | 32.904019 | 12.091397 | 13.217320 | 7.969440 | 1.647427 | 1.541120 |
| 2 | candidate | 1704 | 18.250353 | 19.242796 | 19.780260 | 5.253363 | 7.819826 | 4.676339 | 0.767246 | 1.470464 |
| 3 | candidate | 1718 | 18.115805 | 18.961228 | 19.442355 | 5.210245 | 7.736076 | 4.587334 | 0.776523 | 1.471488 |
| 4 | baseline | 1016 | 30.712183 | 31.760163 | 32.179200 | 12.099179 | 13.117840 | 7.881706 | 1.638976 | 1.541120 |

The complete [per-run metrics](evidence/a100-loader-abba-20261012/metrics.tsv) also retain acquisition, presentation, command encoding, encoder finish, queue submission and nested encode-submit medians.

## Independent checks

- All four processes exited 0. All 5,449 eligible primary/CPU-substage/v2-detail/GPU attempts have complete, exact-primary-hash joins and measured GPU rows; no missing rows are zero-filled.
- Source, shared assets and both executable identities were rechecked before/after the runs. Every earlier run's retained file inventory and bytes were checked again after later runs and at finalization.
- The three HUD cohorts have 384 / 471 / 485 characters. Their other counters agree between variants. All process IDs have five digits, avoiding the earlier PID-length workload difference; cohort frequencies and numeric text still vary with frame rate.
- Within each matching HUD cohort, the candidate uploads exactly 7,858,680 fewer vertex bytes. Every recorded row on both sides retains three destination-buffer reuses and zero new destination/binding allocations.
- Gameplay simulation advances in all four runs. Screenshots show the textured authored model. Simulation starting times differ; this is not an exact time-aligned image comparison.
- Archive CRC, archive SHA-256, all 384 retained file hashes and the unchanged original extraction were independently checked.

The matching-source Windows loader proof remains separate: 22 exact index-expanded corner streams, 22 exact authored overview image pairs, and unchanged 21 fixed / four mixed controls passed at the earlier loader source. Its diagnostic overview does not waive the historical ADS gameplay-framing failure. The repeated Windows WARP sampling run still has four forced-exit failures and is not accepted as a performance result.

## Limits

This is one descriptive ABBA block with two runs per variant, stationary gameplay, a particular public asset pack and a hosted Linux CPU/GPU environment. It does not establish statistical significance, sustained performance, representative mouse-look/combat performance or RTX/DX12 equivalence. Frame and simulation counts are not deterministic replay.

CPU parent spans include their children; do not add them or subtract parent/child percentiles. GPU command timestamps cover the ordered command buffer and exclude CPU work, surface acquisition/presentation, earlier staging copies and trailing readback. The approximately 1.47–1.54 ms GPU spans do not independently prove an idle percentage.

The packet retains executable and asset identities as receipts, not the raw ELF/asset bytes or complete build environment. The exact original public release is linked in the index. The source snapshots, actual drivers, build receipts/logs, primary/sidecar telemetry, screenshots and hardware observations are retained for replay. The initial failed build/dependency probe and paused smoke remain separate earlier evidence, not silently promoted into this successful authored comparison.

## Download and reproduce the audit

- [Raw evidence ZIP](evidence/a100-loader-abba-20261012/raw-evidence.zip): 4,607,502 bytes, 385 entries including its manifest. SHA-256 `f1f6928cc6e5f53368690daca35b5af048b3dfb7ea1245e6a776d5bc9f80d5c8`.
- [Artifact index](evidence/a100-loader-abba-20261012/artifacts.json): all retained relative paths, byte lengths and SHA-256 values; exact source/asset/compiler identities.
- [Independent audit result](evidence/a100-loader-abba-20261012/audit.json): strict summaries, runtime evidence, per-run cohorts and explicit limitations. SHA-256 `e9dcc07ad758d3c39cee431d0dbf7357a1016aadb51169b2db7945c72f0bf285`.
- [Per-run metrics TSV](evidence/a100-loader-abba-20261012/metrics.tsv), SHA-256 `f39e17596db39ad7127076cf036b6daae9de20500e134bdf79a9d8478a0c19e0`.

After checking the ZIP digest and safe extraction, replay each `authored-r0N-work/telemetry-sessions/*/frames.json` using the strict frame, CPU-substage, encode-detail and GPU readers at candidate source `c111eba1`. The ZIP includes the exact executed `run-authored-pair.py`, each per-run driver, preparation script, source snapshots and their manifests. Readers must bind the original primary bytes and preserve original verdicts. Rebuilding requires the separately linked public asset archive and a compatible Vulkan-capable Linux environment; no Windows adapter substitution is implied.
