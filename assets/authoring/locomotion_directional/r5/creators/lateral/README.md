# HIP lateral r5 creator candidate

Unscored local WIP responding to [Elara's r4 review](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5972182972). No repository, runtime, production source, gallery or reference-video bytes were changed by this lane. No render was performed. Future rendering must use genuine Eevee Viewport Render Animation; Cycles and regular offline render are excluded.

## Frozen source and new Actions

- Input: combined `halcyon_hip_directional_r4.blend`
- Input SHA-256: `d220162819fb7267aa6b93b209afc8ce5212a0692e6a4e02c5c43602b08907e3`
- Candidate: `halcyon_hip_lateral_r5.blend`
- Candidate SHA-256: `681ffd12e6390b8811b273a5130fe5c74bfe2690da180f9daeadebf610728e44`
- Blender 4.3.2; 80 Actions total, including all 78 original Actions
- Added only `hip_strafe_left_r5` and `hip_strafe_right_r5`
- Both are 49 unique frames at 60 fps, Action frames 1–50, with frame 50 repeating frame 1

Only the six root location/Euler curves are rebuilt in copied new Actions. All 769 non-root curves per Action remain exactly inherited. Meshes, gun, grip, cameras and old motion are untouched. The original active Action, raw pose, NLA and driver state are restored.

## Reference inspection and measurement limits

`inspection/left_r4_reference_sheet.jpg` and `right_r4_reference_sheet.jpg` show actual decoded reference pixels and genuine r3/r4 viewport frames using identical fixed crops. Left offsets inspected: 24,30,34,38,42,46. Right offsets: 12,18,24,34,42,46.

`timestamp_verification.json` checks every row of the reviewed r4 comparison maps, retaining the original mapping and no editorial phase change:

- Left reference `5KM0XSKxTWw`, raw [886,935). Local 0.50–0.70 s = Action 31–43 = raw 916–928
- Right reference `9RRgXvRx43s`, raw [361,410). Local 0.30/0.70 s = Action 19/43 = raw 379/403
- Existing right side peaks remain at offsets 17/37, 0.283/0.617 s. Existing broad dip plateaus cover both these peaks and the review timestamps

`reference_gap_analysis.json` quantifies the optical guide before changing poses. The old manually tracked reference landmarks and frozen scale are used consistently. These are different weapons/cameras, so the measurement does not recover reference 3D yaw, roll or depth.

Important limits:

- Left muzzle-to-receiver screen angle changes −8.2947° in the reference from 0.40→0.60 s; r4 changes −10.4092°. Thus this proxy does **not** identify a positive angle deficit. It cannot justify claiming a measured 3D gap was closed
- Right r4 cuff vertical range is 19.8761 px at native keys; the five-frame-smoothed reference cuff range under the inherited scale is 27.7801 px, a 7.9040 px relative shortfall
- Right muzzle/receiver ranges already exceed their corresponding scaled reference ranges. Fitting the cuff guide does not establish uniform silhouette agreement

## Left: bounded additional inward orientation

At the native-key plateau, add another 0.75° inward camera yaw and 2° inward camera roll beyond r4. The cumulative additions relative to r3 become 2° yaw and 4° roll. This is a bounded candidate following the requested direction, with the screen-angle caveat above explicitly retained.

The existing quintic envelope remains: rise offsets 26–33, plateau 33–42, return 42–48. Camera XY compensates to hold the visible cuff path. Pitch, depth, key times and the already-restored first-phase rightward travel remain unchanged.

480 Hz native results versus r4:

- Cuff X/Y deviation below 0.00464 px
- Muzzle motion through 0.40 s remains exactly unchanged
- Muzzle/cuff lateral extreme offsets remain unchanged
- Maximum additional leftward muzzle displacement: 4.386 px
- Cuff vertical range stays about 29.49 px
- Receiver vertical range grows 60.84→70.23 px as a rigid-pose consequence; this is disclosed, not scored

## Right: deeper existing dips

Add only camera-Y translation using the identical two r4 pulse envelopes. Solve the additional plateau amplitude needed to close the **relative cuff-range** shortfall under that existing pulse shape:

- Additional cuff dip at each plateau: 8.0318466539 px beyond r4
- Cumulative plateau addition over r3: 22.0318466539 px
- First rise/plateau/return offsets: 7–17 / 17–19 / 19–28
- Second: 29–37 / 37–42 / 42–49

Camera yaw/pitch/roll and depth remain r4. All screen-X paths and their extrema remain r4 within numerical precision. Actual native-key cuff range matches the 27.7801 px optical guide. The 480 Hz range is 27.9558 px because of interpolation between keys. Dense muzzle and receiver ranges become about 20.32 and 54.16 px; those different projection amplitudes are not represented as reference matches.

## Native preservation, grip and loop checks

`halcyon_hip_lateral_r5_authoring_preservation.json` records preservation of all 78 original Action fingerprints, eight NLA tracks, original active/NLA state, 185 drivers and packed textures. `validation/curve_contract.json` confirms all 769 inherited non-root curves remain exactly equal per new Action. Right root Euler evaluation remains exactly equal to r4 throughout the dense sweep.

`validation/native_validation.json` and `dense_constraint_comparison.json` include 393 samples per old/new Action at 480 Hz:

- Worst r5 wrist-target error: 7.157e-7 m, about 0.716 micrometers
- Guard angular errors: 0°
- No invalid drivers
- Root, weapon and both-hand repeated endpoint matrices: exactly equal
- Root endpoint curve values: exactly equal; Cycles modifiers retained
- Seam tangent float differences below 2.6e-8 per frame
- Right tracked lateral deviation below 0.00062 px

These are implementation checks. They do not give a visual score, guarantee every hidden mesh intersection, or establish runtime/export acceptance. Full old-evaluated-motion and structural preservation are independently checked by the integration lane.

## Reproduction

The portable authoring set is the frozen combined r4 BLEND, `directional_keyposes_r5_lateral.json`, `author_r5_lateral.py` and `source_integrity.py`. Creation checks the input hash and refuses an existing output path.

```sh
blender --background --factory-startup --disable-autoexec /path/to/halcyon_hip_directional_r4.blend \
  --python-exit-code 1 --python /path/to/author_r5_lateral.py -- \
  /path/to/directional_keyposes_r5_lateral.json /path/to/NEW_lateral_r5.blend
```

Regenerate design from the r4 lateral design JSON, with NumPy/SciPy:

```sh
python build_design_r5_lateral.py --baseline-dir /path/to/r4/lateral --output-dir /path/to/new/design
```

Validate without rendering:

```sh
blender --background --factory-startup --disable-autoexec /path/to/NEW_lateral_r5.blend \
  --python-exit-code 1 --python /path/to/validate_dense_r5_lateral.py -- /path/to/validation
blender --background --factory-startup --disable-autoexec /path/to/NEW_lateral_r5.blend \
  --python-exit-code 1 --python /path/to/verify_curve_contract.py -- /path/to/validation
```

`summarize_lateral_checks.py` writes the local constraint and timestamp report from this lane's CSV/design and the frozen r4 frame maps. Append only the two named r5 Actions into a clean combined r4 base; do not import other lane datablocks or active/NLA state.
