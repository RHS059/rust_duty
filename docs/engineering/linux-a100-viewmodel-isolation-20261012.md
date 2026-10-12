# A100 same-binary visible/hidden viewmodel ABBA

## Finding

At source `ca03e84104d47ecf76ff4feaa4fa307457c0ae2a` (tree
`6fd372fe4c3b4d85e5615c5e45434f4fa6667871`), intentionally omitting the entire
viewmodel render layer lowers the two run medians from 6.526146/6.546757 ms to
5.321608/5.313283 ms. The average of the two visible run medians minus the
average of the two hidden run medians is 1.219006 ms (18.65% lower intervals).
This is a descriptive contrast from one sequential ABBA experiment.

**This is an omission diagnostic, not a usable visual optimization.** Hidden
removes hands/weapon preparation, target clear, geometry and composite together.
The difference cannot be assigned to clear/composite alone, nor prove that a
direct-main-target rewrite preserves appearance. World, HUD and committed
simulation/animation updates remain. The retained-target control at newer
source `61f7b4de3422dad34c7ed94ac661339f205babaf` is preserved in the repository
but was not part of these measurements.

## Setup and run metrics

One retained ELF is used for all four runs (SHA-256
`2be1b817850cb7c74fed411b7148e397aefa1664e07e11095cdd1097cd4c3cc9`).
Actual build: Rust 1.99.0, Linux, NVIDIA A100-SXM4-40GB, Vulkan driver 580.82.07,
explicit adapter selection, Immediate presentation. The physical game window
is 1920 × 1080; desktop screenshots are 2560 × 1440. The stationary default
range uses the authored HK416A5 viewmodel.

| Run | Mode | Eligible intervals | p50 ms | p95 ms | p99 ms | Producer intervals/s | GPU command-span p50 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Visible | 4,718 | 6.526146 | 7.049616 | 7.567802 | 152.1199 | 1.508352 |
| 2 | Hidden | 5,776 | 5.321608 | 5.807054 | 6.232827 | 186.3318 | 0.730112 |
| 3 | Hidden | 5,787 | 5.313283 | 5.737093 | 6.236990 | 186.6611 | 0.730112 |
| 4 | Visible | 4,717 | 6.546757 | 6.940132 | 7.428120 | 152.1414 | 1.508352 |

Inverse frame medians are derived rates (about 153 visible and 188 hidden),
not observed display FPS. Producer throughput is separately calculated from
eligible intervals. Do not compare the visible rate with the earlier
[1ef12e3f ABBA](linux-a100-resident-abba-20261012.md) as a source optimization:
that is a different runtime setup and measurement occasion, not this controlled
same-binary contrast. No RTX 3080 Ti/DX12 or general gameplay target is established.

The two visible runs retain 86 resident draws per eligible frame (75 rigid and
11 skin), versus zero hidden; render passes fall from 13 to 11. Resident uniform
uploads are 54,768 bytes versus zero. Both modes have zero warm resident cache
misses and zero resident vertex/index uploads. The standard 384-character HUD
cohort has 600 total draws visible versus 513 hidden; transient HUD cohorts are
retained separately in the review.

Median game-recording times are 0.338452/0.338728 ms visible versus
0.271163/0.269120 ms hidden; renderer-submit times are 1.602179/1.625444 ms
versus 1.306634/1.305289 ms. Present-call medians also fall. These overlapping
CPU parent/child stages and GPU spans must not be added or subtracted as
independent cost budgets. GPU timestamps exclude earlier upload copies.

## Independent audit and visual review

The raw audit verifies 460 source Git/SHA identities, 133 production inputs,
the retained ELF, launch/setup/input joins, four clean exits, and all 20,998
eligible primary/CPU/GPU joins. Every eligible GPU sample is measured. Raw
summaries are independently replayed; original packet bytes remain unchanged.
The original 77 public asset files are receipt-bound rather than included asset
binaries. Materialized session-local Git identity may be unavailable; the
verified build inputs and retained executable provide the source binding.

All four original screenshots were directly reviewed and captured outside the
measurement window. Visible shows rifle/glove/forearm; hidden removes them,
while world camera, crosshair and HUD layout remain. These are diagnostic
screenshots, not exact image-equivalence tests:

- [Run 1 visible](evidence/a100-viewmodel-ca03e84-20261012/screenshots/run-01-visible.png)
- [Run 2 hidden](evidence/a100-viewmodel-ca03e84-20261012/screenshots/run-02-hidden.png)
- [Run 3 hidden](evidence/a100-viewmodel-ca03e84-20261012/screenshots/run-03-hidden.png)
- [Run 4 visible](evidence/a100-viewmodel-ca03e84-20261012/screenshots/run-04-visible.png)

Failed attempts r1 and r2 each retain a failed driver result with zero raw
primary frame files. Their logs, official Ubuntu display/XKB setup records,
and reviewed startup-race repair/diff/negative-control evidence are retained
alongside successful r3. They are not mixed into the measured sample or hidden
as clean runs.

## Complete evidence

- [Raw independent audit](evidence/a100-viewmodel-ca03e84-20261012/independent-audit.json), SHA-256 `6373f3377756d651eed3da6b15fcf5ff62e304028a8eac5d3b559172a0585977`.
- [Final metrics, screenshot and setup review](evidence/a100-viewmodel-ca03e84-20261012/final-review.json), SHA-256 `3acdb49f0f4ce70e020a2a847e61b09fbaf6dcbe27c0711890a204570a36a901`.
- [Metrics TSV](evidence/a100-viewmodel-ca03e84-20261012/metrics.tsv) and [all archive entry hashes](evidence/a100-viewmodel-ca03e84-20261012/artifact-index.json).
- [Full original archive reconstruction](evidence/a100-viewmodel-ca03e84-20261012/full/README.md): three lossless parts, original 131,468,206-byte ZIP SHA-256 `f62abf0f70c8ce9db540b3630b5bf2677ba40bd4ef33ec4f4dbf7f4d697d90c5`, all 672 member CRCs verified.

Publication reviewed inventories, credential patterns and screenshots; no
credentials, private soldier assets or unrelated personal data were found.

## Unchanged acceptance limits

Two runs per mode in one sequential stationary experiment do not establish
statistical confidence or broad gameplay performance. Captures are not
frame-for-frame animation synchronized, and the gameplay CSV has no health
field. The previous strict arithmetic image gate remains failed: 18 RGB pixels
across 11 pairs, maximum delta 3. This labeled omission experiment does not
change that verdict, waive historical visibility failures, or complete the
140–200+ FPS intended-hardware/gameplay target.
