# GPU telemetry in local playtest sessions

Record telemetry/F8 also starts an opt-in GPU sampler for both the legacy and
wgpu renderers. On Windows it uses the operating system's read-only Performance
Data Helper (PDH) GPU counters. Nothing is installed, repaired, launched as a
subprocess, elevated, uploaded or shared. Other platforms export an explicit
unavailable reason. Unsupported/disabled Windows counters remain unavailable;
the recorder never substitutes zero for missing observations.

## Files and completion

Keep these files with the existing session identity, gameplay CSV and frame trace:

- `GPU_METADATA.json`: provider, process ID, observed renderer description,
  sample semantics, nominal 1-second interval, wall-clock recording start and
  capacity limit
- `gpu.jsonl`: one JSON object per background sample, including monotonic sample
  start/end offsets and the provider call's CPU wall time in milliseconds
- `GPU_STATUS.json`: terminal export state, successfully written sample count,
  samples that contained this process's utilization, and any write error

Stopping is asynchronous to avoid waiting for a driver/provider on the game
thread. Wait for `GPU_STATUS.json` and inspect it independently of `CSV_STATUS.json`
and `frames.json` before sharing. `stopped` means the stream was saved normally;
it does not mean all counters were supported. `interrupted`, `incomplete`, a
missing/partial status, or `sample_limit_reached` must not be treated as a normal
complete recording. A forced process exit can leave samples without terminal
status. The default limit is 86,400 samples (approximately 24 hours).

The initial Windows sample reports warm-up while rate counters obtain two
observations. Afterwards the worker waits at least one second between queries.
No GPU queries, worker joins, subprocesses or per-frame file writes are added to
the rendering loop. Initialization and file creation occur only when recording
is explicitly enabled. Query CPU wall time is diagnostic overhead, not GPU time.

## Utilization and multiple GPUs

Every recognized Windows adapter is identified by its LUID and physical-adapter
index. The selected renderer's name remains in the session identity and GPU
metadata. These are **not automatically bound to one another**: every row marks
renderer binding as unverified. In a multi-GPU system, inspect the per-adapter
process data instead of assuming the first GPU is the rendering GPU.

- `process_busiest_engine_pct`: the largest engine-occupancy percentage reported
  for this exact game process ID on that adapter
- `adapter_busiest_engine_pct`: sum process contributions separately for each
  adapter/engine, then select the busiest engine across that adapter
- `process_engines` and `adapter_engines`: the corresponding engine ID/type and
  percentages, including 3D, copy, compute or video engines as reported by Windows

Parallel engines are never summed into one utilization percentage. Summed
same-engine percentages are capped at 100, with an explicit marker when capped.
Invalid/duplicate contributions make the affected aggregate unavailable instead
of reporting a partial sum as a full measurement. Engine occupancy is not shader
core occupancy, instruction throughput, memory-controller utilization, or proof
that the graphics workload is the sole bottleneck. A busy video engine can drive
the adapter-wide summary even when the game's 3D usage is low.

Other applications' process IDs/names are not exported. Only adapter/engine
aggregates and the recording game's own process ID are retained.

## Memory and timing limits

`process_dedicated_bytes` / `process_shared_bytes` are the current game's
Windows-reported dedicated/shared GPU memory usage. `adapter_dedicated_bytes` /
`adapter_shared_bytes` are whole-adapter usage, including other applications.
These are usage observations, not installed VRAM capacity or a memory-bandwidth
percentage. Missing process instances, invalid values and unsupported counters
carry a null value plus an unavailable reason; an actually observed zero remains
numeric zero.

GPU frame-duration timestamp queries are not instrumented and are explicitly
unavailable. Existing `frames.json` successful-present-return intervals are CPU
wall-clock pacing. They must not be renamed GPU milliseconds. The GPU sampler
covers all recording wall time, including pause/focus changes, and has its own
monotonic origin; it is not a per-frame sample aligned to the eligible-frame set.
Compare representative gameplay periods, identical settings/resolution/scenes,
and both renderer identities when investigating a performance difference.

## Implementation references

- [Microsoft: GPU engine aggregation and WDDM telemetry](https://devblogs.microsoft.com/directx/gpus-in-the-task-manager/)
- [Microsoft: language-neutral PDH counter paths](https://learn.microsoft.com/en-us/windows/win32/api/pdh/nf-pdh-pdhaddenglishcounterw)
- [Microsoft: wildcard formatted counter arrays and two observations](https://learn.microsoft.com/en-us/windows/win32/api/pdh/nf-pdh-pdhgetformattedcounterarrayw)

The platform-neutral aggregation/export tests and native-buffer decoder tests run
on Linux and Windows. A Windows-only live-counter smoke test verifies either
usable data or explicit unavailability; a hosted Windows runner is not a test of
a user's RTX 3080 Ti, physical GPU load, localized desktop, or playtest performance.
