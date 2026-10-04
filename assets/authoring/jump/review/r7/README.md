# Existing jump r7 native review evidence

This add-only handoff packages the original unstacked Eevee PNGs used for the published r7 comparison. It contains no newly rendered or converted frames, no new video clip, and no animation revision. The 27-file source package and Blender source remain unchanged.

## Immutable pins

- Source commit: `4363837e46ee89b5ca8baa1b5c08e1e3f81cac91`, `assets/authoring/jump/halcyon_jump.blend`
- Source SHA256: `a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`
- Published paired media commit: `84e9ed1bacf56a12243e7668a672a0ba0e76ec83` in `RHS059/rust_duty_updates`
- Paired MP4 SHA256: `9584dd3e3c852ff810caa608d3c7afd003b19d3b5548302a326e6d87c0f29b3e`
- COD reference SHA256: `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`

## Restore original PNGs

The transport stores a lossless ZIP container in eight exact binary parts, avoiding inline transport limits. PNG members are byte-identical to the original render outputs, validated against the original capture proof.

From this directory:

```sh
python restore_native_frames.py
python -m zipfile -e jump_r7_native_frames.zip extracted
```

The restore script verifies every part, the full archive, ZIP integrity, and every original PNG hash. It refuses to overwrite a different existing archive. No network request or third-party package is needed once this directory is downloaded.

Archive: `jump_r7_native_frames.zip`, 63,090,765 bytes, SHA256 `12e5aee93e50a2bc2f5b1763ee5e5afee9b4fe2477102cd07db85469e8a7e504`

## Complete coverage and mapping

All 65 original 1280×720 images are included:

- `frames/jump_takeoff_r7/f0001.png` through `f0012.png`
- `frames/jump_air_r7/f0001.png` through `f0024.png`
- `frames/jump_land_r7/f0001.png` through `f0029.png`

These are complete native samples of all three r7 Actions. The published paired window is also complete: 100 frames at 60 fps, source zero-based n4014–4113 inclusive, at native speed. `reference_frame_map.json` is the exact map used by the paired video. `frame_index.json` reverses that map: each original PNG lists every paired output and COD source frame that uses it.

The paired edit selects 63 distinct Action samples. Takeoff f0012 and air f0024 are captured seam endpoints, included here but superseded by the next Action's equivalent first pose in the paired edit. Early ready holds reuse takeoff f0001 for paired outputs 0–18; late holds reuse land f0029 for outputs 82–99. Outputs 19 and 81 are the native start/end frames. This package covers the complete existing r7 capture and paired review window; it does not claim a full-length render of the entire supplied COD video.

## Technical evidence and limits

`viewport_process_proof.json` is the unchanged capture proof. It records genuine foreground `bpy.ops.render.opengl(animation=True, view_context=True)` using Eevee, the fixed camera, companion Action bindings, each original PNG hash, and source/geometry/material preservation. Capture occurred before source publication, so the proof's original `source_commit: null` remains unchanged; the manifest above supplies the verified publication pin.

`delivered_r7_landmarks.json` contains measured pixel tracks from the delivered r7 PNGs, covering the ready anchor and landing frames. Intermediate takeoff/air track entries are empty because this diagnostic measured only the landing correction. `delivered_receiver_check.json` compares the receiver dip against COD and r6; neither file is a similarity score or artistic acceptance. `measure_delivered_landmarks.py` is the exact script used for that measurement, renamed for this handoff. It needs NumPy and OpenCV and accepts `--frames` and `--output`.

The existing source package already contains the 120 Hz evaluated projection/framing samples in `jump_technical_validation.json`, camera/virtual-guide definitions in `reference_geometry.json` and `front_sight_geometry.json`, and exact authored root-control values in `authored_root_keys.json`. Those files remain at the pinned source commit. No additional unexported evaluated bone-matrix packet is claimed.

The reference and model geometry differ, single-view 3D transforms are inferred, and COD retains its world/camera arc while the Eevee camera stays fixed. Independent reviewers own similarity judgments and scoring. R7 remains unchanged pending that review.
