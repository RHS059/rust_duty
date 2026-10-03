# Locomotion authoring source + normal_walk_r1

`locomotion.blend` now contains a newly authored **regular ready-carry walking WIP**, `normal_walk_r1`, alongside the existing normal-sprint entry, loop, exit, bridges and archived Actions. This does not restore the former procedural Rust walking bob. No runtime, converter or shared CI code is changed here.

The source contains **62 Actions, eight NLA tracks, 185 valid native drivers and packed textures**. All 61 prior Action fingerprints, seven prior NLA tracks, driver definitions and packed-image bytes are unchanged. The new Action is active for review, frames 1–45 at 60 fps. Its new NLA strip is intentionally **muted**: the exporter selects the Action explicitly and constructs its own export-only tracks. The embedded `RD_LOCOMOTION_README` describes the historical baseline; this sibling README and JSON contracts describe the current revision.

## New regular walking cycle

- Action / exported clip / NLA name: `normal_walk_r1`
- Source range: **1–45**, including repeated endpoint; play unique frames **1–44**
- Source rate: **60 fps**; period **44/60 = 0.733333 seconds**
- 23 root keyposes, at two-frame spacing; free Bezier handles and cyclic root channels
- Six animated channels: `righthand_prop` XYZ location and Euler rotation
- Both hands and the seated magazine keep **Weapon Follow = 1**; the supplied IK, wrist guards, poles, attachment offsets, meshes and camera remain intact
- Source time is baked at **480 Hz**, giving **353 samples including the repeated endpoint**

The walk is a new camera-space root rotation about the attached support wrist, with small lateral/vertical translation. Its reference-guided peak-to-peak authoring values are approximately 6.07 mm lateral translation, 10.58 mm vertical translation, 1.85° pitch and 5.51° yaw. These are artistic native-rig choices, not recovered game-space motion. No camera animation, independent free-hand path, legacy procedural oscillator or new weapon geometry was added.

### Reference and limits

