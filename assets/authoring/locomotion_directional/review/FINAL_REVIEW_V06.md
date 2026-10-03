# Final independent hip-loop review: v06

Source SHA256: `6d6d5c6a150bd8d74f24b29bf18b192e2f5fe2cd93a531c77b7a1e5ce93a8b35`

## Result

Ready as a bounded WIP source handoff; no all-four full-window80% match or runtime approval is claimed.

All four clean periodic cores pass amplitude, centered angular-motion, visible contact, and local-loop continuity checks. Forward, left and right pass every clause of the narrow60-point motion-only core rubric. Backward has one unresolved flat-peak timing clause, retained as a failed detector check with inconclusive source timing evidence.

| Action | Exact reference core | XY motion RMS | Angular RMS | Core points | Decision |
|---|---|---:|---:|---:|---|
| Forward | R2[48,86),38f |5.29px|0.47°|60/60|Pass, narrow core only|
| Backward | R2[211,256),45f |1.15px|0.29°|50/60|Inconclusive timing; no formal pass|
| Left | R2[886,935),49f |1.05px|0.63°|60/60|Pass, narrow core only|
| Right | R1[361,410),49f |1.14px|0.17°|60/60|Pass, narrow core only|

These are in-sample reference/authoring-core motion scores, not percentages of overall animation quality or pose equivalence. All core comparable sample coverage is100% across the three visible homologous regions. The firing wrist is unobservable. Sourcefps60/1; timebase1/15360; PTS=n×256. The exact numeric reports preserve scales, phase, source coordinates, uncertainty and every clause.

Backward has50/60 motion points supportable, with10 timing points inconclusive; the original60-point denominator is conservatively retained rather than claiming50/50. Backward's conservative50/60 is83.33%, but its timing category is10/20, below the required60% category minimum. The flagged source muzzle-X maximum at raw245 is8frames from the detector's candidate maximum. Original sourceframes236–246 are nearly flat at703–704px, only1px of variation versus approximately3px localization uncertainty. We did not change thresholds, erase the failure, award posthoc points, or force a distorted animation to chase an unresolvable peak.

## What was checked

- Original source footage at every third raw frame over all declared windows, with all60Hz numerical tracks retained
-185 final native front renders available;66 reviewed dense20Hz/end-point samples, plus actual native loop-seam views
-32 side/underside witness renders at cuff-XY extrema, with stable native grip/contact and no observed detachment, sudden reach, wrist flip or pose reset
- Exact projected endpoint errors0px for every tracked region in every Action
- Native wrap maximum displacement6.51px and axis step0.757°, within declared bounds; wrap movement consistent with ordinary interior movement
- Author480Hz guards report maximum wrist error below0.0000007m, zero guard-angle clipping, and stable relative hand/root matrices; independent source/export preservation is the integrator's separate gate

The visible source hand anchor is the cuff/glove boundary region, not a recovered anatomical wrist. The candidate uses the frozen real mesh-surface triangle at baseline pixel[663,491]. Bone-head wrist points remain contact guards only.

## Preserved failures and runtime handoff

The original pose-equivalence failure remains intact: shotgun/HK416 geometry and hand spacing cannot be made equivalent through one honest static registration. No anatomy/rest-pose/camera change was made to fake that result.

The earlier full-window v2 measurements remain unchanged in `candidate_v04_motion_v2_metrics.json`, and final v06 full-window diagnostics are also supplied. Source drift/settling and secondary uncertainty mean the complete original windows have not passed. The right clean core has approximately8px muzzle-Y motion versus25px across the initial fullR1window. A repeated loop must not contain that entire settling envelope.

Aella owns blend_in/loop/blend_out integration, direction/carry settling, original-window envelope comparisons,30/60fps start/stop/tap/reversal/diagonal tests, ADS motion/alignment, selected clip identity and production exports. Source input onset is hidden, so video transition times must not be asserted as exact keypress times. This report does not certify those pending runtime gates.

All third-party footage and derived reference pixels remain local. `public_numeric/` contains only text, numerical data and a local-only measurement reproduction script.
