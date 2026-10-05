# Frame-performance recording

The wgpu runtime can record CPU wall-clock intervals between successful present returns. These measurements describe application frame pacing. They are not GPU execution time, display/scan-out timing, or simulation time, and do not by themselves prove that a playtest looks or feels correct.

## Recording and files

F8 and the pause menu’s Record telemetry button use the same recorder. A persistent indicator shows recording, stopping, incomplete capture and export errors even when the debug HUD is off. Each recording gets a unique local `telemetry-sessions/session-<time>-<pid>-<sequence>/` folder containing `gameplay.csv`, `frames.json` when the wgpu frame recorder is available, `IDENTITY.json`, `CSV_STATUS.json`, and an editable `OBSERVATIONS.txt` guide. The compatibility `telemetry.csv` beside the game retains its existing columns and is overwritten when a new recording starts; earlier session folders are never overwritten. No files are uploaded or shared automatically. Stopping requests a final successful present before completion; closing the window or encountering a fatal presentation error first produces an incomplete recording.

Per-session export uses exclusive file creation: an existing path, including a symlink, is never overwritten. A write failure after creation may leave a partial file and reports that possibility. Do not submit a partial file as a valid trace. Keep gameplay telemetry, frame traces, the build identity, and your own observations together when reporting a playtest.

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

Eligible intervals use exact nearest-rank percentiles: sort the intervals and select rank `ceil(p * n)` without interpolation for p50, p95, and p99. The serialized method is `nearest_rank_ceil_p_times_n_no_interpolation`. No eligible intervals, non-monotonic timestamps, capacity errors, or a missing required final present prevent a complete recording.

A complete trace means recording/export semantics succeeded. It is not a performance pass, hardware certification, visual-quality verdict, or gameplay approval. Describe visible glitches, input/animation behavior, and when problems occurred alongside the recorded evidence.

If a session closes before a normal stop, CSV_STATUS.json records interruption; frames.json retains its own independent complete/incomplete verdict. CSV-only recording remains available on the legacy renderer. A missing/partial frame trace is never a successful frame export. Review the local folder and add observations before manually sharing it.

## Finding and returning a session

Press F8 or Stop telemetry in the pause menu, then wait for the stopping indicator to resolve. In File Explorer, open `telemetry-sessions` beside the extracted game and select the complete `session-...` folder named by the indicator. Add your observations to `OBSERVATIONS.txt`. Use File Explorer’s ZIP/compressed-folder action on that entire folder, then manually attach the resulting ZIP when reporting the run. Keep the folder’s files together, including incomplete-status/error evidence; do not send only `telemetry.csv` or a screenshot. Nothing is uploaded automatically.
