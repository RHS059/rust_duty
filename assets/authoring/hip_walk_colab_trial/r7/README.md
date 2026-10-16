# PR41 forward/backward r7 total-roll diagnostic

Status: **diagnostic, numerical PASS; native visual review pending**. Six profile
tests passed, and the separate candidate was saved and reopened in Blender 4.3.2.
All numerical checks passed across 1,332 samples at 480 Hz. All 86 original Actions,
source bytes, camera, rig, weights, materials and protected object defaults remain
unchanged. Both wrist guards report zero error, source-relative attachments pass,
and root/weapon/hand closure errors are exactly zero.

Backward's internal receiver seam is 2.00004 px, improved from r5's 4.60026 px.
Forward's corresponding seam is exactly preserved. These are internal witness
measurements; they do not approve the rendered mask-centroid seam or visual match.

Private local candidate SHA-256:
`93bc53dc981b9643cb1e398c051c6254e0853ba15de054976aa86bdbd0fa717a`.
The BLEND contains 88 Actions and has not been uploaded, rendered or activated.
See `validation_summary.json` for exact checks and `native_frame_maps.json` for timing.

## Changes from rejected r6

- Forward peak correction: 28.0 to 27.7 px at f8. The r6 cubic output reached
  28.2362 px at f8.25, above a self-imposed numerical bound. Elara clarified that
  this 0.24 px excess is visually immaterial and the pixel guidance is not a cap.
  This small adjustment leaves the meaningful beats and exact seam keys intact.
- Backward roll now targets a TOTAL -6 degrees early / +6 degrees at f30–34,
  subtracting the r5 contribution. Elara's 2026-10-14 02:06 clarification explicitly
  rejected interpreting this as another +/-6-degree addition (Discord message
  1559749159958085683). The earlier proposed +3-degree incremental cap was superseded
  before execution. The original translation beats and seam repair remain.
- No anatomy guard, constraint, driver, rest bone, skin weight, camera or original
  Action is changed. No elbow/pole or additional control family is introduced.
- The five-setting wrist-twist probe is rejected: its best tested worst guard
  error was 2.8289 degrees near f32. No broader numerical search is planned.

Rejected r6 code and evidence: `RHS059/rust_duty@499f205f095c5ab4d47be1459a69a591944edc98`,
`assets/authoring/hip_walk_colab_trial/r6/`.
Original review: https://github.com/RHS059/rust_duty/pull/41#issuecomment-6158919419

## Immutable source and new Actions

Use `RHS059/rust_duty@6a1c145ca63143e99bbf694a76f9d19bd31becf5`,
`assets/authoring/hip_walk_colab_trial/v1/hip_four_walks_colab_visual_v1.blend`.
SHA-256: `f7d6e76d387a07508f61b2ade708fa930b93bd73b167110469a43c88ecf8eaf4`.
Copy the retained `hip_walk_forward_r5` and `hip_walk_backward_r5` Actions directly.
Output Actions are `hip_walk_forward_elara_r7` and `hip_walk_backward_elara_r7`.
All 86 preexisting Actions remain unchanged beside the two new Actions.

Forward has 38 unique 60 fps frames, R2 source `[48,86)`, with f39/source86 an
excluded closure witness. Backward has 45 unique frames, R2 `[211,256)`, with
f46/source256 an excluded closure witness. Source R2 SHA-256 is
`cff413d8d114b611bbe6f50cc553ef109d61eb8eb1fff960425f506b84d6767e`.
Use the exact saved 1280×720 `RD First Person Review` camera and unchanged timing.

## Checks and limitations

Run six pure-Python profile tests, then author a separate private local BLEND,
then reopen it in a fresh Blender 4.3.2 process for 1,332 samples at 480 Hz.
The verifier checks source fingerprints, complete protected key/handle records,
object defaults, fixed projection, source-relative hand and actor attachments,
wrist guards, dense pixel/depth/roll bounds, native drivers and exact loop closure.
Every change is root-only: location curves for forward, location plus rotation
curves for backward. The source remains unchanged and is never overwritten.

The source's camera-relative root roll is measured from the preserved canonical
ready Action, using the same Rx(pitch) @ Ry(yaw) @ Rz(roll) decomposition as r5.
The author analytically solves only the required camera-Z correction, accounting
for the fact that it is left-applied to existing pitch/yaw; it does not naively add
or subtract Euler components as if the rotations commuted.
The dense verifier tests the total authoring profile within 0.05 degrees. This
is an internal authoring witness, not a claim that a mask-edge fit has the same
angle; only the native preview establishes the total rendered roll. Grip takes
priority, and Elara explicitly permits a reduced rendered late peak if necessary.
The independent maximum incremental correction is conservatively capped at
6 degrees; that fail-closed cap is distinct from the +/-6-degree total target.
The verifier independently rebuilds the reference Action's frame1 root witness.

Displacements are calibrated at an internal native receiver point. Elara's source
receiver and native weapon mask centroid are different physical metrics; a numeric
pass cannot establish rendered amplitude, the <=3 px mask-centroid seam, anatomy,
visual improvement, FBX parity or game acceptance. Any rendered roll residual must
remain explicit even if numerical checks pass.

Only genuine foreground Eevee viewport previews may be rendered. Root coordinates
capture and publication. Inspect the whole loops, first/last joins, both hand grips,
forward f8 lateral peak and two dips, backward two dips/rise and remaining roll.
Elara owns the final visual verdict. Keep r5 as baseline while review is pending.

## Reproduction after the coordinator releases compute

1. `python -m unittest -v test_correction_profiles.py`
2. `blender --background --threads 1 --disable-autoexec --python-exit-code 1 SOURCE.blend --python author_walk_r7.py -- output`
3. `blender --background --threads 1 --disable-autoexec --python-exit-code 1 output/hip_longitudinal_elara_r7.blend --python verify_walk_r7.py -- output`

Publish only original code/tests/docs and summarized evidence. The generated BLEND
contains supplied private assets and is excluded from upload. Neither an accepted
save nor these numerical checks implies runtime activation or approval.
