# Resident authored meshes and vertex-stage lighting/skinning

This WIP moves the native authored skin and rigid paths from per-vertex CPU
updates and mesh cloning to immutable resident vertex/index buffers. Each draw
retains its own root, lighting, albedo and actor opacity. Each skin pose retains
all eight ordered influences and its own position/inverse-transpose palette.
The legacy/reference path remains available. Renderer capability is frame-local;
ordinary `facade::begin_frame` remains CPU-only. Headless native callers must use
`begin_frame_with_renderer` to exercise the production recording route.

The native shader retains vertex-stage lighting, RGB saturate/truncate to RGBA8
before interpolation, rigid opacity rounding and the distinct rigid versus skin
normal transforms. A 128-bone palette is two fixed 8,192-byte matrix arrays in a
16,384-byte uniform binding. Root/material/light data is separate. Vertex layouts
are explicitly serialized to 32/80 bytes; Rust structure padding is never read.
Per-submission aligned uniform slices prevent one pose from overwriting another.

The device-owned geometry cache retains at most 512 meshes and 256 MiB of
vertex/index buffers. Absent entries are evicted on pressure. Overflow uses
uncached immutable buffers; no old buffer is explicitly destroyed while queued
work may refer to it. These are retained-cache bounds, not total driver/staging
or in-flight memory bounds. Device replacement drops the cache; errors clear it.
Warm frames still allocate two snapshot uniform buffers and two bind groups.

CPU encode-detail v3 adds resident counters and an explicit resident policy.
Existing v1/v2 reports retain their original fields and meanings. Arena upload
allocation counters still describe the existing dynamic arenas; separate resident
counters cover cold static destinations and per-submission uniform allocations.
The compile-time `frame_resident_policy::ENABLED` constant supplies an exact
one-line CPU reference control. It is not an environment override. The expanded
43-file witness admits candidate/control separately and preserves historical
source classes. The older loader-only and upload-only comparison producers still
reject this new production tree rather than relabeling it as their experiment.

## Native correctness command

The bounded resident workflow builds the exact library test executable and runs
`render::resident_tests::native_resident_poses_preserve_order_and_queued_results`
with `--exact --ignored --nocapture --test-threads=1`. Windows explicitly requests
DX12 fallback and verifies actual Cpu device type. Linux selects Vulkan and
requires an actual discrete/integrated GPU; missing hardware fails the test.
A fresh `RUST_DUTY_RESIDENT_TEST_OUTPUT` directory retains all original PNGs and
per-pair raw differences.

The fixture queues twelve changing-pose frames and three textured perspective
frames before its first capture/readback. It tests late bone127, all eight
influences, nonuniform transforms, normal fallback, actor opacity, all blend
modes, depth occlusion, GPU-only intermediate snapshots, warm reuse, cache clear
on failure and transient buffers. It then compares 27 exact synthetic image
pairs, followed by a fresh-device cache check. The production loader's pure test
also requires resident skin/rigid commands and unchanged CPU vertex storage.

Native results are pending at this WIP. These bounded synthetic cases do not
establish arbitrary authored-scene floating-point parity or a speedup. Authored
native captures and matched hardware timings must be reviewed before making
those claims. GPU timestamps remain explicit-command-buffer spans, excluding
queue-scheduled upload copies and presentation.
