# Linux A100 resident-path ABBA: recovered original evidence

## Verdict

The original experiment at source `1ef12e3f5840e1411c131e2859b133737f4ec565`
(tree `18d01cae913011f577f2d34802806693c95cc75d`) shows substantially lower CPU
present-return intervals with resident geometry/skinning enabled. **It is a
failed-correctness diagnostic, not an accepted optimization or target-FPS pass.**
The exact-image gate remains failed: 18 differing pixels across 11 of 22 pairs,
maximum RGB channel delta 3, unchanged alpha; all 22 expanded-corner pairs match.
No tolerance has been substituted for exact comparison.

The newer normalization/probe source `5f253fb0f60ec328d56cdd7fb19dbdca09c67b57`
is preserved by this documentation-only publication. These measurements do not
measure or validate that newer candidate. No new A100 run was performed for
this recovery, and no PR was merged.

## Setup and measured results

- NVIDIA A100-SXM4-40GB, NVIDIA driver 580.82.07, Linux Vulkan, explicitly selected adapter, Immediate presentation.
- Physical window 1920 × 1080, authored HK416A5 viewmodel, stationary default range.
- Actual compiler: rustc 1.99.0 (`b940084d7`, 2026-09-28); cargo 1.99.0.
- Sequential baseline/candidate/candidate/baseline experiment. The source variants differ only in `src/frame_resident_policy.rs`; staging is held fixed.

| Run | Variant | Eligible intervals | Interval p50 ms | p95 ms | p99 ms | Producer intervals/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Baseline | 1,508 | 20.679151 | 21.533033 | 22.400868 | 48.14 |
| 2 | Resident candidate | 3,840 | 8.094806 | 8.703337 | 9.140135 | 122.69 |
| 3 | Resident candidate | 3,878 | 8.029369 | 8.521505 | 8.903669 | 123.89 |
| 4 | Baseline | 1,506 | 20.686359 | 21.572718 | 22.633681 | 48.14 |

Candidate inverse-median rates are approximately 124–125 per second. Those are
not producer-throughput averages or observed display FPS. The producer interval
rate is the interval count divided by the sum of eligible intervals. Neither
metric proves scan-out cadence. The 140–200+ FPS optimization target and Windows
RTX 3080 Ti / WGPU-DX12 validation remain open, as does accepted correctness.

Median game-recording CPU time falls from 6.082791/6.024015 ms to
0.441974/0.430553 ms; median renderer-submit CPU time from 8.720348/8.798187 ms
to 2.136377/2.097285 ms. Median main-command GPU spans are 1.489920 ms for both
baseline runs and 1.507328 ms for both candidate runs. The detailed phase
metrics are retained below; overlapping parent/child percentiles must not be
added or subtracted, and CPU and GPU work may overlap.

## Independent recovery checks

The independent audit rehashed all 450 source files per variant, including 128
critical compile inputs. It verified preparation, executable hash receipts,
matched runtime identity, final input/output inventories, four clean process
exits, and complete eligible primary/CPU-substage/encode-detail/GPU joins for all
10,732 intervals. All original retained files remain unchanged.

The failed-correctness packet retains the original source sets, 44 A100 PNGs,
report, and raw-stream hash inventories. Its 44 large corner streams are omitted
from the compact archive. Independent replay used explicitly cross-artifact
Windows `5f253fb` raw bytes whose complete hashes and every 4 MiB chunk hash match
the original A100 inventories; this provenance is recorded in the audit. These
substitutes are not described as newly downloaded A100 raw streams.

## Published originals and audit

All evidence below is under [the evidence directory](evidence/a100-resident-20261012/).

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| [Original telemetry ZIP](evidence/a100-resident-20261012/a100-resident-diagnostic-abba.zip) | 4,949,071 | `581b0b054ea4d17cdf2ebe6dd978df6b1ca87c40e1dfedc1e0dcc82eb4c7d806` |
| [Original failed-correctness compact ZIP](evidence/a100-resident-20261012/a100-resident-failed-correctness-compact.zip) | 5,392,213 | `93a172e7d93ffcc77e8f4f714115325703adc4cc6d262d4d0470109816c7391d` |
| [Independent audit](evidence/a100-resident-20261012/independent-audit.json) | See index | `e44a631c1593060316f358efb2e2fa21eab27954847ae40117fedbd6d4b2ed1e` |

- [Per-run phase metrics TSV](evidence/a100-resident-20261012/metrics.tsv)
- [Archive entries and file hashes](evidence/a100-resident-20261012/artifact-index.json)

The telemetry archive has 118 files; the failed-correctness compact archive has
963. Publication reviewed both archive inventories, credential-pattern scanning,
and retained screenshots. No credentials, private soldier asset payloads, or
unrelated personal material were found. Public asset receipts refer to the
existing v0.1.9 release. The archives are published without alteration.

## Limits and next acceptance work

1. One sequential ABBA experiment, two runs per variant, stationary scene. No statistical-significance claim, broad gameplay result, or RTX/DX12 inference. HUD-count cohorts match, but animation samples are not frame-for-frame synchronized.
2. CPU present-return intervals are not display cadence. GPU timing covers the main ordered command buffer and excludes earlier staging copies, surface acquisition, presentation, and trailing resolve/readback.
3. The session-local Git identity is explicitly unavailable; source binding comes from the verified preparation/source pair and matching executable hash receipts. Compiled ELFs and public asset binaries are receipt-bound, not included in these compact packets.
4. The separate `gpu.jsonl` OS-utilization provider is unavailable on Linux. Actual frame timestamps come from `frames.gpu-timing.json`; retained `nvidia-smi` samples provide adapter utilization only.
5. Capture protocol success does not supersede the failed exact-image gate. The historical ADS gameplay visibility gate is also not waived. Diagnose and fix the pixel discrepancy under the unchanged gate, then measure source-matched intended hardware and gameplay workloads before claiming target completion.
