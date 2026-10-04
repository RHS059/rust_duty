# Prone entry and four HIP crawl segments: source WIP

Editable source: `halcyon_prone_crawl_r1.blend`, Blender 4.3.2, 60 fps. Five scoped Actions: `prone_crawl_enter_r1` and four nonlooping directional segments. Entry occupies frames 1–69 inclusive. This is a nonlooping entry, not a crawl loop or exit. Independent motion review and runtime integration are pending.

## Pinned inputs

- Frozen source: `4363837e:assets/authoring/jump/halcyon_jump.blend`, SHA256 `a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`
- Entry-only predecessor SHA256: `793546897db5634fca6ba6da7cefd5240e3712932c239bbabea7dfaa0f03419e`
- Current 108-Action source SHA256: `7807f7e16f6fabb2833d9e61ae5a942ee9a57f455a6c3e40e15ed4e03fa153b4`
- Aella source map: [PR33 checkpoint](https://github.com/RHS059/rust_duty/blob/fe5ab7cc6793a9fe2964fd9fc00d10e534e66ed8/references/movement/remaining_20261004/source_map.json)
- Reference: R3 `Modern_Warfare_2022_Movement_Reference.mp4`, SHA256 `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`
- Exact source excerpt: zero-based half-open `[2241,2310)`, 69 native frames. Blender frame = source frame − 2241 + 1. A held playback of all 69 images lasts 69/60 s; the Action's first-to-last sample interval is 68/60 s.

## Motion and limits

This WIP retargets the visible optic-region foreground path, apparent size and roll onto the established viewmodel using `righthand_prop`. The reference and model differ. Single-view apparent size and rotation are used as a constrained artistic depth/roll inference, not recovered physical motion. This first candidate does not independently match receiver or hand deformation; the genuine Eevee viewport preview is required for independent review. There is no artistic score or acceptance claim.

Native-frame Lucas–Kanade tracking rejects inconsistent forward/backward tracks and fits a robust optic-region similarity. Five-frame quadratic smoothing reduces measurement jitter without retiming. The fitted endpoint remains distinct from standing ready. No forced neutral closure, source warp, invented exit, full-body animation, or world/camera descent is introduced. The game continues to own stance/camera motion. Four directional HIP segments are now authored from source-owner validated windows; see `crawl_r1/README.md`. Every segment is nonlooping; cycle endpoint evidence remains pending. Prone ADS remains secondary reference evidence for Aella's existing reusable layer.

All 103 prior Actions, rig/rest pose, meshes, weights, materials, drivers, constraints, packed images, cameras, NLA and original active state are preserved; the preserved entry-only checkpoint has 104 Actions, and the current four-direction segment checkpoint has 108. Authoring and fresh reopen fingerprints are in `authoring_preservation.json` and `reopen_preservation.json`. Their passes concern data integrity only.

## Reproduce

Run Blender with `--background --factory-startup --disable-autoexec FROZEN_BASE.blend --python-exit-code 1 --python author_entry.py -- entry_design.json NEW_OUTPUT.blend`. The source recipe refuses overwrites and validates the frozen source hash. It never renders or saves the input. `validate_source_structure.py` performs read-only fresh-file preservation checks with `--output REPORT --baseline baseline_fingerprint.json --expected-actions prone_crawl_enter_r1`.

Optional track recreation uses Python, OpenCV, NumPy and Pillow: `measure_reference.py --reference ORIGINAL.mp4 --output-dir OUTPUT`. `fit_entry.py` uses the adjacent tracks and reference geometry to recreate the design with NumPy/SciPy. Neither script writes source excerpts or changes Aella's source inventory.

Render only through foreground Blender's Eevee Viewport Render Animation, using the unchanged `RD First Person Review` camera and guarded initialization. Independent review precedes Aella's stable runtime mapping and export. Runtime ID remains explicitly unassigned. No common exporter, registry, runtime controller, or Colab file is changed here.

## Current directional checkpoint

Forward 241 frames, backward 229, right 139 and left 55 are authored as observed nonlooping WIP segments. `crawl_r1/` contains their independent source recipe, witness selections, fresh preservation checks and technical attachment diagnostics. All 104 entry-checkpoint Actions remain unchanged. No preview has been produced while the rendering authorization clarification remains unresolved, and no artistic acceptance or game export is claimed.

The initial directional checkpoint exposed a right-arm reach limit during extreme forward/backward poses. The current source adds minimal right-clavicle location keys only within the four owned Actions; no constraint, limb length, root, camera or prior Action is changed. Fresh evaluation of all 664 directional samples passes a 0.1 mm bone-origin attachment threshold (worst approximately 0.0152 mm). This numerical repair still requires visible review.

## Nonrender technical handoff and subframe repair

The 240 Hz export check found a remaining between-frame firing-hand reach gap, previously missed at 60 fps. Only new-Action shoulder location sampling was densified to 480 Hz. All 104 older Actions, all weapon curves and every native-frame bone matrix remain exactly unchanged. The corrected five-take FBX passes inventory, bake timing, finite-key, and 240/480 Hz numerical contact checks (worst wrist residual 0.0154 mm).

See `technical_handoff/README.md` for suffix-free proposed take IDs, exact source/Action mapping, failed-initial versus corrected evidence, and byte-exact FBX recovery. This is an isolated technical export, not production activation or artistic acceptance. All four directions remain nonlooping segments. No render was attempted.
