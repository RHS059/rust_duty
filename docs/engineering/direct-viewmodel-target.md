# Direct native authored viewmodel target

This candidate submits the normal native authored hands/weapon layer directly to
the main target. It removes the viewmodel target clear, offscreen geometry target
and full-screen composite from that path. Geometry and animation remain unchanged;
this is independent of the separate resident chunk-coalescing candidate.

The existing perspective matrices and near/far clipping planes remain unchanged.
Viewport depth mapping, after clipping, reserves [0,0.05] for the viewmodel and
[0.1,1] for the world. The gap prevents LessEqual ties at a shared slice boundary.
The main color/depth clear happens before both. Normal
opaque viewmodel poses render before the world, allowing world depth rejection
behind covered weapon/hand pixels. HUD restores the default screen camera and
[0,1] depth range. Compatible same-attachment camera changes may continue in the
same ordered native draw pass; clears, captures, target and depth-attachment
changes retain their observable boundaries.

Actor transparency is handled without sorting parts. If any visible rigid actor
has opacity below1, including zero, the entire original-order viewmodel layer is
submitted directly after the world instead. It retains the same viewmodel depth
slice. This prevents transparent depth writes from hiding the world behind fades
and preserves ordering between overlapping opaque/translucent viewmodel parts.
Skin/material texture alpha remains the original loader-enforced opaque alpha.

Reference/capture, legacy and non-authored paths explicitly retain their existing
offscreen route. The old target descriptor stays available for those routes but
is not submitted or allocated by the direct normal-play path. Historical reference
captures therefore do not accidentally read an unfilled viewmodel target.

## Matched control

The native live-manifest diagnostic accepts
--diagnostic-viewmodel-target=direct|offscreen. Both require normal authored play,
a loaded explicit manifest and no fixed-time/reference/capture/hidden-layer mode.
The explicit offscreen control uses the same executable and original layer route.
Existing visible/hidden/target-only diagnostics retain their old behavior unless
an explicit target diagnostic is supplied; direct is compatible only with visible.
Normal native authored play defaults to direct.

Trace metadata records the explicit target policy and opacity ordering. The
render-layer diagnostic's target_clear_and_composite flag is false for direct.
A source-bound same-ELF comparison must verify warm resident geometry, identical
asset/settings/pose routes, actual main-target depth/pass behavior, retained images
and frame/CPU/GPU distributions. No measured speedup is claimed at implementation.

Direct native1920×1080 rasterization replaces1440×900 rendering plus filtering.
That intentional sampling change may produce sharper edges and different pixel
values. Equal-resolution original fixtures can test projection/blend/depth
semantics exactly; full-resolution visual checks must separately inspect sampling,
pose, visibility and occlusion. The earlier18RGBpixel shader-arithmetic failure
remains unchanged and is not relabeled by this architecture experiment.
