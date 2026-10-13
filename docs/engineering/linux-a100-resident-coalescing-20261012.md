# Linux A100 resident part coalescing: audited timing and native pixels

Measured source: `332e389a08330ce2be701f251ec355f94b12e5fb`, tree `c38e6b703403c4a329adb04ade95673cb1dfc9c0`. This same-binary ABBA comparison switches legacy resident chunks versus coalesced authored parts, with direct viewmodel rendering enabled in both. NVIDIA A100-SXM4-40GB, Linux release/Vulkan, Immediate presentation, physical 1920×1080; stationary after Enter, no movement or mouse replay.

## Initial compact-stage result and evidence boundary

This section records the first publication stage. Its retention limitations are closed by the final full-archive audit below; the original compact receipt remains unchanged.

The producer and strict controller report all 22 legacy-resident/coalesced-resident native image pairs and ordered source-part/material/pose/corner checks passing. Resident draws fall from 86 (75 rigid, 11 skinned) to 34 (31 rigid, 3 skinned). The compact packet contains every native report, two representative PNG pairs and four game screenshots. Remaining native PNGs, binary layout/corner streams, raw performance timeseries and both executable bytes are omitted from this compact packet, with their hashes and explicit omission list retained. Full transfer and independent raw replay remain pending at this publication stage.

This is a separate legacy-resident/coalesced-resident gate. The earlier CPU/resident strict image failure remains **FAILED: 18 RGB pixels across 11 of 22 pairs, maximum difference 3**, with unchanged alpha/masks. These new reports do not waive that failure or the earlier gameplay/ADS visibility gates.

The [independent compact review](evidence/a100-coalesced-332e389a-20261012/independent-compact-review.json), SHA256 `29122c69bc8d097feb6c6700f3a12cf6cafc1c1833ddac469d4bb7ffb558a4db`, verifies build/pins/native process, all present hashes and the explicit omissions. Both retained representative native pairs independently pass exact RGBA/foreground replay. All four game screenshots were visually reviewed: hands, weapon, world and HUD remain visible; these unsynchronized screenshots are not an all-pose pixel-equality test. The other 20 native pairs and binary streams remain receipt-bound until full-byte replay.

## Independently replayed matched timing

The following original controller values have now been independently reproduced from recovered raw CPU/GPU timeseries. All 21,682 eligible GPU samples were measured; runtime/build/scene/gameplay joins pass. Each leg recorded 30 seconds after warmup and exited normally.

| Leg | Mode | Intervals | Frame median ms | Frame p95 ms | Frame p99 ms | GPU command median ms | CPU encode median ms |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | Legacy | 5,385 | 5.710171 | 6.134409 | 6.698713 | 1.175552 | 1.328101 |
| 2 | Coalesced | 5,489 | 5.597254 | 6.003187 | 6.570273 | 1.175552 | 1.221000 |
| 3 | Coalesced | 5,432 | 5.651460 | 6.073559 | 6.675276 | 1.175552 | 1.248757 |
| 4 | Legacy | 5,376 | 5.707708 | 6.210655 | 6.785746 | 1.175552 | 1.320740 |

Mean run medians: 5.708940 → 5.624357 ms, a 0.084583 ms reduction (about 1.48%). GPU medians are unchanged in all four legs. Two repetitions per mode do not establish statistical significance or a general gameplay speedup. Producer throughput is 173.67 / 177.13 / 175.27 / 173.49 intervals per second; reciprocal median intervals are derived rates, not display FPS.

Controller counters retain three render passes in both modes. Resident uniform bytes per frame fall from 54,768 to 41,456; resident warm-cache misses and resident vertex/index uploads are zero. CPU/GPU work overlaps; parent and child percentiles must not be summed or subtracted. GPU command timestamps exclude staged copies, presentation and scan-out. Do not combine this delta with earlier different-source or different-time controls as a causal total.

## Durable compact evidence

- [Original compact ZIP](evidence/a100-coalesced-332e389a-20261012/a100-coalesced-332e389a-results-native.zip): 4,255,017 bytes; SHA256 `6bdc2197084aa5b0ed441e7f522637e98247f504f18a5ce60dae7610140aed48`; all 70 entry CRCs pass.
- [All compact entry hashes](evidence/a100-coalesced-332e389a-20261012/artifact-index.json).
- [Controller metrics TSV](evidence/a100-coalesced-332e389a-20261012/controller-metrics.tsv).

Windows RTX/DX12 performance and gameplay-wide acceptance remain open. The initial compact review is frozen; the supplemental stage below closes its pixel/timing omissions without implying full source/ELF/stream retention.


