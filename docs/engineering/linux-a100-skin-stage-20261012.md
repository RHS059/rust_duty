# A100 skin/root intermediate probe: source 80cb324

## Result and limits

At source `80cb324c744e3299d1dd2417c571cdc69c6e46cf` (tree
`a5abfd3c89f9729e842efbb995347b640bf79fda`), the bounded version-2 probe
retains 108 selected vertex records and intermediate skin/root data for 105
vertices. Ninety observed post-root world-position tuples differ from the
CPU-position reference. Both intermediate invocations' final clip outputs
match the ordinary probe exactly; the additional stage readback does not
change those sampled final clips.

The ordinary probe still has 84 differing clip tuples and zero differing color
tuples versus CPU. Current and historical normalization routes remain identical.
All 264 isolated byte-conversion checks pass. These preserve the narrower
conversion result from [the preceding 0476992 run](linux-a100-exact-color-20261012.md).

**Strict image correctness still fails.** All 44 PNG files match the preceding
A100 images byte for byte: the same signed 18 RGB pixel discrepancies across
11 of 22 image pairs, maximum channel delta 3, with exact alpha and foreground
masks. The unchanged strict fixture exits 1. The conversion process exits 0,
and the diagnostic finishes while retaining the failed original image verdict.

All 24 sampled skin draws have bit-exact identity roots, and all 105 GPU
skin/world tuples are identical. The 90 discrepancies are therefore already
present in pre-root accumulated skin coordinates for this sample set. Of 32
samples with a single positive weight exactly 1, 28 already differ, placing
those examples in the bone matrix-times-point evaluation before multi-bone
blending. Independent CPU replay reproduces all 105 original corner tuples
exactly from the uploaded inputs. This does not identify a specific GPU
instruction, establish the complete cause of the final-image pixels, or prove
a successful correction. The
instrumented entry points may affect compiler optimization and bounded
CPU-projection selection is not a raster primitive trace. No tolerance or
acceptance predicate is relaxed.

## Workload and provenance

NVIDIA A100-SXM4-40GB, Linux/Vulkan, NVIDIA driver 580.82.07. This is an isolated
conversion contract plus fixed authored correctness and explicit diagnostic
readback. The diagnostic source change does not alter production shader math.
There is no new frame-rate measurement, no update to [the original ABBA result](linux-a100-resident-abba-20261012.md),
and no claim of RTX/DX12 or 140–200+ FPS target completion.

## Frozen compact-stage evidence

- [Original compact ZIP](evidence/a100-skin-stage-80cb324-20261012/a100-80cb324-compact-skin-stage-r1.zip): 3,536,177 bytes, 559 entries, SHA-256 `28dc0a2e3baa9a4a8ffc6bb663d4afa27a60112a2bda11705d01daedc61cfda1`.
- [Independent compact-stage audit](evidence/a100-skin-stage-80cb324-20261012/independent-compact-audit.json).
- [Per-vertex metrics](evidence/a100-skin-stage-80cb324-20261012/probe-metrics.tsv).
- [Intermediate-stage metrics](evidence/a100-skin-stage-80cb324-20261012/stage-metrics.tsv).
- [All compact entry hashes](evidence/a100-skin-stage-80cb324-20261012/artifact-index.json).

The compact packet retains source/build/process/input/setup receipts,
conversion output, 44 PNGs and 23 version-2 probe JSON files. Publication
review found no credentials, private soldier assets, or unrelated personal data.

The frozen independent audit verifies all 460 source files and 133 production
compile inputs, both builds, 264 conversion rows, actual A100 identity,
final inventories, strict version-2 structure and raw-parent replay. Its SHA-256
is `572e3becb20138ea96a71384c10ac3a4f991fb00d8de14348a11af8f7694aead`.
At this stage all 44 corner streams are replayed using exact current hashes
matched to previously downloaded A100 bytes; both newly built ELFs are still
receipt-bound. The ordinary metrics remain identical to the preceding run.

The complete ZIP_STORED archive is 626,639,135 bytes, SHA-256
`7bc09f2d5ec8fd69d195c7a5dff4c023ebf944516a8ce2cfc0ac74ad4712a8b3`.
It also retains both compiled ELFs and all 44 raw corner streams. At the initial compact publication, full transfer and direct current ELF/corner
verification were pending; that frozen compact audit is preserved unchanged.

## Completed full-byte audit and durable retention

The separate [direct full-stage audit](evidence/a100-skin-stage-80cb324-20261012/independent-full-audit.json)
(SHA-256 `d5f76f2dd155828bbcb4652e842adfa493c8a31e05065b477bac2f9439422eab`)
verifies the original full archive hash, all 604 member CRCs and path/inventory
checks, and all 558 byte-identical shared compact/full files. It directly
replays all 44 current raw corner streams and command slices, uses current CPU
raw bytes for the strict version-2 replay, and hashes both current x86-64 ELFs
against the build receipts. No prior-artifact corner substitute is needed for
this separate direct-byte audit. The reported failures and sample counts are
unchanged.

The exact original archive is retained in [four lossless ordered XZ parts](evidence/a100-skin-stage-80cb324-20261012/full/README.md)
with per-part hashes and a tested reconstruction verifier. Concatenated XZ size
is 21,247,544 bytes, SHA-256
`50f0625b040e5b0968ae0763f457387c19b204fd16be079f8649fe51244f0656`.
Reconstruction reproduces all 626,639,135 original ZIP bytes exactly.

A separate [reviewed offline arithmetic-fit appendix](a100-skin-arithmetic-fit-20261012.md)
records compatible finite-sample models. It does not identify actual GPU
instructions, a portable correction, or the cause of the final-image failure.

## Remaining acceptance

Continue isolated analysis of the recorded stages with exact images retained
as the acceptance rule. No final cause or fix is established here. The original
strict image failure, historical ADS visibility failure, intended gameplay and
hardware validation, and performance targets remain open.
