# Direct viewmodel and resident coalescer closeout

Measured production source is `332e389a08330ce2be701f251ec355f94b12e5fb`, tree `c38e6b703403c4a329adb04ade95673cb1dfc9c0`. Later evidence commits do not change that source.

## Included behavior

Normal native authored play uses same-part coalesced resident meshes and renders the viewmodel directly on the main target. Opaque authored layers draw before the world; a visible fractional-opacity actor routes the original-order layer after the world. Projection and clipping are unchanged. Viewmodel depth range is [0, 0.05], world depth range [0.1, 1], followed by restored HUD state.

Reference/capture and legacy routes retain their offscreen target and legacy chunk policy. Existing public loader wrappers default to LegacyChunks, retaining the historical 4,998-index chunk contract. Same-binary diagnostic flags independently select target and batching policy.

Coalescing preserves triangle order, original part/actor/material boundaries, immutable vertex attributes, all eight skin influences, pose state and existing 16-bit bounds. The fixed actual-loader fixture retains 344,016 submitted indices while reducing resident draws from 86 to 34.

## Validation and measured result

Scoped production check/Clippy, 53 binary and 28 integration tests pass. The actual-loader example passes 27 CPU tests and scoped Clippy; its strict reader passes six positive/negative tests. The controller passes 25 tests and three mock build flows, independently repeated.

The [A100 report](linux-a100-resident-coalescing-20261012.md) links the complete original archive and independent audits: 464 source files, 134 compile inputs, both ELFs, all process joins, 22 exact ordered/source/state/corner cases and 44 exact full-RGBA images. Original-hash CPU reconstruction recovered the exported evidence without another GPU run.

Four same-ELF stationary ABBA legs independently replay to legacy frame medians 5.710171 / 5.707708 ms and coalesced medians 5.597254 / 5.651460 ms. Mean run medians decrease about 1.48%; all four GPU medians remain 1.175552 ms. All 21,682 eligible GPU samples were measured. These descriptive results do not establish statistical significance or identify the remaining GPU bottleneck. Game screenshots retain hands, weapon, world and HUD; their animation timing is unsynchronized.

## Remaining acceptance

The historical CPU-versus-resident strict image gate remains failed: 18 RGB pixels in 11 pairs, maximum difference 3. Resident-to-resident coalescer parity does not resolve it. The broader 24-pair synthetic native coalescer test remains unrun; the actual-loader gate was prioritized. Aggregate all-target compilation retains the pre-existing missing `v9_native_runtime_oracle.json` fixture limitation. The 77 public runtime asset binaries and toolchain binaries outside the archive are receipt-bound.

Windows RTX/DX12 and broader gameplay acceptance remain open. No merge or universal frame-rate guarantee is claimed. GPU capacity was exhausted after this run; further GPU execution requires a new authorized capacity window. Recovery used only existing evidence and CPU work.

Further optimization should follow the retained CPU/timestamp distributions. Optional pass-level profiling and HUD glyph batching remain proposals requiring independent correctness and performance validation; neither is established as the bottleneck by this run.
