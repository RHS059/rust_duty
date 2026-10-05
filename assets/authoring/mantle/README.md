# Aella mantle and vault source, diagnostic r1

This is the first editable Blender weapon-root checkpoint for the remaining
movement work. It is **diagnostic**, with no independent fidelity score, no
80% claim, no hand/contact approval, and no export/runtime integration yet.

Two new Actions are in `aella_mantle_r1.blend`:
- `aella_vault_low_r1`: source R3 native frames [7284,7348), Blender 1–64
- `aella_mantle_onehand_r1`: source R3 [7787,7883), Blender 1–96

Both use the exact original 60 Hz clock, with source frame = start + Blender
frame − 1. Excerpts include contextual lead/tail and do not identify engine
input timestamps. Their last stored frame is an actual observed frame, not
an invented repeated endpoint. The source map owner supplies separately
verified lossless cuts and full decoded PTS. Source SHA256 is
`491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.

The initial spatial keys are artist hypotheses constrained by viewed source
poses and event ordering. They are not a 3D reconstruction or measured source
translations. `design_r1.json` records them explicitly. Root tracks remain
unlocked. Current hands retain inherited weapon-follow; the source's free-hand
release/regrasp has not yet been authored. These limitations are deliberately
visible in the source metadata rather than being hidden by a pass claim.

## Frozen baseline

This separate source copy extends the public r5 movement source at current main
`61c3ccd26e8cf9f288e5e56c536c92b7d30409ef`, SHA256
`36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d`.
PR27 `d4d9b622` declares the same exact r5 source bytes. A fresh structural
comparison against that revision's ADS source (`3acdf3e2…`) found identical
meshes, armature rests, skin weights, object bindings/constraints, materials,
cameras, base Action, driver definitions and packed images. The prior 82 Actions
remain unchanged. `baseline_snapshot.json` and `baseline_comparison.json` retain
that measured evidence. The original NLA/active Action state stays intact; new
Actions use fake users and are selected explicitly by the evaluation script.
No production source file is replaced and no private Soldier assets are added.

## Reproduce and inspect

With Blender 4.3.2, run `author_movement.py --kind mantle` against the frozen
`../locomotion_directional/r5/halcyon_hip_directional_r5.blend` in background
with factory startup, disabled auto-execution and `--python-exit-code 1`.
Use a fresh output copy; the script refuses to overwrite an existing result.
`--kind climb` creates the sibling roof-ascent source. It performs no rendering.

Reopen each saved source and run `evaluate_movement.py --output NEW_DIRECTORY`
for integer-frame evaluated weapon matrices and quarter-frame wrist/guard/reach
diagnostics. Raw projected points are marked uncertain until visibility review.
Existing exporter/runtime owners remain responsible for their separate boundary.

All requested previews must use foreground rendered Eevee viewport. An initial
cloud-viewport attempt exited before saving any witness; that is a render blocker,
not a successful preview. No Cycles, background/offscreen, or substitute rendering
was performed. Source authoring and validation continue independently.

## Fresh diagnostic finding

A reopened quarter-frame sweep found large inherited wrist-guard clipping:
42.60 degrees for low vault and22.53 degrees for the one-hand mantle. Wrist
target positions remain within0.000762mm, but positional IK success does not
certify wrist orientation/contact. Both clips fail contact review at this
checkpoint. The next hand pass must solve the release and forearm roll without
widening guards or changing rests. The WIP is preserved despite this failed gate.
