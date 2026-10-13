# Recovered release CPU sample, 12 October 2026

## Result and limits

The renderer-thread sample points first to fresh geometry-buffer allocation and
initialization. `create_buffer_init` appears on 4,572 of 5,803 sampled stacks
(78.79% inclusive), all called from `encode_frame`. `Device::create_buffer`
appears on 4,536 (78.17%); 4,482 of those include `memset`. FrameArena packing
appears on 454 (7.82%), queue submission 354 (6.10%), and encoder finish 37 (0.64%).
These overlapping inclusive counts must not be added or converted into frame time.
The next controlled experiment is capacity-bounded vertex/index/uniform-buffer
reuse with unchanged pixels and fresh matched baseline/candidate builds for sampling.

This is a release Rust 1.99 MSVC build with matching full PDBs, running the original
authored scene on hosted Windows 2022 DX12 WARP, Immediate, at observed physical
1920×1080. Runtime instance flags were 32 (indirect-call validation only), with
application debug assertions false and GPU timestamps disabled. It is not an
RTX 3080 Ti speedup or 60 FPS acceptance result. Authored-load success was logged;
visibility of every sampled frame was not independently proven.

The report filters CPU `Profile` stack events to PID 3404/TID 7244. It covers the
full 32.2728386-second ETL, including small margins around the 30.0169-second
stationary replay; no exact replay-time filter was applied. Trace statistics
report zero lost buffers/events. Samples are CPU observations, not wall-clock
frame durations. Other process threads, including WARP workers, are excluded
from this table; the whole-process profile is retained separately and should
not be interpreted as renderer-thread cost.

Rust/wgpu symbols resolve, but 2,398 exclusive leaf samples (41.32%) remain
unknown. All 2,400 unknown-inclusive hits have resolved immediate callers
`HvlSwitchToVsmVtl1` (1,966) or `HvcallpExtendedFastHypercall` (434).
The deepest hypervisor attribution is incomplete. This hosted-machine overhead
makes an RTX rerun necessary before claiming a hardware-performance gain.

## Top 20 renderer-thread entries by exclusive samples

Unknown and kernel entries are deliberately retained. Inclusive counts below
are context for each row and overlap across rows. Percentages use 5,803 as the
denominator. All exclusive rows in the full original report sum to 5,803.

| Rank | Function/module | Exclusive | Share | Inclusive |
| ---: | --- | ---: | ---: | ---: |
| 1 | `***unknown***!***unknown***` | 2398 | 41.32% | 2400 |
| 2 | `ntkrnlmp.exe!HalpInterruptSendIpi` | 1007 | 17.35% | 1010 |
| 3 | `ntkrnlmp.exe!KeFlushProcessWriteBuffers` | 747 | 12.87% | 1795 |
| 4 | `vector-range.exe!vector_range::render::arena::GpuVertex::append_bytes` | 202 | 3.48% | 227 |
| 5 | `ntkrnlmp.exe!KiPageFault` | 120 | 2.07% | 2727 |
| 6 | `vector-range.exe!vector_range::scene_lighting::SceneLighting::shade_rigid` | 98 | 1.69% | 98 |
| 7 | `vector-range.exe!vector_range::authored_viewmodel::AuthoredViewmodel::draw_pose_opacity` | 88 | 1.52% | 271 |
| 8 | `ucrtbase.dll!memcpy_repmovs` | 85 | 1.46% | 145 |
| 9 | `vector-range.exe!vector_range::draw::Mesh::validate` | 84 | 1.45% | 84 |
| 10 | `vector-range.exe!alloc::vec::Vec<u8,alloc::alloc::Global>::extend_trusted<u8,alloc::alloc::Global,core::array::iter::IntoIter<u8,2> >` | 57 | 0.98% | 78 |
| 11 | `ntdll.dll!memcpy` | 55 | 0.95% | 93 |
| 12 | `ntkrnlmp.exe!MiCompletePrivateZeroFault` | 40 | 0.69% | 70 |
| 13 | `vector-range.exe!vector_range::render::arena::FrameArena::try_append` | 39 | 0.67% | 454 |
| 14 | `ntkrnlmp.exe!HvcallpExtendedFastHypercall` | 37 | 0.64% | 471 |
| 15 | `vcruntime140.dll!memcpy_repmovs` | 36 | 0.62% | 38 |
| 16 | `D3D10Warp.dll!JITRenderContext::CompileShaderInternal` | 34 | 0.59% | 46 |
| 17 | `vcruntime140.dll!Mov0YmmBlocks` | 34 | 0.59% | 34 |
| 18 | `ntkrnlmp.exe!KiIpiSendRequest` | 33 | 0.57% | 1046 |
| 19 | `vcruntime140.dll!memset_repstos` | 26 | 0.45% | 4482 |
| 20 | `ntkrnlmp.exe!MiChangePageAttributeBatch` | 22 | 0.38% | 2357 |

## Source and evidence

- Sampled source: [f2eab4d4](https://github.com/RHS059/rust_duty/commit/f2eab4d4d3d527d153b08a7a9ae403fb40509b0d), tree `d68a1ae81453f75d36a2870cca007076e5fd0f58`.
- [Original compact receipts](https://github.com/RHS059/rust_duty/actions/runs/38194089349/artifacts/11723430502).
- [Original ETL, EXE and PDB](https://github.com/RHS059/rust_duty/actions/runs/38194089349/artifacts/11723285843), archive SHA-256 `98eea81efe3266abad6aa676ab6b1f26a2a69f094f8acd6bcc71886bd9327d1e`.
- ETL SHA-256 `b1a49c1eaba233c2fb58363e822c61cf014f9277625cdc314630952a2da4204d`.
- [Recovery execution and original-download digest](https://github.com/RHS059/rust_duty/actions/runs/38195837044/job/114638146864), tool source `70f67908408012646cd37195d82c94fbe66ab62b`.
- [Recovered raw reports](https://github.com/RHS059/rust_duty/actions/runs/38195837044/artifacts/11723054041), archive SHA-256 `9cb9bbb09138710d26dca42ec79769525764c0eb09dfc177440218e2197dd2da`.
- `renderer-stack.txt` is the original XHTML stack report. SHA-256 `4ede6faa055cd90996ae230edf00aa52a9b62ffbd8653ecc1f74054eea66919e`.

The original game failed its 20-second F10 exit wait **after the trace was saved**;
owned-process cleanup returned 1. Its capture verdict remains failed. Recovery
verified the 15 original compact report hashes, full 19-file retained inventory,
actual retained EXE/PDB bytes against original receipts, five exported report
hashes and unchanged input bytes. The recovery job's downloaded archive digest
matches the original GitHub digest. The ETL hash agrees with an independent
extraction. Original post-capture source/assets/settings checks skipped by the
shutdown failure remain unverified. A successful export does not upgrade that
original capture, establish a normal-exit pass or approve authored-image quality.
