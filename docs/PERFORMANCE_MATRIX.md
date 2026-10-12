# Real-game performance matrix

`tools/performance_matrix.py` prepares a finite experiment, drives separate game
processes sequentially through the existing controls, and validates/summarizes
their real Record exports. Preparation and analysis never start a game or request
a GPU. Running needs a prebuilt package and an already available dedicated
desktop. It neither creates a display nor installs software. No PNG readback is
requested during measurement. Renderer validation remains enabled.

The performance goal is stable 1080p at 60 Hz on the selected RTX 3080 Ti. Results
from WARP, another GPU, or the experimental Linux native-GL entrypoint have their
own scope and cannot establish that goal. A complete matrix is evidence, not a
visual/gameplay approval or automatic performance verdict.

## Inventory of actual controls

The inspected production source starts at 1440×900 logical pixels; the existing
reference flag selects 960×540 and changes calibrated presentation, so this
matrix does not use it. Native window resizing changes the physical world/HUD
render extent. The viewmodel's offscreen texture stays 1440×900. Therefore the
resolution sweep varies world/HUD pixels and the final composite, not every
render target. Every trace's observed physical extent and CPU-stage extents must
match its case. DPI scale must stay constant between runs.

| Axis | Implemented matrix support |
| --- | --- |
| Surface resolution | 1280×720, 1920×1080, 2560×1440, diagnostic 3840×2160 via real window resize |
| Present mode / FPS limit | Matrix stays at native `Fifo`; the integrated candidate exposes opt-in concrete present modes separately. No application limiter; Fifo is not necessarily 60 Hz |
| AA | Native single-sample targets/pipelines; no AA selection. Legacy requests 4x window MSAA, single-sample viewmodel texture |
| LOD / visibility | No selectable LOD, frustum/occlusion-culling or offscreen mesh hiding mode; mesh `cull_mode=None` |
| Scene complexity | Existing `--procedural-weapon` versus packaged presentation in the same default range |
| Record overhead | Record remains on for every measured case; no frame trace exists with Record off, so overhead is unavailable |
| HUD | Existing F1 debug-panel command trial; actual panel state is not emitted by telemetry. Ordinary HUD remains on |
| Actions | Stationary hip, held RMB ADS using `--hold-controls`, W/S movement alternating every two wall-clock seconds |
| Backend | Production DX12/Vulkan/Metal native runtime; explicit, separately labeled Linux native-GL harness when packaged with its provenance |

`--renderer=gl` on the production executable means legacy Macroquad, whose Record
export has no CPU present-return trace. It is excluded from this measurement
runner. The isolated `gl-harness` mode is an experimental entrypoint importing the
unchanged production application and native runtime; it is not the production GL
launcher and must not be reported as one. Its selected A100 adapter must still
match the native runtime's exact requested/actual fingerprint evidence.

### Measurements and limitations

- Primary: real CPU wall-clock successful-present-return intervals, p50/p95/p99
  using the existing nearest-rank method. The reciprocal mean is labeled
  effective present Hz, not GPU FPS or scan-out rate.
- Existing paired CPU spans: surface acquisition, application/draw-list work,
  renderer submission, and the present call. Missing spans stay unavailable.
- Retained hitches are not trimmed. A surface skip remains part of the next
  present interval. Focus/pause/resize/capture boundaries invalidate a run.
- Existing GPU occupancy/memory files are retained with their status, including
  unsupported platforms. They are not synchronized GPU frame timestamps.
- GPU durations remain unavailable by default. Reviewed DX12 sources can opt in
  to the strictly joined command-buffer timing path below. Actual-game draw/pass/
  triangle counts, Record-off overhead and unimplemented graphics settings remain
  unavailable, never estimated from the synthetic pass-submission example.
- F1's requested state is supported by the driver command, but the current
  telemetry does not independently report HUD state. Movement/ADS are checked
  against the gameplay CSV. CSV `render_fps` is never used for frame statistics.
- Actual CSV simulation time is reported as first/last/span, advancing/unchanged
  adjacent samples, and `advancing`, `intermittent_progress`, or `stalled`.
  Frozen simulation is labeled static rendering evidence. ADS/movement tests
  cannot count a zero-span recording as evolving gameplay, even if a held pose
  happens to match. A single CSV row cannot establish progression.
