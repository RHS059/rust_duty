# Resident normalization candidate and vertex-stage diagnostic

This WIP starts from `2a1776a46fbcd9ad95371ea3ba49ab272a742c58` (tree
`124328c8a5b8cabdaf308ce3305d51dc53836b03`). Its original production bytes equal
the measured resident/staging revision `1ef12e3f5840e1411c131e2859b133737f4ec565`.
The only intended ordinary-render arithmetic change is `inverseSqrt(length²)`
to `1.0 / sqrt(length²)` in `normal_or_y`. Upload policy, assets, draw order,
skinning influences, lighting location and byte truncation stay the same.

## Evidence and limits

The original Windows resident-on/off control isolates 495 one-level RGB pixel
changes across 553 frames to resident offload. The separate A100 authored gate
retains 18 changed pixels in 11 of 22 pairs, maximum channel delta 3. Alpha and
foreground masks were equal. Both are preserved failed exact-pixel observations;
the unrelated historical ADS visibility failure is also still a failure.

The CPU path uses pinned glam 0.27: sequential three-term dot, square root,
reciprocal, then multiplication. Skin normalizes twice, including irradiance.
The prior shader used `inverseSqrt`. Local float32 sensitivity cases show that
this difference can cross an RGB8 truncation boundary. They do not establish
the cause of the observed pixels. WGSL permits reassociation/fusion and gives
different accuracy contracts to these operations, so the candidate is an
experiment, not a cross-backend bit-exactness guarantee.

Primary references: [pinned glam Vec3](https://github.com/bitshifter/glam-rs/blob/0.27.0/src/f32/vec3.rs),
[pinned Mat4 transforms](https://github.com/bitshifter/glam-rs/blob/0.27.0/src/f32/sse2/mat4.rs),
[WGSL accuracy](https://www.w3.org/TR/WGSL/#floating-point-accuracy) and
[reassociation/fusion](https://www.w3.org/TR/WGSL/#reassociation-and-fusion).

## Bounded native proposal

The original companion-backed example first finishes and saves all 22 original
CPU/resident image and corner comparisons. Only an explicit `--vertex-probe-dir`
starts the additional readback pass. The runner's `--vertex-probe` selects a
separate retained directory; normal gameplay and default example invocations do
not invoke it. Existing image predicates and failure exits are unchanged.

For each case, the diagnostic selects at most 16 pixel locations, including the
previously observed A100 locations and current mismatches. At most two nearest
CPU-projected triangles per point are selected. Uncovered or omitted requested
pixels remain incomplete. This selection is an aid, not proof of the rasterizer's
primitive identity.

Three instrumented vertex routes emit raw clip-coordinate and color float bits
through integer attachments: the original loader's CPU-lit mesh pipeline, the
current resident shader body, and an exact normalization-only historical shader
control. Command, triangle-corner and vertex indices, camera/pose metadata,
source receipt and shader hashes accompany the samples. Missing point writes
fail explicitly. Exact generated shader sources are independently reconstructed
from the bound production source and probe template before accepting their hashes.

The altered entry point and extra outputs may change compiler optimization.
These values diagnose arithmetic; they are not a trace of the original production
binary. Differences never become a tolerance or an image acceptance decision.
Probe/map/selection failures are exported separately after the original image
report exists. No probe failure can promote an original failed pixel verdict.

The existing Windows authored workflow requests this diagnostic on the same
source-bound fresh build and original public companion set. Both complete and
compact artifacts retain the probe JSON alongside the unchanged image report.
Local tests do not execute a GPU. A100 execution needs a separately approved,
source-bound invocation after the outstanding original archive is recovered.
