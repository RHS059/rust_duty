# Bounded staging source integration seam

Status: isolated implementation for Aella's combined renderer integration.
Base: `c111eba1bbd67b9988aeada4fbf9b2b528d43b65`.
This branch intentionally does not change the production frame caller, backend,
frame plan, resident mesh/shader work, animation, HUD, or shared evidence schema.
Existing callers therefore keep their original queue-write path. The new native
tests call the staging seam directly. A passing helper test is not an integrated
game performance result.

## Shared-file ownership and exact calls

Hal owns `src/render/upload_cache.rs`, the three new `upload_staging*.rs`
implementation/test files, `src/frame_staging_policy.rs`, and the dedicated
staging test workflow. Aella owns `frame.rs`, `backend.rs`, and combined v3
schema/readers/source inventories. No new renderer field is required: staging
state is a private member of the existing `UploadCache`.

The additive API leaves old tests/callers compilable:

```rust
cache.begin_frame_with_device(&gpu.device)?;
cache.upload_with_encoder(
    &gpu.device, &gpu.queue, &pipelines, arena_index, arena, &mut encoder,
)?;
let counters = cache.staging_stats();
let policy = UploadCache::staging_policy_identity();
// Exactly the existing one Queue::submit, then immediately:
cache.submitted();
// Existing outer error path, after abandoned encoder/buffer locals drop:
cache.clear();
```

The legacy `begin_frame()`/`upload()` methods retain queue-write behavior. Narrow
dead-code allowances mark only the additive entry points while the branch has
no production caller; they may be removed during integration.

Create the one command encoder before GeometryUpload. Pass that same encoder
to every upload, then keep timestamp start after these upload copies and before
existing draw encoding. Keep EncoderFinish, QueueSubmit, validation, present,
readback and error handling in their existing order. Encoder creation remains
inside the existing encode-submit aggregate; account for its location explicitly
in the v3 phase definition rather than silently comparing changed child scopes.
Do not add another submit, GPU wait or polling call. Existing error checking and
ordinary submissions already provide asynchronous callback progress.

## Source-only pool and queue ordering

The existing destination cache remains capped at eight arenas / 64 MiB. The
new pool is a separate, lazy maximum of eight source chunks / 64 MiB, including
ready, leased, submitted, retired and failed live chunks. This is not a limit on
driver allocations, CPU arena vectors, or transient fallback staging.

Each nonempty cached arena packs its three payloads into one
`MAP_WRITE | COPY_SRC` buffer. The internal `UploadSlice` interface takes a
destination buffer, destination offset and byte slice; it can express one to
three writes, including a uniform-only group for a future resident-mesh caller.
That internal interface is not an extra requirement on resident mesh layout.

Each source segment starts on an eight-byte boundary. Copy lengths round up to
four bytes, including zero-filled tails, exactly as the current index uploader
does. Callers must own the full padded destination range. Arithmetic, device
limits, destination usage/extent and overlapping padded writes are checked
before that group mutates any data. Empty slices do nothing. A group that does
not fit an available bounded source uses the original queue writes as a whole;
invalid ranges are errors, never a reason to fall back.

The frame-wide range ledger includes pooled and queue-write groups. This is
necessary because pending queue writes execute before all explicit copies in
the submitted encoder. Overlapping groups would otherwise reverse CPU-call
order. Disjoint ranges in the same destination buffer are permitted.

No destination is mapped. There is no new device feature, unsafe backend access,
`Buffer::destroy`, blocking map, added poll, or fixed-frame-count reuse.

## Completion, cancellation and failure

Every source checkout has a fresh `Arc<AtomicU8>` completion token. The callback
cannot address a newly recycled slot or a different device/pool. Source handles
remain in the owning pool while their budget charge is live.

The source is filled, its view is dropped, and it is unmapped before recording
copies. `map_buffer_on_submit` registers the remap on that encoder. A source is
not reusable until both `submitted()` has relinquished the frame's ownership
and that checkout's callback reports successful mapping. `submitted()` never
overwrites callback completion; callbacks may execute during Queue::submit.