- This is a timed external input replay, not a fixed-tick simulation replay.
  Mouse motion and other user input must be absent on the dedicated desktop.
  The driver checks focus/extent at the same 100 ms cadence in all cases. Its
  overhead remains in the protocol, including subprocess calls on X11.

## RTX 3080 Ti / Windows DX12 capture checklist

The target is stable **1920×1080 physical pixels at 60 FPS on the selected
RTX 3080 Ti using the production wgpu DX12 runtime**. A software-adapter run,
another backend, a build-only check, or an average alone cannot establish it.
Keep the existing evidence-quality checks below; this checklist adds no new
automatic pass threshold.

Before comparing a baseline and candidate:

1. Record both exact source commits, executable SHA-256 values, embedded build
   labels and `BUILD_IDENTITY.json` files. Retain the actual build command,
   Cargo profile/features, Rust toolchain, target and any compiler/profile
   overrides from their build receipts. Current build identity binds the binary
   and source but does not independently report the optimization profile,
   `debug_assertions`, enabled features or compiler fingerprint. Do not infer
   these from a filename or invent missing values. `Cargo.toml` configures thin
   LTO and one codegen unit for release; the actual build must use that profile.
   The convenience `run.bat` uses release but does not enable `wgpu-runtime`;
   its default launch is legacy Macroquad, so it is not this DX12 protocol.
2. Use the already selected exact DX12 `graphics-device.json`, not Auto, a name
   substring or forced fallback. Keep the observed adapter fingerprint,
   `driver` and `driver_info` with each trace. Record CPU model, Windows version,
   display/refresh rate and power settings in `--hardware` notes, explicitly as
   operator claims. Keep the same monitor, refresh, DPI and window mode for both
   builds. Native Fifo does not itself mean 60 Hz; refresh/cadence is not
   independently observed by this runner.
3. Retain settings, graphics preferences, adjacent asset/UI hashes and observed
   scene/presentation identity. Use the same default range, packaged presentation
   and action protocol. Require actual 1920×1080 surface and CPU-stage extents;
   do not use `--reference-viewport`. The viewmodel target remains 1440×900, so
   label a resolution sweep accordingly. Keep Record on for all compared cases
   and avoid screenshots/readbacks or unrelated GPU workloads during samples.
4. Run the setup smoke, then the bounded pilot on each build on the same
   dedicated Windows desktop. Preserve baseline brackets and individual runs.
   Check simulation progression as well as ADS/movement outcomes; a static or
   stalled scene cannot establish evolving-gameplay performance. A changed
   inventoried runtime requires review of the source binding before capture;
   do not bypass that check or reuse an older package as the candidate.
5. Return each run's retained interval count/duration, p50/p95/p99, effective
   present Hz, paired CPU-stage distributions and all failures with the raw
   session exports. The 60 Hz budget is about 16.67 ms, but present-return
   intervals are CPU pacing evidence, not scan-out or GPU execution time.
   Compare application/draw-list, renderer-submit, acquire and present spans
   before attributing a regression. GPU occupancy is not GPU frame duration;
   default traces have no timestamp-query durations. Opted-in command-buffer
   durations are separate from present intervals. Actual-game draw/pass/triangle
   counts and Record-off overhead remain missing.

A repeatable RTX pilot is the next measurement after a source optimization.
Synthetic submission benchmarks can explain a narrower cost but cannot replace
that same-device, same-scene comparison or claim the 1080p60 target is met.

## Bounded experiment

The full plan has ten distinct cases. Seven change one baseline variable:
720p, 1440p, 4K, ADS, movement, added debug HUD, and procedural presentation.
Two justified interactions combine 1440p with movement or debug HUD. Three
rotated repeats each start/end with 1080p baseline: 33 fresh, isolated game
processes total. Defaults are 15 seconds stationary warmup and 45 seconds Record
per run, plus startup/export time. ADS settles before recording; movement begins
at the start of its measured replay. Baselines bracket drift rather than mixing
all frames into one percentile.

