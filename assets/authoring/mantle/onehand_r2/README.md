# One-hand mantle: diagnostic r2, failed guard gate

Status: **diagnostic; attached-wrist guard check fails**. The WIP is preserved
for review and correction. No visual, hand-surface, export or runtime approval.

Candidate `candidate/aella_mantle_onehand_r2.blend`, SHA-256
`11502d04b39758faa4c11d312e8d55d777b7119b5a88ca491dd27bfa3546f6f8`.
Action `aella_mantle_onehand_r2`, 96 frames at 60 fps, native R3 [7787,7883).
It extends the frozen low-vault source, preserving all 85 prior Actions and
adding one for 86 total. The separate low-vault BLEND is unchanged. Neither
source replaces the canonical Jump or Prone rig.

## Evidence and bounded change

Native-pixel review found visible finger opening at 7830–7831, unambiguous
separation by 7834–7836, return at 7870–7872 and wrapped regrip at 7873–7874.
The earlier low-framing interval does not establish first physical release or
hidden contact. In particular, 7840–7844 does not show regrip: the open support
hand is visibly left of the rifle and then leaves the frame.
`source_observations.json` records the independently inspected frame hashes,
PTS and uncertainty. No candidate registration or percentage is approved.

The old Action retained its support grip and clipped the wrist guard by up to
22.53 degrees. This revision adds compensated ownership fades, open fingers,
a free-hand path and regrip. A single bounded existing shoulder-control family
(maximum 0.06 m on each of pose-space Y/Z) changes the arm plane during the
attached lead-in. No rest, driver, constraint, guard, inverse, camera, material
or mesh is changed. All older Actions and weapon curves remain unchanged.
Depth, hidden trajectory and shoulder movement are authoring hypotheses.

## Fresh saved-source results

- 1,533 evaluated times, including 960 Hz and near-endpoint samples
- 3,899,154 full-skin vertex samples, all finite; all drivers valid
- Exact equality of sampled weapon matrices against r1
- Actual wrist-to-rig-target residual below 0.000808 mm
- Free wrist margin at least 6.45 degrees
- No measured position/orientation discontinuity across the sampled ownership endpoints
- Attached guard residual improves to 0.596 degrees but **fails** the 0.1-degree gate near native 7806.375
- The authoring inverse-compensation solver's intended-target residual reaches 0.641 mm after three iterations; this is separate from the much smaller evaluated wrist-to-rig-target residual

The next revision must repair the early shoulder interpolation and tighten the
bounded compensation solve. It must not widen guards or weaken rejection.
Full visible pose, silhouette, finger contact and trajectory remain unreviewed.
No render was attempted for this one-hand source.

## Reproduce

Use Blender 4.3.2, factory startup, disabled auto-execution, and a fresh output
directory. Run `author_onehand.py` on the pinned low-vault r2 input. Then reopen
the saved one-hand BLEND and run `verify_onehand.py --output NEW_REPORT.json`.
The verifier writes evidence before exiting with code 2 for the failed guard.
`report_contract.py` contains the same technical gates, not artistic criteria.
