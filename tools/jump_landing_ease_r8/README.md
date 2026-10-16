# Jump r8: bounded two-key landing correction (WIP)

This is a text/code preservation checkpoint for a diagnostic candidate related
to [Jump PR20](https://github.com/RHS059/rust_duty/pull/20). It adds no animation
asset or game-runtime binding. Elara's visual approval is still required before
integration. Numerical checks are not artistic approval.

The original authoring script is preserved byte-for-byte. A small entry wrapper
checks all pinned local inputs and exclusively claims a new output directory. The
reopen verifier has portable command-line paths; its verification functions
are unchanged from the recorded authoring run.

## Exact correction

The candidate copies `jump_land_r7` to `jump_land_r8_ease_candidate`, preserving
all 103 existing Actions. It changes only two keys and their value handles:

- Bone: `righthand_prop`
- Curve: `rotation_euler`, array index 1 (Euler Y)
- Landing f5 / native4071: approximately +0.348741 degrees
- Landing f6 / native4072: approximately +0.076047 degrees
- f4 / native4070 and f7 / native4073 values and handles remain unchanged

`correction.json` retains the exact before/after coordinates and handles. Every
other candidate curve (774 curves), translation, grip/finger channel and
constraint remains unchanged. The landing trough at f12 / native4078 and final
pose at f29 / native4095 are preserved, as are takeoff, air, ready holds and late
recovery. No camera, geometry, texture, material, weight or rest-skeleton edit
is included.

The inferred target is a cubic Hermite ease of the calibrated projected sight
guide angle on f4–f7, matching the existing endpoint angles and tangents. The
inverse changes only Euler Y. Projected guide angle is not the Euler pitch
channel itself, and this inferred target is not a newly measured reference curve.

The original r7 motion was continuous Bezier motion with a sharp projected-angle
slowdown and an inter-frame overshoot. The correction does not characterize the
original motion as an instantaneous pose discontinuity.

## Evidence and limits

`evidence/author-checks.json` summarizes the original authoring and saved-file
reopen checks, retaining full-report hashes without bundling their private data:

- 173 samples: whole landing at 240 Hz and f3–f8 at 960 Hz
- All 103 old Action curve hashes preserved; 774 other candidate curves identical
- Exactly zero local/world root translation change
- Root world matrices identical at and outside f4/f7, including f12 and f29
- Matching mesh/material/rest-rig/camera/constraint structure digests on reopen
- Saved evaluated root matrices exactly match pre-save witnesses
- 5,704 vertices with more than 99.9% hand/finger weight preserve baseline weapon-relative
  placement within 0.000985 mm across 49 samples

The last check preserves baseline contact placement. It does not certify
absolute clearance, anatomy or animation quality. These historical checks were
not rerun by this publication task while live graphical capture was in progress.

The candidate's 960 Hz projected-angle overshoot above its f7 angle is 0.05234
degrees, peaking at f6.5625. A small residual remains because the original
negative f7 tangent is retained. Baseline overshoot relative to f7 was 0.85705
degrees; its separately reported 0.59104-degree overshoot used f5 as the reference.
Those quantities must not be conflated. All guide measurements come from
evaluated authored transforms, not newly tracked rendered pixels.

The required landing preview is exactly 29 native 60 Hz frames, f1–29 mapped to
reference4067–4095. All 29 belong in playback; f29 is not a closure-only walk
witness. This checkpoint includes no preview, frame corpus, score, approval,
FBX export or game-integration claim.

## Local reproduction, when the graphical capture machine is idle

Use Blender 4.3.2 with its NumPy module, and Python 3.11+ for the asset-free tests.
Only run Blender work in a quiet window. These scripts contain no render
operator. Embedded source scripts must remain disabled.

The four externally provisioned inputs are listed by immutable repository
reference and SHA-256 in `provenance.json`. Keep them together in a private
input directory:

- `halcyon_jump.blend`
- `authored_root_keys.json`
- `reference_geometry.json`
- `front_sight_geometry.json`

The source BLEND hash is
`a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`.
The historical saved candidate hash is
`db30e98a8d63cb4e9075ec2930cd5d34d385780ab374e1d6386f42d1e0fe7b3b`.
Neither file nor the calibration input contents are included or downloaded by
this checkpoint.

```sh
blender --background --factory-startup --disable-autoexec --threads 2 \
  --python-exit-code 1 --python tools/jump_landing_ease_r8/run_authoring.py \
  -- --inputs /path/to/private-inputs --output /path/to/new-r8-output
```

Use the wrapper entry point, not the archived original script directly. It
verifies input and original-script hashes before opening the source.
It runs the unchanged `refine_jump_landing.py`, which clones the landing Action,
checks the narrow two-key scope, restores original playback bindings, and saves
only a separate candidate. The output includes private local numeric witnesses
and full curve records; do not automatically publish that output directory.
Reproduced BLEND hashes can differ across saves. Compare the recorded curve and
evaluated-transform witnesses instead of claiming byte-identical reproduction.

```sh
blender --background --factory-startup --disable-autoexec --threads 2 \
  --python-exit-code 1 --python tools/jump_landing_ease_r8/reopen_verify.py \
  -- --source /path/to/private-inputs/halcyon_jump.blend \
  --reports /path/to/new-r8-output \
  --candidate /path/to/new-r8-output/halcyon_jump_r8_ease_candidate.blend \
  --output /path/to/new-reopen-receipt.json
```

The reopen verifier reads the reports produced by that specific authoring run.
It writes new output evidence with exclusive creation, so existing evidence is
never truncated. The `--candidate` override permits moving
the private output folder without editing a historical receipt.

## Asset-free tests

```sh
python3 -m unittest discover -s tools/jump_landing_ease_r8 -p 'test_*.py' -v
```

The package is also discovered by the repository's normal `tools/` unittest
lane. Tests execute the original pure Hermite function and the actual input
guard with original synthetic fixtures. They check exact scope, preserved
script/function hashes, input tamper and overwrite rejection, derivative
behavior, reference mapping and the distinction between numeric evidence and
approval. They do not import Blender, generate media or load private assets.

`SHA256SUMS` identifies the published checkpoint files. Existing PR20 and the
separate PR59 capture-tooling checkpoint remain unchanged by this work.
