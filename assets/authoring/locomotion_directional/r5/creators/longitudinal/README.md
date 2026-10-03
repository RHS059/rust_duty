# HIP longitudinal r5: reference-measured source handoff

Unscored WIP for independent integration and visual review. Adds only `hip_walk_forward_r5` and `hip_walk_backward_r5`; all 78 previous Actions remain. No rendering, publication, commit or runtime edit was performed by this lane.

## Identity and review

- Input: combined r4, `halcyon_hip_directional_r4.blend`
- Input SHA-256: `d220162819fb7267aa6b93b209afc8ce5212a0692e6a4e02c5c43602b08907e3`
- Output: `halcyon_hip_longitudinal_r5.blend`
- Output SHA-256: `147541d32421e3e431946a9cf5a4209d6072bede97355238bd6180b2491fdae8`
- Blender 4.3.2; 60 fps; 80 Actions total
- Review: https://github.com/RHS059/dot_chat/pull/1#issuecomment-5972182972

## Evidence and choice of changes

Actual published r4 comparison frames were inspected at forward output frames 9/11/29/32 and backward 4/27/29/31. These show the original reference above the genuine Eevee Viewport Render Animation panel. Inspection images are under `inspection/`; they are not new renders.

`reference_gap_analysis.json` records the inherited raw reference trajectory, a five-frame quadratic periodic smoothing pass, the already-frozen native/reference motion scale, and measured ranges/angles before editing. There is no new registration, time warp, camera solve, or scoring function.

Forward's smoothed reference Y ranges under the frozen scale are 26.7227 / 52.1205 / 44.1713 px for muzzle / receiver / cuff. R4 has 25.2437 / 43.8011 / 30.4972 px. The review explicitly asks for approximately another tenth of reference depth, so r5 uses fixed additional low-point drops of 2.6723 / 5.2120 / 4.4171 px. It does not multiply r4 by another arbitrary gain.

Backward requires a more qualified interpretation. Its r4 vertical ranges already exceed the same frozen-scale reference ranges, so those nonmatching landmarks do not support another blanket vertical multiplier. The measured optical muzzle-to-receiver angle is clearer: r4 spans 6.9665°, while the smoothed reference spans 10.6014°, leaving a 3.6349° angular shortfall. R5 transfers this angular excursion amplitude while preserving the native angle phases. Additional muzzle/cuff depth is bounded to one tenth of the measured reference excursions, 0.9670 / 2.5795 px, with broader drop shoulders. These are different weapons and cameras; the silhouette-angle constraint is not recovered reference 3D roll or proof of visual equivalence.

## Exact changes

Only six location/Euler channels of `righthand_prop` vary in each new Action. Depth remains zero. The rest of the established ready pose, mesh, gun, grip, camera, NLA and prior motion are not edited.

### Forward

- Preserve every r4 muzzle/cuff lateral coordinate and all 38 native key times
- Let `t = (y - original_Y_min) / original_Y_range`. Add each anchor's fixed reference-derived drop multiplied by `t^3`
- Preserve original top positions and all vertical-extreme and lateral-extreme phases
- Muzzle Y range 25.2437 → 27.9159 px; receiver 43.8011 → 49.0131 px; cuff 30.4972 → 34.9143 px
- Solve all three Y plus both primary X constraints with bounded root translation/pitch/yaw/roll; receiver X changes by at most 0.151 px as a rigid-pose consequence

### Backward

- Preserve every r4 muzzle/cuff lateral coordinate and all 45 native key times
- Add the fixed extra primary drops weighted by `t*(2-t)`. This deepens and broadens the existing lower arc without shifting primary troughs
- Set screen barrel angle to `old_min + (reference_angle_range / old_angle_range)*(old_angle-old_min)`. Native angle extrema remain at Actions 2 and 32
- Muzzle Y range 28.1492 → 29.1162 px; cuff 34.0496 → 36.6291 px
- Measured screen angle range 6.9665° → 10.6014°. Native camera roll at the cuff trough changes by -2.6251°; its range changes from [-4.0757°, +2.4129°] to [-6.9111°, +2.4294°]
- Solve two primary X, two primary Y and the screen-angle constraint at zero depth. Receiver is not an independent control: its Y travel increases by up to 24.038 px, and X changes by up to 1.562 px. This coupled receiver motion is a specific item for visual review

