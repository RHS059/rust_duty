# Consecutive render-pass batching

This implementation reduces native command-recording work without reordering
draws. Its native comparison and updated finite ADS source-equivalence evidence
are pending. Source counts and CPU preparation timings are not gameplay FPS.

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

## Required native follow-through

Compare the production renderer before and after this change on the same Windows
DX12/WARP compiler and adapter, retaining the existing fixed pixel expectations
and decoded-pixel equality across its captures. A bounded submission benchmark
must keep PNG readback outside timed frame submission and identify WARP results
as diagnostics, not RTX 3080 Ti gameplay FPS.

The retained finite ADS class pins the earlier `frame.rs` and `plan.rs` and must
currently reject these changed bytes. The independent finite probe has its own
encoder; its shared clear function, shaders, packing, target and capture code
are unchanged. Update only a specifically reviewed exact source-equivalence
mapping after the production scheduling comparison; do not skip either file,
change masks or tolerances, or describe the historical arithmetic proof as a
new batching execution.
