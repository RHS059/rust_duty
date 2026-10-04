# Jump r7 one-point diagnostic: independent arithmetic recheck

Date: 2026-10-04. Status: **diagnostic arithmetic reproduced; no animation acceptance or score**.

Evidence revision: `6e30c65502eb6d78939d917de45057f51aa027ef`, directory `docs/verification/movement_comparison/jump_r7/`. Reviewed raw input, raw summary, README, Colab motion summary and provenance. The 100 coordinate pairs were independently recomputed without running Aella's comparator.

## Verified from the serialized input

- Exactly 100 samples: native source frames [4014,4114).
- Every source PTS equals frame*256, timebase 1/15360.
- Every corresponding candidate sample time equals (frame-4014)/60 seconds.
- Baseline frame is 4033; whole-window means are separately computed for source and candidate.
- Raw vector RMS: 68.9448694572321 px.
- Mean-centered vector RMS: 6.660364499879335 px.
- Pre-event-baseline-relative vector RMS: 6.79145662112803 px.
- Baseline-relative p95: 13.636217872745588 px; maximum: 16.558491939835523 px.
- These independently computed results match the published diagnostics to floating-point precision. p95 uses linear interpolation at rank 0.95*(N-1).

For each sample, raw residual = candidate_xy - source_xy. Centered residual subtracts each series' own whole-window mean. Baseline residual subtracts each series' own frame4033 position. RMS = sqrt(mean(dx^2+dy^2)). No phase fitting, scaling or candidate-driven exclusion was performed by this recheck.

## Pixel scope and interpretation

Actual source n4014 and the existing native r7 model baseline image were inspected. An aft protrusion exists at the proposed source point, and a corresponding model-region feature is visible. This supports an explicitly **provisional one-point image-motion diagnostic**, not certified three-dimensional physical homology, a three-anchor rigid axis, fixed L or whole-weapon acceptance.

The 100/100 coverage claim is one point's declared observation coverage. This recheck does not independently certify every coordinate by pixel review; Aella's report states that it inspected all 100 point crops and 57 full-view pairs. No normal/slow full-clip playback was performed by this recheck.

The published Colab evidence correctly distinguishes locally verified source/candidate bytes from JSON-only execution: source/candidate video bytes were **not** verified inside Colab. Actual Colab execution/session release is Aella's recorded provenance; this reviewer did not operate or independently observe that browser session.

## Decision

The arithmetic is suitable for publication with its existing diagnostic-only labels and limitations. The 68.94 px raw RMS includes fixed framing differences; 6.79 px baseline-relative RMS isolates relative image displacement but does not establish physical equivalence. The 16.56 px maximum lies near the stated usual 16 px annotation residual bound; these are visual uncertainty estimates, not statistical confidence intervals.

No protected takeoff/air revision is justified by this packet alone. Missing L, muzzle/axis and third homologous landmark remain unsupported. Independent Elara r6=78 is unchanged; r7 acceptance remains pending. No percentage or 80% match is inferred.