Exact keys, control bounds and measurements are in `directional_keyposes_r5.json`, `motion_changes_r5.json` and the authored-root-key file.

## Timing and maps

All 166 r4 comparison-map rows were checked against source/reference frame identity:

- Forward: 38 unique frames; source 1–39 including repeated endpoint; reference `5KM0XSKxTWw` [48,86)
- Backward: 45 unique frames; source 1–46 including repeated endpoint; reference [211,256)
- Forward review approximately 0.15 / 0.48 s maps to output 9 / 29, Actions 10 / 30, reference 57 / 77; repeats at output 47 / 67
- Corrected backward review 0.45–0.48 s maps to output 27–29, Actions 28–30, reference 238–240; repeats at output 72–74
- Two-loop media must use `Action = 1 + output % N`, `reference = core_start + output % N`, without displaying the repeated endpoint as an extra frame

There is no editorial retiming, new reference offset, camera/crop change, or moved native key. The r4 backward timestamp ambiguity is resolved by the corrected r5 review.

## Native validation

Creation checks 78 old Action curve fingerprints, 8 NLA tracks/active state, 185 drivers and packed-image hashes, restoring original raw-pose and frame state before saving. Fresh read-only native evaluation covers 666 samples over new Actions at 480 Hz, plus both retained r4 Actions.

- Maximum wrist-target error: 7.166e-7 m (about 0.72 micrometers)
- Guard angular error: 0°; no invalid drivers
- Root, weapon and both hands have exactly equal repeated-endpoint matrices
- Retained r4 projected tracks match prior r4 evidence exactly: 0 px difference
- Native keys match authored design within 0.000655 px
- Forward preserved-X error at 480 Hz: under 0.001526 px; nonlinear Y-map interpolation residual: under 0.03766 px
- Backward preserved-X error: under 0.001069 px; primary Y-map residual: under 0.001622 px; screen-angle constraint error: under 0.000229°
- Only six root channels vary in each new Action. Root endpoint values are exact; free-handle endpoint-tangent discrepancy is below 2.57e-8

Primary vertical-extreme phase sets remain unchanged at a 0.002 px numerical-tie tolerance. The pre-existing backward cuff high position ties at native offsets 4/5 and primary X peaks tie at 26/34; float rounding can choose either raw argmin/argmax. These are recorded honestly rather than interpreted as retiming. The receiver is a coupled consequence: its backward upper Y extremum changes from offset 4 to 3; its dense low changes from Action 31.25 to 31.375. Primary troughs and the constrained screen-angle extrema retain their phases.

These checks do not assign visual acceptance, establish runtime/export acceptance, or certify every hidden intersection. Independent full source and prior-motion evaluation belongs to integration. New visual previews must use actual Eevee Viewport Render Animation; Cycles is forbidden.

## Reproduction

Portable creation set: `author_r5.py`, `source_integrity.py`, `directional_keyposes_r5.json`, and the frozen combined r4. The author checks the input hash and refuses to overwrite an existing output.

```
blender --background --factory-startup --disable-autoexec /path/to/halcyon_hip_directional_r4.blend \
  --python /path/to/author_r5.py -- \
  /path/to/directional_keyposes_r5.json /path/to/NEW_OUTPUT.blend
```

To regenerate the design and evidence-derived parameters:

```
python build_design_r5.py --baseline-dir /path/to/r4/longitudinal \
  --maps-dir /path/to/r4/render/publication --output-dir /path/to/new/design
```

To validate without rendering:

```
blender --background --factory-startup --disable-autoexec /path/to/NEW_OUTPUT.blend \
  --python validate_motion_r5.py -- /path/to/validation
python summarize_validation_r5.py
```

The summary script expects this lane layout and the existing r4 dense-evidence path. Scripts, source identity and numeric deliverables are pinned by the package manifest/checksums.
