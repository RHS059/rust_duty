# A100 direct viewmodel: compact native/result evidence

## Interim verification status

At source `aec1955e93867fb88df7b0d51526e338b8375761` (tree
`a64256619f1f880ec9aa726ca6e2131e149d3efe`), the five-case native viewport-depth
fixture passes on NVIDIA A100/Vulkan. Independent review replays the compact
compile/artifact/process/adapter and pixel checks. Four original in-game
screenshots were also reviewed.

**Full raw performance replay is pending.** The timing values below come from
the controller's retained summaries; they have not yet been independently
recomputed from complete raw timeseries. Direct inspection of retained game/test
ELF bytes, complete materialized source and Xvfb/Openbox raw records is also
pending. This frozen compact review must remain distinct from a later full audit.

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

## Controller-derived offscreen/direct ABBA

| Run | Mode | Eligible intervals | Frame p50 ms | GPU p50 ms | Encode/submit p50 ms | Resident draws | Render passes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Offscreen | 5,228 | 5.885511 | 1.305600 | 1.350529 | 86 | 4 |
| 2 | Direct | 5,367 | 5.721387 | 1.175552 | 1.319332 | 86 | 3 |
| 3 | Direct | 5,396 | 5.685009 | 1.175552 | 1.313673 | 86 | 3 |
| 4 | Offscreen | 5,221 | 5.883115 | 1.305600 | 1.337621 | 86 | 4 |

Means of the two run medians are 5.884313 ms offscreen and 5.703198 ms direct;
GPU medians are 1.305600 ms and 1.175552 ms. These are provisional descriptive
same-binary results, not an independently replayed timeseries result, display-FPS
measurement, statistical confidence claim, or completed optimization target.
CPU/GPU and parent/child stages overlap and cannot be summed as separate budgets.

Both modes retain 86 resident draws. The offscreen control already includes
shared renderer pass consolidation, so its four passes must not be compared
causally with the older 13-pass source. Only these same-binary legs isolate the
direct-route contrast; cross-source/environment deltas cannot be assigned to it.

## Screenshots and sampling difference

Hands, glove and rifle remain visible with the same pose/framing and world/HUD
layout in all four post-record captures. Direct rendering samples at native
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
screenshots. It contains no credentials or private soldier assets. Neither
source bytes nor raw executable/performance completeness is implied by this
compact publication. Full evidence will be published separately after transfer
and independent replay; no source changes or PR merge accompany this report.
