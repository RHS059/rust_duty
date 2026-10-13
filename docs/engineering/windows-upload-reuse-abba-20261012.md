# Geometry-buffer reuse: matched Windows CPU experiment

Source: `eef575860862dba1b6273b450cd8dd619dae2d10` · 2026-10-12 · draft PR49

## Result

The warm reuse path eliminated the measured per-frame destination-buffer and transform-binding allocations and reduced the observed geometry-upload CPU medians from 3.362/3.396 ms to 1.931/1.991 ms in this four-run experiment. Whole-frame medians overlap; there is no consistent end-to-end frame-time improvement in these runs. The RTX 3080 Ti / 60 FPS goal remains unverified.

This is one stationary Windows DX12/WARP sequence at a verified physical 1920×1080 client extent, with Immediate presentation, release application assertions off, WGPU descriptor flags 32, Record enabled and GPU timestamps disabled. It is not an RTX or general gameplay benchmark.

## Exact experiment and evidence

- [Published source](https://github.com/RHS059/rust_duty/commit/eef575860862dba1b6273b450cd8dd619dae2d10)
- [Native job](https://github.com/RHS059/rust_duty/actions/runs/38200091947/job/114651743269)
- [Compact original reports](https://github.com/RHS059/rust_duty/actions/runs/38200091947/artifacts/11725963816), SHA-256 `bd88cf3ae20c9e2105fe2fe35ec818582e239dacba487d0886b08a532e722c3a`
- [Full raw traces, binaries and symbols](https://github.com/RHS059/rust_duty/actions/runs/38200091947/artifacts/11726128374), published archive SHA-256 `76e7b681bdb589ea9e682953aec2f6c67108badaaadaba55004ef159844fd489`

Two fresh Rust1.99.0 MSVC release/PDB builds share the same bound production inputs except the compile-time `REUSE_ENABLED` policy line. A is immutable-per-frame allocation; B is bounded reuse. Runs are A, B, B, A. Both preserve the same instrumentation. The actual origin is the published candidate commit; the baseline is an explicitly described source overlay, not a fabricated Git commit.

The native job reports all four captures passed with normal F10 exit code 0, no forced termination, and successful final source/assets/settings/retained-binary checks. The original failed single-capture shutdown attempts remain failed; this mode’s success does not retroactively repair them.

## Record-window measurements

All times below are per-run nearest-rank medians in milliseconds, except frame p95. Parent spans contain their children. Percentiles are neither added nor subtracted; runs are not pooled.

| Run | Policy | Complete intervals | Frame p50 | Frame p95 | Acquire texture | Encode/submit | Frame plan | Geometry upload | Queue submit |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | baseline | 478 | 92.948 | 119.013 | 45.510 | 33.486 | 19.657 | 3.362 | 8.032 |
| 2 | candidate | 461 | 92.687 | 116.955 | 46.821 | 31.921 | 19.775 | 1.931 | 7.932 |
| 3 | candidate | 442 | 94.922 | 124.142 | 47.511 | 33.542 | 20.931 | 1.991 | 8.229 |
| 4 | baseline | 442 | 94.082 | 119.464 | 45.946 | 34.435 | 20.606 | 3.396 | 8.018 |

Across all complete warm candidate rows, the v2 counters report zero destination-buffer allocations, zero newly allocated destination bytes, zero transform-binding allocations and three buffer reuses per frame. Immutable controls report three destination allocations and one transform binding per frame, approximately 14.85 MB of requested destination-buffer bytes. These counters do not measure staging or driver allocations.

Strict independent replay verified 904 Git source hashes (885 ordinary inputs and 19 generated-transport source inputs), 281 shared asset-receipt entries, the exact 122-input one-line source pair, four normal F10 exits and all 1,823 complete primary/CPU/v2 attempts. Raw asset, EXE/PDB and ETL bytes are represented by full-artifact receipts in the compact packet; they were not independently rehashed locally.

The outer renderer_submit medians are 36.299, 34.718, 36.488 and 37.345 ms in ABBA order; these contain the nested encode_submit values shown above.

Geometry-upload p95 in ABBA order is 4.294, 2.618, 2.386 and 4.611 ms. Whole-frame p99 is 143.816, 140.879, 156.173 and 149.115 ms; the overall tails remain mixed.

Workload identity is bounded rather than identical: run 2 has PID 972, while the others have four-digit PIDs. The Record HUD displays the session path. Run-2 rows 1–62 and 461 have two fewer characters/draws; rows 63–460 have one fewer. This PID explanation is supported by the source and counter differences, not independently observed pixels of the sampled scene. All retained gameplay positions are [0, 0, 9], with speed and ADS zero.

Record interval totals are 44.696, 42.942, 42.346 and 41.912 seconds. These cover longer windows than WPR, including its stop/flush period; WPR Profile-hit counts must not be divided by Record frame counts. A stale replay_basis description mentions W/S, contradicting the actual stationary action and empty input-transition list. That original metadata is preserved as a limitation, not silently rewritten.

## Renderer-thread sampling

These are Profile-event samples for the bound renderer thread across the full ETL. Inclusive shares overlap and are not frame-duration percentages. The retained inclusive/caller tables truncate low-count rows; absence is not proof of zero sampled calls.

| Run | Profile hits | ETL seconds | create_buffer_init inclusive | FrameArena::try_append inclusive | GpuVertex::append_bytes exclusive | Unknown exclusive |
|---|---:|---:|---:|---:|---:|---:|
| r01-baseline | 15680 | 35.238 | 7.36% | 40.98% | 18.48% | 0.34% |
| r02-candidate | 15119 | 35.449 | Absent from retained table | 42.36% | 19.13% | 0.44% |
| r03-candidate | 15292 | 34.737 | Absent from retained table | 43.01% | 18.59% | 0.40% |
| r04-baseline | 15652 | 34.579 | 7.12% | 42.20% | 18.08% | 0.33% |

Every trace reports zero lost events and buffers. Every exclusive table sums to its exact renderer Profile total; all five exported report hashes and process/thread joins were checked. The full ETL windows are approximately 34.58–35.45 seconds around the roughly 30-second replay. The compact packet retains reports and hashes, not the raw ETL/EXE/PDB bytes, so this local audit does not independently rehash those large raw inputs.

`FrameArena::try_append` and `GpuVertex::append_bytes` are the strongest remaining measured CPU lead. A separate byte-preserving packing experiment is being reviewed locally; it has no matched native-game result yet.

## Correctness and limits

- Exact-current native GPU/session, queued-upload and synthetic image evidence passed independent source-bound replay.
- The image control preserves all 21 fixed RGBA pairs and four mixed line/text images. The retained 94-file/six-directory archive passes the unchanged structural validators.
- Queued reuse tests cover nine frames submitted before readback, immutable parity, uncached fallback, abandoned writes and production capture checkpoints.
- The sampled authored scene was positively loaded and its error logs checked. These samples are not an authored visual-acceptance or animation-quality verdict.
- GPU timestamps were off. This packet cannot support a GPU-duration comparison; the existing explicit command-buffer timing would also exclude queued staging copies.
- High acquire time on WARP is not uniquely attributable to vsync. No hardware FPS or overall performance pass is claimed.
- Broad PR quality jobs were still running when this report was assembled.

## Top 20 exclusive renderer samples

Function labels and displayed percentages below are preserved from the retained xperf reports. Tables are per-run; do not add inclusive and exclusive counts.

### r01-baseline

| Function | Exclusive hits | Exclusive share | Inclusive hits |
|---|---:|---:|---:|
| `vector-range.exe!vector_range::render::arena::GpuVertex::append_bytes` | 2898 | 18.48% | 3223 |
| `vector-range.exe!vector_range::draw::Mesh::validate` | 1393 | 8.88% | 1405 |
| `ntdll.dll!memcpy` | 1276 | 8.14% | 1784 |
| `vector-range.exe!vector_range::scene_lighting::SceneLighting::shade_rigid` | 1153 | 7.35% | 1166 |
| `ucrtbase.dll!memcpy_repmovs` | 804 | 5.13% | 809 |
| `vector-range.exe!vector_range::authored_viewmodel::AuthoredViewmodel::draw_pose_opacity` | 748 | 4.77% | 3078 |
| `vcruntime140.dll!Mov0YmmBlocks` | 549 | 3.50% | 554 |
| `vcruntime140.dll!memset_repstos` | 492 | 3.14% | 493 |
| `D3D10Warp.dll!JITRenderContext::CompileShaderInternal` | 490 | 3.13% | 590 |
| `vcruntime140.dll!memcpy_repmovs` | 482 | 3.07% | 587 |
| `vector-range.exe!vector_range::render::arena::FrameArena::try_append` | 460 | 2.93% | 6425 |
| `vector-range.exe!alloc::vec::Vec<u8,alloc::alloc::Global>::extend_trusted<u8,alloc::alloc::Global,core::array::iter::IntoIter<u8,2> >` | 431 | 2.75% | 677 |
| `D3D10Warp.dll!StateBlock::SafeGetEditable<ShaderStateBlock>` | 331 | 2.11% | 1264 |
| `ntdll.dll!ExpInterlockedPopEntrySListResume` | 272 | 1.73% | 273 |
| `ntkrnlmp.exe!MiCompletePrivateZeroFault` | 241 | 1.54% | 402 |
| `ntkrnlmp.exe!KiPageFault` | 203 | 1.29% | 930 |
| `ntdll.dll!RtlpLowFragHeapAllocFromContext` | 169 | 1.08% | 210 |
| `ntkrnlmp.exe!MiDeleteClusterPage` | 139 | 0.89% | 157 |
| `ntkrnlmp.exe!MiDeleteVa` | 130 | 0.83% | 136 |
| `vcruntime140.dll!memcpy` | 130 | 0.83% | 130 |

### r02-candidate

| Function | Exclusive hits | Exclusive share | Inclusive hits |
|---|---:|---:|---:|
| `vector-range.exe!vector_range::render::arena::GpuVertex::append_bytes` | 2892 | 19.13% | 3258 |
| `vector-range.exe!vector_range::draw::Mesh::validate` | 1322 | 8.74% | 1338 |
| `ntdll.dll!memcpy` | 1209 | 8.00% | 1725 |
| `vector-range.exe!vector_range::scene_lighting::SceneLighting::shade_rigid` | 1164 | 7.70% | 1183 |
| `vector-range.exe!vector_range::authored_viewmodel::AuthoredViewmodel::draw_pose_opacity` | 764 | 5.05% | 3121 |
| `ucrtbase.dll!memcpy_repmovs` | 744 | 4.92% | 748 |
| `vcruntime140.dll!Mov0YmmBlocks` | 555 | 3.67% | 559 |
| `D3D10Warp.dll!JITRenderContext::CompileShaderInternal` | 513 | 3.39% | 578 |
| `vcruntime140.dll!memcpy_repmovs` | 472 | 3.12% | 637 |
| `vector-range.exe!vector_range::render::arena::FrameArena::try_append` | 450 | 2.98% | 6405 |
| `vector-range.exe!alloc::vec::Vec<u8,alloc::alloc::Global>::extend_trusted<u8,alloc::alloc::Global,core::array::iter::IntoIter<u8,2> >` | 429 | 2.84% | 686 |
| `ntdll.dll!ExpInterlockedPopEntrySListResume` | 289 | 1.91% | 290 |
| `D3D10Warp.dll!StateBlock::SafeGetEditable<ShaderStateBlock>` | 282 | 1.87% | 1160 |
| `ntkrnlmp.exe!KiPageFault` | 258 | 1.71% | 1040 |
| `ntkrnlmp.exe!MiCompletePrivateZeroFault` | 255 | 1.69% | 425 |
| `ntdll.dll!RtlpLowFragHeapAllocFromContext` | 160 | 1.06% | 204 |
| `ntkrnlmp.exe!MiDeleteClusterPage` | 158 | 1.05% | 189 |
| `vcruntime140.dll!memcpy` | 139 | 0.92% | 139 |
| `ntkrnlmp.exe!MiDeleteVa` | 101 | 0.67% | 113 |
| `ntkrnlmp.exe!MiConvertEntireLargePageToSmall` | 97 | 0.64% | 97 |

### r03-candidate

| Function | Exclusive hits | Exclusive share | Inclusive hits |
|---|---:|---:|---:|
| `vector-range.exe!vector_range::render::arena::GpuVertex::append_bytes` | 2843 | 18.59% | 3267 |
| `vector-range.exe!vector_range::draw::Mesh::validate` | 1361 | 8.90% | 1379 |
| `ntdll.dll!memcpy` | 1267 | 8.29% | 1873 |
| `vector-range.exe!vector_range::scene_lighting::SceneLighting::shade_rigid` | 1104 | 7.22% | 1127 |
| `ucrtbase.dll!memcpy_repmovs` | 792 | 5.18% | 798 |
| `vector-range.exe!vector_range::authored_viewmodel::AuthoredViewmodel::draw_pose_opacity` | 728 | 4.76% | 3077 |
| `vcruntime140.dll!Mov0YmmBlocks` | 553 | 3.62% | 554 |
| `D3D10Warp.dll!JITRenderContext::CompileShaderInternal` | 514 | 3.36% | 601 |
| `vcruntime140.dll!memcpy_repmovs` | 510 | 3.34% | 663 |
| `vector-range.exe!vector_range::render::arena::FrameArena::try_append` | 486 | 3.18% | 6577 |
| `vector-range.exe!alloc::vec::Vec<u8,alloc::alloc::Global>::extend_trusted<u8,alloc::alloc::Global,core::array::iter::IntoIter<u8,2> >` | 399 | 2.61% | 653 |
| `D3D10Warp.dll!StateBlock::SafeGetEditable<ShaderStateBlock>` | 325 | 2.13% | 1242 |
| `ntdll.dll!ExpInterlockedPopEntrySListResume` | 284 | 1.86% | 286 |
| `ntkrnlmp.exe!MiCompletePrivateZeroFault` | 257 | 1.68% | 416 |
| `ntkrnlmp.exe!KiPageFault` | 254 | 1.66% | 1168 |
| `ntdll.dll!RtlpLowFragHeapAllocFromContext` | 166 | 1.09% | 217 |
| `ntkrnlmp.exe!MiDeleteClusterPage` | 132 | 0.86% | 174 |
| `vcruntime140.dll!memcpy` | 132 | 0.86% | 133 |
| `ntkrnlmp.exe!KeZeroPages` | 117 | 0.77% | 117 |
| `ntkrnlmp.exe!MiDeleteVa` | 105 | 0.69% | 112 |

### r04-baseline

| Function | Exclusive hits | Exclusive share | Inclusive hits |
|---|---:|---:|---:|
| `vector-range.exe!vector_range::render::arena::GpuVertex::append_bytes` | 2830 | 18.08% | 3241 |
| `vector-range.exe!vector_range::draw::Mesh::validate` | 1296 | 8.28% | 1310 |
| `ntdll.dll!memcpy` | 1262 | 8.06% | 1864 |
| `vector-range.exe!vector_range::scene_lighting::SceneLighting::shade_rigid` | 1130 | 7.22% | 1145 |
| `ucrtbase.dll!memcpy_repmovs` | 781 | 4.99% | 793 |
| `vector-range.exe!vector_range::authored_viewmodel::AuthoredViewmodel::draw_pose_opacity` | 773 | 4.94% | 3019 |
| `vcruntime140.dll!Mov0YmmBlocks` | 538 | 3.44% | 540 |
| `D3D10Warp.dll!JITRenderContext::CompileShaderInternal` | 507 | 3.24% | 587 |
| `vcruntime140.dll!memcpy_repmovs` | 477 | 3.05% | 575 |
| `vector-range.exe!alloc::vec::Vec<u8,alloc::alloc::Global>::extend_trusted<u8,alloc::alloc::Global,core::array::iter::IntoIter<u8,2> >` | 469 | 3.00% | 732 |
| `vcruntime140.dll!memset_repstos` | 465 | 2.97% | 465 |
| `vector-range.exe!vector_range::render::arena::FrameArena::try_append` | 458 | 2.93% | 6605 |
| `D3D10Warp.dll!StateBlock::SafeGetEditable<ShaderStateBlock>` | 276 | 1.76% | 1199 |
| `ntdll.dll!ExpInterlockedPopEntrySListResume` | 258 | 1.65% | 260 |
| `ntkrnlmp.exe!KiPageFault` | 217 | 1.39% | 1122 |
| `ntkrnlmp.exe!MiCompletePrivateZeroFault` | 214 | 1.37% | 396 |
| `ntdll.dll!RtlpLowFragHeapAllocFromContext` | 182 | 1.16% | 224 |
| `ntkrnlmp.exe!MiDeleteClusterPage` | 163 | 1.04% | 206 |
| `ntkrnlmp.exe!KeZeroPages` | 135 | 0.86% | 135 |
| `vcruntime140.dll!memcpy` | 132 | 0.84% | 133 |
