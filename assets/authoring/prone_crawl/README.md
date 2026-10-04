# Prone entry r1: source WIP

Editable source: `halcyon_prone_crawl_r1.blend`, Blender 4.3.2, 60 fps. One new Action: `prone_crawl_enter_r1`, frames 1–69 inclusive. This is a nonlooping entry, not a crawl loop or exit. Independent motion review and runtime integration are pending.

## Pinned inputs

- Frozen source: `4363837e:assets/authoring/jump/halcyon_jump.blend`, SHA256 `a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`
- Candidate SHA256: `793546897db5634fca6ba6da7cefd5240e3712932c239bbabea7dfaa0f03419e`
- Aella source map: [PR33 checkpoint](https://github.com/RHS059/rust_duty/blob/fe5ab7cc6793a9fe2964fd9fc00d10e534e66ed8/references/movement/remaining_20261004/source_map.json)
- Reference: R3 `Modern_Warfare_2022_Movement_Reference.mp4`, SHA256 `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`
- Exact source excerpt: zero-based half-open `[2241,2310)`, 69 native frames. Blender frame = source frame − 2241 + 1. A held playback of all 69 images lasts 69/60 s; the Action's first-to-last sample interval is 68/60 s.

## Motion and limits

This WIP retargets the visible optic-region foreground path, apparent size and roll onto the established viewmodel using `righthand_prop`. The reference and model differ. Single-view apparent size and rotation are used as a constrained artistic depth/roll inference, not recovered physical motion. This first candidate does not independently match receiver or hand deformation; the genuine Eevee viewport preview is required for independent review. There is no artistic score or acceptance claim.

Native-frame Lucas–Kanade tracking rejects inconsistent forward/backward tracks and fits a robust optic-region similarity. Five-frame quadratic smoothing reduces measurement jitter without retiming. The fitted endpoint remains distinct from standing ready. No forced neutral closure, source warp, invented exit, full-body animation, or world/camera descent is introduced. The game continues to own stance/camera motion. Four directional HIP crawl Actions await source-owner native windows and cycle evidence. Prone ADS remains secondary reference evidence for Aella's existing reusable layer.

All 103 prior Actions, rig/rest pose, meshes, weights, materials, drivers, constraints, packed images, cameras, NLA and original active state are preserved; one new Action yields 104. Authoring and fresh reopen fingerprints are in `authoring_preservation.json` and `reopen_preservation.json`. Their passes concern data integrity only.

## Reproduce

Run Blender with `--background --factory-startup --disable-autoexec FROZEN_BASE.blend --python-exit-code 1 --python author_entry.py -- entry_design.json NEW_OUTPUT.blend`. The source recipe refuses overwrites and validates the frozen source hash. It never renders or saves the input. `validate_source_structure.py` performs read-only fresh-file preservation checks with `--output REPORT --baseline baseline_fingerprint.json --expected-actions prone_crawl_enter_r1`.

Optional track recreation uses Python, OpenCV, NumPy and Pillow: `measure_reference.py --reference ORIGINAL.mp4 --output-dir OUTPUT`. `fit_entry.py` uses the adjacent tracks and reference geometry to recreate the design with NumPy/SciPy. Neither script writes source excerpts or changes Aella's source inventory.

Render only through foreground Blender's Eevee Viewport Render Animation, using the unchanged `RD First Person Review` camera and guarded initialization. Independent review precedes Aella's stable runtime mapping and export. Runtime ID remains explicitly unassigned. No common exporter, registry, runtime controller, or Colab file is changed here.