The supplied [movement video](https://drive.google.com/file/d/1hxAU4KKtB8hP0Ch1o-rOWgOV93ye-Y7i/view?usp=sharing) is 1280×720 at 60 fps. SHA-256: `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.

Selected non-sprint ready-carry window: **5.916667–8.133333 s**, source frames **355–488**. It shows an attached support hand, lateral weapon sway, two vertical pulses per lateral cycle, and a rear-of-weapon arc larger than the support-cuff motion. There is no input overlay: **walking versus jogging and movement speed cannot be established**. The existing low-diagonal sprint window was not relabeled as walking.

Normalized feature tracking measured:

- Optic visible displacement: **57.77×29.05 px peak-to-peak**
- Rear sight: **64×50 px**; support cuff: **16×26 px**
- Best periodic optic fit: **0.736234 s**; consecutive crest intervals average **0.738889 s**, sample SD **0.050918 s**
- Feature-center uncertainty is approximately ±3 px; individual crest timing approximately ±2 source frames

Linear drift was removed and two harmonics were fit to the cuff and rear-sight traces. These guide the new native motion rather than reconstructing source 3D. The source has a different optic, appearance and proportions; the native asset and original ready pose are deliberately retained. A front-rail track with poor correlation was rejected. `walk_reference.json` records the selected observations, template bounds and caveats; `walk_design.json` records the periodic model and exact root keys. Small mathematical fit residuals in that file measure the chosen screen-motion targets only, not full reference fidelity.

### Start, stop and ownership metadata

`export_config.json` contains proposed integration values: **120 ms start**, **160 ms stop**, cubic smoothstep, and a continuous walk phase through fades. They are authoring recommendations, not observed source input latency or validated game transitions. There are no separately baked walk-start or walk-stop Actions in this revision.

Capture the complete currently evaluated bone/actor pose before changing presentation owner or rapidly reversing a transition. Blend to `normal_ready` on stop and into the existing connected entry for sprint; do not snap to walk frame 1. Use one weapon-driven rig, preserve attachment behavior, and measure full skin/actor/hand continuity in the receiving runtime. Higher-priority gameplay starts immediately. Runtime owner Aella is responsible for binding this clip, speed scaling, and validating these blends in actual game capture.

## Exact headless export

Run from the repository root with **Blender 4.3.2** and a new output directory:

```sh
blender --background --factory-startup --disable-autoexec \
  assets/authoring/locomotion/locomotion.blend \
  --python-exit-code 1 \
  --python assets/authoring/locomotion/export_locomotion.py -- \
  --config assets/authoring/locomotion/export_config.json \
  --output-dir build/locomotion-fbx
```

The exporter verifies exact source bytes and Action/NLA/driver/texture integrity, executes no embedded source Text blocks, and never saves its input BLEND. It produces `locomotion.fbx`, `native_oracle.json`, `native_oracle.npz` and extracted packed textures. Source 60 fps is evaluated/baked at 480 Hz (`bake_anim_step=0.125`), with simplification disabled. Do not reinterpret historical manifests that reported 240 fps despite storing 480 Hz keys.

The config selects **44 FBX source takes = 43 gameplay takes + one diagnostic**:

1. Existing seven named ready/entry/loop/exit/connected gameplay takes
2. Existing 35 `normal_exit_bridge_000` through `_034` takes
3. Existing `normal_diagnostic_sequence`, which is staged diagnostic animation
4. New `normal_walk_r1`

The original seven conversion groups are preserved, with a separate eighth walk-only group. A constant ready take is still generated only in memory from original entry frame 1.

## Runtime settle derivation remains unchanged

For the **44-clip gameplay package**, exclude `normal_diagnostic_sequence`, then derive `normal_settle` from already-converted `normal_exit_connected`:

1. Select stored float32 timestamps **>= 0.25 s**, corresponding to source frames **16–25**
2. Require 73 frames and an exact first selected timestamp of 0.25 s
3. Copy every bone, rigid-actor and visibility byte unchanged; subtract 0.25 only from each float32 timestamp
4. Require first derived timestamp 0.0, last 0.15000000596046448, and mark the clip nonlooping
5. Preserve other clip records; require identical companions and ordered skin/actor bindings before merging, and retain interpolation, allocation and CRC guards

Do not independently rebake or interpolate settle. Including the optional diagnostic produces **45 runtime clips**. The baseline's 73-frame byte-subrange proof is retained separately; it is not a claim that an entire future runtime package is byte-identical.

## Verification and remaining review

The new source was reopened with factory startup and embedded auto-execution disabled. A 353-sample native sweep at 480 Hz verified:

- Maximum wrist solve error: **0.000600 mm**
- Wrist guard clipping: **0°**; minimum raw guard margin **1.99996°**
- Minimum reach margin: **146.8566 mm**
- Maximum hand-in-weapon attachment drift: **0.000466 mm**, rotational drift reported **0°**
- Exact repeated hand and elbow endpoint positions
- Root endpoint values and tangents explicitly repeated; finite-difference seam checks, including Float32/IK evaluation noise, are retained in `validation.json`
- Every original Action, NLA track, packed texture and driver definition preserved; all 185 drivers valid

`walk_export_validation.json` records the independent revised **44-take FBX export**: all take names and three packed textures pass; the walk has 675 exported curves with 353 keys each, and all five walk endpoint arrays (bones, actors and three skin meshes) repeat exactly. The 217 prior evaluated arrays remain within explicit 1e-6 m position and 1e-6 matrix-component tolerances: 88 are byte-identical, including every rigid-actor array; 129 have tiny Float32 differences after save/reopen. Maximum prior skin displacement is **0.000794 mm** and maximum prior bone-position difference **0.000608 mm**. Existing wrist solve errors remain below 0.05 mm and guards remain unclipped. **Full prior evaluated-array byte identity is not claimed for this new source.** The baseline export's 217-array numerical-preservation result is retained under `validation.json` → `baseline_validation`; new-source reproduction results are stated separately so that old evidence is not mistaken for a new test.

Preview videos compare the supplied source window with **Blender renders**, not gameplay. The new walk remains WIP pending visual acceptance and live-game integration. Attachment-transform tests do not certify hidden finger-to-surface contact, every possible arm-body intersection, or blended runtime output. Retained reload Actions are historical context, not the current reload master.

Exports select 72 deform bones, three arm meshes and rigid actors `hk416_weapon` / `hk416_magazine`. Reload-only outgoing magazine, helpers, camera and scenery are excluded. Blender `(x,y,z)` becomes `(x,z,-y)` in FBX, and the existing game applies its whole-model Y rotation once. `sanitize_source.py` remains the historical one-time packaging utility; running it is not needed for normal exports and does not recreate the new walk.
