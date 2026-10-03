# Four-direction native locomotion source (WIP)

This is an isolated, source-first handoff on PR #16 commit
`7ffdd6eb1d6ae20d5e8e6445f07759a225c952eb`. The canonical locomotion BLEND,
production exporters/configuration, packaged assets and runtime are untouched.

## Independent review outcome

**WIP: no all-four formal pass, no full-window 80% fidelity claim, and no
runtime acceptance.** Forward, left and right each score 60/60 on their narrow
in-sample periodic cores. Backward scores 50/60, but its 10/20 timing category
fails the minimum; the source peak is nearly flat within measurement uncertainty.
All four pass local visible-contact and loop-continuity checks. Earlier pose
equivalence and full-window failures remain in the review packet.

Read [the final independent review](review/FINAL_REVIEW_V06.md) before integrating.
Compact [native-only video](previews/directional_native_preview.mp4) shows two
loops each in forward, backward, left and right order at 60 fps. The previews
folder also contains native dense and side/underside contact sheets. None is
gameplay footage or third-party reference pixels.

## Verified final source

Frozen source SHA-256: `6d6d5c6a150bd8d74f24b29bf18b192e2f5fe2cd93a531c77b7a1e5ce93a8b35`.

- All 27 fresh source checks pass, including raw pose-channel defaults
- All 222 sampled evaluated arrays across the 44 original selected takes are
  byte-identical to the frozen baseline; maximum measured drift is zero
- All four FBX takes have 675 curves with the expected 480 Hz sample counts;
  native bone, actor and skin endpoint arrays repeat exactly
- The checked-in authoring script/design reproduces all 66 Actions and all
  protected source data identically; BLEND serialization bytes may differ

These are source/export checks. The separately labeled independent motion and
contact review governs visual acceptance, with full-window and runtime limits
retained. See `handoff.json`, `authoring_reproduction.json`,
`source_preservation.json`, `preserved_evaluation.json` and
`preview_export_validation.json`.

## Source contract

Open `halcyon_hip_directional_r1.blend` in **Blender 4.3.2**, with embedded
Python auto-execution disabled. Four new fake-user Actions use the existing
native `Arms` rig, geometry, materials, camera, weapon and attached hands:

| Action | Inclusive source range | Unique frames | Duration |
|---|---:|---:|---:|
| `hip_walk_forward_r1` | 1–39 | 38 | 0.633333333 s |
| `hip_walk_backward_r1` | 1–46 | 45 | 0.750000000 s |
| `hip_strafe_left_r1` | 1–50 | 49 | 0.816666667 s |
| `hip_strafe_right_r1` | 1–50 | 49 | 0.816666667 s |

Source rate is 60 fps. Each last frame repeats the first; play only the unique
frames when looping. The six varying native control channels are
`righthand_prop` XYZ location and Euler rotation. Other keyed channels freeze
the native ready pose. These are **absolute native poses**, not additive deltas.
The source preserves every pre-existing Action, NLA track, driver, packed
texture and rig/mesh binding; no directional NLA tracks are added.

The FBX preview selects 72 deform bones, three `Actual arms mesh` objects, and
rigid actors `hk416_weapon` and `hk416_magazine`. The reload-only outgoing
magazine stays excluded. Conversion basis remains Blender `(x,y,z)` to FBX
`(x,z,-y)`; the receiving runtime's whole-model rotation must be applied once.

## Explicit ownership and acceptance boundary

The receiving integration lane owns appending these Actions into the canonical
source and changing production configs/runtime. ADS reuses these base clips at
reduced amplitude; there are no duplicate ADS loop Actions here. Derive any
additive deltas against the complete evaluated `normal_ready` pose under the
existing attachment-aware composition contract. Fade the directional layer
out concurrently with run-layer fade-in, preserving evaluated pose and phase.

The supplied motion reference has different weapon/grip geometry. Motion-only
scores must not be described as pose equivalence or whole-gameplay fidelity.
Read the versioned independent measurement contract, raw derived numeric
tracks, category scores, coverage/exclusions and hard-gate outcomes included
with this handoff. Missing firing-wrist visibility and pending runtime
transitions earn no unobserved points. No third-party footage or source frames
are included in the public repository.

## Reproduce source verification

From the repository root, use new output directories for every export:

```sh
blender --background --factory-startup --disable-autoexec \
  assets/authoring/locomotion_directional/halcyon_hip_directional_r1.blend \
  --python-exit-code 1 \
  --python assets/authoring/locomotion_directional/validate_directional_source.py -- \
  --baseline assets/authoring/locomotion_directional/baseline_fingerprint.json \
  --config assets/authoring/locomotion_directional/preview_export_config.json \
  --output build/directional-source-preservation.json

blender --background --factory-startup --disable-autoexec \
  assets/authoring/locomotion_directional/halcyon_hip_directional_r1.blend \
  --python-exit-code 1 \
  --python assets/authoring/locomotion_directional/export_directional_preview.py -- \
  --config assets/authoring/locomotion_directional/preview_export_config.json \
  --output-dir build/directional-preview

blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python assets/authoring/locomotion_directional/verify_preview_fbx.py -- \
  --directory build/directional-preview \
  --config assets/authoring/locomotion_directional/preview_export_config.json \
  --output build/directional-preview-validation.json
```

The preview is baked at 480 Hz with simplification disabled. Expected keys per
exported curve, including the repeated endpoint: forward 305, backward 361,
left/right 393. The exporter validates frozen source bytes and its complete
Action/NLA/driver/packed-image snapshot, never saves the BLEND, and runs no
embedded source Text block. It produces a derived FBX, native matrices/skin
oracle and copied packed textures locally. Those large derived preview files
are intentionally not checked in.

## Reproduce old-clip numerical preservation

First run the canonical frozen exporter against the unchanged canonical source
into `build/directional-baseline` using its existing README command. Then:

```sh
blender --background --factory-startup --disable-autoexec \
  assets/authoring/locomotion_directional/halcyon_hip_directional_r1.blend \
  --python-exit-code 1 \
  --python assets/authoring/locomotion_directional/evaluate_preserved_clips.py -- \
  --config assets/authoring/locomotion/export_config.json \
  --output-dir build/directional-preserved

python assets/authoring/locomotion_directional/compare_preserved_evaluation.py \
  --baseline build/directional-baseline \
  --candidate build/directional-preserved \
  --output build/directional-preserved-comparison.json
```

This compares all 44 selected baseline takes (43 gameplay plus one diagnostic),
222 evaluated arrays, using the frozen sample schedule. Position tolerance is
1e-6 m and matrix-component tolerance is 1e-6. Exact static source fingerprints,
sampled native preservation, FBX bake validation, reference-motion review and
runtime acceptance are distinct checks. None substitutes for the others.
