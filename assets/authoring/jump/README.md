# First-person jump: current source r2

Original jump choreography revised from [Elara's r1 feedback](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5973648930). This is editable source WIP awaiting Elara's r2 review and runtime integration. The supplied locomotion videos contain no usable first-person jump cycle; this is not a reference-matched animation.

## Current editable file

`halcyon_jump.blend` is the stable current-source filename. It presently contains r2, SHA256 `ade77291cf65a6e2bd8563ebe7449a3b64e8df2f504dc6d2cdf0e93b534064fd`, in Blender 4.3.2 at 60 fps. The local authoring file was named `halcyon_jump_r2.blend`; renaming does not alter its bytes.

The previous standalone r1 file, recipe and revision-named scripts are retained in Git history rather than copied into an archive. Inside the current `.blend`, all 85 r1-baseline Actions remain intact, and three r2 Actions bring the total to 88. Existing mesh geometry, rig, weights, materials, packed images, drivers, constraints, camera, NLA and active/default state are preserved.

## What changed

Elara requested greater jump weight while retaining phase timing, the quiet extendable airborne pose and the three-Action split. The new extrema are purposeful rather than a uniform scale:

- Takeoff peak: downward displacement 21 → 36 mm, backward displacement 12 → 16 mm, muzzle dip 1.4 → 3.1 degrees
- Landing peak: downward displacement 32.5 → 48 mm, backward displacement held at 18 mm, muzzle dip 2.25 → 5.3 degrees
- Modestly stronger recovery rebound; lateral/roll accents unchanged
- Every phase boundary and beat frame unchanged; airborne Action curves fingerprint-identical to r1

Added pitch lowers the forward muzzle while keeping the rear receiver readable in the fixed camera. These numbers describe the authored recipe, not an artistic score or approval.

## Action contract

| Current Action | Stable runtime ID | Inclusive source range | Duration |
| --- | --- | --- | --- |
| `jump_takeoff_r2` | `jump_takeoff` | 1–11 | 10/60 s |
| `jump_air_r2` | `jump_air` | 1–2 | 1/60 s, static extendable hold |
| `jump_land_r2` | `jump_land` | 1–17 | 16/60 s |

Export these r2 Actions to the stable runtime IDs; do not export both revisions to duplicate bindings. All three start and end at the exact evaluated pose of `RD_Locomotion_Normal_Entry_4419_4434_WIP2`, frame 1 (`normal_ready`). Endpoint velocity is zero. Only `righthand_prop` location/rotation varies. The hands and seated magazine remain attached.

There is no armature/world/player-root movement or camera animation. Gameplay supplies the world jump arc and existing camera `landing_kick`; do not add another camera displacement from these clips. Landing must start on authoritative ground contact, including early impacts with a bounded transition, rather than on a fixed flat-flight timer. Takeoff must follow an accepted normal jump, excluding mantle, rejected input and Space-to-stand.

These are absolute HIP source poses. ADS requires deliberate aim-safe viewmodel-relative composition on the existing ADS base. Preserve ADS articulation and intent, firing, reload and mantle authority. This source package changes no runtime behavior.

## Evaluation and review setup

- Use `RD First Person Review` without moving it
- On `Arms`, mute legacy NLA tracks and set `use_nla=False`
- Initialize `RD_00_Supplied_Base_Guarded_Recovered` at frame 1, then assign the desired r2 Action
- Preserve companions: `hk416_weapon` → `hk416_weaponAction.001`; `hk416_magazine` → `hk416_magazineAction`. Their `use_nla=True` and empty NLA tracks remain unchanged
- The outgoing magazine is not a jump actor
- Play takeoff, extend static air, and play land. A preview's roughly 0.625-second flat flight is illustrative; runtime ground contact remains authoritative
- Use actual Eevee Viewport Render Animation for Elara. Never use Cycles

The saved file intentionally retains its baseline active Action/scene state. Choose a jump Action to inspect the new motion.

## Technical checks

- `source_preservation.json`: freshly reopened source preserves all 85 original Actions, their metadata/modifiers, structural data, pose defaults, camera, NLA, drivers and images
- `jump_technical_validation.json`: 120 Hz samples confirm attached grips, exact ready endpoints, zero endpoint tangents, quiet static air, no camera/world-root motion, and valid drivers
- Muzzle, receiver and support-wrist landmarks remain in frame. The anatomical firing-wrist origin is already outside the baseline frame and is reported as such
- `feedback_revision.json`: phase ranges, beat frames, static-air curves and stable runtime IDs are unchanged
- `reproduction_check.json`: a fresh rebuild reproduces all 88 Action fingerprints and structural snapshots

These are technical checks, not artistic acceptance. No game export, controller edit, build/load or triggered game playback is claimed by this authoring package.

## Reproduce from the frozen historical baseline

The r2 input is the published r1 file at commit `a5ecdaa09680e043fe608842f7d38acc810ed864`. Its SHA256 is `4e923368b0b07d87e737d6575266b2ba4b2d4b020d4bc4cf0c0848c7cf94acb6`. It was originally derived from HIP r5 SHA256 `36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d`.

From a repository clone containing that commit, with Blender 4.3.2 installed:

```sh
mkdir -p /tmp/jump-r2-rebuild
git show a5ecdaa09680e043fe608842f7d38acc810ed864:assets/authoring/jump/halcyon_jump_r1.blend > /tmp/jump-r2-rebuild/frozen-r1.blend

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-r2-rebuild/frozen-r1.blend \
  --python assets/authoring/jump/author_jump.py -- \
  assets/authoring/jump/jump_design.json /tmp/jump-r2-rebuild/halcyon_jump.blend

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-r2-rebuild/halcyon_jump.blend \
  --python assets/authoring/jump/validate_source_structure.py -- \
  --output /tmp/jump-r2-rebuild/source_preservation.json \
  --baseline /tmp/jump-r2-rebuild/baseline_fingerprint.json \
  --expected-actions jump_takeoff_r2 jump_air_r2 jump_land_r2

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-r2-rebuild/halcyon_jump.blend \
  --python assets/authoring/jump/validate_jump.py -- \
  /tmp/jump-r2-rebuild/jump_technical_validation.json
```

The author script refuses to overwrite an existing output file. No original or derived reference footage belongs in this source handoff.
