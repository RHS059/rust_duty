# Standing hip directional locomotion: native source handoff

This is a bounded **source-only clean-periodic-motion handoff** for the native HK416 and attached hands. The four new Actions are in a separate copy of the canonical Blender source. No canonical source, runtime controller, production export configuration, rig/rest pose, geometry, camera, existing Action, or existing NLA track was edited.

The measured references use a shotgun. Their fixed shape and grip spacing are not equivalent to the native HK416. The original whole-pose rubric fails that static equivalence test. Independent review reports full-window timing/amplitude limits separately from clean-core transfer; **do not describe this source as an overall 80% reference match or runtime acceptance**.

## Independent final review

All four native dense 20 Hz front sequences, exact loop seams, and 32 side/underside extrema witnesses pass local contact and continuity review. The original source and all prior evaluated arrays remain preserved.

The **narrow in-sample clean-core motion** scores are forward **60/60**, left **60/60**, right **60/60**, and backward **50/60**. Backward's timing category is **10/20**, below its category minimum: one flat muzzle-X maximum is 8 source frames from the candidate maximum against a 4.5-frame tolerance. This remains unresolved. There is **no all-four formal pass**, no full-window 80% claim, and no runtime acceptance. Broader source-window settling and fixed geometry differences remain documented; no gain or rig distortion was used to erase them.

## Frozen source and Action identity

- Baseline commit: `7ffdd6eb1d6ae20d5e8e6445f07759a225c952eb` (PR 16, stacked on PR 15)
- Canonical input: `assets/authoring/locomotion/locomotion.blend`
- Input SHA-256: `1b01f49d7fe92f39c7bd180823ee4556a0074dd9ff8ef9c10b3fb4d3f3059e43`
- New separate source: `halcyon_hip_directional_r1.blend`
- New source SHA-256: `6d6d5c6a150bd8d74f24b29bf18b192e2f5fe2cd93a531c77b7a1e5ce93a8b35`
- Blender **4.3.2**, source **60/1 fps**, native coordinates in meters under the original export contract
- 66 Actions total: the original 62 plus four new fake-user Actions; the original 8 NLA tracks and active source state are retained

| New absolute Action | Period | Blender range with repeated endpoint | Unique playback frames | Measured source core |
|---|---:|---:|---:|---|
| `hip_walk_forward_r1` | 38/60 s | 1–39 | 1–38 | R2 `[48,86)` |
| `hip_walk_backward_r1` | 45/60 s | 1–46 | 1–45 | R2 `[211,256)` |
| `hip_strafe_left_r1` | 49/60 s | 1–50 | 1–49 | R2 `[886,935)` |
| `hip_strafe_right_r1` | 49/60 s | 1–50 | 1–49 | R1 `[361,410)` |

To inspect in Blender, select `Arms`, choose one of the four `hip_*_r1` Actions in the Action Editor, and set the playback end to its last unique frame. The original active Action and NLA state are intentionally unchanged on file open.

All source ranges are zero-based, half-open; their final listed frame is the same-phase endpoint observation. Native PTS is `n × 256` in time base `1/15360`. R1 is `9RRgXvRx43s`; R2 is `5KM0XSKxTWw`. Original videos and their frames are not part of this source handoff.

## What was authored

The new Actions clone the native ready-carry controls from `RD_Locomotion_Normal_Entry_4419_4434_WIP2`, frame 1. The only varying controls are the six XYZ location/Euler channels on `righthand_prop`. Both hands and the magazine retain their existing weapon-follow configuration, source IK, wrist guards, attachment offsets, mesh skinning, materials, and camera.

Measured native-frame muzzle, receiver, and visible cuff trajectories guide explicit pose keys. Each unique source frame yields an authored key; five-frame periodic smoothing removes pixel-scale tracking noise, and the repeated endpoint and central-difference Bezier tangent are made exact. The sequence is not time-warped. There is no runtime oscillator or newly invented independent hand motion.

The fit preserves the native mean carry pose. It uses lateral/vertical root translation and pitch/yaw about the attached support wrist. Backward and strafing also use small optical roll and bounded **±12 mm optical-depth translation** to transfer the measured differential projection of the three landmarks. This is a physically bounded native pose fit, not recovered reference 3D. Forward retains zero extra roll/depth. The fixed four projection scales were frozen before later iterations and never changed to raise scores.

`directional_keyposes.json` retains the source anchors, scale calibration, observation caveats, filter error, exact pose parameters, and raw numeric source tracks. `authored_root_keys.json` records the actual native root channels and points to the exact design hash.

## Cuff and contact evidence

The source hand landmark is a visible glove/cuff boundary, not an anatomical wrist reconstruction. The final native counterpart is the upper black cuff lip at ready-view pixel `[663,491]`, evaluated mesh `Actual arms mesh 0`, vertices `5681/5679/5666`, with fixed barycentric weights recorded in the design and validation. Native bone-head tracks remain separate attachment guards.

Every new Action is swept at **480 Hz**, including the repeated endpoint. `native_validation.json` and `candidate_tracks_60fps.csv` record actual evaluated native motion, zero wrist-guard clipping, sub-micron wrist solve error, hand-to-root stability, all 185 driver validity checks, and exact root/actor/hand endpoint repeats. These are source tests; they do not claim unseen reference firing-hand contact or guarantee every hidden mesh intersection.

Native first-person frames cover every source frame at 1280×720. Diagnostic side and underside witnesses use separate in-memory cameras at visible-cuff phase extrema; they never change the saved source camera or rig. Only native authored renders are eligible for publication. Reference footage/contact sheets are excluded.

## Preserving the existing work

The source is saved with all original raw pose-bone transform components and custom properties restored before restoring the original Action and frame. This avoids floating-point decomposition changes to untouched defaults. The independent source validator checks original Action curves and modifiers, NLA/active state, 185 driver definitions, packed textures, full meshes/UV/weights, rest skeleton, bindings, materials, cameras, and raw pose channels. The final-source native comparison evaluates the original 44 takes against the frozen source: **all 222 evaluated arrays are byte-identical**, with zero maximum matrix and position difference. Portable authoring reproduction also preserves all 66 Action fingerprints and static/raw-pose data. See `preserved_evaluation.json` and `authoring_reproduction.json` for the independent checks.

The new file is a native compressed BLEND, not an external archive. Source bytes and all report hashes must refer to the final SHA above. Any source revision requires fresh source/export/review verification.

## Reproduction and receiving ownership

Run `author_directional.py` with Blender 4.3.2, factory startup and embedded auto-execution disabled, opening the frozen canonical input and passing the design path plus a **new output path**. The sibling `source_integrity.py` dependency is supplied by the lane integrator. The helper checks input SHA, refuses canonical overwrite, adds only the four named Actions, and preserves all original data.

Aella owns canonical append, controller behavior, all production exports/configuration, and gameplay validation. Append only these named Action datablocks; never replace the canonical BLEND wholesale. Select the Actions explicitly for the isolated lane export at source60/bake480 Hz with the existing 72 deform bones, three arm meshes, and `hk416_weapon`/`hk416_magazine` actors.

The receiving runtime should retain shared base-walk motion at reduced amplitude during ADS and use `blend_in → animation → blend_out`; ADS and walk should fade out concurrently as running fades in. No independent ADS walking Actions or special transition animations were authored here. Settling and directional carry envelopes remain the runtime owner's work. Runtime selection, reversals, ADS alignment, start/stop response, and frame-rate consistency still require 30/60 fps gameplay checks.
