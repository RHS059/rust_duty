# Prone entry r6: real depth and paired camera authoring

Status: locally authored in Blender 4.3.2; fresh-reopen preservation, contact, geometry and guard non-regression checks passed. A strict 0.08° wrist-guard diagnostic would fail: 0.763° remains. This is disclosed, not represented as a zero-guard pass. No Eevee capture, artistic score, runtime export or runtime binding is claimed.

Candidate BLEND SHA256: `bd65f2eb280a6c08d413fd331a19b3b52b0990089cc4f06e802fc02813b85fd8`.

## Exact inputs and review

- PR #34 source commit: `9c5da4a2bb9920ce65390abfd7c287116d369e8a`.
- Input: `halcyon_prone_crawl_r5.blend`, SHA256 `67cf025fc31d9804cb0259432a91e496d7d8f84d1d4ac6be2b1914a6a98510ad`.
- Reviewed Action: `prone_crawl_enter_r5`; Elara's 64/Fail [frame brief](https://discord.com/channels/1554885571489566783/1556808474984325191/1559752200761376912).
- Actual inspected diagnostic: [native 69-frame paired video](https://raw.githubusercontent.com/RHS059/rust_duty_updates/e98e3142916fdd9607dabc0bf966458b3d1c0289/media/prone-entry-r5-diagnostic-native69-20261014/pr34-prone-entry-r5-diagnostic-native69-paired.mp4). Its full capture audit failed separately; it remains diagnostic evidence.
- Reference: R3 source frames `[2241,2310)`, SHA256 `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.

Every candidate native frame is unchanged in time: output index `i` maps to Action frame `i+1` and reference frame `2241+i`. The Action key span is 68/60 seconds; the 69 native video frames occupy 69/60 seconds. Neither is retimed.

## Why there are two new Actions

The inspected r5 camera has no animation, parent or camera bone. Its matrix is static throughout. Its Actions explicitly describe `camera_motion=none`. Therefore a weapon-only revision cannot produce the requested real ground-height drop.

R6 adds:

1. `prone_crawl_enter_r6`, copied from r5, containing corrected weapon/shoulder channels plus matched armature-object motion.
2. `prone_crawl_enter_camera_r6`, an isolated camera-object Action bound only while reviewing the candidate.

The original camera data, lens, shift, projection, transforms and unbound state are restored in the saved file. All 112 older Actions and original scene defaults survive. Opening the file keeps the original scene's active Action/range; use the explicit pair helper to inspect r6.

The common rig-object transform follows the new camera in world space, so the hands travel with the descending viewpoint. Static ground and environment objects do not move. Weapon-relative corrections are authored separately on `righthand_prop`; they are not a camera reframe or a substitute for the real camera motion.

## Correction on the existing beats

- f1–11: exactly retain all evaluated bone matrices and the original camera pose.
- f12–20: grow downward camera/weapon pitch, real descent, and inward weapon roll without changing the source clock.
- f21–35: continue to true prone height. The camera reaches 0.30 m above the unchanged source ground by f35. The weapon moves toward low-center, reaching a bounded 60-pixel lower and 45-pixel leftward optic-guide correction, 4° additional downward pitch and up to 8° additional camera-space roll.
- f36–45: hold 0.30 m eye height while camera/added weapon roll clear together by f45. The source foreground motion still runs at its original frames.
- f46–69: recover only from this low body height. The camera settles at 0.34 m above ground, not standing height; the weapon stays 60 pixels lower, reaches 50 pixels left, flattens with 8° additional downward pitch, and receives only 12 mm of additional forward travel after f45.

All values and quintic envelopes are in `correction_design.json`. They are bounded artistic choices guided by the actual pixels, not recovered COD metres or 3D angles. The two weapons have different geometry, so projected virtual optic guides are directional evidence rather than calibrated silhouette equivalence. Native Eevee frames must establish the visible result, including the reference-angle bound.

## Checks completed

- 114 saved Actions: all 112 predecessors unchanged; only the rig/camera pair added.
- Prior geometry, rest pose, bindings, drivers, materials, packed images, cameras, NLA and active/default state preserved on fresh reopen.
- 545 samples across the complete Action at 480 Hz, all bone matrices finite; all drivers valid.
- Exact all-bone equality to r5 over f1–11, including subframes.
- Maximum hand-target residual: left 0.002330 mm, right 0.001712 mm, below the unchanged 0.1 mm gate.
- Shortest-angle wrist guard residual: r5 peak 6.512843°, r6 peak 0.763097°. No sampled frame is worse than r5. The remaining subframe residual around f37.5–37.875 is disclosed; zero guard error is not claimed and no guard limits changed.
- 1,046,760 evaluated skin/weapon vertex samples were finite. No onscreen arm/weapon vertices crossed the unchanged ground in probes at f1,12,20,21,28,32,35,41,45,55,69. These are geometry probes, not a render-based occlusion proof.
- Paired camera/rig matrices matched design within 0.000001; the camera-relative optic target was within 0.000846 pixels.
- `capture_pair.py` exercised all 69 native frames and restored all Actions, scene fields, camera-unbound state and object defaults exactly.
- 17 source-free contract/adversarial tests passed.

## Reproduce privately

Use an untracked local authoring directory containing this recipe. Supply the existing private r5 BLEND locally; it is not included in the source-free package. No embedded BLEND scripts are executed.

```sh
blender --background --factory-startup --disable-autoexec /private/path/halcyon_prone_crawl_r5.blend --python-exit-code 1 --python revise_entry.py
blender --background --factory-startup --disable-autoexec halcyon_prone_crawl_r6.blend --python-exit-code 1 --python verify_revision.py
blender --background --factory-startup --disable-autoexec halcyon_prone_crawl_r6.blend --python-exit-code 1 --python test_capture_pair.py
python -m unittest discover -p test_contracts.py -v
```

The authoring script refuses an incorrect source/version/Action count, an existing output, source overwrite, contact failure or preservation failure. It generates local baseline/receipts for fresh verification. The generated BLEND is private working material and must not be committed/uploaded with this source-free recipe. Saving on another machine may yield a different file hash; regenerate and pin that machine's receipts and verify both Action fingerprints before capture.

## Genuine capture contract

Aella owns foreground Blender Eevee Viewport Render Animation and the separate finalization/preservation repair. This executor has no display; no substitute render was generated here.

Use `capture_pair.bind_pair()` before capture. It verifies the actual BLEND hash and both Action fingerprints, guards the source pose, selects the original review camera, and sets native frames 1–69 at 60 fps. `select_frame(f)` confirms both bindings and returns the actual per-frame camera/rig matrices. The existing capture process can record these alongside image hashes. After capture, call `restore_pair()` and independently verify source preservation before reporting a clean audit. Do not save the temporary capture state over either source.

A weapon-only capture, a camera-only capture, a missing Action fingerprint or a static substitute camera is not this candidate. Do not crop, reframe, change FOV, retime, or move the environment. See `capture_request.json` and `frame_map.json`.

## Runtime boundary and camera sidecar

This is an authoring handoff. Existing runtime stance eye-height easing is separate from this new camera Action. The currently inspected FBX path does not automatically carry camera Actions; the actual game camera uses player eye/direction/lean. No runtime files changed.

`camera_motion_samples.json` is a source-free 480 Hz evaluation sidecar. Coordinates are Blender world metres, +Z up; camera local +X is right, +Y up and -Z forward. Every sample includes the evaluated absolute camera matrix and common world delta `D = C(frame) × inverse(C(initial))`. The armature-object motion is exactly `D × R(initial)`.

Future integration must define the Blender-to-game axis conversion and how authored height replaces/composes with stance easing. It must remove common object co-motion from a camera-relative viewmodel export or otherwise avoid applying it twice. Do not blindly add this 1.30 m descent to the generic stance drop, and do not treat an armature-only export as proof the camera motion reached the game. That binding remains explicitly pending.


### Confirmed consumer route and explicit height ownership

Aella identified the current route: PR34 `technical_handoff/export_prone_fbx.py` samples bones/actors and exports ARMATURE/MESH; `tools/export_viewmodel.py` disables camera export, and `tools/import_fbx_viewmodel.py` has no camera consumer. `src/app.rs` takes the world view from `Player.eye()`, `direction()` and `camera_up()`; `viewmodel_draw.rs` uses a separate fixed-origin weapon camera. [Current stance easing](https://github.com/RHS059/rust_duty/blob/87d1d6c51cd76e0fed2b4a6beb1404c66633daa9/src/sim.rs#L1078-L1110) already approaches prone eye height 0.2794 m over 0.4 s.

The future height contract is replacement during the r6 clip, not an additive full drop. For continuity from the actual entry stance, the sidecar supplies normalized descent `a = source_descent / 1.26`; a runtime adapter can own height as `entry_eye_height + a * (target_prone_eye_height - entry_eye_height)`. At f1, a=0; at f69, a=1. The impact trough briefly exceeds 1, retaining the authored overshoot. In the source scene, entry=1.60 m and endpoint=0.34 m reproduce the exact authored heights. Runtime uses its entry height and 0.2794 m prone target, subject to collision safety. This endpoint-normalized contract is documented, not implemented or parity-tested in the game.

The camera and rig Actions hold their f69 values with constant extrapolation while the clip owns the view. At runtime ownership release, the final height must match the same prone target without a second easing/drop. Camera pitch and roll return to zero at the endpoint. The actual source preview remains unnormalized and uses the exact paired camera/rig matrices. Weapon-object co-motion must still be removed or separated before exporting a camera-relative viewmodel, so the camera path is not applied twice.
