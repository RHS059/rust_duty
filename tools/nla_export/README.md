# Single-file weapon animation export

Upload/replace **`assets/authoring/weapon_animations.blend`** in this repository. Keep this path unchanged on subsequent uploads. The **Export canonical weapon NLA tracks** Action automatically runs on source changes (or use **Run workflow** against the desired branch). No per-animation uploads are needed.

Download the **canonical-weapon-fbx** artifact from the successful run. It contains `<clip-id>.fbx` for every explicitly designated logical NLA track, plus `manifest.json` documenting source hash, selected scene/objects, camera pairing, original frame range and FPS, take name, duration, and output hashes. The artifact belongs to that exact commit/run. A failed export never publishes a partial bundle. GitHub artifact retention applies; the BLEND stays in the repository.

## Authoring contract inside the one BLEND

The `EXPORT_MANIFEST` Blender text datablock is the only required configuration. It travels inside the BLEND; no JSON upload is required. Its schema is `rust-duty-weapon-nla/v1` with a nonempty `clips` list:

```json
{
  "schema": "rust-duty-weapon-nla/v1",
  "clips": [{
    "id": "reload",
    "scene": "Reload",
    "rig": "Arms",
    "track_name": "EXPORT::reload",
    "frame_start": 1,
    "frame_end": 120,
    "fps": 60,
    "fps_base": 1.0,
    "bake_step": 0.125,
    "camera": "ViewCamera",
    "camera_track_name": "EXPORT::reload_camera"
  }]
}
```

- Each ID is a unique lowercase identifier using letters, digits and underscores; it controls the stable FBX filename and sole FBX take name.
- `scene`, `rig`, `track_name`, frame bounds and FPS are explicit. Source tracks must be named `EXPORT::...`. Historical actions and `ARCHIVE::...` tracks are never enumerated as exports.
- Every same-scene animated object/data track with the exact logical track name is enabled together. The separately named camera track is enabled only on the declared camera. Active Actions and other tracks are temporarily disabled so unrelated animation cannot leak into a clip.
- The rig's declared NLA strip range must cover the export range. The exporter does not rescale, move or retime strips. `fps_base` defaults to 1.0. The default bake interval is 0.125 native frames (480 samples/second at 60 FPS); simplification is disabled. Set an explicit smaller interval for authored detail that requires it.
- Include any required baseline animation in the designated NLA track itself, or in the authored static transforms. An active Action outside the designated track is not part of the export contract.
- `camera` and `camera_track_name` are optional; paired cameras are exported alongside rig motion, including their evaluated transforms. Cameras without a paired track remain static. No unrelated camera is selected.
- Optional `objects` is an explicit list of export object names and must include the rig. Otherwise all meshes, empties and the single armature in that scene are exported, plus the specified camera. Scenes with multiple rigs require explicit `objects`. Keep source scenes self-contained; excluded view-layer collections must not contain required export objects.
- Optional `object_name_map` maps selected source-object names to stable FBX names (for example `Arms.004` to `Arms`). Renaming only affects the in-memory export copy; source scene/rig names remain in the manifest, alongside `exported_rig` and `exported_camera`.
- Single-frame ranges are supported for static poses; integral JSON floats are accepted without retiming.
- All geometry, constraints and driver dependencies remain in the loaded source scene for evaluation. Meshes/armature are exported with evaluated motion and embedded textures. The exporter never saves over the BLEND. It reopens the pristine file for each clip to prevent cross-clip state leakage.

## Local use and checks

Use official Blender **4.3.2**, the same checksum-pinned version installed by `.github/actions/setup-blender/action.yml`:

```sh
python -B -m unittest discover -s tools/nla_export -p 'test_*.py' -v
blender -b --disable-autoexec --python-exit-code 1 --python tools/nla_export/smoke_blender.py
blender -b --disable-autoexec --python-exit-code 1 --python tools/nla_export/export.py -- --source assets/authoring/weapon_animations.blend --output build-assets/weapon-fbx
```

The output directory must be empty. The small smoke test constructs its own temporary source and checks isolated export mechanics, stable output names, sole takes, paired-camera selection and source preservation. It does not certify the completeness or quality of the weapon library.

## Runtime integration boundary

These are ordinary evaluated FBXs compatible with the repository's FBX conversion stage (`tools/import_fbx_viewmodel.py`). The timing and take selection inputs are supplied in the artifact manifest. Existing runtime bundles/builds remain independently supported. This Action deliberately does not invent a per-clip skeleton, actor mapping, camera runtime convention, material policy, crop or loop setting, and does not overwrite runtime assets. Feed each FBX through the supported converter only with its explicit approved runtime mapping. Exporting a camera in FBX does not, by itself, add camera support to a game consumer.

Workflow permissions are read-only. It performs no pushes, credential changes or public uploads. Embedded scripts are not auto-executed. Changes to the exporter/workflow also trigger it, permitting an initial export after a bot-authored source publication (which does not itself trigger follow-on Actions).
