# Arena serialization: matched Windows CPU experiment

Source: `adc270635ee2faa24fe66ee0dfaa85b0b617ba5c` · 2026-10-12 · draft PR49

## Result

Both candidate runs have lower observed frame-plan, outer renderer-submit and whole-frame medians than both baseline runs in this single ABBA sequence. Frame-plan medians are 19.9843/20.9891 ms for the baseline and 16.2103/17.9108 ms for the candidate. Whole-frame medians are 93.9166/94.8290 ms versus 91.3145/90.5512 ms. This is descriptive evidence from two runs per variant on Windows DX12/WARP. It is not a significance test, an RTX result or proof of the 60 FPS goal.

The candidate packs each 40-byte GPU vertex on the stack and appends it with one bounded vector extension. The control is the prior scalar serialization path. Bounded GPU-buffer reuse is enabled in both. The exact 122-input baseline production tree equals the previously measured `eef5758` source; only `src/render/arena.rs` differs in the candidate. PR51 vertex deduplication is not included.

## Source and evidence

- [Published source](https://github.com/RHS059/rust_duty/commit/adc270635ee2faa24fe66ee0dfaa85b0b617ba5c)
- [Native paired job](https://github.com/RHS059/rust_duty/actions/runs/38204091125/job/114663842970)
- [Compact original reports](https://github.com/RHS059/rust_duty/actions/runs/38204091125/artifacts/11727612287), SHA-256 `62f27ba32953e99fe698669133e4f0e4bf608204467fd83baa0e98aed09cf477`
- [Full raw traces, binaries and symbols](https://github.com/RHS059/rust_duty/actions/runs/38204091125/artifacts/11727667174), published archive SHA-256 `da50349c13c1fcd82925dcaf01ef83766dffd8d9f2b5e1dd07189390de3825e7`
- [Earlier buffer-reuse experiment](windows-upload-reuse-abba-20261012.md), a separate source-bound result

Two fresh Rust1.99.0 MSVC release/PDB builds run sequentially in A/B/B/A order. The client extent is verified physical 1920×1080; the scene is stationary with the authored HK416A5 viewmodel, Immediate presentation and WARP forced fallback. Application assertions are off; actual WGPU descriptor flags are 32. Record is enabled identically, GPU timestamps are disabled.

Independent replay verified 906 source/transport Git hashes, the exact arena-only production pair, all four normal F10 exits with code 0 and no forced cleanup, and 1,829 complete primary/CPU/v2 attempts. All final source/assets/settings checks passed. The original 114-file compact extraction is unchanged. Actual EXE/PDB/ETL/asset bytes are represented by full-artifact receipts in this local compact audit; they were not independently rehashed locally.

## Per-run Record-window timings

Milliseconds, nearest-rank percentiles. Parent spans contain their children. Parent and child spans are not added or their percentiles subtracted. Direct baseline/candidate comparisons are descriptive; runs are not pooled.

| Run | Variant | Complete attempts | Frame p50 | Frame p95 | Frame p99 | Renderer-submit p50 | Encode-submit p50 | Frame-plan p50 | Frame-plan p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | baseline | 466 | 93.9166 | 118.9470 | 144.5501 | 36.8290 | 33.5118 | 19.9843 | 41.4431 |
| 2 | candidate | 454 | 91.3145 | 115.2854 | 141.2409 | 31.9243 | 28.9054 | 16.2103 | 33.6100 |
| 3 | candidate | 466 | 90.5512 | 117.3822 | 143.8399 | 33.6359 | 30.6326 | 17.9108 | 37.7623 |
| 4 | baseline | 443 | 94.8290 | 125.4584 | 158.1565 | 39.0993 | 35.5661 | 20.9891 | 43.4100 |

| Run | Game-recording p50 | Acquire-texture p50 | Geometry-upload p50 | Queue-submit p50 |
|---|---:|---:|---:|---:|
| 1 | 10.6152 | 45.0586 | 2.0161 | 8.9609 |
| 2 | 10.0678 | 48.6915 | 1.9653 | 8.1673 |
| 3 | 9.8678 | 46.3093 | 2.2964 | 7.9613 |
| 4 | 11.0046 | 43.6971 | 1.9886 | 9.7427 |

Unmodified game recording, queue submit and surface acquisition also vary. The entire observed whole-frame difference cannot be attributed to packing from this small, nondeterministic sample. High acquire time on WARP is not uniquely attributable to vsync.

## Matched work and observation limits

- All PIDs have four digits. Every run contains the same three complete counter vectors: text/prepared-draw counts 469/677 during the start notice, 383/598 in the steady cohort, and 483/693 for the stop row. The stop row has nine texture-cache misses. Payload sizes match by cohort.
- Start-notice counts in ABBA order are 60/63/64/61 rows; steady counts are 405/390/401/381; every run has one stop row. Cohort durations, frame counts and simulation times are not deterministic replay.
- Every complete row in both variants reports zero new destination-buffer and transform-binding allocations and three destination-buffer reuses. These counters do not cover staging or driver allocations.
- Record interval totals are 43.8741907/41.7803252/42.4870102/42.5107934 seconds. They enclose separately bounded roughly 30-second stationary WPR replay windows, including stop/flush margins. WPR Profile-hit counts must not be divided by Record frame counts.
- The corrected replay metadata now says wall-clock stationary baseline, with an empty input-transition list; no movement actions were changed.
- GPU timestamps were disabled. There is no GPU-duration comparison, authored visual-quality acceptance or RTX FPS claim.

## Renderer-thread Profile samples

These shares cover each full ETL, not exact Record or replay windows. Inclusive shares overlap and are not frame-duration fractions. Low-count inclusive/caller rows are truncated in the retained xperf tables; an absent row is not zero-hit proof.

| Run | Profile hits | ETL seconds | GpuVertex exclusive | GpuVertex inclusive | FrameArena inclusive | Unknown exclusive |
|---|---:|---:|---:|---:|---:|---:|
| r01-baseline | 15890 | 35.331 | 18.12% | 20.44% | 40.97% | 0.34% |
| r02-candidate | 14148 | 34.624 | 11.66% | 13.92% | 37.62% | 0.32% |
| r03-candidate | 14853 | 34.945 | 12.42% | 15.08% | 40.23% | 0.30% |
| r04-baseline | 16394 | 35.119 | 17.16% | 19.70% | 40.63% | 0.32% |

All four traces report zero lost events and buffers. Exclusive rows sum exactly to their renderer-thread totals. Five report hashes per run and PID/thread joins pass independent replay. `GpuVertex::append_bytes` exclusive shares decline from 18.12%/17.16% in the controls to 11.66%/12.42% in the candidates; those shares describe sampling, not per-frame time.

## Correctness checks

The exact-current image pair preserves all 21 fixed RGBA pairs and four mixed line/text images. Both 124-file materialized inventories differ only in arena.rs, with reuse enabled in both. The unchanged validators replay from 94 retained files and six explicit directories. Native GPU/session and queued-upload artifacts also passed source-bound independent replay. These are bounded synthetic correctness checks; full authored-game image acceptance is separate.

Broad PR quality lanes remained in progress when this report was assembled. This report preserves the successful bounded native experiment without declaring the entire PR green or merged.

## Top 20 exclusive renderer samples

Function labels, raw displayed shares and hit counts are preserved from the retained xperf reports.

### r01-baseline

| Function | Exclusive hits | Exclusive share | Inclusive hits |
|---|---:|---:|---:|
| `vector-range.exe!vector_range::render::arena::GpuVertex::append_bytes` | 2879 | 18.12% | 3248 |
| `vector-range.exe!vector_range::draw::Mesh::validate` | 1497 | 9.42% | 1512 |
| `ntdll.dll!memcpy` | 1387 | 8.73% | 1864 |
| `vector-range.exe!vector_range::scene_lighting::SceneLighting::shade_rigid` | 1172 | 7.38% | 1190 |
| `ucrtbase.dll!memcpy_repmovs` | 942 | 5.93% | 945 |
| `vector-range.exe!vector_range::authored_viewmodel::AuthoredViewmodel::draw_pose_opacity` | 740 | 4.66% | 3197 |
| `vcruntime140.dll!memcpy_repmovs` | 596 | 3.75% | 704 |
| `vcruntime140.dll!Mov0YmmBlocks` | 547 | 3.44% | 552 |
| `D3D10Warp.dll!JITRenderContext::CompileShaderInternal` | 507 | 3.19% | 602 |
| `vector-range.exe!vector_range::render::arena::FrameArena::try_append` | 480 | 3.02% | 6510 |
| `vector-range.exe!alloc::vec::Vec<u8,alloc::alloc::Global>::extend_trusted<u8,alloc::alloc::Global,core::array::iter::IntoIter<u8,2> >` | 387 | 2.44% | 645 |
| `ntdll.dll!ExpInterlockedPopEntrySListResume` | 340 | 2.14% | 340 |
| `D3D10Warp.dll!StateBlock::SafeGetEditable<ShaderStateBlock>` | 317 | 1.99% | 1416 |
| `ntkrnlmp.exe!KiPageFault` | 240 | 1.51% | 947 |
| `ntkrnlmp.exe!MiCompletePrivateZeroFault` | 229 | 1.44% | 392 |
| `ntdll.dll!RtlpLowFragHeapAllocFromContext` | 183 | 1.15% | 237 |
| `vcruntime140.dll!memcpy` | 137 | 0.86% | 138 |
| `ntkrnlmp.exe!MiDeleteClusterPage` | 134 | 0.84% | 147 |
| `ntkrnlmp.exe!MiDeleteVa` | 122 | 0.77% | 129 |
| `ntdll.dll!RtlEnterCriticalSection` | 85 | 0.53% | 88 |

### r02-candidate

| Function | Exclusive hits | Exclusive share | Inclusive hits |
|---|---:|---:|---:|
| `vector-range.exe!vector_range::render::arena::GpuVertex::append_bytes` | 1649 | 11.66% | 1969 |
| `vector-range.exe!vector_range::draw::Mesh::validate` | 1357 | 9.59% | 1368 |
| `ntdll.dll!memcpy` | 1336 | 9.44% | 1835 |
| `vector-range.exe!vector_range::scene_lighting::SceneLighting::shade_rigid` | 1200 | 8.48% | 1216 |
| `ucrtbase.dll!memcpy_repmovs` | 802 | 5.67% | 817 |
| `vector-range.exe!vector_range::authored_viewmodel::AuthoredViewmodel::draw_pose_opacity` | 756 | 5.34% | 3044 |
| `vector-range.exe!vector_range::render::arena::FrameArena::try_append` | 564 | 3.99% | 5322 |
| `vcruntime140.dll!Mov0YmmBlocks` | 551 | 3.89% | 555 |
| `D3D10Warp.dll!JITRenderContext::CompileShaderInternal` | 525 | 3.71% | 601 |
| `vcruntime140.dll!memcpy_repmovs` | 507 | 3.58% | 576 |
| `vector-range.exe!alloc::vec::Vec<u8,alloc::alloc::Global>::extend_trusted<u8,alloc::alloc::Global,core::array::iter::IntoIter<u8,2> >` | 394 | 2.78% | 645 |
| `D3D10Warp.dll!StateBlock::SafeGetEditable<ShaderStateBlock>` | 296 | 2.09% | 1243 |
| `ntdll.dll!ExpInterlockedPopEntrySListResume` | 287 | 2.03% | 287 |
| `ntkrnlmp.exe!MiCompletePrivateZeroFault` | 235 | 1.66% | 390 |
| `ntkrnlmp.exe!KiPageFault` | 208 | 1.47% | 892 |
| `ntdll.dll!RtlpLowFragHeapAllocFromContext` | 189 | 1.34% | 237 |
| `ntkrnlmp.exe!MiDeleteClusterPage` | 137 | 0.97% | 175 |
| `vcruntime140.dll!memcpy` | 126 | 0.89% | 126 |
| `ntkrnlmp.exe!MiDeleteVa` | 123 | 0.87% | 129 |
| `ntkrnlmp.exe!MiConvertEntireLargePageToSmall` | 87 | 0.61% | 87 |

### r03-candidate

| Function | Exclusive hits | Exclusive share | Inclusive hits |
|---|---:|---:|---:|
| `vector-range.exe!vector_range::render::arena::GpuVertex::append_bytes` | 1844 | 12.42% | 2240 |
| `ntdll.dll!memcpy` | 1567 | 10.55% | 2271 |
| `vector-range.exe!vector_range::draw::Mesh::validate` | 1354 | 9.12% | 1368 |
| `vector-range.exe!vector_range::scene_lighting::SceneLighting::shade_rigid` | 1209 | 8.14% | 1217 |
| `ucrtbase.dll!memcpy_repmovs` | 792 | 5.33% | 795 |
| `vector-range.exe!vector_range::authored_viewmodel::AuthoredViewmodel::draw_pose_opacity` | 750 | 5.05% | 3043 |
| `vcruntime140.dll!Mov0YmmBlocks` | 676 | 4.55% | 679 |
| `D3D10Warp.dll!JITRenderContext::CompileShaderInternal` | 527 | 3.55% | 606 |
| `vcruntime140.dll!memcpy_repmovs` | 499 | 3.36% | 573 |
| `vector-range.exe!vector_range::render::arena::FrameArena::try_append` | 487 | 3.28% | 5975 |
| `vector-range.exe!alloc::vec::Vec<u8,alloc::alloc::Global>::extend_trusted<u8,alloc::alloc::Global,core::array::iter::IntoIter<u8,2> >` | 405 | 2.73% | 683 |
| `D3D10Warp.dll!StateBlock::SafeGetEditable<ShaderStateBlock>` | 327 | 2.20% | 1246 |
| `ntdll.dll!ExpInterlockedPopEntrySListResume` | 271 | 1.82% | 272 |
| `ntkrnlmp.exe!MiCompletePrivateZeroFault` | 226 | 1.52% | 383 |
| `ntkrnlmp.exe!KiPageFault` | 225 | 1.51% | 1178 |
| `ntkrnlmp.exe!KeZeroPages` | 167 | 1.12% | 168 |
| `ntkrnlmp.exe!MiDeleteClusterPage` | 160 | 1.08% | 202 |
| `vcruntime140.dll!memcpy` | 148 | 1.00% | 148 |
| `ntdll.dll!RtlpLowFragHeapAllocFromContext` | 143 | 0.96% | 196 |
| `ntkrnlmp.exe!MiConvertEntireLargePageToSmall` | 107 | 0.72% | 107 |

### r04-baseline

| Function | Exclusive hits | Exclusive share | Inclusive hits |
|---|---:|---:|---:|
| `vector-range.exe!vector_range::render::arena::GpuVertex::append_bytes` | 2813 | 17.16% | 3230 |
| `vector-range.exe!vector_range::draw::Mesh::validate` | 1478 | 9.02% | 1491 |
| `ntdll.dll!memcpy` | 1356 | 8.27% | 1976 |
| `vector-range.exe!vector_range::scene_lighting::SceneLighting::shade_rigid` | 1215 | 7.41% | 1233 |
| `ucrtbase.dll!memcpy_repmovs` | 965 | 5.89% | 975 |
| `vector-range.exe!vector_range::authored_viewmodel::AuthoredViewmodel::draw_pose_opacity` | 726 | 4.43% | 3293 |
| `vcruntime140.dll!memcpy_repmovs` | 659 | 4.02% | 813 |
| `vcruntime140.dll!Mov0YmmBlocks` | 526 | 3.21% | 528 |
| `D3D10Warp.dll!JITRenderContext::CompileShaderInternal` | 517 | 3.15% | 601 |
| `vector-range.exe!vector_range::render::arena::FrameArena::try_append` | 477 | 2.91% | 6661 |
| `ntdll.dll!ExpInterlockedPopEntrySListResume` | 419 | 2.56% | 419 |
| `vector-range.exe!alloc::vec::Vec<u8,alloc::alloc::Global>::extend_trusted<u8,alloc::alloc::Global,core::array::iter::IntoIter<u8,2> >` | 394 | 2.40% | 666 |
| `D3D10Warp.dll!StateBlock::SafeGetEditable<ShaderStateBlock>` | 387 | 2.36% | 1572 |
| `ntkrnlmp.exe!KiPageFault` | 247 | 1.51% | 1198 |
| `ntkrnlmp.exe!MiCompletePrivateZeroFault` | 246 | 1.50% | 401 |
| `ntdll.dll!RtlpLowFragHeapAllocFromContext` | 210 | 1.28% | 272 |
| `ntkrnlmp.exe!MiDeleteClusterPage` | 171 | 1.04% | 201 |
| `vcruntime140.dll!memcpy` | 149 | 0.91% | 151 |
| `ntkrnlmp.exe!KeZeroPages` | 138 | 0.84% | 138 |
| `ntkrnlmp.exe!MiConvertEntireLargePageToSmall` | 103 | 0.63% | 103 |
