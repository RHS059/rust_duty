# First-person jump: current reference-guided source r5

This revision refines r4 against the same recovered supplied Call of Duty jump after [Elara's paired feedback](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5974449246). The accepted takeoff and air-lift timing are retained. The remaining forward-weapon landing trough, recovery shoulders and middle path are retargeted from actual foreground tracks, not a general amplitude increase. Elara's r5 paired review and runtime integration are pending.

## Source and reference

- Current editable source: `halcyon_jump.blend`, Blender 4.3.2, 60 fps
- r5 SHA256: `fe47ec2961214252d831e7da743d3145b3ab219043d5a8db9622d3c387b1fa53`
- Supplied reference: `Modern_Warfare_2022_Movement_Reference.mp4`, 1280×720, 60 fps, 9,137 frames
- Reference SHA256: `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`
- The recovered file is byte-identical to the historical supplied Drive copy. Its title, duration and chapter content correspond to [V_QT_cnlBHU](https://www.youtube.com/watch?v=V_QT_cnlBHU); see the repository's `references/movement/` provenance for the independently qualified identity evidence
- The complete recovered reference is stored under `references/movement/` as exact parts with a reassembler
- Jump identification in the other two supplied clips remains unresolved. No claim that those clips contain no jump is made

The stable source filename contains the current revision. Prior standalone source files remain in Git history. Inside this `.blend`, all 94 prior Actions are preserved; three r5 Actions bring the total to 97. Meshes, rig, weights, grips, materials, packed images, constraints, drivers, cameras, NLA and prior active/default state are unchanged.

## What the pixels establish

The first stationary jump is the primary reference. Frame numbers are zero-based source indices at native 60 fps:

- n4033: normal-ready anchor, immediately before visible takeoff
- n4034: first visible ascent
- n4043–4044: held optic/receiver takeoff-lag extrema
- n4048–4052: world apex neighborhood; this world/camera arc is not baked into the rig
- n4061: strongest observed held-weapon lift during the airborne phase
- n4067 ±1 frame: visual ground impact
- n4078–4080: deepest held-weapon landing dip, later than the ground/camera impact
- n4095: recovery endpoint used for normal-ready closure

The weapon dips after launch, pulls back and rotates, rises during the airborne descent, then dips and recovers after impact. The reference's foreground weapon and hand motion is measured directly; terrain/horizon optical flow and the ballistic camera-height arc are excluded from the viewmodel Action.

## Retarget method and limits

`reference_weapon_tracks.json` contains foreground-only native-frame feature tracks for the optic, receiver, hand, forward rail and cuff. The four-guide fit uses optic, receiver, support-hand and forward-rail motion; the additional cuff track remains an observation. `reference_retarget.json` records the corresponding camera-space motion fit and the measured guide trajectories. The existing model's rear-sight, charging-handle, support-wrist and forward-weapon guides are used to retarget the motion while preserving its geometry and grips.

A single-view video does not uniquely recover true 3D transforms, and the reference optic/weapon differs from this model. This is a constrained 2D-motion retarget onto the accepted model, not a claim of model-identical reconstruction. Five-frame quadratic smoothing reduces tracking jitter without retiming the source. During only the last eight intervals, the small remaining measured end offset is removed to connect exactly to existing normal ready.

There is no author match score or artistic acceptance claim. The paired native-speed COD/Eevee preview is the review evidence.

## Refinement boundary

The complete r5 takeoff Action curve fingerprint is identical to r4. Native retarget parameters at n4059–4063, surrounding the accepted air-lift extremum, are also unchanged. The new foreground-rail guide corrects the shallower forward-weapon arc while keeping the already-close rear sight/receiver motion constrained. Smooth influence ramps confine the change to the remaining middle path and landing/recovery. `reference_refinement.json` records the scope checks. No phase or playback retiming is introduced.

## Action contract

| Current Action | Stable runtime ID | Source frames, inclusive | Blender frames | Duration |
| --- | --- | --- | --- | --- |
| `jump_takeoff_r5` | `jump_takeoff` | 4033–4044 | 1–12 | 11/60 s |
| `jump_air_r5` | `jump_air` | 4044–4067 | 1–24 | 23/60 s |
| `jump_land_r5` | `jump_land` | 4067–4095 | 1–29 | 28/60 s |

Export only the r5 Actions to the stable runtime IDs. Revision suffixes do not change game bindings.

Unlike r1–r3, the air Action is a non-looping transition into a raised carry. Clamp/hold its final pose for additional flight; do not repeat the air transition. Internal phase seams intentionally use non-neutral connected poses and matching root-control velocity. Only the overall start and finish are exact `RD_Locomotion_Normal_Entry_4419_4434_WIP2`, frame 1 (`normal_ready`), with zero endpoint velocity.

Only `righthand_prop` location/rotation varies. No new mechanism motion, hand release, armature/world/player-root motion or camera animation is authored. Gameplay still owns its world trajectory and existing `landing_kick`.

Trigger from accepted normal jump, excluding mantle, Space-to-stand and rejected input. Ground contact must start landing from the current airborne pose via a bounded blend; an early/late landing must not be forced to the reference timer. The reference's visible flight is about 33/60 s, while existing game physics is about 0.6245 s. No physics change is requested here. ADS, firing, reload and mantle remain authoritative. These are HIP source poses, not replacement ADS articulation.

## Paired preview

`reference_frame_map.json` gives the exact 100-frame, 1×, 60 fps mapping for source n4014–4113 inclusive. The required presentation is COD above and the actual Eevee Viewport Render Animation below, with native frame/time labels, delivered under stable filename `jump_animation.mp4`. Ready holds occur only outside the authored source interval. The Blender review camera remains fixed; the COD panel retains its real world/camera motion.

Initialize `RD_00_Supplied_Base_Guarded_Recovered` at frame 1, mute legacy `Arms` NLA tracks, set `use_nla=False`, then assign the r5 Actions. Keep `RD First Person Review` unchanged. Preserve companions `hk416_weaponAction.001` on `hk416_weapon` and `hk416_magazineAction` on `hk416_magazine`; both retain `use_nla=True` with no tracks. The outgoing magazine is excluded. Use actual Eevee Viewport Render Animation, never Cycles.

## Checks

- Fresh-disk preservation confirms all 94 prior Actions and structural state unchanged
- Native and half-frame checks confirm attached grips, visible core landmarks, no camera/world-root movement, and valid drivers
- Takeoff→air and air→land pose/velocity seams are connected; overall endpoints exactly equal normal ready
- Air terminal pose remains identical when evaluated beyond its range, with no cycle modifier
- A clean rebuild reproduces all 97 Action fingerprints and structural snapshots

Reports: `source_preservation.json`, `jump_technical_validation.json`, `reproduction_check.json`. These are technical checks. No runtime export, controller change, build/load, triggered game playback or artistic acceptance is claimed by this source package.

## Reproduce the editable source

The frozen input is r4 from commit `2333cef50554fd4408d4950c32fe201b78f21c86`, SHA256 `e6e59edeac62accc185d2b53a9fe5eab7d876b0a64a404bba1495b9875e2482e`. The same commit contains the r4 `jump_design.json` required by the optional refinement fit to preserve the accepted parameters.

```sh
mkdir -p /tmp/jump-r5-rebuild
git show 2333cef50554fd4408d4950c32fe201b78f21c86:assets/authoring/jump/halcyon_jump.blend > /tmp/jump-r5-rebuild/frozen-r4.blend

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-r5-rebuild/frozen-r4.blend \
  --python assets/authoring/jump/author_jump.py -- \
  assets/authoring/jump/jump_design.json /tmp/jump-r5-rebuild/halcyon_jump.blend

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-r5-rebuild/halcyon_jump.blend \
  --python assets/authoring/jump/validate_source_structure.py -- \
  --output /tmp/jump-r5-rebuild/source_preservation.json \
  --baseline /tmp/jump-r5-rebuild/baseline_fingerprint.json \
  --expected-actions jump_takeoff_r5 jump_air_r5 jump_land_r5

blender --background --factory-startup --disable-autoexec \
  /tmp/jump-r5-rebuild/halcyon_jump.blend \
  --python assets/authoring/jump/validate_jump.py -- \
  /tmp/jump-r5-rebuild/jump_technical_validation.json
```

The author script refuses to overwrite an output. The current recipe already contains the native retarget parameters, so source reproduction requires only Blender and the frozen baseline. Optional `measure_reference.py` and `fit_reference.py` document/reproduce the reference measurement stage using Python with NumPy, SciPy, OpenCV and Pillow; pass `--help` for their input/output paths. The refinement fit additionally requires `--baseline-design` pointing to the frozen r4 recipe from the commit above.