Use `--smoke` first for one baseline. Use `--pilot` next for five runs:
1080p baseline, 720p, 1440p, 1080p ADS, repeated baseline. The pilot gives an early
resolution/ADS signal before committing to the full matrix. Neither preset is
presented as full-matrix completion.

`--static-diagnostics` selects only the remaining static conditions:
1080p baseline, 4K, the F1 command trial, procedural presentation, repeated
1080p baseline. This five-run selection does not repeat the completed 720p or
1440p cases and makes no evolving ADS/movement claim. The procedural case must
observe `scene.presentation=procedural`; the F1 case must retain its successful
command receipt while keeping actual HUD state unverified. Historical plans
remain accepted without the new optional `static_diagnostics` field.

The Windows software caller uses this static selection with 120-second samples
and the unchanged 100-interval requirement. Its existing `pilot` file/step names
are retained for caller compatibility; the plan and analysis explicitly identify
`static_render_diagnostics`. An independent setup smoke precedes these cases.
Verified owned-process cleanup permits authorized measurement continuation, but
each failed graceful shutdown remains failed and the final job stays red.

The source-49 package discards simulation time when application frame dt exceeds
250 ms (`session.rs` and `app.rs`). In Windows WARP run 37517711655, the completed
1080p, 720p and 1440p recordings retained 139, 156 and 118 intervals, respectively,
while CSV simulation advanced 0, 9.4666 and 0.0833 seconds over about 120 wall-clock
seconds. ADS remained zero and its simulation time stayed at 0.1667 seconds.
That ADS case remains failed. Median surface acquisition was about 1001 ms in
all four captures. These observations are consistent with hitch-stalled
simulation, not evidence of a driver input fault or RTX performance.

Analysis retains the fraction of present intervals above 250 ms as supporting
hitch evidence. Present-return intervals are not direct measurements of the
application's dt. The simulation-span/present-duration ratio also has different
sampling endpoints; it is not a new physics or performance threshold. Different
simulation progression can confound static cost comparisons and must be reviewed
alongside the resolution, presentation and CPU-stage data.

A smoke validates window/input/recording/export/graceful-exit behavior separately
from statistical sample quality. It reports `setup_complete` only when those
checks succeed; its retained quantiles are descriptive. Fewer than 100 intervals
sets `tail_comparison_ready=false` and makes the analysis command return 1, so an
automated caller cannot advance to the pilot on a low-sample setup. Pilot/full
still require at least 100 intervals per run. A roughly 1 Hz software/CI surface
may be useful for setup diagnosis while remaining unsuitable for this bounded
statistical pilot. Successful export does not turn a failed process exit into
setup success; the original failed receipt stays failed.

## Prepare and run

Run commands from a checkout with the same source commit as the package. The
inventoried runtime files must match one exact reviewed support manifest and be
clean. The historical 17-file inventory remains accepted unchanged for the
source-49 package and pinned Windows software caller. The optional CPU substage
build has a separate 20-file inventory: those same 17 paths plus
`src/frame_cpu_substages.rs`, `src/render/frame.rs`, and `src/lib.rs`. Its recorder,
session and device files were already in the original inventory. This expands
the reviewed diagnostic support surface without changing the source-49 binding,
render controls, four-span frame schema or measurement acceptance checks.
The combined CPU candidate has a separate exact 24-file inventory, adding
`src/draw/mod.rs`, `src/render/lines.rs`, `src/render/text.rs`, and
`src/render/plan.rs` to the sidecar inventory. Its line recorder coalesces adjacent
bit-identical model runs, and its text planner streams stack quads. New live
exports check these four files even for historical builds: a narrower 17/20-file
inventory is allowed only when their exact reviewed baseline bytes are unchanged.
This prevents an edited CPU path from silently receiving a historical witness.
Already exported historical witnesses keep their original bounded scope.
The combined digest is
`0a904c635739b3365ff99569466098e71b3d81e8e456939163421aad311fe4c5`.
Source-level allocation reductions do not establish a measured CPU time or FPS
gain. Line recording is inside `game_recording`; text planning is one part of
`encode_submit`, which also includes uploads, encoding and queue submission.
The present-policy integration has an exact 27-file inventory, adding
`src/render/present_policy.rs`, `src/render/mod.rs`, and `src/render/backend.rs`.
Its digest is
`a6af645f2e1b5c4c71b9a65964a963a1ad1217a75efff7b0cf8f9c39280880a6`.
New live exports also guard the baseline module declarations/backend bytes;
removing the helper cannot authorize fallback to an older inventory. Historical
17/20/24-file artifact witnesses remain valid at their original scopes. The
present integration's plan states that this runner fixes Fifo; it does not pass
a mode selector or relax actual Fifo validation. See the
[integration boundaries and remaining checks](engineering/present-mode-integration.md).
An unknown source change requires an inventory review before its binding
is updated. Use a writable workspace directory as `TMPDIR` when
the host's `/tmp` is full. Outputs are exclusively created and never overwritten.