## Supplemental raw timing and all-native-pixel recovery

All 44 original native PNGs are now locally recovered with original hashes verified. The [independent pixel addendum](evidence/a100-coalesced-332e389a-20261012/independent-all-native-pixels-review.json), SHA256 `8c65740fe3f17a0c86fba5ee6dbe87e7842e5424b767572b6f8f1f8a856899f8`, independently passes exact full-RGBA/foreground comparisons for all 22 pairs. Their [lossless deduplicated archive](evidence/a100-coalesced-332e389a-20261012/a100-coalesced-332e389a-all-native-pngs.zip) is 314,691 bytes, SHA256 `399f88ab335f3a4b68965854222e63fead2388553613252820a947b6077de306`; its reconstruction manifest maps all original filenames to retained PNG bytes.

The [independent raw telemetry review](evidence/a100-coalesced-332e389a-20261012/independent-raw-telemetry-review.json), SHA256 `94b4b3337a55e471563d50c1ad14171dc2a965a19a4a4ec68205e9815497b7f8`, reproduces every reported timing leg from raw records, checks CPU/GPU eligibility and joins, and confirms the unchanged GPU medians. Mean CPU encode medians are 1.3244205 → 1.2348785 ms. The small descriptive frame difference has no significance claim.

[Raw telemetry XZ](evidence/a100-coalesced-332e389a-20261012/a100-coalesced-332e389a-raw-telemetry.zip.xz) is 5,653,528 bytes, SHA256 `c96bb800c310dae41bbccf04e389709127a7fa2c355e905f7cb09cfbb4fa3dd4`. Standard XZ decompression reproduces the exact 104,280,160-byte ZIP, SHA256 `6faa942ec896b17f234c40b7b48fa36c51e4b71e61c788c8f28bbfd470559b33`, containing 46 files with passing CRCs. The [manifest](evidence/a100-coalesced-332e389a-20261012/raw-telemetry-manifest.json) binds both representations.

At the supplemental stage, native layout/ordered streams, materialized source, both ELFs and the complete original outer archive were still pending. The final stage below closes these retention/replay gaps. The historical CPU/resident arithmetic failure remains failed.


## Final complete archive and independent audit

The complete original archive has now been reconstructed byte-for-byte: **839,406,313 bytes**, SHA256 `0453642bac3a105163fa77d0b25ff1e03c4df9e66a9054d4600aeb6981771973`, **706 entries**, all CRCs passing. Recovery reused original-hash-matching retained bytes and CPU reconstruction, without another GPU execution. The self-contained [full retention directory](evidence/a100-coalesced-332e389a-20261012/full/) contains ordered compressed parts, a SHA256 manifest, and a reconstruction/verification script; it does not depend on Colab or any other local workspace. The [complete artifact index](evidence/a100-coalesced-332e389a-20261012/full-artifact-index.json) records every original entry.

- [Final independent review](evidence/a100-coalesced-332e389a-20261012/independent-final-review.json): SHA256 `1dfb4c7e2c9b2b37d820c569d78899038f15f0262a210c84df23f5d3e50fffff`.
- [Detailed archive and raw performance audit](evidence/a100-coalesced-332e389a-20261012/independent-performance-audit.json): SHA256 `2ffaa5b2d942bf1dccf407b8b7aaa03e47c39299fb206b82ddb888f7ac8dea23`.
- [Original-hash native recovery audit](evidence/a100-coalesced-332e389a-20261012/independent-full-native-recovery-review.json): SHA256 `867d78deb4e4ac83cf758f044c8e3bfdb2c345cc2561dcd2a347dff605965f7c`.

The independent final audit verifies 464 Git-bound source files, 134 compile inputs, both original game/native ELF hashes, process/device/build joins and all four raw performance legs. Six layout streams and 14 ordered streams (672,227,200 bytes) match their original hashes. The unchanged strict reader independently passes all 22 source/part/material/state/pose/corner cases and all 44 full-RGBA PNGs. The successful-run inventory is complete at 186 original files, 805,362,039 bytes. Export-retention gaps are closed.

The 77 public runtime asset binaries and toolchain binaries outside the exported evidence remain receipt-bound. The 22-case fixture is bounded, game screenshots are unsynchronized, GPU medians remain unchanged, and the earlier CPU/resident 18-pixel failure remains failed. See the [implementation closeout](direct-viewmodel-coalescer-closeout-20261012.md) for source behavior and remaining acceptance limits.
