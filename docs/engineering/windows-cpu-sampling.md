# Bounded Windows CPU sampling

This lane answers the request for a sampled release-build hot-function report.
It uses the preinstalled WPR and xperf from the Windows Performance Toolkit on
an ephemeral GitHub-hosted Windows2022 runner. Missing tools fail explicitly;
there is no installer, registry change, persistent logger or desktop handoff.

The push-only workflow is limited to `aella/wgpu-1080p-diagnostics`. It reuses the
existing reload, walk, ADS, directional and jump producers, then verifies and
materializes their original companions through the existing package verifier. The standalone weapon-asset directory is excluded from
checkout and compilation. No assets are uploaded with the profiler artifact.

A fresh Rust1.99 MSVC build retains the normal release optimizer/thin LTO and
adds full PDB information without stripping. This instrumented build identity is
retained separately from retail/preview executables. The exact source tree,
tracked compile/tool/UI/settings bytes, materialized asset hashes, compiler, build settings, EXE and
PDB hashes are recorded. Only the five generated companion folders may differ
from their committed transport bytes: both hashes remain explicit, and the exact
materialized inventory must remain unchanged through build/capture. All other
tracked bytes remain exact. Source commit, CI run/attempt, the five same-run
artifact names and package-verification receipt bind the producer boundary;
GitHub's retained job log supplies artifact IDs/digests for independent joining.
PDBs and the matching executable stay with the trace.

The game first uses `--physical-1080p` to verify its initial 1920×1080 client
area before hooks or application polling. The existing desktop driver then
starts authored stationary gameplay, checks the actual client area repeatedly, warms for 10 seconds, and records 30 seconds of CPU
sampling with immediate present and forced DX12 WARP. GPU timestamps and Record
telemetry are left off. The launched PID and verified window-owner thread ID
allow game-main-thread samples to be separated from software-rasterizer workers.
WPR commands always use a unique owned instance and bounded memory mode. Cleanup
never cancels an unnamed/foreign recorder or searches for another process.

The artifact contains the raw ETL, WPR collector/loss status, xperf profile,
process, trace-statistics and stack reports, including a renderer-thread-filtered
stack report restricted to sampled `Profile` events. The unfiltered stack report
also remains available for other collected event types. `capture.json: passed` means the bounded capture/export commands
completed and their source/asset/binary/extent/exit guards held. It does not mean
that symbols resolved adequately, events were lossless, the authored geometry
was visible, or a hot-function conclusion is established. `top_functions_reviewed`
remains false until the retained data has been independently examined.

Analysis must report the top 20 sampled functions on the renderer thread,
separate inclusive and exclusive counts, describe unresolved symbols and lost
samples, and keep WARP-worker/driver cost separate. CPU sample shares are not
frame wall time; CI WARP is not an RTX3080Ti performance result. No expected FPS
or authored-image gate is relaxed by this diagnostic.

The normal shutdown path records its F10 attempt and any 20-second timeout,
including a bounded responsiveness snapshot. It may then request WM_CLOSE only
on the previously bound HWND after rechecking its owner PID. A zero exit through
that normal window path is distinguished from forced process cleanup. The receipt
retains `shutdown.f10`, `shutdown.wm_close`, `cleanup.forced`, `trace_saved` and a
separate `trace_export` result. A stopped trace is exported even after an unresolved
normal-exit failure; successful export never upgrades a failed capture. Explicit
interrupts stop further exports while retaining their error receipt.

## Preserved failed-capture recovery

Run 38194089349 saved its ETL before a 20-second F10 shutdown timeout. Its original
capture remains failed, with owned-process cleanup exit 1. The separate recovery
workflow consumes only immutable artifact 11723285843 from that run. It verifies
all 15 original compact-report hashes and the exact 19-file inventory, including
retained EXE/PDB bytes against the original build/capture hashes. It never launches
the retained executable or changes the original receipt.

Recovery writes new xperf reports with the original process/thread IDs and records
the ETL hash, full input inventory, installed exporter identity and export hashes.
`exports_completed` does not upgrade `original_capture_passed=false`. The original
archive digest is independently checked against the download action log; it is
not falsely reported as rehashed by the runner after extraction. Source/settings
post-capture guards that the original shutdown failure skipped remain unverified.
The recovered trace can support bounded sampled-function analysis only after
symbol adequacy, event loss and its original timing window are reviewed.

Official references:
- [WPR command line and instance ownership](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/wpr-command-line-options)
- [xperf profile reports](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/xperf/profile)
- [xperf stack filtering](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/xperf/the-stack-action)
- [Symbol lookup and PDBs](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/xperf/symbols)
- [Windows2022 installed tool inventory](https://github.com/actions/runner-images/blob/main/images/windows/Windows2022-Readme.md)
