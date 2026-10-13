# Same-part resident chunk coalescing

This candidate reduces per-draw work without changing triangle count, stored
vertex records, vertex words, textures, sampler settings, animation, viewmodel
resolution, lighting, blend/depth state or draw order. Performance and native
image results are pending. It does not resolve or relabel the existing strict
A100 RGB image-parity failure.

## Construction and fallback

The legacy 4,998-index partitioner remains unchanged. Each original chunk still
has its own complete immutable-attribute deduplication and local u16 indices.
The resident path concatenates only contiguous chunks of the same original part,
rebasing their indices by the preceding stored-record count. It deliberately
keeps duplicates across old chunks. Different source parts retain separate
actor visibility, root transform, material/albedo and opacity ownership.

ResidentMesh::coalesce validates vertex kind, skin palette size and texture
resource identity. Existing 65,536-vertex and 65,535-index bounds remain intact.
A single chunk keeps its original resource identity. No geometry is truncated,
reordered or culled. If construction or draw validation fails, the whole affected
group falls back to its original CPU chunks before submitting any of that group's
triangles. The procedural/legacy path still draws those original chunks.

Skin resident geometry is prepared once during loading, like rigid resident
geometry, rather than lazily at its first native draw. This moves immutable
allocation/validation into loading; GPU buffers remain renderer-owned and lazy.
It can increase loaded CPU geometry memory for inactive/CPU-only skin models.
Warm frames retain the existing immutable palette snapshots and shader arithmetic.

ResidentBatching is an explicit loading policy. Existing public loader wrappers
retain LegacyChunks so their historical native/CPU contracts keep the original
command boundaries. The normal native authored app selects CoalescedParts;
reference capture, other captures and the legacy renderer retain LegacyChunks.
All loaded reload companions inherit the selected policy. There is no mutable
global policy or environment override.

The closed --diagnostic-resident-batching=legacy|coalesced control selects either
policy in the same executable, before immutable descriptors are built. Both
policies retain the same preparation structure, geometry, animation and render
path; legacy uses one resident draw per original chunk. The control requires a
live loaded explicit manifest and native visible geometry without capture. Its
exact startup marker and scene receipt identify the policy. The candidate is
based on direct main-target rendering; target and batching controls are separate.
Historical source admission classes and native correctness gates are unchanged.

## Evidence and limits

Original synthetic tests reconstruct all immutable corner words, including
signed zero, normals, UVs and eight ordered skin influences. They reject mixed
layouts/textures and existing-bound overflow, preserve exact u16 boundary values,
and check part/fallback ranges. The public companion decoder fixture exercises
the real authored loader and native recording capability: four source meshes
produce four resident draws instead of twelve legacy chunks, while preserving
every decoded triangle and source corner in order across all actor-visibility
combinations. Existing CPU triangle-deletion/reordering negative tests remain.

An explicit ignored native test,
render::resident_tests::native_coalesced_chunks_preserve_order_and_pixels,
compares 24 pairs of original chunk versus coalesced renders, with rigid/skin
sources, overlapping textured triangles, depth on/off, every blend mode and
opaque/half-opacity poses. It queues every pair before readback and retains48PNG
files plus a strict per-pair pixel report. It requires the existing actual-hardware
Linux Vulkan adapter contract (or the existing Windows DX12 software contract).
This test has not yet run; compiling it is not native image evidence.

The matching real-asset baseline has86draws,344,016indices and147,549summed
chunk-local stored records. The source-derived expected reduction to34draws is a
candidate target, not an observed runtime result. A matched source-bound native
comparison must establish actual counters, exact coalescer/control image equality
and hardware frame/CPU/GPU timings before claiming a gain. No result here proves
a pass/composite architecture change is beneficial or visually equivalent.

The historical resident_authored_contract example and Python reader still require
4,998-index maximum chunks and identical CPU/resident command arrays. Their
unchanged default loader route remains LegacyChunks; those checks are not relaxed.
The separate resident_coalesced_authored_contract example and reader compare two
resident policies across actual-loader poses. Read-only resident_source_groups
exposes original chunk ranges and part IDs independently of draw attributes,
including each reload companion. The contract validates complete range coverage,
same-part ownership, every ordered immutable source record and full material,
root, palette, lighting, alpha and CPU-reference corner state, followed by strict
full-image RGBA equality. Its native results remain pending until the actual
source-bound run. The synthetic native test is not a substitute for that evidence.
