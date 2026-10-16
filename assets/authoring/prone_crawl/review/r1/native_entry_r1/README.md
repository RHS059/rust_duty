# Prone entry native review evidence

All 69 original, unstacked 1280×720 Eevee Viewport Render Animation PNGs.
The archive and part transport contain byte-identical native captures. Nothing is
rendered, resized, retimed or transcoded by this packaging step.

Source commit: `99a804349c3a5ca7d7a9fa64f0c4f213d01e9b35`.
Action `prone_crawl_enter_r1`, frames 1–69, maps exactly to R3 [2241,2310).
The comparison is WIP. Geometry differs; depth/roll are inferred from foreground
optic-region 2D evidence. The model camera remains fixed. No artistic acceptance.

Use `python restore_native_frames.py` to verify and reconstruct the ZIP from its
parts. Extract with `python -m zipfile -e prone_entry_r1_native_frames.zip extracted`.
The restore script validates all part hashes, complete ZIP hash, member names and
individual original PNG hashes. It refuses to overwrite different existing bytes.

`capture_recipe/` preserves the actual capture and composition code plus original
proof/settings provenance, avoiding dependence on an ephemeral render workspace.
The recipe pins current source and reference identities. It includes no source
BLEND or duplicate reference video, which remain in their existing repository locations.
