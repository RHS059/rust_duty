# A100 exact-color conversion: source 0476992

## Result

At exact source `047699250fdcd98700caff66cbc86c4adf585b87` (tree
`576e98bf29ca56acdabaab26c37279f3695198d5`), all 264 isolated conversion
checks pass: 256 byte values plus eight clamp/boundary cases. The 29 differing
sampled vertex color tuples from the [preceding 5f253fb run](linux-a100-normalization-probe-20261012.md)
fall to zero across the same 108 selected records. The 84 differing clip tuples
remain, and the current/historical normalization routes still match each other.

**The strict image gate remains failed.** All 44 PNG files are byte-identical to
the preceding A100 images: the same 18 differing RGB pixels in 11 of 22
CPU/resident image pairs, maximum RGB channel delta 3. Alpha and foreground
masks are unchanged. Exact color conversion resolves the sampled color
representation discrepancy; it does not fix the observed final images.

The isolated conversion process exits 0. The authored fixture exits 1 under
its unchanged strict predicate, with original images, report and probe retained.
No pixel tolerance or acceptance gate was relaxed.

## Scope

NVIDIA A100-SXM4-40GB, Linux/Vulkan, NVIDIA driver 580.82.07. This source-bound
run executes an isolated conversion contract and fixed authored correctness
fixture with explicit vertex readback. It does not measure frame rate, update
[the original 1ef12e3f ABBA result](linux-a100-resident-abba-20261012.md), or prove
Windows RTX/DX12 performance. The 140–200+ FPS target remains open.

The probe samples instrumented vertex outputs selected by a bounded CPU
projection procedure. It is not a trace of original raster primitive identity,
and instrumentation can change compiler optimization. Remaining clip-coordinate
differences are a diagnostic lead, not a proven explanation of all 18 pixels.
No future diagnostic or production correction is part of this evidence result.

## Frozen compact-stage evidence

- [Original compact ZIP](evidence/a100-exact-color-0476992-20261012/a100-0476992-compact-exact-color-r1.zip): 3,334,214 bytes, 558 entries, SHA-256 `1627592c359c037ae746655fa44e295624b42c1ca9fb7969fcae616e56e8b831`.
- [Independent compact-stage audit](evidence/a100-exact-color-0476992-20261012/independent-compact-audit.json).
- [Per-vertex metrics](evidence/a100-exact-color-0476992-20261012/probe-metrics.tsv).
- [All compact entry hashes](evidence/a100-exact-color-0476992-20261012/artifact-index.json).

The compact packet preserves original source/build/process/input/setup receipts,
conversion output, 44 PNGs and the vertex probe. Its synthetic triangle fixtures
are public test data. No credentials, private soldier assets, or unrelated
personal data were found in the publication review.

The frozen compact audit verifies all 459 source files and 133 production
compile inputs, both builds, 264 conversion rows, actual A100 identity,
final inventories, and all 108 probe joins. All 108 clip tuples match their
preceding `5f253fb` values exactly; 84 still differ from the CPU route. Its
corner replay uses exact current hashes matched to the previously downloaded
and directly verified A100 bytes. Both newly built ELFs remain receipt-bound
at this compact stage. The audit SHA-256 is
`dcfd2b0b71ae15ef3ad7205e037fa9f98e2bd1f8dc045b0ee9977c916b449750`.

The full ZIP_STORED archive is 625,606,155 bytes, SHA-256
`7a75575364990e4963f012e2ee8dad5a75a14595a351f3c4d618033cdbbc6237`.
It additionally retains both compiled ELFs and all 44 raw corner streams.
At compact publication, full transfer and direct current executable/corner-byte
verification are pending; receipt binding and any cross-artifact replay in the
frozen compact audit are explicitly labeled. A separate full-stage audit and
lossless durable storage will be linked only after verification completes.

## Remaining work

Keep exact images as the acceptance rule. Investigate the remaining clip
arithmetic/rasterization discrepancy with isolated, source-bound diagnostics.
A passing conversion contract and corrected sampled color words are narrower
results than a passing renderer image gate. Original failures, intended
hardware/gameplay validation, and performance targets remain open.
