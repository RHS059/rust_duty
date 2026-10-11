# Frame-performance recording

The wgpu runtime can record CPU wall-clock intervals between successful present returns. These measurements describe application frame pacing. They are not GPU execution time, display/scan-out timing, or simulation time, and do not by themselves prove that a playtest looks or feels correct.

## Recording and files

F8 and the pause menu’s Record telemetry button use the same recorder. A persistent indicator shows recording, stopping, incomplete capture and export errors even when the debug HUD is off. Each recording gets a unique local `telemetry-sessions/session-<time>-<pid>-<sequence>/` folder containing `gameplay.csv`, `frames.json` when the wgpu frame recorder is available, `IDENTITY.json`, `CSV_STATUS.json`, and an editable `OBSERVATIONS.txt` guide. The compatibility `telemetry.csv` beside the game retains its existing columns and is overwritten when a new recording starts; earlier session folders are never overwritten. No files are uploaded or shared automatically. Stopping requests a final successful present before completion; closing the window or encountering a fatal presentation error first produces an incomplete recording.

Per-session export uses exclusive file creation: an existing path, including a symlink, is never overwritten. A write failure after creation may leave a partial file and reports that possibility. Do not submit a partial file as a valid trace. Keep gameplay telemetry, frame traces, the build identity, and your own observations together when reporting a playtest.

## GPU counters

The same recording also creates `GPU_METADATA.json`, `gpu.jsonl` and, after the background sampler stops, `GPU_STATUS.json`. Windows reports per-adapter GPU engine occupancy and dedicated/shared memory usage for this game and the whole adapter when its counters support them. Both renderers use this sampler. Missing values have explicit reasons, and adapter-to-renderer binding is unverified. These counters do not measure GPU frame duration. See [GPU telemetry](GPU_TELEMETRY.md) for interpretation and independent completion checks.

## JSON contract

- `schema`: `rust_duty_frame_performance_v1`
- `measurement`: `cpu_wall_clock_successful_present_return_interval_ns`
- `clock`: `caller_injected_monotonic_nanoseconds`
- `identity.runtime_observed`: backend, adapter, build, initial window, and scene information
- `identity.operator_supplied`: separately recorded operator claims
- `identity.hardware_classification`: always `unknown`; this observer does not authenticate hardware evidence
- `status`: `complete` or `incomplete`, with an error for incomplete recordings
- `start_ns`, `stop_requested_ns`, `stopped_at_ns`, `last_observed_ns`, and `incomplete_at_ns`: recording boundary evidence; unavailable boundaries can be null
- `limits`, retained-event counts, `summary`, and `records`: bounded observations and their derived statistics

The default record limit is 120,000; configurable limits cannot exceed 250,000. Default metadata capacity is 64 KiB. Consult the trace's own `limits` fields rather than assuming the defaults. Reaching a limit makes the recording incomplete; counts describe retained events only.

Record kinds are `successful_present_return`, `boundary`, `skipped_frame`, and `window_context`. Present records include eligibility, an ineligibility reason when applicable, and an optional interval. Focus, pause, resize, and other explicit exclusions break interval chains. Surface-acquisition retries retain the elapsed gap to the next successful present; they must not silently hide a hitch. Window records retain physical dimensions, scale, and window mode.

## Statistics and interpretation

### Optional CPU substage sidecar

Instrumented native builds also write `frames.cpu-substages.json` after the
primary frame export finishes. This separate file leaves the original
`frames.json` schema and its four paired CPU spans unchanged, so existing readers
and matrix acceptance checks continue to work. Its SHA-256 binds it to the exact
primary frame file; record indexes bind details to the same retained attempts.
No new GPU waits, polls or validation changes are introduced by these hooks.

The sidecar records at most six paired CPU call spans per frame attempt:

- Up to two `acquire_texture` calls around the existing `get_current_texture`,
  each followed by `acquire_validation_cpu` around its existing synchronous
  validation-scope completion. Recovery/reconfiguration between attempts is
  still included in the outer acquisition span, not silently assigned to either
  child call.
- `encode_submit` around frame encoding and queue submission, followed by
  `submit_validation_cpu` around the existing frame validation-scope completion.
  Resource preparation before encoding and error checks/readbacks afterward
  remain in the outer renderer-submit span. This is not GPU execution time.

