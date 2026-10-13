# Authored viewmodel render isolation

The optional `--diagnostic-viewmodel-render=visible|hidden` switch compares the
same executable with and without submission of the authored hands/weapon layer.
It requires an explicit, successfully loaded animation manifest, the live
locomotion route, and no fixed clip time. The default launch is unchanged.

The hidden branch omits `weapon()` at its final draw call and restores the
screen-space camera normally restored by its composite. Simulation updates,
authored `committed_step`, locomotion updates, world rendering, player-body
placeholder, HUD, camera inputs, settings, and loaded assets remain active.
The omitted layer includes its pose-to-draw preparation, target clear, mesh
commands, and composite. Its measured difference is the cost of this whole
layer, not an isolated GPU skinning time. Legacy model animation is deliberately
outside this diagnostic because that route updates presentation inside draw.

Startup logs and the primary CPU trace scene explicitly retain the chosen mode.
A matched run uses one source-bound release executable, identical public assets
and settings, warmed visible/hidden/hidden/visible captures, physical 1920×1080,
and the existing A100 Vulkan/Immediate display configuration. Screenshots are
retained outside the measured Record interval. Strict existing frame, CPU-detail
and GPU readers remain unchanged. Hidden runs must show no resident viewmodel
commands while world/HUD work remains; screenshots independently establish that
the requested layer is absent. Check animation/simulation progression in both
modes before interpreting performance.

The existing exact image-parity failure remains a separate result. This
intentional visibility experiment cannot pass that gate or establish a shader
arithmetic fix. Compare frame, recording, renderer, present/acquire/submit and
GPU distributions separately; their durations overlap and must not be added.

## Retained-target control

`--diagnostic-viewmodel-render=target-only` retains the ordinary viewmodel camera,
render target and transparent color/depth clear, then composites the empty target
through the ordinary full-screen sprite. It returns before pose-to-draw preparation
and all hands/weapon geometry submission. The same live-manifest requirements and
committed simulation/animation updates apply. The trace marks
`viewmodel_submitted: false` and `target_clear_and_composite: true`; hidden marks
both false, while visible marks both true.

The normal game target is 1440×900, independently of the 1920×1080 window. The
reference viewport uses 960×540. The composite always covers the actual window.
The renderer clears color and depth in one pass, draws any viewmodel geometry in
an ordered run, then returns to the main target. An empty target has no geometry
run; its clear and full-screen composite remain real GPU work. World rendering
still happens first in all three modes.

Use visible versus target-only to isolate the added render preparation, draw,
vertex and fragment work, and target-only versus hidden to estimate the retained
clear/composite path. These are measured differences with overlapping CPU/GPU
stages, not additive standalone GPU timers. This control does not emulate an
offscreen-translated mesh, change target resolution, alter projection/depth ranges,
or establish that a direct-main-target rewrite preserves images or actor fades.
No performance result is claimed until the same-binary native runs are audited.
