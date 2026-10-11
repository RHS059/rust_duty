# Opt-in GPU timestamp session integration

Status: new feature, local work in progress. Production Rust compilation,
formatting, Clippy and native game validation have not run for this integration.
There is no RTX 3080 Ti performance result or 1080p60 acceptance claim.

## Entry and scope

The native game accepts the boolean `--gpu-timestamps` flag once, before `--`.
It is off by default, including existing windowed, headless and finite-probe
constructors. Legacy Macroquad rejects an explicit request. Present mode remains
explicit Fifo unless separately requested through the reviewed present policy.

An opted-in windowed device requests the complete timestamp feature pair only
when its selected adapter advertises both bits. Unsupported adapters still
initialize normally. Runtime identity separately records whether timestamps were
requested and whether the created device enabled both features. The existing
seven-field device-evidence log is unchanged.

The imported helper is byte-identical to `src/render/gpu_timing.rs` at tested
commit `f31315a1556e569f6a92ae3dcedff62d2e020765` (Git blob
`e03a31b2062cb44c41b95a261cae00391ed37997`). Its isolated helper validation does not
validate the production wiring in this change.

Timestamps surround the main ordered frame command buffer, from its initial
clear through its final presentation copy. They exclude CPU preparation, surface
acquisition, other submissions such as lazy target initialization, queue present,
scan-out, and the trailing timestamp resolve/readback commands. Backend/driver
ordering and precision still apply. The resulting elapsed span is neither a
present-to-present interval nor GPU utilization or a per-pass profile.

## Ownership and lifecycle

An enabled renderer has a checked, non-wrapping registration identity. Each
accepted CPU capture allocates a new session identity and a bounded attempt
vector. Each `begin_cpu_frame` allocates an attempt key before acquisition; skips
therefore retain their own key rather than shifting subsequent GPU results.
The encoder must match both the current renderer registration and session.
Callbacks only update the helper's atomic completion state.

The four-slot helper never waits or submits work. The integration collects
ready results only after an already existing nonblocking device poll. A mapped
buffer alone does not establish successful submission: a sample becomes measured
only after the production submission validation scope and device-error check
explicitly accept it. Rejected submissions retire asynchronously with null
numeric timing fields, even if their buffer contains an earlier frame's ticks.
A later present failure does not relabel an accepted GPU submission.

Ordinary encoding failure abandons an unsubmitted reservation. A timestamp-end
lifecycle failure exits before queue submission, so it cannot release a slot
while submitting that slot's old queries. Submitted reservations are never
abandoned by a dropped guard. Renderer replacement, early renderer destruction,
clock failures, capacity exits and missing CPU joins remain explicit diagnostic
incompleteness. No device drain, completion wait or extra poll is introduced.

Normal Record stop includes its final actual present, then finalizes the timer
without waiting. Pending, unconfirmed, rejected, failed and unavailable results
remain distinct statuses. Restart creates a fresh session; old callbacks cannot
join the new session. Device loss is still a runtime error, not silent recovery.

## Export and analysis

After primary `frames.json` succeeds, the optional exclusive-created
`frames.gpu-timing.json` is bound to its exact SHA-256. Its schema is
`rust_duty_frame_gpu_timing_v1`. Each sample has session/attempt identity, the
retained CPU terminal record index, status, optional integer ticks, timestamp
period and elapsed nanoseconds. Integer ticks are subtracted before conversion
to a floating duration. Missing timings remain null, never zero-filled.

CPU joins happen only after the corresponding primary terminal and CPU-stage
row were retained. Diagnostic accounting completeness is separate from primary
capture completeness and from the proportion of measured GPU samples. An
unjoined attempt has a null record index and makes diagnostic accounting
incomplete. A primary export failure still retires the timer but writes no GPU
sidecar. Existing files are never overwritten; failed writes may leave a partial
file. Export errors are logged and available through an independent notice.

```sh
python tools/summarize_gpu_timing.py path/to/frames.json \
  path/to/frames.gpu-timing.json --output new-gpu-summary.json
```

The reader checks exact bytes, schemas, bounds, feature facts in both files,
session/attempt ordering, unique CPU joins, status-dependent nulls, timestamp
period and tick arithmetic. Complete diagnostic joins must equal the primary
CPU-attempt index set. Only measured samples paired with eligible retained
present intervals enter nearest-rank p50/p95/p99; incomplete primary or
accounting evidence suppresses these statistics. Missing samples may bias that
subset. Exit codes are 0 for complete accounting and primary evidence, 1 for
explicit incompleteness, and 2 for invalid evidence or file errors. A complete
unsupported capture may have no measured values. None of these statuses is a
performance pass.

The existing matrix remains Fifo-only with GPU timestamps disabled. Its reviewed
29-file runtime inventory includes both GPU modules and retains historical
17/20/24/27-file artifact witnesses at their original scope. A changed live
candidate cannot fall back to a narrower inventory.

## Verification still required

Added Rust CPU-only lifecycle tests cover default-off export, exact primary-byte
parity, final-present joins, skips, shutdown, present failure, record limits,
backward clocks, exclusive-write failures and renderer/session ownership. They
have not executed. Python reader and witness tests use synthetic evidence and
cannot establish Rust compilation or GPU execution.

Before native acceptance, run the combined Rust build, formatter, Clippy and
unit tests, then actual windowed Windows DX12 capture/stop/restart, unsupported
features, validation rejection, pending-at-stop, renderer replacement, recovery,
device loss and map-failure paths where reproducible. Preserve exact build,
adapter, driver, display, physical extent, present configuration and all missing
statuses. Only selected RTX 3080 Ti gameplay measurements can address the target.