```sh
python tools/performance_matrix.py prepare --repository . --renderer dx12 \
  --smoke --warmup-seconds 10 --sample-seconds 10 --output smoke.json
python tools/performance_matrix.py prepare --repository . --renderer dx12 \
  --pilot --warmup-seconds 10 --sample-seconds 10 --output pilot.json
python tools/performance_matrix.py prepare --repository . --renderer dx12 \
  --output full-matrix.json
python tools/performance_matrix.py prepare --repository . --renderer dx12 \
  --static-diagnostics --warmup-seconds 10 --sample-seconds 120 --output static.json
```

For a portable machine without Git, export a bounded source witness from that
verified checkout before allocating runtime. The export includes exactly its
reviewed inventory's 17, 20, 24, 27 or 29 runtime files, `SOURCE_WITNESS.json`, and optionally the isolated GL
harness. It creates no Git repository and makes no claim about the destination's
HEAD. The source commit comes from the checked export's real Git identity.

```sh
python tools/performance_matrix.py export-witness --repository . \
  --harness /path/to/examples/linux_actual_game_gl.rs --output source-witness
```

Keep the printed witness SHA-256 separately from the transferred directory.
Omit `--harness` for a production entrypoint. On the destination, replace
`--repository .` in both prepare and run commands with
`--source-witness source-witness --witness-sha256 EXPECTED_DIGEST`. The expected
digest is required independently; it is never automatically trusted from the
same artifact. Every source file, the reviewed support manifest and optional
harness are checked before execution and again afterward. Each witness must
declare the exact matching inventory digest and path set; mixing the old digest
with the new paths, or dropping a sidecar source file, fails closed. Extra files or links
fail closed. Source commit equality with the package and recorded session still
applies. Plans, execution manifests and analysis distinguish `live-git` from
`artifact-witness` and retain the witness digest.

The package contains the executable, `BUILD_IDENTITY.json`, its adjacent assets
and `ui/theme.css`. Its metadata must bind the executable SHA-256, source commit
and embedded build label. The runner hashes adjacent assets/UI for reproducible
identity; it does not copy asset contents into evidence or upload anything.
Each run gets a new working directory, settings copy, graphics preference copy,
game log, command/result receipt and `telemetry-sessions` folder. The package and
original settings remain unedited.

For the real Windows hardware test, copy the game's existing exact selected-GPU
`graphics-device.json` and supply it. Auto or a name substring is not enough.

```sh
python tools/performance_matrix.py run --plan pilot.json --repository . \
  --executable /path/to/package/vector-range.exe --settings settings.cfg \
  --graphics-settings /path/to/selected/graphics-device.json \
  --driver win32 --output new-pilot-results --execute
```

For an explicitly scoped Windows software diagnostic, replace
`--graphics-settings ...` with `--force-fallback`. Analysis requires observed CPU
adapter classification and retains the fallback request; it never labels this
RTX data. Native Win32 input uses Python's built-in `ctypes` and an interactive
desktop. Windows refusing focus is a failed setup, not a reason to bypass it.
Both desktop drivers request the game's normal F10 exit after exports complete,
verify the same window still has focus, and retain the 15-second exit timeout.

