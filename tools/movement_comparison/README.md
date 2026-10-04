# Weapon motion comparison (measurement-only)

Original bounded CPU diagnostics for one named action at a time. Does not track
points, fit a camera, render Blender, retime a clip, or produce an approval score.
The event amendment remains proposed; Elara's independent Jump r6 78 assessment
and r7 pending status are not replaced by these measurements.

Run from the repository root:

```sh
python3 -m unittest discover -s tools/movement_comparison/tests -v
python3 tools/movement_comparison/compare.py tools/movement_comparison/example.synthetic.json --output /tmp/weapon-comparison-demo --plot
python3 tools/movement_comparison/build_notebook.py
```

The synthetic example is a schema illustration only, never game/reference
validation. The CLI uses only Python standard library; `--plot` requires
Matplotlib. No CUDA allocation is justified for these small landmark arrays.

## Input contract v1

See `example.synthetic.json` for the complete executable example. Supply original
camera pixel coordinates; top-left origin, X right, Y down. Candidate points must
be evaluated camera projections of the exact physically identified rigid weapon
anchors, not bone-local points. Three anchors minimum; declare muzzle-to-receiver
axis and a third noncollinear rigid anchor. Cuff/wrist observations belong in a
separate contact review, never an equivalent weapon landmark.

- `source.artifact` and `candidate.artifact`: name and SHA256 of original source
  media and exact candidate artifact. Hashes are only declared until matching
  bytes are independently supplied to `compare(doc, supplied_artifacts)`.
- `source.time_base`: exact rational `[numerator, denominator]`; `window_frames`
  is `[inclusive_start, exclusive_end]`. Use observed decoded PTS, not a guessed
  CFR conversion. Every native source frame in the window must appear once.
- `registration`: only the exact keys in the example are accepted. Preserve
  original pixels. One frozen scalar per side applies to diagnostic calculations,
  and one common exact time offset applies to all landmarks and events.
  `candidate_time = (source_pts - source_anchor_pts) * time_base +
  candidate_anchor_time + phase_offset`. Speed is exactly 1. No interpolation,
  best-phase search, per-frame fitting, camera change or nonlinear warp occurs.
  `frozen_record` identifies a pre-candidate agreement; software cannot establish
  its authorship/timing. Review that record before accepting any result.
- `normalization.L_px`: one reference visible-axis length in the same fixed
  comparison-pixel scale; record its derivation in `definition`. Never normalize
  each frame independently or alter the frozen geometry scale after inspecting
  residuals. `baseline_frame` is a frozen observable pre-event frame.
- `metrics_stride`: freeze before comparison (existing loop contract uses 3
  native 60 Hz frames for 20 Hz metrics); all native rows are still checked for
  visibility and adjacent steps. Do not change stride to avoid a failure.
- `samples`: exact frame, observed PTS, exact rational candidate evaluation time,
  and every declared landmark on both sides. Each point needs `state` and
  `method`. States: `visible`, `occluded`, `tracker_failed`, `uncertain`,
  `out_of_frame`, `missing`. Visible points additionally require `xy` and a
  conservative `uncertainty_px` bound. Optional model `confidence` is separate
  from observability. An interpolated or inferred hidden point is not visible.
- `events`: names and visible definitions, inclusive source frame uncertainty
  intervals and candidate exact-time uncertainty intervals (or null). These are
  visible-motion events, not inferred button presses. Metrics report the entire
  phase-error interval, with no unapproved duration/milestone pass score.

Weapon dropout during vehicle-roof climbing must remain unobservable. Hidden
continuation cannot count as comparable evidence. Missing candidate visibility
when a source point is visible is reported as a hard-gate finding even between
metric sample frames. Low support never shrinks an approval denominator.

## Outputs and limits

JSON retains input/code hashes, declarations versus byte verification, original
registration, all visibility counts, per-landmark comparable coverage, raw and
mean-centered RMS/p95/max errors, constant removed means, amplitude discrepancies,
fixed-baseline displacement residuals, unwrapped axis traces and angle error,
event timing intervals, native adjacent-step/speed witnesses, third-anchor signed
areas, and the worst exact frames. The optional plot shows raw and centered
residuals together. Mean centering is diagnostic; baseline displacement retains
landing depth/recovery drift. No event duration, loop closure or input response
is inferred from the window length.

Point uncertainty propagates conservatively through residuals and uncertain
means. Threshold boundaries inside or touching annotation uncertainty are
inconclusive. Bounds are visual estimates, not confidence intervals. Degenerate
axes are unsupported. Angle unwrapping assumes less than 180-degree true motion
between observed samples; gaps and large motion require human review.

Current spatial diagnostic limits come from the frozen locomotion motion-only v2
contract: XY RMS `0.06 L`, per-axis amplitude error `max(20% of reference, 0.02 L)`,
axis RMS 5 degrees, angular amplitude `max(20%, 2 degrees)`. These diagnostic
comparisons do not approve the proposed event rubric. A whole clip normal/slow
independent visual review, visible direction/contact/visibility checks, and any
changed export/runtime boundary checks remain separate.

The parser checks the submitted frame/PTS mapping's internal consistency. It
cannot certify that declared PTS values, physical correspondences or annotations
came from the stated video without the independent decoded-PTS map and pixel
witnesses. Do not report declared provenance as verified source evidence.

Optional `--pts-map observed-ffprobe-frames.json` checks every source frame index
and integer PTS against the independently supplied map. If time_base or
source_sha256 metadata is supplied, mismatches are rejected. Absent metadata
remains unverified; matching PTS counts does not certify video bytes or pixels.
Optional `phases` contains uniquely named half-open window_frames; reports all
three native coverage ratios and gaps per phase without collapsing hidden motion.

`normalization.L_px` may be null when the physical reference axis is hidden or
not frozen. Raw, centered and baseline measurements remain available while all
L-dependent threshold comparisons are explicitly unsupported. No replacement
length is inferred from another body part, sight or desired result.
