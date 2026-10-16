# One-hand mantle r3: technical correction, visual review pending

Status: **diagnostic**. This repairs the explicit r2 technical failures, without
promoting the motion to visual/contact approval or changing the frozen low-vault
candidate. No render, export, runtime hookup or canonical source replacement.

Source `candidate/aella_mantle_onehand_r3.blend`, SHA-256
`f289c6d404a6c9c276baac3089887f77a15ac2d18029e1aa39f66d6e335081df`.
Action `aella_mantle_onehand_r3`, native R3 [7787,7883), Blender 1–96 at 60 fps.
The r2 input is preserved exactly, with all 86 prior Actions unchanged. One new
Action makes 87. Older low-vault, one-hand and source rig data remain untouched.

## Bounded fix and preservation

R2 left a 0.596-degree attached guard residual near native 7806.375. The only
spatial-key change is an additional 0.004 m of shoulder pose-space Y at native
7806, within the existing 0.06 m per-axis hypothesis. No guard is widened.
The inverse-compensation solver now performs up to ten iterations, stopping
on target tolerance, instead of always stopping after three. It repairs the
r2 intended-target residual of 0.641 mm. Neither change alters weapon motion,
source timing, visible event brackets or any older Action.

Source observations and their uncertainty are in
`../onehand_r2/source_observations.json`. Visible opening at 7830–7831 does not
establish the first physical release in an earlier occluded interface.
Separation is clear by 7834–7836 and regrip appears at 7873–7874. Hidden hand
path, depth and shoulder motion remain authored hypotheses.

## Fresh saved-source evidence

- 1,533 evaluated times, including 960 Hz and endpoint neighborhoods
- 3,899,154 evaluated skin vertices, all finite; all drivers valid
- Exact sampled weapon-matrix equality with the r1 weapon hypothesis
- Maximum actual wrist-to-rig-target error: 0.000796 mm
- Fully attached guard residual: 0 degrees; minimum free-wrist margin: 6.45 degrees
- No measured endpoint ownership position/orientation discontinuity
- Maximum intended-target compensation residual: 0.000152 mm
- All 86 older Action fingerprints and source structure/drivers/NLA preserved

Seven report-gate tests include the actual failed r2 guard and intended-target
reports, source-hash mismatch, weapon drift, missing dense samples and a broken
switch control. Passing numerical checks does not establish surface contact,
physical realism, reference fidelity, artistic acceptance or game behavior.

Use Blender 4.3.2, factory startup and disabled auto-execution. In a source-only
copy without generated outputs, run `author_onehand.py` on the exact r2 input.
Reopen the saved r3 BLEND with `verify_onehand.py --output NEW_REPORT.json`.
Run `python -m unittest discover -s assets/authoring/mantle/onehand_r3 -p 'test_*.py'`.
The author refuses to overwrite an existing source output.
