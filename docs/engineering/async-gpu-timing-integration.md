# Isolated GPU timing helper: integration contract

Status: isolated helper awaiting renderer-owner integration. This document and
`src/render/gpu_timing.rs` do not change the renderer, feature negotiation,
presentation policy, CPU measurements, or export schema. The baseline is
`70ff2933ebe69b7180e207c7defebeaeb6e240e1`.

## Scope and interpretation

The metric is `frame_command_buffer_gpu_elapsed_ns`; display milliseconds by
multiplying by `1e-6`. It measures two GPU timestamps around the main ordered
frame encoder. Retain the raw u64 ticks and timestamp-period nanoseconds with the
converted duration. Subtract the integer ticks before floating-point conversion.

It excludes CPU preparation, surface acquisition, DXGI presentation/scan-out,
query resolve/readback, and work in other submissions. In particular,
`GpuTexture::new` currently submits initialization clears separately; timestamps
inside the main encoder cannot include those submissions. Cold-start/lazy
initialization must be identified separately. PNG copy commands inside the
bracket are included, but diagnostic capture frames must not become eligible
steady-state gameplay samples. Backend/driver timestamp ordering and precision
apply, so this is a bounded GPU diagnostic, not total frame latency or display FPS.

The existing `renderer_submit` CPU span is still useful and remains independent.
Native wgpu 30.0.1 `pop_error_scope` returns a ready future after CPU mutex/scope
work; it is not a GPU completion fence. This does not make validation CPU work
free. The normal error check uses `Poll`, while PNG capture uses an explicit Wait.

## Renderer-owner hooks

1. For an explicitly opted-in session, call
   `requested_features(true, adapter.features())` before request_device and merge
   those supported bits with the renderer's existing requirements. The helper
   requires both `TIMESTAMP_QUERY` and `TIMESTAMP_QUERY_INSIDE_ENCODERS`. If either
   is absent it requests neither; rendering remains available and timing reports
   unsupported. Keep all current validation/error policies. Do not introduce an
   adapter/backend fallback just to obtain timing support.
2. Create `GpuTimer::new(&device, &queue, enabled)` once per diagnostic session,
   inside the renderer's normal validation boundary. Record `availability()` and
   the precise measurement scope in the session identity. Disabled/unsupported
   sessions allocate no GPU query or buffer resources.
3. Allocate a stable `FrameKey { session, attempt }` before recording. Use the same
   key for the CPU frame attempt and its later present outcome. Never join delayed
   GPU results to the nearest wall-clock timestamp or current CPU frame.
4. After creating the main command encoder, call `begin_frame(key, &mut encoder)`
   immediately before its initial clear. Keep a returned `SampleTicket` locally.
   `BeginFrame::Unavailable` is an explicit result to retain, not a dropped
   gameplay frame. Every ordinary render command still executes.
5. After all included passes have ended, including the final surface-quad pass,
   call `end_frame(&ticket, &mut encoder)`. It adds the end timestamp, aligned
   query resolve and 16-byte readback copy to that same encoder. Call the existing
   queue submit normally, then `after_submit(&ticket)`. Do not add another submit,
   Wait, blocking channel receive or GPU-completion callback wait.
6. If an encoder is abandoned before submission, drop that encoder and call
   `abandon_unsubmitted(&ticket)`. Never call it after submission. A subsequent
   validation/present failure is retained separately from any GPU result. An
   already-submitted ticket still needs `after_submit`, even if later validation
   or presentation fails, so it can safely retire asynchronously.
7. After an existing nonblocking device poll, call `collect_ready()`. It returns
   at most four already-completed results, reads mapped bytes, unmaps and releases
   the slots. It never polls, waits or submits internally. Callback bodies only
   set an atomic flag. If no slot is free, the next attempt reports `ring_full`
   without overwriting resources or stalling gameplay.
8. At terminal session shutdown, call `finish_nonblocking()`. Retain
   `pending_at_stop` and `abandoned_before_submit`; do not wait for a tidier export.
   This permanently stops that timer. New sessions create a new timer and unique
   session key. Late callbacks retain only old per-slot state and cannot attach
   to a replacement timer. Existing fatal device-loss handling remains intact.

## Export requirements

The existing frame-performance schema must not be altered by this isolated helper.
The integration owner decides the additive, source-bound sidecar destination.

- Record session/build commit, OS, actual backend and adapter fingerprint,
  configured present mode, physical resolution, scale, frame-latency setting and
  timestamp availability/period/scope.
- Preserve one result per sampled or unavailable attempt using its FrameKey.
  Keep frame eligibility, capture exclusions and present outcome independent.
- Store status plus nullable start/end ticks, period and duration. Missing or
  failed values are unavailable, never zero. Equal valid ticks may produce a real
  measured zero; reversed ticks are explicitly invalid instead of wrapping.
- Distinguish `ring_full` samples from dropped gameplay frames. Retain measured,
  unsupported, map-failed, invalid-order, abandoned and pending counts separately.
- Do not emit a hardware classification or performance/FPS pass from this module.
  Do not subtract CPU spans from end-to-end time and call the remainder GPU time.

## Verification

`tools/gpu_timing_cpu_contract` includes this actual module and the independently
owned present-policy helper pinned by the workflow. Its Cargo dependency closure
is derived from the baseline lockfile; `cargo --locked` must validate it.

The isolated Windows workflow compiles the APIs, runs Clippy, checks formatting
and runs only the modules' pure CPU tests. It never initializes wgpu, a window or
the game. It retains source SHA-256 values, exact commits, compiler output and
per-check results. This does not exercise GPU callbacks, mapping, renderer hook
placement, device loss, actual capability availability or presentation.

After integration, Windows DX12 hardware verification must cover disabled and
unsupported behavior; asynchronous results paired with the original attempt;
ring saturation without a render stall; stop/restart with pending results;
submission/present errors; and capture exclusions. Keep the actual hardware,
1920x1080 physical extent, scene, build and warm-up/cold-start conditions fixed.
Compare instrumentation enabled/disabled to measure observer overhead. Any
FIFO/Mailbox/Immediate comparison must validate supported modes and preserve
both acquisition and present-call CPU spans. Retain all raw results, including
unavailable samples. No Linux/Vulkan renderer runtime is part of this work.

## Pinned upstream references

- [Feature-pair requirement](https://github.com/gfx-rs/wgpu/blob/v30.0.1/wgpu-types/src/features.rs#L702-L721)
- [Timestamp units and ordering caveat](https://github.com/gfx-rs/wgpu/blob/v30.0.1/wgpu/src/api/command_encoder.rs#L299-L314)
- [Query resolve alignment and result size](https://github.com/gfx-rs/wgpu/blob/v30.0.1/wgpu/src/api/command_encoder.rs#L220-L246)
- [Asynchronous map callback contract](https://github.com/gfx-rs/wgpu/blob/v30.0.1/wgpu/src/api/buffer.rs#L549-L563)
- [Native validation-scope pop](https://github.com/gfx-rs/wgpu/blob/v30.0.1/wgpu/src/backend/wgpu_core.rs#L1860-L1897)
- [DX12 acquisition wait](https://github.com/gfx-rs/wgpu/blob/v30.0.1/wgpu-hal/src/dx12/mod.rs#L1726-L1740)
