# CPU encode-detail evidence

The optional `frames.cpu-encode-detail.json` sidecar separates CPU work inside
`encode_submit`. It supplements the existing [frame report and CPU
substages](FRAME_PERFORMANCE.md#optional-cpu-substage-sidecar). It does not change
either v1 schema, successful-present intervals, GPU timestamp evidence, or
performance acceptance. Analyze all three files together:

```sh
python tools/summarize_cpu_encode_detail.py path/to/frames.json \
  path/to/frames.cpu-substages.json path/to/frames.cpu-encode-detail.json \
  --output new-encode-summary.json
```

The output path must be new. Existing files and symlinks are never overwritten.
The reader prints the summary to stdout, returns 0 only for complete diagnostic
and primary evidence, and returns 1 for invalid or incomplete evidence. A valid
incomplete recording can produce a summary file, explicitly marked incomplete;
it cannot produce complete-frame distributions from incomplete rows. Validation
failures produce an error and no new summary. Write failures can leave a partial
new output, so check the exit status as well as the file's existence.

## Timing contract

The writer emits `rust_duty_cpu_encode_detail_v2`; the reader accepts that
version and the unchanged historical `rust_duty_cpu_encode_detail_v1` contract.
Both use measurement `cpu_wall_clock_nested_encode_phase_ns`. Their shared
top-level fields are exactly `schema`, `measurement`, `interpretation`,
`frame_report_sha256`, `frame_status`, `samples`. v2 additionally requires
`upload_policy`, exactly `bounded_reuse_v1` or `immutable_per_frame_v1`. v1 has no
policy field and rejects one as unknown. The interpretation remains exactly:

> CPU call durations nested inside encode_submit and renderer_submit, not GPU
> time. Parent and child durations must not be added. Missing or incomplete phases
> are unavailable; counters on incomplete rows are observed partial values, not
> complete frame totals.

Each sample contains exactly `record_index` and `details`. `details` contains
`state`, `error`, `spans`, and `counters`. Every retained primary CPU attempt has
one row, in the same strictly increasing record-index order as the existing CPU
substage sidecar, including skipped, failed, unvisited, and partial attempts.

A complete row contains these five paired phases, once each and in this order:

1. `frame_plan`: construction of the prepared frame plan, including its existing
   geometry/text preparation.
2. `geometry_upload`: upload of the plan's geometry arenas.
3. `command_encoding`: command-encoder creation and the existing ordered
   command, draw, clear, presentation, and optional capture-copy encoding.
4. `encoder_finish`: the existing encoder's `finish` call.
5. `queue_submit`: the existing queue's `submit` call.

A span has exactly `stage`, `started_at_ns`, `ended_at_ns`, `duration_ns`.
Timestamps and durations are exact unsigned 64-bit integers. Durations must
match the paired timestamps; phases must be disjoint, ordered, and contained in
both the matching `encode_submit` span and its outer `renderer_submit` span, as
well as the retained frame attempt. Gaps between phases are allowed. These five
phases do not assert coverage of all work in either enclosing span. In
particular, resource/validation work before encoding and validation/readbacks
after it can belong to the enclosing renderer span.

`state: "complete"` requires all five phases and `error: null`. Producer
completion also requires the encode success marker and a closed parent envelope.
An incomplete row uses `state: "incomplete"`, a nonempty error string of at most
256 UTF-8 bytes, and the valid observed phase prefix, which may be empty. An
interrupted enclosing call can lack a paired parent span; such rows must be
incomplete and still lie inside the retained frame and every available parent.
An error label never licenses an out-of-bounds, overlapping, reordered, or
reversed interval. The producer retains a valid prefix rather than clipping or
inventing paired spans. Unobserved encoding is `encode_not_observed`, not a
zero-duration complete frame.

## Counter contract

Every row carries exact unsigned 64-bit integer counters in `[0, 2^64 - 1]`.
v1 requires exactly the original ten names below. v2 retains all ten and requires
exactly five additional names; it never changes the old timing or counter types.
A file declares one schema for all its rows, including incomplete rows. Mixing
counter sets, dropping fields, or extending either set with unknown fields is
rejected. Historical v1 summaries retain their original schema and ten counters;
they do not receive fabricated zeros for unavailable v2 observations.

The original counters are:

- `prepared_draws`: prepared draw commands in the frame plan, excluding its
  separately stored presentation draw
- `text_characters`: Unicode scalar values in input text commands, including
  whitespace; this is not a drawable-glyph or glyph-cache count
- `upload_arenas`: nonempty geometry arenas submitted for upload; v1 used
  per-frame buffer creation, while v2 can update reusable destination buffers
- `vertex_bytes`, `index_bytes`, `uniform_bytes`: lengths of the corresponding
  arena upload buffers, including any padding present in those buffers
- `draw_calls`: observed encoded indexed-draw calls, including presentation
- `render_passes`: observed render-pass creations, including clear and
  presentation passes
- `texture_cache_misses`: observed texture-cache misses taking the creation path
- `pipeline_cache_misses`: observed pipeline-cache misses taking the creation path

The five additional v2 counters are:

- `gpu_buffer_allocations`: destination vertex, index, and uniform buffers created
  during this attempt, including uncached fallback buffers
- `gpu_buffer_reuses`: existing destination buffers reused during this attempt;
  each reused buffer counts once for its arena upload in this frame
- `gpu_buffer_allocated_bytes`: sum of the allocated capacities of all destination
  buffers created during this attempt, including padding, growth capacity, and
  uncached fallback allocations; this is not the logical payload length
- `transform_binding_allocations`: transform bind groups created during this
  attempt, including uncached fallback bindings
- `uncached_upload_arenas`: nonempty arenas uploaded using the uncached path
  during this attempt, whether by fallback or the immutable allocation control

All fifteen values are per-attempt counts or sums. None is a gauge of live
buffers, retained cache bytes, peak occupancy, driver memory, or GPU residency.
A newly created attempt starts at zero; reuse reports the buffers used this
frame, not every retained buffer. Counters describe destination resources and do
not include hidden queue staging allocations. Payload byte counters retain their
original meaning and may differ from newly allocated capacity bytes.

These are CPU-side observations at the instrumented call sites, not
driver-internal counts, physical transfer measurements, full allocation
profiling, or GPU completion.
Counters on interrupted rows are observed partial values and may precede a
subsequent operation's failure. They are retained in source evidence but never
summarized as complete frame totals. Counter overflow invalidates the producer
row; it must not wrap or invent a saturated successful count. The reader rejects
negative, overflowing, boolean, floating-point, null, missing, and unknown
counter values or fields. Python preserves full u64 values exactly; downstream
readers must not silently convert them to imprecise floating-point numbers.

## Upload policy identity

v2 records the policy actually selected by the shared source selector:

- `bounded_reuse_v1`: bounded destination-buffer and transform-binding reuse
- `immutable_per_frame_v1`: matched uncached, per-frame allocation control

Both policies emit the same v2 counter set and retain the same phase and
incomplete-attempt rules. The summary preserves `upload_policy`; it never infers
policy from zero allocations or a single warm frame. The sole source toggle is
`REUSE_ENABLED` in `src/frame_upload_policy.rs`. Changing it to `false` selects the
immutable control while retaining instrumentation. A matched comparison still
requires separate exact source identities and same-device, same-scene captures.
The policy label is source metadata, not proof of a measured performance gain.

## Identity and binding

The reader first validates the historical primary report and CPU-substage
contract. Both sidecars must name the same primary status and SHA-256 of the
exact primary bytes read. Whitespace changes therefore require a new binding.
The files are bounded to the existing 512 MiB reader limit and must be regular,
nonsymlink inputs; duplicate JSON keys and non-finite numbers are rejected.
Record-index and parent-span checks join the three sources; no time-based
nearest-neighbor matching or missing-row substitution is performed.

Both supported encode-detail versions also require
`identity.runtime_observed.actual_adapter.instance_descriptor` in the primary
report. Its exact fields are:

- `schema`: `rust-duty-wgpu-instance-descriptor/v1`
- `wgpu_version`: `30.0.1`
- `flags_bits`: an unsigned integer with no bits outside the version's known
  mask `255`
- `debug`, `validation`, `gpu_based_validation`, `validation_indirect_call`:
  booleans equal to bits `1`, `2`, `16`, and `32`, respectively
- `application_debug_assertions`: boolean build metadata
- `environment_overrides_applied`: exactly `false`

These describe the final descriptor passed to `Instance::new`. They do not
attest that a driver or validation layer actually supplied every requested
facility. The application's debug-assertion setting must not be used to infer
dependency flags: their compilation profiles can differ. The reader rejects
missing, unknown, wrongly typed, or internally contradictory descriptor data.
Historical primary and substage readers remain unchanged; this metadata
requirement belongs only to the new encode-detail reader.

## Summary boundaries and overhead

Only rows with complete encode details, complete corresponding CPU substages,
and an eligible successful-present interval enter distributions, and only when
the primary recording itself is complete. Baseline presents without an interval,
skips, failures, ineligible rows, and partial rows are omitted. If the primary is
incomplete, **all** encode timing and counter distributions are suppressed,
even when earlier individual rows look complete. Missing samples use
`sample_count: 0` and null percentiles, never fabricated zero-duration samples.
An actually observed zero-length phase or zero counter is a valid sample on a
complete eligible row.

Per-phase timings report p50/p95/p99 in nanoseconds; counters report p50/p95/p99
in their stated units. Both use exact nearest rank `ceil(p * n)` without
interpolation. Aggregate totals use exact Python integers. Parent and child
percentiles cannot be added or subtracted: percentile ranks can select different
frames, and enclosing spans already include their children. Remaining gaps do
not establish GPU time or a synchronization bottleneck.

A normal captured encode adds ten phase clock reads. Counter increments add no
clock reads; collection and the extra text/plan scan are gated by an active
encode capture. Disabled hooks still check capture state. Storage, clock,
collection, and export overhead are not a measured performance improvement.
Export and hashing occur after primary export; a failed or unavailable sidecar
does not rewrite the primary result. No GPU waits, device polls, pacing changes,
new validation scopes, or gameplay changes are introduced by these CPU hooks.

This is instrumentation and parser evidence, not a native timing result. A claim
about a particular GPU/CPU, a regression cause, or the Windows DX12 1080p60 goal
still needs new same-device, same-scene, matched-setting captures and native
review. Synthetic tests do not establish those claims.

## Integration status and historical evidence

This instrumentation has a separate exact 33-file runtime inventory in
`performance_matrix.py`, including the recorder, arena packing, and locked
wgpu dependency manifests. Historical GPU/CPU inventories and the immutable
four-file performance-pair baseline remain unchanged. The old paired matrix
will reject this new source rather than silently relabel it; connecting that
runner requires a separately reviewed source pair and detail-consumption path.
The four existing CPU comparison files are unchanged by this patch.

The three-file reader is usable independently on a newly captured session.
The integrated GPU-session fixture uses the production verified physical
1920×1080 path. Its strict output-directory validator requires and validates
`session-0.cpu-encode-detail.json` and `session-1.cpu-encode-detail.json` for both GPU-enabled and default-off controls on this source. The game recording filename is `frames.cpu-encode-detail.json`.
`take_cpu_encode_detail_export_notice()` returns a one-time optional notice with
`output_path` and `error`; no early export is permitted before the normal stop
boundary. Historical fixture results do not validate these new child phases.

The separate `cpu-encode-detail.yml` job uses an asset-free checkout for source,
reader, and pure Rust library contracts. It does not launch a window or establish
native timing, display-extent, or target-hardware performance results. Compiler
and formatting validation must pass on the exact published source before the
instrumentation is treated as compiler-validated.


The combined source keeps the original Hal 33-file inventory as a historical
pin and adds a distinct exact physical/formatter integration pin. The fixed
image comparison binds all 119 production compile inputs and restores only
its original four CPU files in the counterfactual. That image proof is separate
from the historical timing pair, whose closed compile digest remains unchanged.
The old experimental timing-pair autorun is removed for this incompatible
profiling class; original quality, authored, DX12 and image checks remain.
