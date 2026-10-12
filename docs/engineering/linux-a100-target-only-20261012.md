# A100 visible / empty-target / hidden controls

## Finding and attribution boundary

At source `61f7b4de3422dad34c7ed94ac661339f205babaf` (tree
`0709c9595fdd8b75198dcf41ee511f21488ca87f`), one same-binary sequential
visible / target-only / hidden / hidden / target-only / visible experiment
separates two diagnostic contrasts:

- Target-only minus hidden: 0.183808 ms difference between averages of run GPU medians, measuring the retained empty target/clear/composite route.
- Visible minus target-only: 0.595456 ms by the same calculation, including geometry work and its draw-pass setup.

**An empty-target route is not the full cost of routing nonempty geometry
offscreen.** These are not pure triangle/shader timers or a prediction of the
new direct-render architecture's gain. That architecture also changes sampling
resolution/filtering and pass consolidation and requires its own matched
same-ELF measurement. These omission controls do not render a usable hands/weapon
layer in target-only or hidden mode.

## Original workload and all six legs

The retained single ELF has SHA-256
`51b5dc571465462dabe15387a47f52d31f519886cf4ec5183104e583973e8d9a`.
Actual compiler is Rust 1.99.0; device is NVIDIA A100-SXM4-40GB, Vulkan driver
580.82.07, explicitly selected with Immediate presentation. The game window is
physical 1920 × 1080 and the original viewmodel target is 1440 × 900. The
stationary default-range scene uses the authored HK416A5 viewmodel.

| Run | Mode | Eligible intervals | Frame p50 ms | p95 ms | p99 ms | Producer intervals/s | GPU p50 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Visible | 4,821 | 6.371566 | 6.974266 | 7.468192 | 155.4269 | 1.508352 |
| 2 | Target-only | 5,665 | 5.412575 | 5.936944 | 6.355240 | 182.8164 | 0.913408 |
| 3 | Hidden | 5,919 | 5.173262 | 5.715613 | 6.234442 | 190.9555 | 0.729088 |
| 4 | Hidden | 5,853 | 5.243790 | 5.727000 | 6.216583 | 188.8782 | 0.730112 |
| 5 | Target-only | 5,442 | 5.672989 | 6.001650 | 6.507899 | 175.5583 | 0.913408 |
| 6 | Visible | 4,575 | 6.737872 | 7.224906 | 7.606526 | 147.5164 | 1.509376 |

The averages of the two per-mode run medians are frame 6.554719 / 5.542782 /
5.208526 ms and GPU 1.508864 / 0.913408 / 0.729600 ms for visible / target-only /
hidden. Frame medians drift across repetitions, especially visible and
target-only; the table retains that drift rather than replacing it with pooled
frames. There is no confidence interval or statistical-significance claim.
Inverse frame medians are derived rates, not display refresh/FPS; producer
interval rates are separately reported.

Visible has 86 resident draws (75 rigid + 11 skin), 54,768 uniform-upload bytes
and 13 render passes. Target-only has zero resident draws/uploads and 12 passes;
hidden has zero resident draws/uploads and 11 passes. The standard 384-character
HUD cohort has 600 / 514 / 513 total draws respectively. All modes have zero
warm resident cache misses and zero resident vertex/index uploads. Original
world/HUD and committed simulation/animation updates remain.

Target-only retains target camera/clear and full-screen composite but returns
before authored geometry preparation/submission and its draw pass. CPU stages
and GPU command spans overlap and must not be summed as independent budgets.
GPU timestamps exclude earlier upload copies. The descriptive mean frame
contrasts (1.011937 ms visible minus target-only; 0.334256 ms target-only minus
hidden) are not isolated GPU service times.

## Independent raw audit and screenshots

Independent replay verifies 460 source Git/SHA identities, 133 production inputs,
the retained ELF, process/input/launch joins and all 32,275 eligible CPU/GPU
samples. Every eligible GPU sample is measured. Raw summaries and original
hashes are verified; all packet bytes remain unchanged. Original public asset
binaries are receipt-bound, not directly inspected in this telemetry archive.
Source binding comes from verified inputs and ELF even where session-local Git
identity is unavailable.

All six original 2560 × 1440 desktop screenshots were viewed; capture happened
outside the recorded windows. Visible retains rifle/glove/forearm; target-only
and hidden omit them with the same world camera/crosshair/HUD layout. These are
post-record qualitative checks, not frame-synchronized pixel equality.

- [Run 1 visible](evidence/a100-target-only-61f7b4de-20261012/screenshots/viewmodel-r01-visible.png)
- [Run 2 target-only](evidence/a100-target-only-61f7b4de-20261012/screenshots/viewmodel-r02-target-only.png)
- [Run 3 hidden](evidence/a100-target-only-61f7b4de-20261012/screenshots/viewmodel-r03-hidden.png)
- [Run 4 hidden](evidence/a100-target-only-61f7b4de-20261012/screenshots/viewmodel-r04-hidden.png)
- [Run 5 target-only](evidence/a100-target-only-61f7b4de-20261012/screenshots/viewmodel-r05-target-only.png)
- [Run 6 visible](evidence/a100-target-only-61f7b4de-20261012/screenshots/viewmodel-r06-visible.png)

## Full retained evidence

- [Independent raw audit](evidence/a100-target-only-61f7b4de-20261012/independent-audit.json), SHA-256 `899dd5110694bbf8bb3896103d59ee88f1cb02d16dc78238797513402735bbd9`.
- [Final metrics, screenshots and setup review](evidence/a100-target-only-61f7b4de-20261012/final-review.json), SHA-256 `4877cb75129a5eee5828c7408a004c7e571796ac69553a90bc4414ade9302a1a`.
- [Metrics TSV](evidence/a100-target-only-61f7b4de-20261012/metrics.tsv) and [all archive entry hashes](evidence/a100-target-only-61f7b4de-20261012/artifact-index.json).
- [Full original archive reconstruction](evidence/a100-target-only-61f7b4de-20261012/full/README.md): three lossless parts reproduce the 185,810,810-byte ZIP SHA-256 `fa415bf6904e7fe9ce6c3252b582dd522ca9ac5aa4dcc1c35b23366f6ec13f09`; all 693 CRCs pass.

No credentials, private soldier assets or unrelated personal material were found
in archive/inventory/screenshot publication review. Existing source and all prior
evidence are preserved; this publication does not run another test or merge.

## Remaining limits

This single sequential stationary Linux experiment is not RTX/DX12 or broad
gameplay evidence. Animation samples are not frame-for-frame synchronized;
CSV has no health field. The historical strict arithmetic gate remains failed:
18 RGB pixels across 11 pairs, maximum delta 3. These diagnostics do not waive
that gate, historical visibility failures or the intended-hardware performance
target. Results from the older visible/hidden and newer direct/offscreen sources
remain separate experiments, not additive causal components of one speedup.