Linux uses `--driver x11` and needs an existing X11 `DISPLAY` plus installed
`xdotool`; the runner does not provision Xvfb or a GPU. The display/window manager
must permit the requested exact client dimensions. For a production native
Vulkan package use `--renderer vulkan` during preparation. Do not assume the A100
supports this surface just because a different GL test worked.

An explicitly authorized isolated native-GL package uses `--renderer gl-harness`
during preparation. Its `BUILD_IDENTITY.json` must include a
`benchmark_entrypoint` object with kind `linux_native_gl_actual_game_harness`,
source path `examples/linux_actual_game_gl.rs`, its SHA-256, receipt file
`ACTUAL_GAME_HARNESS_RECEIPT.json`, and receipt SHA-256. That receipt must bind its
executable and document the toolchain/dependency overlay. The harness sets the
specific native adapter fingerprint in memory; `--graphics-device=auto` prevents
production preference parsing of the otherwise unsupported GL fingerprint.
The expected fingerprint file remains separate evidence and requested/actual
adapter equality is mandatory. No automatic fallback is permitted in this mode.

Optional `--hardware hardware.json` stores operator CPU/display/refresh/driver
notes separately from observed identities. A shared desktop lock serializes
runner invocations even when output folders or backends differ. Do not run other
games or GPU workloads at the same time. A stale lock is left for inspection,
never automatically broken. Parallel isolated machines are a separate experiment;
simultaneous game instances on one GPU would confound these measurements.

## Analyze

```sh
python tools/performance_matrix.py analyze new-pilot-results --output analysis.json
python -m unittest discover -s tools -p 'test_performance_matrix.py'
```

Analysis validates producer JSON and recomputes statistics, checks actual
backend/selected GPU/present mode/build/source/settings/physical extent, requires
at least 90% of the requested retained duration and, for pilot/full runs, 100
intervals. Smoke reports sample sufficiency separately. Analysis rejects
wrong gameplay, mixed adapters/drivers/DPI, overlapping processes and incomplete
exports. These are evidence-quality checks, not new renderer or gameplay pass
thresholds. Failures/missing runs remain visible; no data is zero-filled. The
first invalid capture stops further execution, keeping its files for diagnosis.

Inspect p50/p95/p99 and CPU spans for each repeat and paired baseline deltas.
Increasing renderer-submit CPU time with unchanged resolution points somewhere
different from resolution-dependent end-to-end intervals; Fifo/acquire waits
can also dominate pacing. Neither observation isolates GPU duration. Compare
actual devices only within their observed backend/present/display conditions,
then re-run the bounded pilot on the selected RTX 3080 Ti before claiming the
1080p60 goal has been met.

### GPU-enabled source inventory

The optional GPU/session integration has an exact 29-file runtime inventory,
extending the reviewed present-policy inventory with `src/frame_gpu_capture.rs`
and `src/render/gpu_timing.rs`. Live dirty, mutated, missing or partial GPU source
cannot silently fall back to a historical witness. Historical artifact witnesses
remain accepted only with their original exact inventories and external hashes.
The initial published 29-file WIP digest is also retained explicitly when a
reviewed formatting/test-fix revision changes that same inventory's bytes.
The default matrix still leaves GPU timestamps disabled and fixes Fifo. The
explicit `--gpu-timestamps` plan option is limited to the exact current candidate
and four-file counterfactual inventories below. It waits for, hashes and runs the
unchanged strict [CPU/GPU sidecar readers](engineering/gpu-session-integration.md)
against the original primary bytes. Neither source acceptance nor a valid sidecar
proves target performance.


### Exact four-file CPU comparison

The current candidate runtime digest is
`9b7ae93be3a4d4aed9b662d0c27ff18d0b1e12e99c4dc916422c98e0c5eae3c6`.
The counterfactual runtime digest is
`dbabe2822dd73410a7f05c0f03807aa80d5720351c4a9c13ebdee1276fecc195`;
its real source commit is `4604e7e4648d05f4750f73f7d4d72ea23ddfb1ef`
(full tree `6027ffefbad4becad75a06e65516898be1bb5990`). It restores only
`src/draw/mod.rs`, `src/render/lines.rs`, `src/render/text.rs` and
`src/render/plan.rs` from `70ff2933ebe69b7180e207c7defebeaeb6e240e1`.
The baseline is a real separate Git source, not an alias for the candidate or an
unmodified historical release. Both retain the same diagnostics and Fifo policy.

