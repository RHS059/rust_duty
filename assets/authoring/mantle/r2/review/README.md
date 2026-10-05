# Low-vault r2 native viewport evidence

64 original 1280×720 PNGs captured at native60fps using foreground Blender4.3.2
Eevee Viewport Render Animation. No source/model/camera edit or source save.
Source SHA256:740e7e2b16d6947075c321467cfe21d36314f68b93829cf8a2d954b4d382cdb5.
PR35 commit:3bc4694df9a8704dd8a6381363f53e23f8a530fb.

Action aella_vault_low_r2, Blender1–64, maps to R3 [7284,7348).
The actual output paths are resolved by Blender's render.frame_path API, checked
against observed scene-frame events and every existing PNG. The map records exact
native/candidate PTS at1/15360, dimensions, bytes and hashes. Duplicate poses are valid.

The author-approved capture-only adaptation replaces the prior still-image loop with
one animation=True operator call. Guarded reset, muted legacy NLA, existing companions,
fixed camera and scene lights/world are retained. The source and every Action curve,
mesh/material structure, drivers and packed images were verified unchanged afterward.

Reconstruct and verify exact ZIP bytes with python restore_native_frames.py, then
extract with python -m zipfile -e vault_r2_native_frames.zip extracted.
Original source remains in its existing repository location; no duplicate BLEND is included.

This is diagnostic capture evidence. Support-hand depth/hidden motion is inferred;
there is no artistic, hand-surface or runtime approval. Inspect the complete trajectory.
