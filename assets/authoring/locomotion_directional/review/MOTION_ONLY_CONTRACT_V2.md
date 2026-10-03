# Shared visible-motion contract v2

Declared 2026-10-03 before scoring candidate v02 or later. This is a new, explicitly bounded task-aligned motion assessment, not a revision that makes the original pose-equivalence rubric pass.

## Scope and immutable earlier result

The supplied task clarification is: “yes it's a shotgun but the animations are the same.” Transfer the visible first-person motion to the native HK416 and native hands. The original 100-point rubric and its mean-pose failure remain unchanged; fixed shotgun/HK416 geometry and grip spacing are not claimed equivalent. No anatomy, rest-pose, exporter, or camera changes are authorized by this review. Runtime integration remains Aella-owned and pending.

Reference hand landmark is the visible cuff/glove boundary region, not a recovered anatomical wrist. The firing-side wrist is offscreen and unobservable. Candidate anatomical wrist/bone points are contact guards, not proof of identical visible glove shape. Candidate contact must also be inspected from side and underside witness views.

## Frozen measurements and alignment

- All original primary/secondary source windows and exact PTS remain in the v1 measurement contract. Source quality masks remain visible, including known R1 muzzle tracking failures; no exclusion based on candidate error
- Review source at native 60/1 fps, PTS=n*256 and time base1/15360. Evaluate every third source frame (20Hz) over whole declared comparable windows; native60Hz for joins; higher-rate numeric guard sweeps are supplemental
- One fixed geometry projection scale per Action, frozen before v02: native muzzle–receiver baseline span251.69886001289618px divided by selected source span. Forward0.9865965134, backward0.8525310028, left0.9848832627, right0.8887616481. Do not revise scales to improve scores
- Translational trajectories may remove one constant mean per homologous landmark because fixed geometry is explicitly outside this new contract. They may not remove trends, drift, amplitude, or directional differences; no per-frame spatial registration
- Angular trajectory may remove one constant mean weapon-axis angle. Retain its waveform, amplitude, orientation, extrema, and phase; do not mirror or rotate each frame
- Exactly one constant phase offset per entire source window, shared by every landmark and the angular trace. No retiming or phase warping
- Use original visible-axis length L for tolerances and show pixels too. L is median projected muzzle→receiver axis length extended to its clipped rear boundary at viewport bottom, not physical weapon length
- Source cycle estimates remain forward38f, backward45f, left49f, right48–49f. A different observed full-cycle start is allowed before the next candidate is authored, must remain in the same predeclared steady window, and must be versioned with exact frames/PTS. No amplitude multipliers are inferred from desired pass rates

## Motion-only rubric: 60 supported points maximum

The original motion weights are retained, not newly tuned. Score is earned/supported points out of this60-point visible-motion scope. An80% result means at least48/60 motion points when all60 are supported; it does not mean80/100 pose fidelity or whole-body equivalence.

1. Timing/cadence:20 points
   -10: measured full-cycle duration differs by≤10%
   -10: after the single shared phase alignment, unambiguous source extrema are within10% of a reference cycle. Record ambiguous/near-flat extrema as unsupported, not passes
2. Translational sway:20 points
   -10: mean-centered XY vector RMS error≤0.06L, over all usable landmark samples
   -5: each usable landmark's horizontal peak-to-peak amplitude error≤max(20% of reference amplitude,0.02L)
   -5: each usable landmark's vertical peak-to-peak amplitude error≤max(20% of reference amplitude,0.02L)
3. Angular motion:15 points
   -7.5: mean-centered screen-axis angular trajectory RMS error≤5°
   -7.5: angular peak-to-peak amplitude error≤max(20% of reference amplitude,2°)
   - Correct directional sway orientation is a hard gate; no mirroring
4. Local loop continuity:5 points
   -1.6667: actual wrap landmark displacement≤0.03L
   -1.6667: actual wrap axis displacement≤3°
   -1.6666: no one-frame reset or anomalous join velocity relative to interior native-frame motion, confirmed in dense pixels and numeric traces

Category passes require≥60% of supported category points. Overall motion pass requires≥80% of supported points,≥80% of the60-point motion rubric supportable,≥80% usable comparable landmark-sample coverage for each Action, and all hard gates. Fractional points only arise from the predeclared clauses above; do not invent a subjective percentage.

## Source comparability and evidence limits

Primary R2 forward/backward/left are the primary scored windows; R1 remains a secondary cross-check with explicit pixel uncertainty. Publish both window results and any contradictory supported clause. A clean primary pass does not erase a clear secondary failure. Do not assign an overall motion pass when a well-supported secondary metric contradicts it; either repair or report the limit.

R2 right [720,786) was found during source-only native tracking to include carry settling and no reliable full-cycle return. Preserve it as a held-out direction/settling diagnostic. Periodic right-loop cadence/waveform is assessed on R1 [330,450); its exact selected authoring cycle is [375,424]. Do not score the R2 settling envelope as periodic sway, or claim that it passed. Report the R2 excluded periodic evidence separately and the source limitation explicitly.

Secondary muzzle/receiver tracks carry approximately10px visual/tracking uncertainty. A threshold crossing within that uncertainty is inconclusive, not pass or fail. Cuff/glove tracking is approximately5px. Primary muzzle/receiver estimates are approximately3px. These are visual review estimates, not statistical confidence intervals. Failed tracker samples remain masked as declared in the v1 contract.

## Contact and runtime hard gates

Visible support-hand contact and native attachment guards must remain stable throughout all four Actions and joins. Require side and underside candidate witness renders at phase extrema; no hand separation, clipping through the grip, wrist flip, or sudden reach. Invisible firing-hand placement cannot be scored against the source, but candidate native contact integrity still must be checked.

All four Actions need their own results. Source-only approval is never runtime approval. Wrong clip selection, idle insertion while moving, broken reversal, ADS misalignment, or changed canonical export semantics remain hard integration failures. Aella must verify them after named-Action integration at30 and60fps. Runtime transition points are not silently awarded here.

### Surface-anchor freeze before refit

The candidate homologous cuff anchor is the visible upper black glove/cuff lip at native baseline pixel [663,491], object `Actual arms mesh 0`, evaluated face8743, triangle vertices[5681,5679,5666], using the raycast's immutable barycentric weights. The earlier [655,515] proposal hits bare forearm and was rejected before refit/scoring. Candidate field `support_cuff_surface` replaces anatomical `support_wrist` only for visible-motion comparison; bone-head wrist tracks remain contact guards. The source CSV's legacy `support_wrist` columns mean visible cuff/glove boundary, not recovered anatomy. No firing-wrist reference track exists.

### Extrema implementation frozen before surface-anchor candidate scoring

Only for finding extrema, use a5-native-frame quadratic Savitzky–Golay filter, prominence max(3px,25% of channel peak-to-peak), and minimum peak separation25% of cycle. Skip channels below0.02L peak-to-peak and extrema within12% of a cycle of a source-window edge or declared tracking failures. Compare each remaining source maximum/minimum to the nearest same-kind candidate extremum at the already-fixed shared phase. All supported extrema must lie within10% of cycle for the timing-extrema clause. Report individual errors and fraction within tolerance, including failures. Neither amplitude nor RMS scoring uses this peak-localization filter.