`tools/build_performance_pair.py` creates fresh release packages from those exact
checked-out sources in the actual `build.yml` CI run. The closed 118-file compile
inventory, compiler identity in each source directory, Cargo configuration and
environment, fixed release command/profile/features, original build logs,
executable hashes, source witnesses, public UI/settings and real build identities
and asset-free package executables are retained in the job artifact. The candidate's actual `GITHUB_SHA` can be a PR merge commit; it is
never rewritten to a branch-head SHA. The baseline retains its actual separate
commit and the receipt also records the CI run's candidate source.

The branch-scoped `dx12-performance-pair` job builds without embedded or adjacent
game assets and runs the production default range with procedural presentation,
1920×1080 physical surface, DX12/WARP and Fifo. It uses 10 seconds warmup and
120 seconds Record per process, to give slow software captures a chance to reach
the unchanged minimum of 100 present intervals and 100 measured eligible GPU rows.
Unavailable/undersampled timing remains explicit and fails readiness. This is a
native protocol check; WARP results do not establish RTX 3080 Ti performance.

For the selected RTX, use the same freshly built reviewed packages and run on an
already available dedicated Windows desktop. The following PowerShell command
uses `BUILD_PAIR.json` from that build; `graphics-device.json` must select the
exact DX12 adapter fingerprint. Hardware notes are retained as operator claims.

```powershell
$pair = Get-Content evidence/performance-build/BUILD_PAIR.json -Raw | ConvertFrom-Json
python tools/performance_matrix.py compare `
  --baseline-source-witness evidence/performance-build/baseline/source-witness `
  --baseline-witness-sha256 $pair.variants.baseline.source_witness_sha256 `
  --baseline-executable evidence/performance-build/baseline/package/vector-range.exe `
  --baseline-build-receipt evidence/performance-build/baseline/build-receipt.json `
  --candidate-source-witness evidence/performance-build/candidate/source-witness `
  --candidate-witness-sha256 $pair.variants.candidate.source_witness_sha256 `
  --candidate-executable evidence/performance-build/candidate/package/vector-range.exe `
  --candidate-build-receipt evidence/performance-build/candidate/build-receipt.json `
  --settings evidence/performance-build/candidate/package/settings.cfg `
  --graphics-settings graphics-device.json --hardware hardware.json `
  --procedural-baseline --driver win32 --warmup-seconds 15 --sample-seconds 45 `
  --execute --output evidence/rtx-cpu-comparison
```

The order is baseline/candidate/candidate/baseline, repeated twice. One common
desktop lock spans all eight fresh processes. Source, package, build receipt,
settings, actual adapter/driver, physical extent/DPI, Fifo and scene must stay
matched; previous captures are rehashed and reanalyzed before final acceptance.
Failures stop the sequence and retain the incomplete evidence. No forced-exit
continuation is allowed. Each run retains its own distributions and measured
subset count; percentiles are never pooled or subtracted to infer a stage cost.

This is controlled stationary input with the real per-frame grid/HUD and draw
recording, not deterministic gameplay replay or authored-presentation approval.
`game_recording` includes the line-recording change and other application work;
`encode_submit` includes FramePlan/text streaming, uploads, encoding and queue
submission, nested inside `renderer_submit`. Do not add parent and child spans.
GPU timestamps cover one ordered command buffer and exclude queue wait, other
submissions, present/DWM and display scanout. Missing/pending/rejected rows stay
null and outside measured percentiles. A long acquire span with short GPU ticks
suggests pacing but does not isolate vsync, compositor or backpressure. Fifo can
hide CPU improvements in present cadence. Timestamp-off overhead and matched
Immediate/Fifo discrimination remain separate investigations; this comparison
holds timestamps on and Fifo fixed in both variants. `performance_improvement`
stays null and `target_1080p60_proven` stays false until the evidence is reviewed.
