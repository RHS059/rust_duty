# Blender-authored ADS r1

`ads.blend` is a separate packed, editable copy of the canonical locomotion source with three new independent Actions and muted NLA tracks. The canonical `../locomotion/locomotion.blend` is unchanged. Existing sprint, `normal_walk_r1`, archived reload Actions and source controls remain intact.

## Clip contract

| Action / runtime semantic name | Source range, 60 fps | Duration | Loop |
| --- | --- | --- | --- |
| `ads_entry_r1` | 1–16 | 0.250 s | No |
| `ads_hold_r1` | 1–61 | 1.000 s | Yes |
| `ads_exit_r1` | 1–16 | 0.250 s | No |

Entry starts at the exact existing `normal_ready` pose. Exit is its authored reverse. Entry end, hold and exit start share the same aimed pose. The hold is intentionally static, so releasing at any hold phase and reversing either transition does not introduce a respiration-phase mismatch. There is no runtime procedural ADS motion or camera-based replacement in these source assets.

The six keyed `righthand_prop` translation/Euler channels move the actual weapon. Its existing native weapon-follow controls drive both hands, forearms, wrist guards and seated magazine. All other channels are frozen from the original ready pose. Entry uses 16 manually generated native keyposes with free Bezier handles, a smooth endpoint tangent, and a 3.5 mm camera-up arc while centering. These keyframes are the authoritative animation; the runtime receives evaluated baked transforms.

The gameplay defaults remain 0.220 s in / 0.160 s out; the M4 candidate uses 0.250 / 0.250. These source files do not edit gameplay readiness, accuracy or timing settings. The receiving runtime owns any phase mapping.

## Actual sight alignment

The existing camera stays at its original origin and orientation, with horizontal FOV 76°, matching the default viewmodel projection. No camera translation, rotation, zoom, geometry modification or new sight mesh is used to achieve aim.

`sight_landmarks.json` records the original mesh vertex indices for the far circular sight aperture and near central post tip. The near post top-edge midpoint and far aperture center define the visual sight axis. The inherited mesh places the post near the camera and has no central post inside the far aperture; this source fact is preserved and explicitly labelled, rather than asserting a conventional sight arrangement. `sight_alignment.json` records those local points, the unchanged camera, the ready/aimed weapon matrices and the runtime axis mapping. At the aimed hold both projected landmarks are within **0.000123 pixel** of the optical center at 1280×720.

`renders/` contains actual Blender Cycles source-camera evidence: ready, entry midpoint, aimed hold, exit midpoint and returned ready, plus an annotated enlarged sight crop. These are source renders, not screenshots of gameplay. Source materials and lighting are retained; the game's base-color material projection is a separate validation step.

## Preservation and verification

The reopened source contains **65 Actions, 11 NLA tracks, 185 valid drivers and the original packed textures**. The three new tracks are muted and `ads_hold_r1` is active for inspection. `frozen_source_validation.json` verifies all 62 original Actions, including FCurve properties, keyframe handles and modifiers, against the canonical file. It also compares every original mesh, topology, UV, skin weight, mesh modifier, rig rest hierarchy/matrix, deform flag, object parent binding, camera property, driver definition, packed image and original NLA track.

A **723-sample sweep at 480 Hz** in `validation.json` establishes:

- Maximum wrist solve error: 0.000584 mm
- Maximum wrist guard clipping: 0°; minimum raw guard margin: 1.5878°
- Minimum reach margin: 149.0983 mm
- Maximum hand-in-weapon translation drift: 0.000440 mm
- Both hands remain at weapon-follow 1
- Exact native endpoint joins across all 72 deform bones, both rigid actors and every evaluated vertex of all three arm meshes
- Exact static hold endpoint and midpoint equality after reopening
- BVH ray test: the optical ray and rays 0.1 / 0.5 pixel above the post clear the weapon; the ray 0.5 pixel below meets the near post

These checks establish source rig continuity and attachment transforms. They do not certify hidden finger-to-surface contact, every possible arm/body intersection, exported interpolation quality or final gameplay presentation. Those require their own tests.

## Reproduce

From repository root, with Blender 4.3.2:

```sh
blender -b --factory-startup --disable-autoexec \
  assets/authoring/locomotion/locomotion.blend --python-exit-code 1 \
  --python assets/authoring/ads/author_ads.py
blender -b --factory-startup --disable-autoexec --python-exit-code 1 \
  --python assets/authoring/ads/verify_frozen_source.py
blender -b --factory-startup --disable-autoexec \
  assets/authoring/ads/ads.blend --python-exit-code 1 \
  --python assets/authoring/ads/verify_and_render_ads.py
blender -b --factory-startup --disable-autoexec \
  assets/authoring/ads/ads.blend --python-exit-code 1 \
  --python assets/authoring/ads/verify_sight_geometry.py
blender -b --factory-startup --disable-autoexec \
  assets/authoring/ads/ads.blend --python-exit-code 1 \
  --python tools/export_ads_fbx.py -- \
  --config assets/authoring/ads/export_config.json \
  --output-dir build/ads-fbx
```

The authoring script writes only this ADS directory and checks that the canonical input bytes stayed unchanged. The export config selects exactly three ADS Actions while keeping the original ready pose as the static binding reference. The scoped exporter restores source controls before each take, evaluates at 480 Hz, exports the existing 72 deform bones / three skin meshes / weapon and seated magazine, and does not save the source. The reload-only outgoing magazine is excluded.