Call `submitted()` immediately after Queue::submit returns, before validation
or readback can return an error. Later output failure still clears destination
residency. Pending source storage remains counted; clear retires it and releases
it only after a successful mapping is observed.

For a pre-submit error, drop every abandoned encoder and command buffer before
the outer clear. Dropping the deferred callback marks its token Cancelled, which
never means mapped/Ready. Retired unsubmitted chunks can then be released, not
reused. If clear is early, pending chunks remain charged until cancellation is
observed. A late real callback from a submitted frame cannot resurrect retired
storage. A failed or unexpectedly cancelled submitted mapping remains charged
and reports an error rather than silently falling back or inventing success.
Device replacement constructs a fresh UploadCache/pool; no state migrates.

## Named v3 counter handoff

`staging_stats()` returns a copied `StagingStats`. Events reset at
`begin_frame_with_device`; partial attempts retain only observed events.
These names are proposed for Aella's combined v3 contract. Do not insert them
silently into the historical strict v1/v2 dictionaries.

| Field | Meaning |
| --- | --- |
| `staging_buffer_allocations` | Explicit pool source buffers created in this attempt |
| `staging_buffer_reuses` | Successfully mapped existing source chunks reserved |
| `staging_buffer_allocated_bytes` | Capacities of source buffers newly created |
| `staging_copy_bytes` | Padded bytes scheduled by explicit pooled buffer copies |
| `staging_queue_write_calls` | Successful fallback staging-view requests |
| `staging_queue_write_bytes` | Padded bytes written through those fallback views |
| `staging_fallback_arenas` | Whole nonempty cached-arena groups using queue writes |
| `staging_retained_bytes` | Live pool capacity at the point stats are read |
| `staging_pending_buffers` | Live unavailable chunks: leased, submitted, retired or failed |
| `staging_map_failures` | Newly observed failed/cancelled submitted mappings |

The retained-bytes and pending-buffers fields are live gauges, not cumulative
allocation totals.
Read the snapshot at a documented point, preferably at GeometryUpload exit,
including its error path if a partial attempt is retained. The existing 15
destination/workload counters and primary/substage missing/error semantics do
not change in this helper branch. Uncached immutable destination uploads remain
outside this source pool and continue through the original upload_geometry path.

For a completed new-seam frame, pool allocations + reuses + fallback arenas
equals cached nonempty upload groups. For frames without uncached immutable
arenas, pooled copy bytes + queue-write bytes equals the three payload totals
rounded individually to four bytes. Never zero-fill missing observations.

Counterfactual: change only `STAGING_REUSE_ENABLED: bool = true` to `false` in
`src/frame_staging_policy.rs`. Policy identities are `bounded_staging_v1` and
`queue_write_staging_v1`; destination reuse stays independently enabled.
Both builds must retain identical new counters and fresh compiler/source hashes.

## Required evidence and remaining limits

Pure tests cover checked layout, limits, budget arithmetic and completion-token
ownership. Separate Windows tests exercise the new entry points on actual
DX12/WARP, compare every retained changed-frame image against the queue-write
control, force busy/budget fallback, and preserve aborted/submitted lifetimes.
All frame submissions precede the test's blocking final readback. Missing WARP
fails; zero selected native tests is not a pass. The dedicated workflow retains
the exact source inventory, test binary/PDB hashes, logs and formatter proposals.

Integration must rerun the unchanged 21 renderer pairs, four mixed controls,
authored 22-pose parity, GPU/session contracts and source-pinned readers. Keep
normal-shutdown failure a failure. Pool reuse removes recurring source-buffer
creation on the successful path; CPU memcpy and possible map/cache costs remain.
No FPS improvement, shutdown repair, RTX extrapolation, or animation acceptance
is implied by helper/native correctness.
