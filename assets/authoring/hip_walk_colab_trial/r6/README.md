# PR41 forward/backward r6 diagnostic

Status: **diagnostic, numeric FAIL**. Executed in Blender 4.3.2 on 2026-10-14.
All 5 pure-Python profile tests passed. Both isolated Actions were saved and reopened;
71/75 numerical checks passed across 1,332 samples at 480 Hz. All 86 original Actions
and all protected source/scene data were preserved. No render or runtime check ran.

- Forward: the cubic interpolant reaches +28.2362 px X at f8.25, exceeding the
  declared +28 px bound plus 0.1 px interpolation tolerance. Contact checks pass.
- Backward: the requested added roll reaches the existing left-wrist guard during
  roughly f27.75–35. Guard error peaks at 2.8316 degrees; the root-relative left-hand
  matrix error reaches 0.04205. This fails the guard and both relative-grasp checks.
- Backward's internal receiver seam improves from 4.6003 px to 2.0001 px. This does
  not establish the requested rendered mask-centroid seam or excuse contact failure.
- Saved private local candidate SHA-256:
  `c072976d9e3846a6b0d9229984994f9e4b21ae1a28cdc6692279ac259e2dc7d9`.

Keep this failed WIP as evidence and revise it. Do not widen the guard, relabel the
failure as a visual pass, replace r5, or promote the candidate as accepted.

## Authority and immutable inputs

- Review: https://github.com/RHS059/rust_duty/pull/41#issuecomment-6158919419
- Canonical source container: `RHS059/rust_duty@6a1c145ca63143e99bbf694a76f9d19bd31becf5`,
  `assets/authoring/hip_walk_colab_trial/v1/hip_four_walks_colab_visual_v1.blend`
- SHA-256: `f7d6e76d387a07508f61b2ade708fa930b93bd73b167110469a43c88ecf8eaf4`
- Input Actions: `hip_walk_forward_r5`, `hip_walk_backward_r5`.
- Output Actions: `hip_walk_forward_elara_r6`, `hip_walk_backward_elara_r6`.
- Keep all 86 preexisting Actions, including rejected visual-v1 Actions, unchanged.
- All changes stay in a distinct file. No source overwrite or in-game activation.
- Only original scripts, tests and documentation may be published. This folder's
  generated BLEND contains supplied private assets and is excluded from upload.

## Bounded hypothesis

The r5 forward weapon motion has insufficient vertical excursion and an early,
narrow lateral maximum. The r5 backward motion needs two distinct downward beats
instead of one broad arc, a wider lateral path, stronger roll and a smaller seam.
The hypothesis is a root-only spatial correction with fixed camera and key times.

The requested pixel envelopes come from Elara's published review. Those metrics
use a tracked source receiver and a native weapon mask centroid, which are not
homologous physical landmarks. The script calibrates displacement at the fixed
native receiver witness `hk416_weapon` local `(0.020, 0.075, 0.020)`. Its numeric
match is an internal authoring witness only. It does not claim that the rendered
centroid moved by the same amount or that the source weapon was matched exactly.
Both native complete-loop previews must be independently judged.

Allowed channels: the copied root's three location curves, and only for backward,
its three Euler rotation curves. Camera matrices, FOV, shift, timing, source-frame
mapping, all other curves, source Actions, NLA, drivers, bone rests, skin weights,
geometry, materials and packed images remain protected. No warp, image alignment,
depth adjustment, global retiming or camera change is permitted.

- Forward changes are capped at 28 px X and 25 px Y at the native receiver witness.
  Corrective X reaches its maximum at f8. Exact source key values and handles are
  retained at f1, f2, f38 and closure f39; all forward rotations remain unchanged.
- Backward changes are capped at 27 px X, 21 px Y and a 6-degree added screen-roll
  envelope. Clockwise image roll is positive. The roll request is interpreted as
  an incremental correction, not a guaranteed total 13-degree rendered range.
  Native review must determine whether this overshoots the source excursion.
- Backward seam repair is limited to translation keys f44–45, weighted 0.5/1.0,
  capped at 15 px, to make the receiver last-unique-to-first gap 2 px when it was
  larger. The rendered mask-centroid gap still requires a <=3 px visual gate.
- Root translation from the envelope is capped at 5 cm. Any failed bound, contact
  gate or preservation check is a failed diagnostic, not permission to relax it.

The reopened sweep also bounds actual fractional-frame output, allowing at most
0.1 px numerical/cubic-interpolation slack, 0.02 degrees unintended off-axis or
roll slack, 0.00001 m receiver-depth drift and 0.00001 relative matrix/scale drift.
It compares root-relative hand and weapon attachments directly with r5 at matched
480 Hz samples, verifies all object defaults after reopening, and checks unchanged
camera and armature object matrices at every sampled frame. Signed roll must match
the intended periodic cubic within 0.02 degrees. Seam-bound allowance is restricted
to the final curve neighborhood (strictly f42–46) plus f1–2, where the periodic
first-key tangent depends on the final unique key.

## Timing and preview contract

- Forward: 38 unique frames, 60 fps, R2 source `[48,86)`, closure witness f39/source86.
- Backward: 45 unique frames, 60 fps, R2 source `[211,256)`, closure witness f46/source256.
- Original R2 SHA-256: `cff413d8d114b611bbe6f50cc553ef109d61eb8eb1fff960425f506b84d6767e`.
- 1280×720 saved `RD First Person Review` camera unchanged.
- Native Eevee foreground viewport rendering only, performed by the coordinator
  after numeric/source checks. No offline render, Cycles, or substitute raster.
- Compare source, retained r5 and r6 at exactly the same original frame map.
- Independently inspect every unique frame, quarter frames and both loop joins.

## Execution after resource release

1. Run `python -m unittest -v test_correction_profiles.py` from this folder.
2. Run Blender 4.3.2 with `--background --disable-autoexec` opening the exact source,
   `--python author_walk_r6.py -- output`. This is authoring only and never renders.
3. Reopen the generated BLEND in a fresh process with
   `blender --background --disable-autoexec output/hip_longitudinal_elara_r6.blend --python verify_walk_r6.py -- output`.
4. Inspect `authoring_preservation.json`, `reopened_numeric_validation.json`,
   `authored_root_keys.json`, `evaluated_tracks_60fps.json`, and native frame maps.
5. Give the exact candidate bytes/hash and Actions to the native capture owner.
6. Retain r5 as baseline pending an explicit independent native visual verdict.

Required visual witnesses: forward step-A dip f6–13, rise f17–25, step-B dip f29–33,
lateral maximum near f8, unchanged clean seam; backward dips f14–17 and f34–37,
rise f24–26, roll shape, <=3 px rendered seam, both hand attachments and full skin.
Numerical gates include reopened preservation of all originals and 480 Hz wrist,
guard, relative-contact, exact closure and driver checks. They do not certify
fingertip contact, hidden anatomy, visual approval, FBX parity or runtime behavior.

## Evidence provenance

The included `inputs/source_integrity.py` and `inputs/validate_directional_source.py`
come from source commit `6a1c145ca63143e99bbf694a76f9d19bd31becf5`, directory
`assets/authoring/hip_walk_colab_trial/v1/`. The local research also retrieved that
directory's `validate_visual_v1.py`, `longitudinal-r5-design.json`, `build_visual_design.py`,
and Elara's measurement JSON and analysis scripts from
`02080665f668616ab63b6414b2648aa76c6df0f2/review_sbs/2026-10-14/walk_{forward,backward}_pr41`.
The additional research inputs need not be copied into this revision; only the two
included snapshot helpers are imported by its author/verifier.
