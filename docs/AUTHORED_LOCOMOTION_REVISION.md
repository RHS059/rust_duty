# Authored locomotion revision

Run the game with the private, matching animation pack:

```
vector-range --no-update --viewmodel-asset=assets/locomotion/asset.vra --viewmodel-clip=locomotion --viewmodel-fov=76
```

The three companion files (`asset.vra`, `asset.vrs`, `asset.vrm`) must remain together. These rig-derived assets are delivered privately, not committed to the public source repository.

This revision wires the existing ready, entry, sprint-loop and exit animations into committed gameplay ticks. Shift/sprint drives entry and looping; releasing sprint uses the evaluated phase-specific exit. Repeated toggles retrace validated paths. The animation is not advanced by rendering. Restarting the range resets the path. Existing explicit single-clip/fixed-time capture modes remain available.

The supplied motion is unchanged. Runtime transition bridges and small bounded phase corrections preserve hand contact. This revision does not include new reload, firing or ADS authored clips: the existing authored renderer already bypassed legacy procedural weapon posing. Gameplay action timing is unchanged, but those visual actions remain pending integration with Aella's authored action set. The default legacy renderer remains unchanged when no authored asset is selected.

Validation: local Rust tests, formatting and strict all-target Clippy. Real-asset controller sweeps and exported-pose parity are documented in the private handoff. Native windowed visual verification remains unavailable on this executor; no gameplay recording is claimed.
