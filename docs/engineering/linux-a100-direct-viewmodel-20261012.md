# A100 direct viewmodel: native checks and audited matched performance

## Verification status

At source `aec1955e93867fb88df7b0d51526e338b8375761` (tree
`a64256619f1f880ec9aa726ca6e2131e149d3efe`), the five-case native viewport-depth
fixture passes on NVIDIA A100/Vulkan. Independent review replays the compact
compile/artifact/process/adapter and pixel checks. Four original in-game
screenshots were also reviewed.

**Full raw performance replay is complete.** The independently recomputed
four raw legs reproduce the controller summaries exactly. The completed audit
verifies 460 source identities, 133 production inputs, both retained game/test
ELFs, process/display/setup record joins, all 21,212 measured eligible GPU
samples and the native five-case artifact/process/pixel checks. The earlier
compact review remains frozen with its original pending fields; the separate
full audit below records the completed verification.

## Bounded native result

The five original cases are opaque-first, resident-first, near-clipped,
far-clipped and ordered-fade. Their expected center/world/HUD probes pass,
with retained CPU pass-planning checks and original images. Opaque and resident
cases show the foreground sample; near/far clipped cases retain the world;
ordered fade retains its expected blended sample.

This validates those specific probes and native process/device evidence. It is
not an actual-game full-image equivalence test or gameplay-wide acceptance.
The original 18-RGB-pixel arithmetic mismatch across 11 pairs, maximum delta 3,
remains failed. Earlier design decisions, historical visibility failures and
intended RTX/DX12 validation are not waived.

## Independently replayed offscreen/direct ABBA

| Run | Mode | Eligible intervals | Frame p50 ms | GPU p50 ms | Encode/submit p50 ms | Resident draws | Render passes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Offscreen | 5,228 | 5.885511 | 1.305600 | 1.350529 | 86 | 4 |
| 2 | Direct | 5,367 | 5.721387 | 1.175552 | 1.319332 | 86 | 3 |
| 3 | Direct | 5,396 | 5.685009 | 1.175552 | 1.313673 | 86 | 3 |
| 4 | Offscreen | 5,221 | 5.883115 | 1.305600 | 1.337621 | 86 | 4 |

Means of the two run medians are 5.884313 ms offscreen and 5.703198 ms direct;
GPU medians are 1.305600 ms and 1.175552 ms. The difference between those mean frame medians is 0.181115 ms (3.08%); the
GPU-median difference is 0.130048 ms (9.96%). These are descriptive same-binary
results from two runs per mode, not display-FPS measurements, statistical
confidence claims or a completed optimization target.
CPU/GPU and parent/child stages overlap and cannot be summed as separate budgets.

Both modes retain 86 resident draws. The offscreen control already includes
shared renderer pass consolidation, so its four passes must not be compared
causally with the older 13-pass source. Only these same-binary legs isolate the
direct-route contrast; cross-source/environment deltas cannot be assigned to it.

## Screenshots and sampling difference

Hands, glove and rifle, world and HUD remain visible in all four post-record
captures. The screenshots are not frame-synchronized and their silhouettes
differ; they cannot isolate animation changes from sampling differences. This
refines the initial compact review's qualitative "same pose" wording, without
altering that frozen receipt. Direct rendering samples at native
1920 × 1080 rather than rendering the viewmodel at 1440 × 900 and filtering it
into the window. Sharper/different edges are therefore expected. Qualitative
review does not claim equal game pixels or establish all poses, fades or occlusion.

- [Run 1 offscreen](evidence/a100-direct-aec1955e-20261012/screenshots/run-01-offscreen.png)
- [Run 2 direct](evidence/a100-direct-aec1955e-20261012/screenshots/run-02-direct.png)
- [Run 3 direct](evidence/a100-direct-aec1955e-20261012/screenshots/run-03-direct.png)
- [Run 4 offscreen](evidence/a100-direct-aec1955e-20261012/screenshots/run-04-offscreen.png)

## Frozen compact packet

- [Original 62-file compact ZIP](evidence/a100-direct-aec1955e-20261012/a100-direct-aec1955e-results-native.zip): 1,454,244 bytes, SHA-256 `5371b5701726e8dc16a8819ce3b0e73d4396b6010a8fa6a05d4c645b541aaab2`.
- [Independent compact/native review](evidence/a100-direct-aec1955e-20261012/independent-compact-native-review.json), SHA-256 `58ac4cb6ea738dcf297fd5e8741825080d0e4340f3178e37088009e677a63bce`.
- [Controller metrics TSV](evidence/a100-direct-aec1955e-20261012/controller-metrics.tsv) and [all compact entry hashes](evidence/a100-direct-aec1955e-20261012/artifact-index.json).

The compact archive retains build/pin/process/launch receipts, original native
wrapper and five fixture images, original performance summaries and four game
screenshots. It contains no credentials or private soldier assets. The compact packet alone does not contain complete source, raw executables or
performance timeseries; those are now retained and audited separately below.
No source changes or PR merge accompany this report.

## Completed full-byte evidence

- [Independent raw performance audit](evidence/a100-direct-aec1955e-20261012/independent-performance-audit.json), SHA-256 `88ca42c3ed3abc5a17201b58df7f586916171ed037e6f4e6e65fecda9ef9a34c`.
- [Final native/source/ELF/metrics review](evidence/a100-direct-aec1955e-20261012/independent-final-review.json), SHA-256 `3e9f5ea64f7c2c945a12fdf8ba79f8ea647794380ceacfa101e0267762326ea1`.
- [Audited metrics TSV](evidence/a100-direct-aec1955e-20261012/audited-metrics.tsv), preserving each leg's p50/p95/p99, producer throughput and overlapping CPU/GPU stages.
- [Full original archive reconstruction](evidence/a100-direct-aec1955e-20261012/full/README.md) and [all 649 original entry hashes](evidence/a100-direct-aec1955e-20261012/full-artifact-index.json).

Three ordered lossless parts reproduce the original 142,867,383-byte ZIP,
SHA-256 `b679f8d20ab9a855b6b136ef6d8e4515c4bd1980ed3242c192daa68dd2e0a5b4`.
The concatenated XZ is 17,441,004 bytes, SHA-256
`8a37433a5a5c49450d1b2da4551198d84bfe2ffc0d91811766ddb1c239288361`.
Reconstruction verifies the exact ZIP and all 649 member CRCs; both raw ELFs
match source/build receipts. Original public asset binaries and Cargo/rustc
executables remain receipt-bound rather than fully exported. Earlier compact
records, source and all historical evidence remain unchanged.

Per-run producer rates are 168.6141 / 173.1358 / 174.1060 / 168.4304 eligible
intervals per second. They differ from inverse median rates and are not display
refresh. The experiment uses one same-binary stationary A100/Vulkan/Immediate
workload; it is not RTX/DX12 or broad authored-animation evidence. The five
native fixtures are not the actual-loader 22-pose gate. The earlier strict
18-pixel arithmetic failure, other historical visibility failures and broader
intended-hardware acceptance remain open.
