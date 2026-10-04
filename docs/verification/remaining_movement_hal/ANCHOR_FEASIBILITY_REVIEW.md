# Independent anchor feasibility and arithmetic review

Review date: 2026-10-04. Status: **raw diagnostics supported; no approved homologous three-anchor set, no fixed L, no whole-event match percentage**.

## Evidence inspected

- Original recovered R3 SHA-256 `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.
- Actual full-resolution decoded source images: native frames 7284, 7288, 7290, 7291, 7292, 7298, 7300, 7301, 7302, 7303, 7304 and 7310.
- Source native frame n uses timestamp n/60 and PTS n*256 at timebase 1/15360. Fast-seek decoding at 121.4 seconds was checked against full sequential selection of n7284; PNG hashes agree: `335d3665dc96f83c3cfbf521c6df5b596a8f86c461d3b3c0af0f47c0d77463a6`.
- Existing genuine r7 Eevee raw image `jump_takeoff_r7/f0001.png` was inspected solely to check visible model feature/geometry correspondence. This is a Jump pose, not a mantle candidate. **It was not treated as an action-matched comparison with source n7284.**
- Aella source map at `fe5ab7cc6793a9fe2964fd9fc00d10e534e66ed8`, `references/movement/remaining_20261004/source_map.json`, was read. Its five declared half-open ranges have correct counts: [7284,7348)=64, [7787,7883)=96, [8507,8583)=76, [4028,4095)=67, [2241,2310)=69. This read and count audit does not certify every cut frame or overwrite the existing r7 paired 100-frame mapping.
- No source image/footage is included in this note or published by this review.

Source proposals:
- [Arithmetic](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5983371742)
- [Preliminary physical anchor coordinates](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5983509972)

## Concrete anchor disposition

1. **Physical muzzle: unsupported at baseline.** It is occluded in source n7284. Optic center is not a replacement for muzzle center.
2. **Rear sight / optic correspondence: rejected.** Source shows an optic; the inspected r7 model shows a different iron-sight arrangement. A convenient source optic or folded-sight point must not be equated to the candidate rear iron sight.
3. **Proposed charging-handle-right-ear feature: source-side diagnostic candidate only.** The visible aft protrusion near the supplied approximate (967,579) can be marked as an observed source feature with uncertainty, but these pixels alone do not certify the exact cross-model physical endpoint. In particular the handle/sight/receiver labeling and which physical corner is meant remain insufficiently resolved to freeze a homologous pair.
4. **Receiver left top edge near (775,609): not yet a unique hardpoint.** The description identifies an aft receiver region. A silhouette edge depends on projection and is not automatically the same 3D endpoint on two different models. Do not silently turn a region into a measured homologous corner.
5. **Receiver rail ridge near (862,556): not accepted as the third homologous landmark.** Repeated rail teeth/ridges and the different sight assembly leave the exact corresponding tooth/end plane unestablished. Merely selecting another noncollinear image point does not establish physical correspondence.
6. **L is not frozen.** Neither a hidden muzzle-to-receiver span nor an arbitrary separation of the three exploratory points is a validated common physical scale. Until corresponding physical endpoints are established, publish native pixels and frames with uncertainty. Image-width/height units, if shown, must be labeled display normalization and must not silently replace weapon-length L in scored tolerances.

This disposition does not claim that correspondence is impossible; it states which claims the inspected evidence currently supports. An author can resolve ambiguity by naming exact model mesh/surface/vertex features and marking the same source feature before examining candidate error. No inferred source point should be invented.

## Visibility finding

The aft receiver/handle features move out of the image around n7291–7292 in the inspected sequence. Aft features progressively return near the lower/right image region by n7302–7304 and are substantially readable at n7310.

Therefore a blanket statement that every proposed anchor is absent through n7305 is too broad for an exact shared mask. The inspected frames support **per-anchor masks and independent reseeding on return**, not a single shared disappearance interval. This is a bracketed visual finding; exact per-anchor visibility transitions require the source landmark owner to classify each intervening native frame.

No track may bridge disappearance by following background features. No hidden trajectory is established by entry and reappearance alone. The unobservable middle phase remains a critical gap for whole-event weapon-motion certification even if some aggregate sample count later exceeds 80%.

The initial +/-6 px coordinate estimates are uncertainty bounds, not subpixel truth. Carry endpoint uncertainty into displacement, angles and amplitudes; a small central-value angular residual is not a pass if its uncertainty crosses the tolerance.

## Arithmetic disposition

The explicit 60-point binary bookkeeping in the arithmetic proposal is internally reproducible as written and can be retained for future supported actions:
- Timing: 10 duration + 10 milestone clause.
- Translation: 10 XY RMS + 5 X amplitude + 5 Y amplitude.
- Angular: 7.5 axis RMS + 7.5 angular amplitude.
- Continuity: three clauses of 5/3 each (position boundary, axis boundary, explicit independent no-reset/velocity result).

Unsupported and inconclusive clauses earn zero in the fixed denominator. The simultaneous category floors imply:
- Both Timing clauses must pass to reach the 12-point category minimum.
- Both Angular clauses must pass to reach the 9-point minimum.
- Translation requires at least 15 actual earned points, given its discrete allocation.
- Continuity requires at least two of three clauses, totaling at least 10/3, to exceed the 3-point minimum.

Use exact rational arithmetic for 5/3 rather than rounding each clause before summation. A global numerical total does not override category gates, critical gaps or uncertainty. No conversion to Elara's independent scores is authorized; r6 remains 78 and r7 remains pending independent review.

**Current support ceiling:** without a supported homologous rigid axis, Angular 15 and axis-boundary Continuity 5/3 remain unsupported. Even granting every other clause for illustration, support cannot exceed 130/3 = 43 1/3 out of 60, below the required 48. This is a logical upper bound on support, not a measured score. Unfrozen L and other gaps may reduce actual support further.

## What can proceed now

Approved review scope for measurement-only diagnostics:
- Native source coordinates with explicit feature IDs and uncertainty.
- Visible-segment pixel displacement and baseline-relative recovery displacement.
- Native frame/PTS event timing with annotated source uncertainty.
- Per-anchor/per-phase source-visible/planned, candidate-valid/source-visible and total-comparable/planned counts, with all exclusions disclosed.
- Separate clearly labeled candidate diagnostics where physical correspondence has not been certified.

No overall percentage, orientation pass, hidden-motion fit, whole-event match or runtime completion follows from these diagnostics. Final per-action acceptance still requires a frozen homologous anchor/scale contract and observable critical phases. Missing evidence should stay unsupported rather than prolonging arbitrary score negotiation.