In the pinned [wgpu 30.0.1 native backend](https://github.com/gfx-rs/wgpu/blob/v30.0.1/wgpu/src/backend/wgpu_core.rs),
`pop_error_scope` locks CPU error-scope state and returns an immediately ready
future containing the recorded error. Its `pollster` wrapper is not a GPU fence.
The `validation_cpu` labels measure this existing CPU work; they do not imply a
GPU synchronization bottleneck. An actual GPU-duration investigation needs
separate timestamp-query evidence.

The existing parent spans include these child times. Do not add parent and child
durations, subtract percentiles from each other, or call a remaining gap GPU time.
Only active Record sessions read these extra clocks. Fixed-size storage avoids
per-call allocation; export and hashing happen after the final present, outside
the recorded intervals. Four normal child spans add eight clock reads per frame;
one acquisition retry raises that to twelve. Disabled hooks still check session
state, but read no clock. Probe and recording overhead remain unmeasured.

Analyze both files together:

```sh
python tools/summarize_cpu_substages.py path/to/frames.json \
  path/to/frames.cpu-substages.json --output new-substage-summary.json
```

The reader validates the existing frame report, exact hash binding, bounds,
record indexes, parent containment, ordering, paired timestamps and call limits.
For complete diagnostic attempts paired with eligible present intervals it
reports observed call counts and p50/p95/p99 of each stage's per-frame total.
Repeated acquisition calls are summed within that frame before summarizing.
Explicitly invalid producer detail is retained as incomplete evidence and never
enters a timing summary; an unmarked containment violation fails validation.
Absent calls remain unavailable; zero is retained only for a real paired
zero-duration call. Skips, baseline presents and incomplete detail do not enter
these distributions. The original long present intervals remain unchanged.

Sidecar completeness and write errors are independent of the primary export.
Existing paths, including symlinks, are never overwritten; a failed write can
leave a partial sidecar. Check the sidecar reader result and game log even when
the primary frame capture completed. The reader returns failure for incomplete
primary or diagnostic evidence. A missing sidecar on an older build is not a
zero-duration validation wait and does not invalidate its original frame report.

These details distinguish CPU time in validation-scope handling from encoding and
surface calls. They do not establish the cause of an RTX regression or the
Windows DX12 1080p60 goal without new same-device gameplay captures.

Eligible intervals use exact nearest-rank percentiles: sort the intervals and select rank `ceil(p * n)` without interpolation for p50, p95, and p99. The serialized method is `nearest_rank_ceil_p_times_n_no_interpolation`. No eligible intervals, non-monotonic timestamps, capacity errors, or a missing required final present prevent a complete recording.

A complete trace means recording/export semantics succeeded. It is not a performance pass, hardware certification, visual-quality verdict, or gameplay approval. Describe visible glitches, input/animation behavior, and when problems occurred alongside the recorded evidence.

If a session closes before a normal stop, CSV_STATUS.json records interruption; frames.json retains its own independent complete/incomplete verdict. CSV-only recording remains available on the legacy renderer. A missing/partial frame trace is never a successful frame export. Review the local folder and add observations before manually sharing it.

## Finding and returning a session

Press F8 or Stop telemetry in the pause menu, then wait for the stopping indicator to resolve. In File Explorer, open `telemetry-sessions` beside the extracted game and select the complete `session-...` folder named by the indicator. Add your observations to `OBSERVATIONS.txt`. Use File Explorer’s ZIP/compressed-folder action on that entire folder, then manually attach the resulting ZIP when reporting the run. Keep the folder’s files together, including incomplete-status/error evidence; do not send only `telemetry.csv` or a screenshot. Nothing is uploaded automatically.

## Optional GPU timing sidecar (new feature, integration under review)

Native builds with explicit `--gpu-timestamps` can attach bounded asynchronous
GPU spans to the same Record session. The feature is off by default and does not
change the original primary frame schema. Read
[the integration scope and validation limits](engineering/gpu-session-integration.md)
before interpreting `frames.gpu-timing.json`. Unsupported, rejected and pending
samples are retained with null durations; GPU spans do not measure scan-out,
present cadence or the 1080p60 goal. Production native validation remains pending.
