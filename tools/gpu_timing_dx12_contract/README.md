# Isolated Windows DX12 GPU timing correctness

This harness compiles and exercises the **unchanged** GPU helper published in
PR #47 at `f5a7493302842a2b7bbd1c19e244d325d67a21b5`. CI materializes its canonical
Git blob `e03a31b2062cb44c41b95a261cae00391ed37997`; CRLF checkout conversion is not
allowed to change the included source bytes. This branch adds only this isolated
harness and its workflow. It does not integrate the helper into the game or alter
Aella's held renderer/compiler/publication work.

## Execution boundary

- Windows only, with only the wgpu DX12 backend compiled and selected.
- Explicit fallback-adapter request, actual adapter/backend/device/driver and
  available/requested/enabled feature sets retained in every process's log.
- wgpu validation remains enabled; the existing system FXC choice is explicit.
- No surface/window, game, renderer, capture, Linux or Vulkan runtime.
- Each native case is a separate process bounded to 45 seconds. Future and
  nonblocking `PollType::Poll` callback loops have a 15-second deadline.
- Harness-only queue-completion witnesses are allowed to await correctness
  outcomes; the pinned helper still adds no wait, poll or queue submission.
- A missing DX12 adapter is failure. Missing timestamp capability is explicit
  unsupported/incomplete, never a successful native-timing result.

## Scenarios

1. Disabled timer on a real device: explicit unavailable sample.
2. Device requested without timestamp features: `device_features_not_enabled`;
   adapter support is retained separately, so this is not evidence of unsupported
   hardware.
3. Four live mapped slots with withheld verdicts: no sample publication and a
   fifth `ring_full`; after accepted verdicts retire each original key exactly
   once, reuse a slot and reject its stale ticket.
4. Prime a slot, then deliberately encode an out-of-bounds clear under the real
   validation scope. Require a captured validation error, publish only
   `submission_rejected` after callback retirement and reuse the slot normally.
5. Separately inject a caller rejection of a valid submission, labelled synthetic.
6. Abandon an encoded-but-unsubmitted reservation and reuse its slot.
7. Stop with an unconfirmed submitted reservation, create a replacement session,
   reject the old ticket and observe old-work completion before a new sample.

The stop case proves owner/session separation. `unmap` may synchronously cancel
the old map callback; this harness does **not** claim an old map callback was
observed arriving after restart. The accepted-verdict `pending_at_stop` race is
not exercised by this withheld-verdict scenario. Map failure and device loss are
not induced.

The queue witness uses the pinned wgpu guarantee that mapped-buffer callbacks
registered for the same submission have run before
[`Queue::on_submitted_work_done`](https://docs.rs/wgpu/30.0.1/wgpu/struct.Queue.html#method.on_submitted_work_done).
It is not inferred from elapsed time or an empty submit queue. All ticks and frame
keys are decimal strings in JSON to preserve u64 values losslessly. Missing
numeric values remain null; equal valid timestamps may be a genuine zero.

## Evidence and checks

Run `python tools/gpu_timing_dx12_contract/run.py` only on Windows after the
workflow's pinned helper checkout. CI runs Python evidence-parser positive and
negative controls, Rust formatting, canonical-lock comparison, locked Clippy,
the helper's CPU tests, builds the current executable and runs every native case.
The first lock/format normalization is retained but does not turn its failed
commit gate green; exact normalized files must be committed and rerun.

Every attempt retains source identities and hashes, executable hash, toolchain,
raw stdout/stderr, errors, expected scenario, actual samples, deadlines, callback
witnesses, and terminal process/aggregate outcomes. Results do not establish game
integration, presentation, performance, FPS, or instrumentation overhead. WARP
results are correctness evidence only.
