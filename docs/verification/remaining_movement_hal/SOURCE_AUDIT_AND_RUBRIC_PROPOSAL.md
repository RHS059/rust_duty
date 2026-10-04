# Remaining movement independent review: source audit and contract proposal

Status: **measurement-only; rubric not frozen; unscored**. Reviewed 2026-10-04. This note does not change Elara's Jump r6 score of 78 or accept r7.

## Ownership

Hal's independent review lane owns this documentation directory on `halcyon/remaining-movement-review`. Aella owns consolidated source annotations/cuts, shared comparison code/notebook, Colab operation, canonical integration and production runtime/export paths. No clips, footage, private assets, animation, notebook, runtime or export settings were changed by this review.

Planning release and source-first dependency: https://github.com/RHS059/dot_chat/pull/1#issuecomment-5983276672

## Source pins and checks

All local raw-source SHA-256 hashes were recalculated during this review:
- R1 `9RRgXvRx43s`: `5b883e85d1179d06987509e4ede2b18fbc54433c4578b316af355e68d17becf5`; 47,049,387 bytes; 6,822 native frames.
- R2 `5KM0XSKxTWw`: `cff413d8d114b611bbe6f50cc553ef109d61eb8eb1fff960425f506b84d6767e`; 52,915,134 bytes; 7,976 native frames.
- Recovered R3 corresponding to `V_QT_cnlBHU`: `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`; 50,406,346 bytes; 9,137 native frames.
- All are 1280x720 and 60 fps. Existing validated R1/R2 PTS tables use zero-based frame n, timestamp n/60 seconds and n*256 ticks at timebase 1/15360. Fresh full R3 PTS inspection confirms the same formula for all 9,137 frames, first tick 0, last tick 2,338,816.
- R3 repository evidence is pinned at `58dad13f51db3dd951f43f3fd7ddc3fbd020ad00`: seven exact binary parts and a reassembler under `references/movement/`. It is not a single direct-playback MP4 URL.
- R3 provenance is strong title/runtime/chapter correspondence with the recovered source. Independently downloaded YouTube encoded-byte/live-pixel equivalence was not established.

Jump PR20 was open at `4363837e46ee89b5ca8baa1b5c08e1e3f81cac91`, r7 source SHA-256 `a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`. Its paired independent review remains pending.

## Annotation audit

Pinned existing R1/R2 annotation revision: `be1c746db2aafead7af967708927c03e807f9325`. The remote `reference_annotation.json` blob is `c99ef260beaec44d3023420ba8c196e62eec1dcc`.

Structural review confirms 62 R1 segments plus 87 R2 intervals: 149 total, contiguous without gaps/overlaps, valid integer increasing bounds, covering [0,6822) and [0,7976). This is a schema/coverage audit, not fresh pixel-level reclassification or native-boundary approval.

The pinned remote JSON is schema 1.0 with historical 'awaiting agreement' and 'all eight Actions' text. Later local schema 1.1 is not byte-identical and must not silently replace the pinned source. Prior authoring-scope statements are historical, not this batch's current scope.

**Import hazard:** R2 `selected_excerpts` use inclusive `end_frame_inclusive`; timeline intervals use exclusive `end_frame_exclusive`. Normalize deliberately before refinement. For example the historical crawl-forward selected excerpt [4932,5172] inclusive becomes [4932,5173) half-open; this is not approval to cut that provisional range. General boundaries came from 10 fps sampling, with approximately +/-6 raw-frame uncertainty. Aella must refine actual onset/extrema/recovery at 60 fps before exact cuts or dependent authoring.

Historical discovery intervals for raw review:
- R1 prone-like entry [3660,3708); forward [3750,4092); backward [4110,4440); right [4614,4908); left [4926,5274).
- R2 forward crawl [4896,5202); backward [5238,5538); right [5592,5802); left [5802,6156).
- R1 left crawl explicitly reports weapon sweeping off the lower edge. R2 left crawl reports other players crossing during 98.6–102.4 seconds. These require explicit source-visibility and background-motion handling.
- R3 chapters are discovery ranges only: prone 36–65 seconds, jumping 65–72, mantle/vault 117–140, climbing 140–end. They do not determine exact event boundaries or prove every variant.

R1/R2 current durable original-footage repository locations are not established by this review. Text annotations and local raw hashes are verified; no duplicate conversion was started.

## Event rubric amendment: independent review disposition

Reviewed Aella proposals:
- https://github.com/RHS059/dot_chat/pull/1#issuecomment-5983296976
- https://github.com/RHS059/dot_chat/pull/1#issuecomment-5983301138

Agreement in principle:
1. Retain the proposed **60 nominal motion points**, with a frozen denominator. Unsupported clauses do not reduce it or earn points. Coverage is an additional gate. No conversion between this diagnostic and Elara's independent score.
2. Timing 20: 10 points for complete observed event duration within 10%; 10 for every predeclared unambiguous milestone within 10% of event duration. Exclude presentation padding/ready holds, retain source onset/settle uncertainty, and never infer input-event times.
3. Proposed spatial tolerances remain subject to final freeze: translation 20 uses centered RMS 0.06L and amplitude tolerance max(20%,0.02L); angular 15 uses axis RMS 5 degrees and amplitude tolerance max(20%,2 degrees).
4. For nonloop events, continuity 5 examines actual pre-event→event and event→settled joins, rather than invented loop closure, with proposed 0.03L/3-degree limits and dense no-reset/velocity review.
5. Preserve fixed pre-event-baseline displacement and recovery residuals separately from centered RMS. Use a third physically corresponding noncollinear rigid-weapon anchor for orientation corroboration. Wrists, cuffs, world/camera motion, appearance and inferred anatomy do not become weapon-motion points.
6. Native 1x timing, immutable source/candidate/render pins, declared fixed geometry/projection scale, whole-window constant means and one pre-frozen shared time offset only. No candidate-optimized phase search, per-frame registration or dynamic retiming.

Required clarifications before scoring:
- Declare each component's point allocation and whether tolerance checks earn binary or graded points. Translation/angular/continuity tolerances alone do not specify arithmetic. State whether 80% support means at least 48 supported nominal points and how each category's 60% gate is calculated with unsupported clauses.
- Define L, physical anchor correspondence, orientation sign and third-anchor visibility. Geometry differences can make an apparent pair of landmarks nonhomologous. Missing third-anchor evidence cannot be fabricated from a cuff or background point.
- Freeze separate source-visible/planned coverage and valid candidate-pair/source-visible coverage. Candidate offscreen/failed tracking when the source is visible cannot be masked away. Publish per-phase/category coverage; a missing critical recovery or extremum yields inconclusive review even if aggregate coverage is high.
- Freeze event segmentation before candidate evaluation. A long multi-cycle climb cannot use its entire duration to create a loose milestone tolerance. Score complete individual events/cycles and disclose per-phase residuals.
- Separate the fixed observed Jump example's event timing from runtime-variable airborne holds and contact-triggered landings. Runtime hold/landing behavior is verified under the action contract, not forced to a reference physics timer or silently mixed into motion duration scoring.
- Give velocity/no-reset inspection an explicit rule; a separately named qualitative independent-review veto is acceptable. A plausible position seam alone does not prove velocity continuity.
- Any uncertainty interval crossing a threshold is inconclusive, not rounded into a pass. Identify endpoints and settle criterion before viewing candidate error.

No remaining-action percentage is produced here. Numerical diagnostics, independent review and actual runtime/export checks remain distinct gates. No PR merge or production-completion claim is made.
