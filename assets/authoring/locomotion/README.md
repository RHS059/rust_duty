# Locomotion authoring source

This is the portable, editable source for the existing **normal sprint locomotion**
checkpoint. `locomotion.blend` preserves all 61 Actions, all seven NLA tracks,
185 valid native drivers, and the packed textures. Original entry/exit Actions,
the selected AngleFix loop, 35 phase-specific exits, connected transitions,
diagnostic staging, and earlier revisioned Actions remain available.

**This frozen checkpoint contains no authored regular-walk Action.** Walking at
this checkpoint was procedural Rust bob. A newly authored walk must be added as
a separately versioned Action; it is not silently synthesized by this exporter.
Retained reload Actions are historical context, not the current reload master.

## Exact headless export

Run from the repository root with Blender **4.3.2**, whose bundled Python includes
NumPy. Use a new output directory; existing export files are never overwritten.

```sh
blender --background --factory-startup --disable-autoexec \
  assets/authoring/locomotion/locomotion.blend \
  --python-exit-code 1 \
  --python assets/authoring/locomotion/export_locomotion.py -- \
  --config assets/authoring/locomotion/export_config.json \
  --output-dir build/locomotion-fbx
```

The command creates `locomotion.fbx`, `native_oracle.json`, `native_oracle.npz`,
and extracted packed textures in the output directory. It does not save changes
to the input BLEND and executes no embedded source Text blocks. The original
source checksum and complete Action/NLA/driver/texture snapshot are checked
before export; source bytes are checked again afterward.

Source time is **60 fps**. Evaluation and FBX baking use **480 Hz**, with
`bake_anim_step = 0.125` source frames and simplification disabled. Some old
converter manifests reported 240 fps despite retaining 480 Hz key records.
Do not use that old metadata to resample or reinterpret this source.

The reviewed selection is frozen in `export_config.json`:

- Seven named gameplay takes: ready, original entry/loop/exit, connected entry,
  loop-to-exit, and connected exit
- Thirty-five phase-specific exits, `normal_exit_bridge_000` through `_034`
- One staged `normal_diagnostic_sequence` take, explicitly not gameplay input

That is **43 FBX source takes = 42 gameplay takes + one diagnostic**. A constant
ready Action is made only in memory from exact original entry frame 1.

## Required runtime selection and settle derivation

Aella's common workflow owns conversion, bounded per-take compilation, companion
merging, and runtime semantic bindings. This directory changes none of those.
Its `source_take_groups` reproduce the established seven conversion groups.

For the **43-clip gameplay package**, exclude `normal_diagnostic_sequence`, then
add `normal_settle` from the already-converted `normal_exit_connected` records:

1. Select stored frames whose float32 elapsed timestamp is **>= 0.25 seconds**
   (source frames **16 through 25**, inclusive)
2. Require **73 frames** at the existing 480 Hz sampling and an exact first
   selected timestamp of 0.25 seconds
3. Copy every bone, rigid-actor, and visibility byte unchanged. Subtract 0.25
   only from each timestamp and encode that timestamp as little-endian float32
4. Mark the derived clip nonlooping. Require first time 0.0 and last time
   **0.15000000596046448** seconds
5. Preserve all other original clip-record bytes. Before combining batches,
   require identical companion geometry and skeleton/actor-binding bytes;
   preserve the converter's interpolation guards, allocation limits, and CRC
   validation

Do not independently rebake or interpolate settle. For the optional diagnostic
package, retain the diagnostic too: the result is **44 runtime clips**. The
byte-subrange operation above was checked against the existing 43-clip runtime
fixture: all 73 derived frame records match byte-for-byte. No claim is made that
a future common-workflow conversion produces a byte-identical entire package.

## Verified handoff

- Both identified upstream BLEND hashes were verified; identities are in
  `provenance.json`
- Sanitized source was reopened in Blender 4.3.2 with auto-execution disabled;
  all 61 Action fingerprints, seven NLA tracks, packed-image bytes, and driver
  definitions match the final source; all 185 drivers evaluate as valid
- The portable export's **217 native-oracle arrays are byte-identical** to the
  historical export oracle; maximum numeric difference is **0.0**. Sample
  metadata and all contact samples also match exactly
- A second fresh portable export was run for repeatability. See
  `validation.json` for the final checks and clip counts
- Source and scripts contain no machine-local paths. Decompressed BLEND scanning
  checked for original workspace, home, temporary, and checkpoint path fragments

This is numerical/source-preservation evidence, not renewed artistic acceptance,
whole-arm clearance certification, or an end-to-end gameplay/rendering pass.
FBX container bytes can differ with exporter-generated identifiers and output
paths; reproducibility here means the frozen selection, authored curves, sampling,
and evaluated geometry/transforms, not a promised FBX SHA across machines.

## Editing and maintenance

Open `locomotion.blend` directly; textures are packed and no external BLEND is
needed. The active review is `RD_Normal_Diagnostic_Sequence`, frames 1–223 at
60 fps. Keep archived Actions and NLA tracks. A new animation should get its own
Action and updated versioned config/integrity snapshot, not overwrite original
curves. The exporter intentionally rejects unreviewed source changes.

Existing connected paths animate the `righthand_prop` location/Euler control;
IK, hand attachment, and wrist guards are native and remain active. Evaluation
resets unkeyed controls from `RD_00_Supplied_Base_Guarded_Recovered` for each
Action. Exports select three arm meshes and the two rigid actors
`hk416_weapon` / `hk416_magazine`, with 72 deform bones. The zero-scaled,
reload-only outgoing magazine, helpers, camera and scenery are excluded.
Blender `(x,y,z)` becomes `(x,z,-y)` in FBX; the game applies its existing whole-
model Y rotation once. Runtime ownership/ADS/reload bindings are outside scope.

`sanitize_source.py` records the optional, one-time packaging step from the
identified original final source. It removes stale embedded recovery/UI texts,
replaces them with a short readme, makes paths relative, and reopens the result
to verify animation/rig integrity. It is not required for normal exports and does
not recreate authoring decisions from reference footage. `source_integrity.py`
provides the shared fingerprint helpers. `source_integrity.json` records every
preserved Action plus NLA, packed-image and driver definitions.
