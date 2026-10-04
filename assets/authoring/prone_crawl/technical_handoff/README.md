# Prone technical export handoff

Status: isolated technical export verified; independent fixed-view visual review and Aella's canonical integration remain pending. This packet does not activate runtime clips or certify crawl loops. No rendering was attempted.

## Identities

- Corrected packed BLEND SHA256: `7807f7e16f6fabb2833d9e61ae5a942ee9a57f455a6c3e40e15ed4e03fa153b4`
- Previous source commit: `6dd8674b1483a8b283f86afceaf7e1c8f6a2d7b5`, BLEND SHA256 `959ecf46308195f942af817ee845173db9e8b4fd8f39c4cdd455a29bbfebcb49`
- Final source map: PR33 `85f43ef3bb6f2dbfa73f04eb8c293a0f4aa67df1`
- Corrected FBX SHA256: `a02cb5d57c7112d039d5181670431de3b782811106aa081cc873e41f499573ff`

## Proposed stable take mapping for Aella

The registry currently has no prone bindings. These suffix-free identities are integration proposals and actual isolated FBX take names, not newly installed runtime hooks. All five config entries have `loop=false`, `production_activation=false`, absolute pose space, and no additive derivation.

| Source Action | Stable FBX/clip ID | Native reference frames (half-open) | Blender frames | FBX duration | 480 Hz samples |
| --- | --- | --- | --- | --- | --- |
| prone_crawl_enter_r1 | prone_crawl_enter | R3 [2241,2310) | 1–69 | 68/60 s | 545 |
| prone_crawl_forward_segment_r1 | prone_crawl_forward | R2 [4932,5173) | 1–241 | 4 s | 1921 |
| prone_crawl_backward_segment_r1 | prone_crawl_backward | R2 [5280,5509) | 1–229 | 3.8 s | 1825 |
| prone_crawl_right_segment_r1 | prone_crawl_right | R2 [5628,5767) | 1–139 | 2.3 s | 1105 |
| prone_crawl_left_segment_r1 | prone_crawl_left | R2 [5844,5899) | 1–55 | 0.9 s | 433 |

Blender frame = native source frame − source start + 1. The full displayed reference excerpt lasts sample_count/60 seconds; exported first-to-last pose duration is (sample_count−1)/60 seconds. The one-frame difference is deliberate endpoint semantics, not retiming.

## Verified technical scope

Blender 4.3.2; source 60 fps; evaluated export 480 Hz; 72 deform bones, three existing skinned meshes and two rigid actors. Existing axis, units, strip baking, exact endpoint keying, no simplification and packed texture settings were reused. Each FBX take has675 curves with precisely the stated key count and duration. Every FBX key and sampled native array is finite. The exporter never saves its input BLEND.

The initial technical export exposed firing-hand IK residuals between native keys: forward 4.459 mm and backward 0.822 mm at 240 Hz. The existing 60 fps check had missed them. Only shoulder compensation sampling was corrected; weapon trajectories and all 664 native-frame bone matrices remain exactly identical, as do all 104 older Actions. No rig constraints, limb lengths, root, camera, meshes or materials changed.

Corrected contact checks cover 240 Hz and 480 Hz. All 5,829 evaluated 480 Hz poses pass the 0.1 mm wrist-target threshold; worst residual 0.0154 mm. `before_after_contact.json` preserves the failed initial result and the corrected evidence. This is numerical attachment validation, not a claim of visible hand deformation quality.

## Unfinished boundaries

Forward/backward/right source recurrence pairs remain provisional. Existing authored pose/velocity gaps are retained in `seam_diagnostics.json`; no cyclic closure or retiming was introduced. Left remains a 55-frame segment-only. Entry and the four segments are separate excerpts and must not be hard-concatenated. Holding the terminal pose is a diagnostic interpretation, not authorization to activate an unfinished loop.

Aella alone owns canonical append, stable runtime mapping approval, production exporter configuration, asset container conversion, controller integration and Colab. No gameplay build/load/triggered-playback checks have been performed. The unresolved Eevee rendering denial remains held; no visual acceptance or 80% match claim is made.

## Reproduction and recovery

`restore_packet.py` reconstructs the byte-exact archive parts, verifies every member and extracts the FBX, evaluated oracle and packed textures to a new destination. The source BLEND remains in the parent authoring directory, not duplicated in this packet.

Run Blender with `--background --factory-startup --disable-autoexec SOURCE.blend --python-exit-code 1 --python export_prone_fbx.py -- --output-dir NEW_DIR --config proposed_export_config.json`. It refuses to overwrite existing artifacts. Then run Blender background with `--python-exit-code 1 --python verify_export.py -- --directory NEW_DIR --config proposed_export_config.json --output REPORT.json`. The verification report separates technical passes from visual/contact acceptance and production activation.

`compare_native_poses.py --old OLD.blend --new NEW.blend --output REPORT.json`, run inside background Blender after `--`, reproduces the native-pose preservation comparison. No render operator, runtime code, common export file or source map is changed by these tools.
