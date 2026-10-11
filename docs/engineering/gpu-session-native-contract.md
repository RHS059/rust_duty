# Asset-free windowed GPU-session contract

This fixture adds the missing native session/export exercise. It does not replace
the renderer, game-UI, CPU observer, or existing Windows pipeline contracts.
Production runtime code is unchanged by this fixture.

## What runs

`examples/gpu_session_contract.rs` draws three original rectangles in a 320×180
logical winit window using actual Windows DX12/WARP and default concrete Fifo.
There are no model, soldier, scene, capture-PNG, or authored-animation inputs.

`tools/run_gpu_session_contract.py` builds that example once, into a new target
directory, then runs two **fresh processes**:

1. `default-off` calls the preserved default `create_frame_hooks` constructor.
   Two CPU recordings must finish normally with CPU substage sidecars and **no**
   GPU notices or GPU sidecars. Actual device evidence must say timestamps were
   neither requested nor enabled.
2. `enabled` explicitly opts into GPU timestamps. Each of two sessions records
   64 normal presents; four ordinary idle presents precede each session. Stop is
   requested before the last present, and neither primary nor GPU export may
   exist before that present. All completion notices must be consumed once.
   The second session must have a newer session ID and its own attempt zero.

Idle frames give ordinary nonblocking callback collection an opportunity to run.
The test does **not** assert that a late callback from the retired session actually
arrived after restart. No new poll, GPU wait, readback, or synthetic timestamp is
added to force callbacks to finish. Pending-at-stop rows remain explicit.

Each primary and sidecar is validated with the existing strict readers against
the primary's exact byte SHA-256. The contract additionally verifies actual
Dx12/Cpu/Fifo evidence, source identity, per-session scene identity, frame counts,
normal stop ordering, unique ordered CPU joins, and complete CPU/GPU accounting.

- If the device enables the required timestamp feature pair, **each** session
  must contain at least one measured eligible GPU span. Complete accounting with
  no measured spans fails this path.
- If the adapter lacks the pair, explicit `device_features_not_enabled` rows are
  accepted as unavailable-device lifecycle coverage. The summary says
  `measurement_path_verified: false`; this does not verify measured GPU timing.
- Map errors, submission rejection, unconfirmed validation, reversed timestamps,
  source/hash mismatches, early window closure, and incomplete exports fail.

This is synthetic DX12/WARP lifecycle evidence. It provides no RTX 3080 Ti,
1080p60, representative gameplay, scan-out, or comparative performance verdict.
Close-while-recording, forced device loss, and deliberately rejected native GPU
submissions are still separate validation cases.

## Exact Windows invocation

Prerequisites: Windows with an interactive desktop and DX12 WARP, official stable
Rust/MSVC build tools, Python 3.12, and the existing process verifier's Pillow
11.3.0 dependency. Use a fresh **asset-free sparse checkout** of the reviewed
revision, selecting `src`, `updater`, `examples`, `tools`, and `docs` (cone mode
also includes root Cargo/build files). Do not remove assets from another working
tree. The runner refuses an optional `assets/weapons/hk416a5.vrm` or a set
`VR_WEAPON_ASSET`; it never opens that model. All tracked public source inputs
in the selected directories, including the built-in public text font, must be
materialized.
Disable checkout line-ending conversion in that new checkout before populating
it (`git config core.autocrlf false`); runtime bindings require exact committed
bytes. The dedicated Windows workflow supplies this Git setting explicitly.

From the checkout root in PowerShell:

```powershell
$env:PYTHONPATH = 'tools'
python -m unittest -v test_gpu_session_contract test_summarize_gpu_timing test_dx12_contract_process
if ($LASTEXITCODE -ne 0) { throw 'Evidence guard tests failed' }
python tools/run_gpu_session_contract.py --root . --evidence evidence/gpu-session-attempt-1 --timeout 90 --build-timeout 1200
if ($LASTEXITCODE -ne 0) { throw 'GPU session contract failed; retain evidence logs' }
```

Use a new evidence directory for every attempt. The runner, rather than a manual
Cargo command, supplies compile-time `GPU_SESSION_SOURCE_COMMIT` and
`GPU_SESSION_SOURCE_SHA256`. It temporarily sets/restores the fixture-only
`GPU_SESSION_CONTRACT_MODE` for each process; both the report and validator check
that mode. No global graphics settings are read or modified: fallback is explicit
and the fixture supplies its own nonexistent settings path.

The source binding requires a clean committed tree, the reviewed 29-file runtime
inventory, and hashes of tracked public compile/validator inputs. It rejects
untracked inputs in those scopes and an inconsistent `GITHUB_SHA`. Source is
rechecked after building and after each execution. A new target directory avoids
reusing a stale executable; the existing process runner hashes the executable
before and after execution and requires actual DX12/WARP/FXC startup evidence.
Both process receipts must also match the executable hash pinned immediately
after the fresh build; replacing the binary between controls fails validation.
This records source/build/process provenance; it is not a claim of a hermetic or
bit-for-bit reproducible toolchain.

## Retain and interpret

Retain the evidence directory **except `target/`**: `source-binding.json`,
`build-invocation.json`, `built-executable.json`, build stdout/stderr/result,
top-level `summary.json` or
`failure.json`, and both `default-off/` and `enabled/` output/process directories.
Each process keeps its command, exit code, executable hash, stdout/stderr and
validated summary or failure. Enabled outputs contain two primary reports, two
CPU sidecars, two GPU sidecars, and the fixture report. Default-off outputs omit
both GPU sidecars.

Inspect `summary.json` → `controls.enabled.measurement_path_verified` before
claiming the measured path ran. `passed: true` plus
`unavailable_device_features` means only the unsupported-device path ran.

Local Linux Cargo check/Clippy and Python guard results establish compile/source
and synthetic evidence behavior only. Native execution must come from the
Windows command above; another backend is never substituted.
