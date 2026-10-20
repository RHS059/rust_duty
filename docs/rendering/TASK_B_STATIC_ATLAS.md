# Static atlas range batching (WIP)

This renderer-only revision follows the stage2 measurement regression: exact
instance visibility reduced submitted triangles but greatly increased per-draw
CPU and transform-upload work. It does not change visibility, geometry, LOD,
command recording, or the public immutable-mesh interface.

Static geometry is uploaded once into append-only shared vertex/index pages.
Indices are checked and rebased as u32 into the page. Consecutive submitted
opaque untextured ranges coalesce only when their page, matrix slot, and adjacent
index endpoints agree. A visibility hole, reversed/repeated range, different
matrix, dynamic draw, material change, camera, clear, or capture prevents unsafe
coalescing. Receipts retain individual draws and hash the actual uploaded index
payload with its atlas base, preserving source triangle identity.

Adjacent identical static transforms reuse one immutable frame matrix slot.
Pages are weak-tracked by the allocator and strongly held by cached live meshes;
occupied ranges are never reused or overwritten. Empty pages retire when their
last mesh/cache or temporary owner goes away; WGPU retains in-flight resources.
First-use metrics count written payload bytes, not reserved page capacity.

Trade-offs: pages reserve up to 8 MiB of vertex space and 2 MiB of index space
(or a larger individual valid mesh); first-touch ordering and later visibility
holes limit draw reduction. There is no per-frame geometry reconstruction or
optional multi-draw dependency. Memory can remain partly unused until every
mesh on its page retires. No performance improvement is claimed until matched
native measurements are complete.

Validation: WGPU build and focused CPU allocation, u32 rebasing/receipt, and
visibility-gap tests passed. The 14 frame-plan tests passed, including identical
transform reuse and matrix/command barriers. Explicit native Vulkan SwiftShader
tests passed for the high-u32 path and atlas captures versus separately rendered
dynamic references: exact pixels/triangle counts, first-use and warm uploads,
visibility holes, reverse/repeated ranges, transforms, alpha/textures, dynamic
interleaving, camera boundaries, page splits, and weak-owner retirement. This
is small-fixture correctness evidence, not a full-city performance result.
Existing measurement evidence remains unchanged.
