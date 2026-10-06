# High-obstacle climb / mantle source, diagnostic r1

The feature is climbing or mantling onto an obstacle taller than the player.
It is not restricted to vehicles. The reference happens to use a vehicle roof;
that is one example of the intended broader obstacle geometry.

The existing source file `aella_climb_r1.blend` and legacy authoring Action
`aella_climb_roof_r1` retain their identities so this terminology correction
does not silently break source pins or future integration contracts. They use
the frozen public r5 baseline documented in `../mantle/README.md`.

The reference excerpt is R3 [8507,8583), Blender frames 1–76 at the original
60 Hz. Observed onset is 8513 ± 1, raised-weapon apex 8518, reappearance 8561,
and ready recovery 8574 ± 2. The weapon leaves the frame during the middle.
Its hidden continuation is an explicitly inferred hypothesis and earns no
source-match evidence. No exact world-space obstacle height or collision path
has been reconstructed from this first-person clip.

This is diagnostic WIP: initial unlocked weapon-root motion only, inherited
attached hands, no independent score, contact approval, successful preview,
export or runtime claim. Spatial hypotheses and timing remain in
`../mantle/design_r1.json`; native control curves are in `authored_controls.json`.
All 82 prior Actions and original rest, mesh, skin, weapon, camera and driver
information remain unchanged. There is no vehicle-specific runtime activation.

Run the sibling `author_movement.py --kind climb` against the frozen r5 source
to reproduce in a fresh copy, then reopen with `evaluate_movement.py` for native
diagnostics. Only foreground rendered Eevee viewport previews are permitted.
Future authoring and gameplay integration should use the general high-obstacle
climb/mantle scope, while retaining the exact reference and artifact identities.
