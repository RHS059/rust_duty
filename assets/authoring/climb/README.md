# Vehicle-roof source checkpoint

**Status: baseline; no climb BLEND or climb Action recovered or authored.** See `../mantle/README.md` for immutable baseline identity, read-only rig inventory, reproduction and the unresolved visual-review block.

This is R3 native [8507,8583), 76 displayed frames at 60 fps; endpoint pose span is 75/60 seconds. It shows a vehicle-roof ascent, not a ladder or ledge hang. Every frame was visually inspected in the source-only sheets. The weapon lifts around 8513, reaches a high pose around 8518, sweeps out of view, then returns around 8561 and settles near 8574. Timing uncertainty is stated in the JSON rather than treating a contextual cut as an engine trigger.

During approximately [8532,8559), hands and weapon are absent; edge visibility is uncertain by ±2 frames. Those tracks are **unscored**. The upper-body pose, hidden contacts and root/collision trajectory cannot be recovered from this interval. No invented ladder/rung motion or extra handhold was introduced.

`recovery_contract.json` and `native_frame_map.csv` define the scoped future `climb_vehicle_roof_wip1` Action, not an existing Action. New source/candidate rendering and contact/silhouette review remain blocked; no shipping payload changes were made.
