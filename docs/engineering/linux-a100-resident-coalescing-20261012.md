# Linux A100 resident part coalescing: compact-stage evidence

Measured source: `332e389a08330ce2be701f251ec355f94b12e5fb`, tree `c38e6b703403c4a329adb04ade95673cb1dfc9c0`. This same-binary ABBA comparison switches legacy resident chunks versus coalesced authored parts, with direct viewmodel rendering enabled in both. NVIDIA A100-SXM4-40GB, Linux release/Vulkan, Immediate presentation, physical 1920×1080; stationary after Enter, no movement or mouse replay.

## Result and current evidence boundary

The producer and strict controller report all 22 legacy-resident/coalesced-resident native image pairs and ordered source-part/material/pose/corner checks passing. Resident draws fall from 86 (75 rigid, 11 skinned) to 34 (31 rigid, 3 skinned). The compact packet contains every native report, two representative PNG pairs and four game screenshots. Remaining native PNGs, binary layout/corner streams, raw performance timeseries and both executable bytes are omitted from this compact packet, with their hashes and explicit omission list retained. Full transfer and independent raw replay remain pending at this publication stage.

This is a separate legacy-resident/coalesced-resident gate. The earlier CPU/resident strict image failure remains **FAILED: 18 RGB pixels across 11 of 22 pairs, maximum difference 3**, with unchanged alpha/masks. These new reports do not waive that failure or the earlier gameplay/ADS visibility gates.

The [independent compact review](evidence/a100-coalesced-332e389a-20261012/independent-compact-review.json), SHA256 `29122c69bc8d097feb6c6700f3a12cf6cafc1c1833ddac469d4bb7ffb558a4db`, verifies build/pins/native process, all present hashes and the explicit omissions. Both retained representative native pairs independently pass exact RGBA/foreground replay. All four game screenshots were visually reviewed: hands, weapon, world and HUD remain visible; these unsynchronized screenshots are not an all-pose pixel-equality test. The other 20 native pairs and binary streams remain receipt-bound until full-byte replay.

## Controller-reported matched timing

The following values are extracted from the retained controller result; they are not yet an independent replay of the omitted raw timeseries. Each leg recorded 30 seconds after warmup and exited normally.

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

Windows RTX/DX12 performance and gameplay-wide acceptance remain open. Full raw evidence and its independent audit will be added separately, preserving this compact-stage record.
