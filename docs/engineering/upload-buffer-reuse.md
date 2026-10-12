# Bounded destination-upload reuse experiment

Status: draft experiment, based on PR49 `70f67908408012646cd37195d82c94fbe66ab62b`.
No throughput, RTX 3080 Ti, or 1080p60 improvement is claimed. The recovered
WARP profile motivates testing destination-buffer creation; it does not predict
hardware results. Existing native validation failures remain independent gates.

## Scope and ownership

Only GPU destination buffers and their transform bindings are retained. Frame
planning, CPU packing, line/text commands, shaders, draw order, timestamp rings,
validation flags, and the immutable diagnostic upload helper are unchanged.
The renderer owns its cache together with its device and pipelines; replacing
that renderer replaces the cache. Resizing a surface with the same device does
not change buffer ownership.

Eight arena-index slots and 64 MiB total retained destination capacity are
explicit conservative memory bounds, not an empirically optimal workload size.
A frame may contain more arenas or larger payloads: those arenas keep using the
previous immutable allocation path. The limits never reject otherwise valid
geometry. A retained slot grows each of its three capacities geometrically,
clamped to the actual required size when the next power of two exceeds the
device's buffer limit. Every prospective three-buffer total is checked before
allocating. Slots unused by the just-submitted frame are explicitly dropped;
a failed frame or renderer replacement drops all slots. No explicit GPU buffer
destroy is used; wgpu retains handles required by in-flight commands.

## Queue and failure contract

The mutable renderer completes Queue::submit for frame N before beginning
uploads for frame N+1. Each arena has a distinct slot within one frame, and
cache guards reject a second use of the same slot before submission. Data is
copied into wgpu staging, with four-byte payload padding (including odd u16
index counts); vertex/index draw ranges and dynamic uniform offsets are not
changed. Each frame's queued writes precede its commands and follow earlier
submissions on the same queue. There is no CPU wait, device poll, extra empty
submit, mapped destination overwrite, or new ring lifecycle.

Every returned error from submission, including preflight, encode, validation,
device, and capture readback failures, invalidates the cache. If encoding fails
after staging writes but before submit, wgpu may retain those pending writes;
dropping cached destination handles ensures the next frame cannot reuse their
storage. Existing error reporting and diagnostic completion rules remain in
force. A failed validation does not become a successful frame.

Slot retirement runs immediately after the measured Queue::submit call, inside
the existing encode_submit aggregate but outside its five child spans. It is
not reassigned to a child; parent-minus-children residual still represents such
unmeasured setup/retirement work.

The pinned wgpu 30.0.1 Queue::write_buffer_with API allocates native staging
memory per call. This experiment removes repeated destination/bind-group
creation on stable frames; it is not an allocation-free upload path. Staging
pooling and shader or validation changes are outside this experiment.
Reference: https://docs.rs/wgpu/30.0.1/wgpu/struct.Queue.html#method.write_buffer_with

## Matched control and diagnostics

Change exactly `pub const REUSE_ENABLED: bool = true;` to `false` in
`src/frame_upload_policy.rs` to build the immutable-per-frame control. Do not
revert the v2 diagnostics or any other production input. Both paths retain the
five CPU child spans and workload counts. CPU-detail v2 records the policy as
`bounded_reuse_v1` or `immutable_per_frame_v1` and adds destination-resource
allocation calls, reused buffer count, allocated capacity bytes, transform
binding creations, and uncached upload arenas. These counters describe
application resource operations, not allocator/driver calls, resident memory,
or GPU execution time. Partial failed-attempt counts remain partial.

The v1 reader contract and all historical source digests remain replayable.
New 35-file runtime candidate/control inventories bind the policy and cache.
Aella's subsequent matched image/profile experiment must bind complete source
inventories and fresh same-compiler EXE/PDB hashes for both one-line variants.
The historical four-file CPU comparison is a separate experiment and supplies
no acceptance for this new cache.

## Validation

The separate upload-buffer-reuse workflow runs source/reader contracts, Rust
capture/cache contracts, and an explicit Windows DX12/WARP native queue test.
Native tests compare changed frames against the unchanged immutable helper,
queue all submissions before deferred readbacks, and cover stable reuse,
growth/shrink, multiple slots, odd indices, empty trimming, slot/budget fallback,
and production capture/error recovery. Native test-only waits finish evidence
readbacks; production upload code adds none. Formatter proposals are retained
separately and never rewrite the tested source.

Matched hardware profiling and unchanged-image paired evidence are still
required before claiming a performance win or integrating this draft.
