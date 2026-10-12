# Reviewed offline skin arithmetic fit

This appendix concerns only retained instrumented samples from source
`80cb324c744e3299d1dd2417c571cdc69c6e46cf`. It is separate from
[the native A100 evidence and failed strict image gate](linux-a100-skin-stage-20261012.md).
No additional GPU run or production change was made for this analysis.

## Observed sample and CPU replay

All 24 selected skin draws have identity root matrices. GPU skin/world values
therefore coincide in all 105 sampled records, while 90 differ from original
CPU corner positions. Independently evaluating the uploaded bone/input/weight
payloads with the pinned CPU float32 operation order reproduces all 105 original
CPU world tuples exactly. This verifies the CPU reference in these samples;
it is not general validation of non-identity roots.

## Compatible arithmetic models

The fit evaluated 384 fixed arithmetic families: 192 bone matrix-times-point
families (24 term orders and separate/fused rounding choices), each combined
with either separate weight multiply/add or fused weight accumulation in source
influence order. One complete family and an equivalent variant reproduce all
105 recorded skin tuples / 315 components. A corresponding separately rounded
weight multiply/add comparison matches only 78 of 105 tuples.

The independent reviewer decoded raw payloads without importing the fitter,
reproduced all 384 scores using `libm fmaf`, and checked 1,872 fitted operations
against an independent exact-rational implementation of IEEE rounding.

These are models compatible with the recorded finite sample, fitted after
observing it. They are not observed GPU instructions or a held-out prediction.
Equivalent fits and compiler instrumentation effects remain possible. The
analysis does not establish a unique instruction sequence, a portable fix,
or the cause of every changed final-image pixel. All roots in the observed
set are identity. Strict image failure remains the same 18 pixels.

## Frozen records

- [Full family-fit data](evidence/a100-skin-stage-80cb324-20261012/arithmetic-family-fit.json), SHA-256 `7458b161b7d406ed0095ef6b80d20421a2491ad2b667e57cbb750a142c634867`.
- [Independent fit review](evidence/a100-skin-stage-80cb324-20261012/arithmetic-fit-review.json), SHA-256 `11b0cbae8fa56bdf07f8a5b6289e0d5801f1f5ecb383eeb56cf5e8a7b239ac04`.
- [Independent CPU-model replay](evidence/a100-skin-stage-80cb324-20261012/cpu-model-review.json), SHA-256 `c226ddfdc87cd559ca91aecb90758906c1ed1b51f70f356be917aaeab1d0f47e`.

The fitter and reviewer are independent implementations and their script hashes
in these receipts intentionally differ. Raw input/probe hashes and the original
compact-stage provenance remain in the frozen records; direct current corner
and executable bytes are retained in the separate full archive and audit.
