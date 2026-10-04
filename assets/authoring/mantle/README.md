# Mantle source recovery checkpoint

**Status: baseline. No mantle BLEND or mantle Actions were recovered or newly authored.** The earlier local WIP has no recoverable saved pointer. This packet makes the next authoring step reproducible; it is not a completed animation or preview.

The exact R3 reference was reconstructed from seven blobs at `58dad13f51db3dd951f43f3fd7ddc3fbd020ad00`; its 50,406,346 bytes match SHA-256 `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`. Every native frame in the low-obstacle [7284,7348), slower one-hand [7787,7883), and vehicle-roof [8507,8583) excerpts was inspected in labeled, unwarped, full-frame source sheets. There are 236 images total, displayed at 320×180. Small finger contact patches remain unresolved at that display size.

`recovery_contract.json` records phase observations, ±2-frame semantic uncertainty, protected inputs, proposed **not-yet-created** Action names and blockers. Exact native index/PTS/Blender correspondence is in `native_frame_map.csv`. The first two cuts belong here; roof evidence lives in `../climb/`.

Both mantle references require a visible free-left-hand phase and a return to the fore-end. The low-obstacle release occurs around 7293–7303; the slower take contains a long low weapon presentation and open-hand reach around 7829–7843. Neither clip proves contact force, exact contact depth, or the invisible hand path. A generic root-only motion with both grips held would omit visible behavior. No such substitute was authored.

## Preserved editable baseline

The reusable baseline is the existing `assets/authoring/jump/halcyon_jump.blend` at commit `e9317f90ea171976306e2f17c111325d948ea357`, SHA-256 `a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`. It is referenced rather than duplicating its frozen binary.

It was freshly opened with Blender 4.3.2, factory startup, embedded auto-execution disabled, and **no render/save**. `r7_baseline_inventory.json` contains all 103 Action fingerprints and extended curve metadata, eight NLA tracks, 185 native driver definitions, geometry/rest/weights/material/camera hashes, packed textures and pose defaults. No mantle/climb Actions exist in that baseline. `source_integrity.py` and `validate_source_structure.py` are unchanged inspection helpers copied from the same pinned source commit.

A separate fresh read-only invocation initialized the supplied guarded base then the established normal-ready entry frame 1. `r7_ready_baseline.json` records actual control hierarchy/properties, attachment target matrices and camera. All 10,234 evaluated skin vertices were finite; all 185 drivers valid. Left/right wrist-to-attachment positional residuals were approximately 2.72e-7/3.58e-7 rig units. These are single-pose matrix checks, **not** anatomical or finger-surface contact approval, and do not certify a detached-hand branch.

## Reproduction

Use a local clone containing the two pinned commits and new output paths:

```sh
python assets/authoring/mantle/restore_inputs.py --repo . --kind baseline --output /tmp/new-mantle-input/halcyon_jump.blend
python assets/authoring/mantle/restore_inputs.py --repo . --kind reference --output /tmp/new-mantle-input/R3.mp 4
python assets/authoring/mantle/inspect_reference.py /tmp/new-mantle-input/R3.mp 4 --output /tmp/new-mantle-evidence
blender --background --factory-startup --disable-autoexec /tmp/new-mantle-input/halcyon_jump.blend --python-exit-code 1 --python assets/authoring/mantle/validate_source_structure.py -- --output /tmp/new-mantle-input/inventory.json
blender --background --factory-startup --disable-autoexec /tmp/new-mantle-input/halcyon_jump.blend --python-exit-code 1 --python assets/authoring/mantle/inspect_ready.py -- --output /tmp/new-mantle-input/ready.json
```

The inspection commands never execute embedded source Text or save the input. The source sheet generator is ordinary video decoding, not a rendered animation substitute. It requires ffmpeg and Pillow.

## Next bounded authoring step and blocker

Create only new mantle/climb Actions in a separate copy; preserve all 103 prior Actions, source defaults, rest skeleton, geometry, camera, grips, driver definitions and attachment inverses. First establish visible foreground weapon landmarks against the fixed camera. Then solve a matched left-hand detach, free reach and regrip with the existing anatomical mechanism. Freeze hidden tracks as explicit inference rather than scoring them. Test finite evaluated skin, integer/quarter-frame switch continuity, wrist reach/guards, prop-relative attachment, and clean-file reset before asking for visual review.

The current render path is blocked by the earlier rejected Eevee operation. No retry, alternate renderer, or alternate operator was attempted. A new editable action would still need actual source/candidate silhouette and hand-contact inspection; baseline numerical checks cannot establish those. This checkpoint therefore stops before inventing animation curves. No export or runtime activation exists.

Keep these source screenshots and authoring diagnostics out of the shipping asset payload. Numerical parity, visual approval, and runtime behavior are separate future gates.
