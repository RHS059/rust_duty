# Linux A100 normalization candidate: original correctness and vertex probe

## Verdict

At exact source `5f253fb0f60ec328d56cdd7fb19dbdca09c67b57`, the normalization
candidate **does not fix the strict image failure**. All 44 retained PNGs are
byte-identical to the original `1ef12e3f` A100 captures. The result remains 18
changed RGB pixels across 11 of 22 CPU/resident image pairs, maximum channel
delta 3. Alpha and foreground masks remain exact. The unchanged strict gate
fails and the fixture exits 1 while retaining its original reports and probe.

This is a bounded correctness/diagnostic run on NVIDIA A100-SXM4-40GB,
Linux/Vulkan, driver 580.82.07. It is not a new performance run, does not update
[the original ABBA measurements](linux-a100-resident-abba-20261012.md), and does
not establish Windows RTX/DX12 correctness or the 140–200+ FPS target.

## Instrumented vertex observations

The explicit probe retains 108 selected vertex records across CPU,
current `1.0 / sqrt` and historical `inverseSqrt` routes. Both resident routes
are bit-identical to each other for every sampled clip and color tuple.
Against the CPU route, each resident route has 84 differing clip tuples and
29 differing color tuples. These are record counts, not changed pixel counts.

The 29 color tuples contain 87 RGB component discrepancies, each +1 ULP, while
all 432 sampled color components represent the same quantized byte values.
Source analysis finds that the CPU route uses the correctly rounded value of
`byte / 255`, whereas the resident values match `f32(byte * f32(1/255))`.
This identifies a sampled float representation difference; it does not establish
why all 18 final pixels differ. The separate 84 clip tuple differences remain
relevant. There is no observed change in sampled RGB8 quantization.

The instrumented entry point and integer readback attachments may affect compiler
optimization. Selected triangles are based on bounded CPU projection, not a
trace proving the original rasterizer's primitive identity. Matching the two
normalization routes in these samples cannot prove backend-wide equivalence.
No threshold was relaxed and no source correction is included in this evidence
publication.

## Independent compact-stage audit (frozen snapshot)

The independent audit verifies all 457 source Git blobs and 133 production
compile inputs, actual Rust 1.99.0 build receipts, build exit 0, fixture exit 1,
NVIDIA adapter identity, final input/output inventories, unchanged originals,
and strict probe structure. The asset receipt binds 76 public release files
plus the original Git-source `animations.cfg`, preserving the original 77-file
set. The original release animation-config mismatch and its isolated repair
are retained in the setup evidence.

At the initial compact-stage publication the full archive had been verified on
its producing runtime but its transfer was pending. The independent raw-corner replay uses
explicitly cross-artifact retained Windows WARP bytes with matching hashes;
it is not a replay of downloaded current A100 raw corner files. At that stage the current
ELF was receipt-bound and not yet locally rehashed. The audit explicitly records
`full_zip_available_and_replayed: false`. The completed full-byte audit below remains distinct from this frozen
compact-stage snapshot.

## Completed direct full-byte audit

The separate [full-stage audit](evidence/a100-normalization-5f253fb-20261012/independent-full-audit.json)
(SHA-256 `41dcb9ef3147587c91a9ee85dfd07082193da9eb4e4aafd1d4661d556f571d04`)
directly replays all 44 retained current A100 corner streams and hashes the
7,012,328-byte x86-64 ELF against the original source/build receipt. All 551
files shared by compact/full packets are byte-identical. The full archive hash
and all 596 ZIP member CRCs pass. No cross-artifact corner substitution is
needed for this separate full-stage audit. The original compact audit and
per-vertex metrics remain unchanged; the strict image failure and probe
conclusions are unchanged too.

## Evidence and retention

The original compact packet has 552 files, including the original source/build
receipts, capture reports, 44 PNGs, strict 23-file probe output, and setup/asset
repair receipts. It excludes 44 large raw corner streams and the compiled ELF;
the full packet retains those bytes. The compact packet remains unmodified.

- [Original compact ZIP](evidence/a100-normalization-5f253fb-20261012/a100-5f253fb-compact-correctness-vertex-probe-r1.zip): 3,315,866 bytes; SHA-256 `883a01366cddd17cd42d7e284d939574c5a17fb5792674c21e2a1642600ff057`.
- [Independent audit](evidence/a100-normalization-5f253fb-20261012/independent-audit.json).
- [Per-vertex metrics TSV](evidence/a100-normalization-5f253fb-20261012/probe-metrics.tsv).
- [Pixel and probe replay](evidence/a100-normalization-5f253fb-20261012/pixel-probe-audit.json).
- [Source interpretation](evidence/a100-normalization-5f253fb-20261012/vertex-source-analysis.json).
- [All compact archive entry hashes](evidence/a100-normalization-5f253fb-20261012/artifact-index.json).

The full archive is 147,411,430 bytes, SHA-256
`dd8b187a5c6077a8998eb8caecd356ffebc843678ee67ae5a3a03489c66effdb`.
It is durably retained as [eight ordered lossless XZ parts](evidence/a100-normalization-5f253fb-20261012/full/README.md)
with per-part hashes, reconstruction instructions, and a tested Python verifier.
The concatenated XZ is 46,171,336 bytes, SHA-256
`dd7c707ec16d784ffbf02792ead7636be20dee8956e3e70b7b775a169e3a2d6d`.
Reconstruction reproduces the exact original ZIP, including raw corners and
ELF; it does not repack or modify its members. The compact packet remains
available separately for convenient review.

## Acceptance remains open

The normalization-only hypothesis has no observed corrective effect in this
run. Investigate the independently identified color representation and clip
coordinate differences with isolated source changes and unchanged strict image
controls. That future work is distinct from this result. The original image
failure, historical ADS visibility failure, intended gameplay/hardware checks,
and performance targets remain open.
