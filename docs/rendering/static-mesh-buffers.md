# Persistent static geometry (Task B, stage 1)

`StaticMesh::new(Vec<Vertex>, Vec<u32>, Option<Texture>)` validates geometry once
and assigns a fresh resource identity. Its storage is private and immutable.
Clones, `Command::StaticMesh`, and `DrawList::draw_static_mesh` share that storage
through `Arc`; changing geometry requires a new handle. Existing mutable `Mesh`
and u16 dynamic drawing remain compatible. The facade exposes
`draw_static_mesh` and `draw_static_mesh_transformed`.

WGPU lazily packs and uploads static vertices and native u32 indices on the first
issued draw for a resource. Subsequent frames append only the aligned transform
to the frame arena. A static-only frame creates no transient vertex/index buffers.
City loading converts its decoded chunks once; both city presentation paths use
the persistent handles. This stage retains the existing city binary layout and
partitioning; changing those belongs to later material/spatial batching work.

The per-renderer cache holds weak CPU ownership. A live mesh or recorded draw
list keeps its cached buffers resident, including temporarily culled meshes.
Entries without any CPU owners are removed at the next valid frame submission.
Dropping cache handles does not destroy buffers referenced by recorded or
in-flight WGPU commands. Separate renderer/device instances have separate caches.

Normal gameplay does not retain a second packed CPU copy. An explicit visibility
receipt retains the exact packed input bytes used for upload and hashes the u32
triangle stream, preserving order and multiplicity. Requesting a receipt after a
normal upload replaces those buffers once to capture actual upload provenance;
it does not silently claim a receipt for unavailable bytes. Existing receipt
pipeline/platform restrictions remain fail-closed. The temporary legacy backend
remaps complete u32 triangle batches without truncation until its separate removal.

## Verification

The focused tests cover invalid construction, O(1) cloning, draw-list lifetime,
indices above 65,535, static/dynamic ordering, aligned matrix-only chunks, adapter
size rejection, and exact receipt hashes. The opt-in native test renders a
triangle whose three indices exceed 65,535, checks its captured pixels, verifies
cache reuse, capture-only reupload, and eviction after the last draw-list owner
drops. Run it with a supported Vulkan adapter:

```
cargo test --locked --no-default-features --features wgpu-runtime --lib static
cargo test --locked --no-default-features --features wgpu-runtime --lib \
  native_static_u32_reuse_capture_and_eviction -- --ignored --nocapture
```

These fixtures establish buffer/geometry behavior, not Cedar Junction hardware
performance or complete Windows receipt acceptance. Benchmark metrics count
first-use static uploads at cache misses and zero static geometry bytes on warm
cache hits, in addition to aligned matrix uploads. Native tests verify exact
metrics for duplicate static draws sharing one upload, warm static draws, and
mixed static/dynamic draws. The benchmark inventory counts both command kinds.
