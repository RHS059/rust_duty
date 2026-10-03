# Authored locomotion revision

The complete game distribution includes the matching animation pack. The explicit diagnostic launch form is:

```
vector-range --no-update --viewmodel-asset=assets/locomotion/asset.vra --viewmodel-clip=locomotion --viewmodel-fov=76
```

The three companion files (`asset.vra`, `asset.vrs`, `asset.vrm`) must remain together. These exact converted companions are included in the repository and complete game builds under the project owner's authorization. Original source files and unrelated assets remain excluded.

This revision wires the existing ready, entry, sprint-loop and exit animations into committed gameplay ticks. Shift/sprint drives entry and looping; releasing sprint uses the evaluated phase-specific exit. Repeated toggles retrace validated paths. The animation is not advanced by rendering. Restarting the range resets the path. Existing explicit single-clip/fixed-time capture modes remain available.

The supplied motion is unchanged. Runtime transition bridges and small bounded phase corrections preserve hand contact. This revision does not include new reload, firing or ADS authored clips: the existing authored renderer already bypassed legacy procedural weapon posing. Gameplay action timing is unchanged, but those visual actions remain pending integration with Aella's authored action set. The default legacy renderer remains unchanged when no authored asset is selected.

Regular walking now retains the previous deterministic, speed-scaled vertical
bob while the authored path is Ready. One camera-space root translation is
applied equally to the complete skin and rigid weapon/magazine actors; no bone
locals, grip offsets, source Actions, or animation pack bytes are changed. A
walking offset already visible when sprint starts decays monotonically to zero
over 100 ms. This captured transition residual does not add an ongoing bob over
the authored sprint entry, loop, or exit. Returning to Ready fades walking back
in without exposing a hidden oscillator offset. Pause and render reads cannot
advance it; range reset clears both bob and residual. Explicit selected-clip
and fixed-time captures, plus the public complete-pose rendering API, retain
their original unmodified root. This restoration does not implement or change
the separate ADS/reload visual owner.

Validation: local Rust tests, formatting and strict all-target Clippy. Real-asset controller sweeps and exported-pose parity are documented in the private handoff. Native windowed visual verification remains unavailable on this executor; no gameplay recording is claimed.
