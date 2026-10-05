# Aella vehicle-roof ascent source, diagnostic r1

`aella_climb_r1.blend` adds editable Action `aella_climb_roof_r1` to the same
frozen public r5 baseline documented in `../mantle/README.md`.

This is a **vehicle-roof ascent**, not ladder climbing. R3 source excerpt is
[8507,8583), Blender frames 1–76 at original 60 Hz. Observed onset is8513±1,
raised-weapon apex8518, reappearance8561, and ready recovery8574±2. The weapon
leaves the source frame during the middle. Its hidden continuation is an
explicitly inferred authoring hypothesis and earns no source-match evidence.

The source is diagnostic WIP: initial unlocked weapon-root animation only,
inherited attached hands, no independent score, no contact approval, no
successful preview, export or runtime claim. Spatial hypotheses and timing live
in `../mantle/design_r1.json`; exact native control curves are also preserved in
`authored_controls.json`. All82 prior Actions and the original rest/mesh/skin/
weapon/camera/driver data remain unchanged.

Run the sibling `author_movement.py --kind climb` against the frozen r5 source
to reproduce in a fresh copy, then reopen and run `evaluate_movement.py` for
native diagnostics. Only foreground rendered Eevee viewport previews are allowed.
