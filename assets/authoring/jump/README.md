# First-person jump: current source r3

Original jump choreography revised from [Elara's r2 feedback](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5973802198). This is editable source WIP awaiting Elara's r3 review and runtime integration. The supplied locomotion videos contain no usable first-person jump cycle, so this is not a reference-matched animation.

## Current editable source

`halcyon_jump.blend` is the stable current-source filename. It contains r3, SHA256 `cad1c8e661bc10a8ac2db6017598c1cc0daafdec6b09576e9b78d85edf4f642f`, in Blender 4.3.2 at 60 fps. The local authoring file was named `halcyon_jump_r3.blend`; renaming leaves its bytes unchanged.

Prior standalone source files and recipes remain in Git history rather than a bulk archive. Inside this `.blend`, all 88 r2-baseline Actions remain intact; three r3 Actions bring the total to 91. Existing mesh geometry, rig, weights, materials, packed images, drivers, constraints, camera, NLA and active/default state are preserved.

## What changed from r2

Elara requested deeper and wider takeoff/landing arcs rather than a taller short spike. The original peak, rebound and endpoint frames remain fixed. Added compression shoulders carry the held rig through broader arcs:

- Takeoff now retains 90% of peak compression at frame 6, before the existing frame-8 rebound
- Landing retains 90% at frame 7 and 55% at frame 8, before the existing frame-10 rebound
- Monotone cubic Hermite interpolation moves through the intermediate shoulders; it stops at actual extrema and clip endpoints, rather than stopping at every shoulder
- Takeoff peak: downward 36 → 46 mm, backward 16 → 18 mm, muzzle dip 3.1 → 4.1 degrees
- Landing peak: downward 48 → 62 mm, backward 18 → 10 mm, muzzle dip 5.3 → 8 degrees
- Landing backward movement is reduced while its downward/pitch arc increases, keeping the rear receiver visible in the fixed camera
- Existing rebound poses, main phase beats, neutral endpoints and quiet airborne pose are retained

This is a curve-shape revision, not a uniform amplitude multiplier. Recipe measurements and technical checks are not an artistic score or approval.

## Action contract

| Current Action | Stable runtime ID | Inclusive source range | Duration |
| --- | --- | --- | --- |
| `jump_takeoff_r3` | `jump_takeoff` | 1–11 | 10/60 s |
| `jump_air_r3` | `jump_air` | 1–2 | 1/60 s, static extendable hold |
| `jump_land_r3` | `jump_land` | 1–17 | 16/60 s |

Export the r3 Actions to these stable runtime IDs. Do not export multiple revisions to duplicate bindings. All three start and end at the exact evaluated pose of `RD_Locomotion_Normal_Entry_4419_4434_WIP2`, frame 1 (`normal_ready`). Endpoint velocity is zero. Only `righthand_prop` location/rotation varies; hands and seated magazine remain attached.

There is no armature/world/player-root motion or camera animation. Gameplay supplies the world jump arc and existing camera `landing_kick`; these clips must not add another camera displacement. Landing starts on authoritative ground contact, with a bounded transition for an early impact, rather than a fixed flat-flight timer. Takeoff follows an accepted normal jump, excluding mantle, rejected input and Space-to-stand.

These are absolute HIP poses. ADS requires deliberate aim-safe viewmodel-relative composition on the existing ADS base. Preserve ADS articulation and intent, firing, reload and mantle authority. This source package changes no runtime behavior.

## Evaluation and review setup

- Keep `RD First Person Review` unchanged
- On `Arms`, mute legacy NLA tracks and set `use_nla=False`
- Initialize `RD_00_Supplied_Base_Guarded_Recovered` at frame 1, then assign the desired r3 Action
- Preserve companions: `hk416_weapon` → `hk416_weaponAction.001`; `hk416_magazine` → `hk416_magazineAction`. Both retain `use_nla=True` and no NLA tracks
- The outgoing magazine is not a jump actor
- Play takeoff, extend static air, then land. A preview's roughly 0.625-second flat flight is illustrative; runtime ground contact remains authoritative
- Use actual Eevee Viewport Render Animation for Elara, never Cycles

The saved source retains its baseline active Action/scene state. Select a jump Action to inspect the new motion. Fractional shoulder timing is authoritative in the recipe; integer-only pose markers round the frame-6.8 shoulder marker to frame 7.

## Technical verification

- `source_preservation.json`: fresh-disk check preserves all 88 prior Actions, metadata/modifiers, structural data, pose defaults, camera, NLA, drivers and images
- `jump_technical_validation.json`: 120 Hz samples verify attached grips, exact ready endpoints, zero endpoint tangents, static air, no camera/world-root movement and valid drivers
- Muzzle, receiver and support-wrist landmarks remain in frame. The anatomical firing-wrist origin is already outside the baseline camera frame and is reported accordingly
- `feedback_revision.json`: original phase ranges, main beat frames, static-air curves and stable runtime IDs are retained; both compression shoulders are measurably wider in the authored native-frame recipe
- `reproduction_check.json`: a clean rebuild reproduces all 91 Action fingerprints and structural snapshots

These are technical checks, not artistic acceptance. No game export, controller edit, build/load or triggered game playback is claimed by this authoring package.

## Reproduce from the frozen historical baseline

The r3 input is r2 at commit `f5040f042ef5e988e5486e4ebdab12049ac9b2e4`, path `assets/authoring/jump/halcyon_jump.blend`, SHA256 `ade77291cf65a6e2bd8563ebe7449a3b64e8df2f504dc6d2cdf0e93b534064fd`. The previous recipe/checks in that commit preserve its earlier provenance.

From a repository clone containing that commit, with Blender 4.3.2 installed:

```sh
mkdir -p /tmp/jump-r3-rebuild
git show f5040f042ef5e988e5486e4ebdab12049ac9b2e4:assets/authoring/jump/halcyon_jump.blend > /tmp/jump-r3-rebuild/frozen-r2.blend

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-r3-rebuild/frozen-r2.blend \
  --python assets/authoring/jump/author_jump.py -- \
  assets/authoring/jump/jump_design.json /tmp/jump-r3-rebuild/halcyon_jump.blend

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-r3-rebuild/halcyon_jump.blend \
  --python assets/authoring/jump/validate_source_structure.py -- \
  --output /tmp/jump-r3-rebuild/source_preservation.json \
  --baseline /tmp/jump-r3-rebuild/baseline_fingerprint.json \
  --expected-actions jump_takeoff_r3 jump_air_r3 jump_land_r3

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-r3-rebuild/halcyon_jump.blend \
  --python assets/authoring/jump/validate_jump.py -- \
  /tmp/jump-r3-rebuild/jump_technical_validation.json
```

The author script refuses to overwrite an existing output. No original or derived reference footage is included in this source handoff.
