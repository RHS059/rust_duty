# One-hand mantle r4: original-source correction WIP

Status: **diagnostic, failed technical guard check, unrendered**. This is the
first retained revision for PR35's one-hand correction. It is published as WIP
rather than withheld while the next correction is prepared. No merge requested.

The current local candidate has SHA-256
`f6d8cf85c065f703cfd7d480303568fad3ebba5246fc3068600f4804f3d703bb`,
Action `aella_mantle_onehand_r4`. It retains all 87 prior Actions and adds one.
It uses the unchanged 96-frame R3 [7787,7883) mapping at 60/1 fps.

## What changed

- A copied Action changes the weapon root inside f8–85 using the actual mesh's
  measured muzzle slice, the original perspective camera and a bounded two-ray
  depth solve. It changes neither source mesh nor camera to win the comparison.
- The support hand follows the weapon, releases on f44–48, and continuously
  returns over f58–65. Attachment is complete at f65 and stays continuous.
- Weapon/camera are protected on f85–96. Reviewer-confirmed interpretation
  permits support recovery through f88 and protects the complete f89–96 hold.
- Existing Actions, rests, geometry, weights, constraints, guards, drivers,
  material data and NLA are preserved. No low-vault, runtime or export edits.

Review basis: [Elara's onehand-r3 review](https://github.com/RHS059/rust_duty/pull/35#issuecomment-6158919317).
The original raw 1280x720 reference pixels were inspected at explicit native
frames. The receiver-axis targets are approximate functional landmarks on
different weapon geometry, not claimed exact correspondences. Broad contour,
motion and visible contact still require genuine Eevee review by Elara.

## Actual checks

Nine pure contract tests passed. Fresh saved-BLEND reopen evaluated 1,563 times
and 3,899,154 skin vertices. All evaluated bones/skin are finite; drivers are
valid. Prior Action and structural preservation passed. Protected full-pose
matrix delta is at most 7.75e-7; protected weapon delta is at most 5.97e-8.
The support follow is exactly 1 at f65. Maximum wrist-to-rig-target error is
0.000508 mm, and the sampled ownership boundaries have no detected jump.

**Failure:** the attached left wrist guard clips up to 22.753 degrees at
f35.375, within f20–44. This is not acceptable contact. The inherited r3
shoulder correction was fitted to the old weapon path, so the next bounded
diagnostic tests its removal/limited adjustment without changing any guard.
The initial f8–16 blending also still leaves f11 low and must be shortened or
reframed on the same source beats. Numerical projection is not visual approval.

No new render, export, game hookup or runtime validation has been performed.
The current BLEND and its private mesh/rig/texture contents are not in this
publication. `evaluation_summary.json` records both passed and failed gates.

## Reproduce locally

Requirements: Blender 4.3.2; exact local r3 BLEND whose SHA-256 is
`f289c6d404a6c9c276baac3089887f77a15ac2d18029e1aa39f66d6e335081df`;
the sibling repository `assets/authoring/locomotion_directional/r5` integrity
helpers. Never execute embedded source text or enable auto-execution.

Run `author_correction.py` with Blender background, factory startup, disabled
autoexec and one thread. Arguments: `--output LOCAL_CANDIDATE.blend` and
`--integrity-dir PATH_TO_R5_HELPERS`. It refuses to overwrite an output.
Then reopen that exact BLEND with `verify_correction.py`, passing `--output
LOCAL_REPORT.json`, `--authoring-dir OUTPUT_PARENT` and the same integrity dir.
Run `python -m unittest discover -s assets/authoring/mantle/onehand_r4 -p
'test_*.py'`. A failing numerical check exits nonzero and still leaves its
honest report. Foreground Eevee viewport capture is a separate required step.
