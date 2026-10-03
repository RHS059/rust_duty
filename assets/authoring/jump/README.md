# First-person jump r1 source

Original jump choreography, ready for Eevee Viewport Render Animation review by Elara. This is editable source WIP, not an artistic acceptance or a runtime integration claim. Neither supplied locomotion video yielded a usable first-person jump sequence, so this motion is not described as reference matched.

## Current source

- `halcyon_jump_r1.blend`: frozen, packed Blender 4.3.2 source at 60 fps
- SHA256: `4e923368b0b07d87e737d6575266b2ba4b2d4b020d4bc4cf0c0848c7cf94acb6`
- Baseline: committed `assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend`
- Baseline SHA256: `36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d`
- All 82 baseline Actions are preserved; exactly three new Actions give 85 total
- Existing meshes, 148-bone / 72-deform-bone rig, weights, materials, packed images, constraints, drivers, camera, NLA and active/default state are preserved

## Actions and stable export names

| Source Action | Runtime ID | Source range | Duration | Behavior |
| --- | --- | --- | --- | --- |
| `jump_takeoff_r1` | `jump_takeoff` | 1–11 | 10/60 s | Compact takeoff lag, restrained rebound and ready recovery |
| `jump_air_r1` | `jump_air` | 1–2 | 1/60 s | Static ready carry; identical frames can hold or repeat for any remaining flight |
| `jump_land_r1` | `jump_land` | 1–17 | 16/60 s | Ground-contact compression, small rebound and ready settle |

The ranges include both endpoints. Source revision suffixes are not game bindings. Every Action begins and ends at the exact evaluated pose of `RD_Locomotion_Normal_Entry_4419_4434_WIP2`, frame 1, which is the existing `normal_ready` anchor. Root-control endpoint velocity is zero. The air Action has no varying channel.

Only `righthand_prop` location/rotation varies. Both hands and the seated magazine remain attached; no hand release, new mechanism animation, armature/world/player-root translation, or camera movement is authored. This is viewmodel inertia, separate from the gameplay world-space trajectory and existing camera `landing_kick`.

## Evaluating / previewing

1. Open the frozen source with auto-execution disabled
2. Keep the `RD First Person Review` camera unchanged
3. On `Arms`, mute all legacy NLA tracks and set `use_nla=False`
4. Evaluate `RD_00_Supplied_Base_Guarded_Recovered` at frame 1, then assign a jump Action
5. Preserve object companions: `hk416_weapon` uses `hk416_weaponAction.001`; `hk416_magazine` uses `hk416_magazineAction`. Both have `use_nla=True`, with no NLA tracks. The existing outgoing magazine is not a jump actor
6. At 60 fps, play takeoff, hold/repeat air, then land. A representative flat-flight preview may start landing at about 0.625 s after launch, but this is illustrative timing; the runtime must use real ground contact
7. For motion review, use actual Eevee Viewport Render Animation, never Cycles. Preview publication and Elara's assessment are separate from these technical checks

The saved file deliberately retains the baseline's original active Action and scene state rather than rewriting them for presentation. Select the desired jump Action to inspect it.

## Runtime boundary

The source Actions are absolute HIP poses. An ADS route needs deliberate aim-safe viewmodel-relative composition on the existing separate ADS pose; replacing ADS articulation with these HIP poses is not supported. `authored_root_keys.json` includes the exact camera-space deltas, ready anchor and pivot to support the integration owner.

Start takeoff only after an accepted normal jump, excluding mantle, Space-to-stand and rejected jump edges. Hold the air pose for longer falls; start landing from grounded contact. An early impact needs a bounded blend from the current takeoff pose. Preserve existing firing, reload, ADS intent and mantle authority. The source package changes none of those controllers and does not add a second camera kick.

## Technical verification

- `source_preservation.json`: a fresh process reopened the saved candidate and confirmed all prior Action fingerprints, metadata, modifiers, NLA/active state, pose defaults, structure, bindings, drivers, packed images, materials and cameras unchanged
- `jump_technical_validation.json`: 120 Hz sampled evaluation of the short clips confirms contact, exact ready endpoints, static air, zero endpoint tangents, no world/camera motion and valid drivers
- Maximum wrist-to-grip-target error is 0.000000514 m; hand-to-root matrix drift is below 0.0000009, consistent with floating-point evaluation. All endpoint bone/weapon/magazine matrices exactly equal ready in this evaluation
- Muzzle, receiver and support-wrist landmarks remain in the unchanged camera frame. The anatomical firing-wrist origin is already below/right of the baseline frame and is recorded without being misclassified as new clipping
- `reproduction_check.json`: a fresh process reran the author script against the frozen baseline into a separate output; all 85 Action fingerprints and all NLA, driver, image and structural snapshots matched

These are technical checks, not a motion score. No GLB/export, game controller change, runtime build/load, triggered game playback or artistic acceptance is claimed here.

## Reproduce

From the repository root, with Blender 4.3.2 installed, choose a new empty output directory. The script refuses to overwrite an existing blend:

```sh
blender --background --factory-startup --disable-autoexec \
  assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend \
  --python assets/authoring/jump/author_jump_r1.py -- \
  assets/authoring/jump/jump_design_r1.json /tmp/jump-rebuild/halcyon_jump_r1.blend

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-rebuild/halcyon_jump_r1.blend \
  --python assets/authoring/jump/validate_source_structure.py -- \
  --output /tmp/jump-rebuild/source_preservation.json \
  --baseline /tmp/jump-rebuild/baseline_fingerprint.json \
  --expected-actions jump_takeoff_r1 jump_air_r1 jump_land_r1

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-rebuild/halcyon_jump_r1.blend \
  --python assets/authoring/jump/validate_jump_r1.py -- \
  /tmp/jump-rebuild/jump_technical_validation.json
```

Keep only this current candidate and its current recipe/checks in the source handoff. No reference video, derived frame sheet, superseded candidate or canonical runtime asset is part of this package.
