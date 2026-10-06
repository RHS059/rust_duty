# Consecutive render-pass batching

This implementation reduces native command-recording work without reordering
draws. Its independently reviewed Windows WARP comparison passed, with median
whole-submit time falling from 47.8049 ms to 11.25665 ms. Updated finite ADS
source-equivalence evidence is retained separately; fresh current-source leaf,
aggregate and complete Windows-package validation remain required. These native
submission timings are not RTX 3080 Ti gameplay FPS.

The paired user exports identify the same executable and source `3a0c73b`,
recorded back-to-back using the regular and DX12 launchers. Mean sampled FPS is
81.2007 versus 21.3309. All eight shared gameplay-state bins show the DX12 deficit;
even the initial stationary/full-ammo position averages 77.33 versus 20.43 FPS.
The complete DX12 trace averages 46.8643 ms between successful present returns.
These existing recordings establish a sustained regression, while omitting
CPU-stage and GPU-execution measurements needed to attribute it.

## Changed boundary

The old renderer opened a render pass for each prepared draw, including every
text glyph. Upload arenas had already removed its three-buffer allocation per
draw; they did not introduce or remove the per-draw pass pattern. In the pinned
wgpu 30 implementation, each ordinary pass also records a separate transition
command buffer. The DX12 backend resets or creates and closes native command
lists for those buffers. This makes pass count a concrete driver-submission cost
candidate, not proof that it accounts for the entire observed frame time.

`plan::draw_run_len` selects only a consecutive prefix with the same target and
depth-attachment choice. Every camera command, clear, capture, target change or
depth change ends the run. The encoder opens one Load/Store pass for that run.
It still issues every indexed draw immediately, in its original order, rebinding
the pipeline, texture and transform groups, dynamic matrix offset, vertex and
index slices, and index count each time. Blend, primitive and texture changes
remain per-draw state. Existing texture identity, feedback and depth checks remain.

Clear, capture copy and final presentation implementations are unchanged.
Presentation stays a separate pass. No borrowed temporary resource cache,
deferred draw accumulator or unsafe lifetime extension is introduced.

## Completed source checks

The same production CPU world/HUD fixture produced:

| Item | Previous encoder | Grouped encoder |
| --- | ---: | ---: |
| Prepared indexed draws | 324 | 324 |
| Text glyph draws | 170 | 170 |
| Draw pass scopes | 324 | 8 |
| Clear plus presentation pass scopes | 3 | 3 |
| Total pass scopes | 327 | 11 |
| Vertex/index/uniform arena bytes | 174960 / 11908 / 83008 | unchanged |

The fixture asserts complete command identity and order, not only equal counts.
It excludes weapon geometry and is not a replay of the user's recording.
Its source-derived pass-related native command-list count falls from 654 to 22;
this is not a runtime GPU counter or measured FPS improvement.

On the cloud CPU harness, existing text preflight/packing averaged 0.479 ms
(p95 0.693 ms, 3000 iterations), and world/HUD recording averaged 1.080 ms
(p95 1.378 ms, 1000 iterations). These optimized harness measurements reuse
debug dependency artifacts and exclude native driver, GPU and presentation.

The candidate passed 132 focused Rust tests, formatting and strict clippy.
New cases cover explicit barriers, empty groups, alternating pipeline/texture/
arena state, and bounded-arena rollover with separate presentation. Existing
asymmetric, alpha, text, target-state, capture and cutover contracts remain.

## Reviewed native comparison

[Run 37482428571](https://github.com/RHS059/rust_duty/actions/runs/37482428571),
attempt 1, compiled restored baseline `17023450076b668c279539e0e450b8cb58a7c1a2`
and candidate `5abf2bca825a252fb7ad6665c444c89861ee8ef9` under verifier source
`4c116be39e426f38f65772ae83ce539891a54e55`. All 112 compile inputs, the identical
harness, all four executable files, compiler transcript and ten actual WARP
device records were independently verified. Both unchanged production contracts
passed their fixed expectations and four failure/recovery cases; all 21 decoded
capture pairs and all 16 synthetic before/after controls match exactly.

This native fixture has 305 prepared draws, including 170 glyphs. It is distinct
from the 324-draw CPU fixture above: its 20 adjacent identity-transform line
commands coalesce into one prepared line draw. Four alternating paired trials
retained all 32 capture-free whole-submit samples. Median time was 47.8049 ms
before and 11.25665 ms after, a 4.2468 ratio; individual paired median ratios were
4.5249, 4.5194, 4.1250 and 4.3194. These wall times include preparation, uploads,
encoding, submission and polling/backpressure, not an isolated GPU duration.

Complete four-submit batches including the extra final control, queue drain,
readback and PNG I/O improved by 2.89–3.12 times. This checks that the improvement
is not merely work deferred beyond the short submit interval, while retaining
the I/O cost in the stated scope. It is a bounded headless software-adapter
diagnostic, not steady-state gameplay, window presentation or an RTX measurement.

Full artifact `11422371812` has ZIP SHA-256
`f29ff7c9fada89478e86f3bae86e0382350d1ac249771116dc920274de5b8994`.
The independent compact review receipt is retained in
`tools/finite_ads_pass_batching_evidence/native-review.json`, SHA-256
`4c2ae5f087ac1e548a9285f635fbb17de9de3defbaa4fab0da014fdb5c976699`.
The separate [finite source-equivalence extension](finite-ads-pass-batching-extension.md)
admits only the reviewed complete old/old or new/new source pair. It preserves
the original descriptor, historical arithmetic evidence, masks, tolerances and
false flags. Current-source native leaf/aggregate checks remain separate from
this scheduling comparison.
