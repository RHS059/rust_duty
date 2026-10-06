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
| Present mode / FPS limit | Native `Fifo` only; no application limiter or vsync selector. Fifo is not necessarily 60 Hz |
| AA | Native single-sample targets/pipelines; no AA selection. Legacy requests 4x window MSAA, single-sample viewmodel texture |
| LOD / visibility | No selectable LOD, frustum/occlusion-culling or offscreen mesh hiding mode; mesh `cull_mode=None` |
| Scene complexity | Existing `--procedural-weapon` versus packaged presentation in the same default range |
| Record overhead | Record remains on for every measured case; no frame trace exists with Record off, so overhead is unavailable |
| HUD | F1 debug panel off/on; ordinary HUD and recording indicator remain on |
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
- GPU durations, actual-game draw/pass/triangle counts, Record-off overhead and
  unimplemented graphics settings are explicitly unavailable, never estimated
  from the synthetic pass-submission example.
- F1's requested state is supported by the driver command, but the current
  telemetry does not independently report HUD state. Movement/ADS are checked
  against the gameplay CSV. CSV `render_fps` is never used for frame statistics.
- This is a timed external input replay, not a fixed-tick simulation replay.
  Mouse motion and other user input must be absent on the dedicated desktop.
  The driver checks focus/extent at the same 100 ms cadence in all cases. Its
  overhead remains in the protocol, including subprocess calls on X11.

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
17 inventoried runtime files must match the reviewed support manifest and be
clean. An unknown source change requires an inventory review before its binding
is updated. Use a writable workspace directory as `TMPDIR` when
the host's `/tmp` is full. Outputs are exclusively created and never overwritten.

```sh
python tools/performance_matrix.py prepare --repository . --renderer dx12 \
  --smoke --warmup-seconds 10 --sample-seconds 10 --output smoke.json
python tools/performance_matrix.py prepare --repository . --renderer dx12 \
  --pilot --warmup-seconds 10 --sample-seconds 10 --output pilot.json
python tools/performance_matrix.py prepare --repository . --renderer dx12 \
  --output full-matrix.json
```

For a portable machine without Git, export a bounded source witness from that
verified checkout before allocating runtime. The export includes exactly the 17
inventoried runtime files, `SOURCE_WITNESS.json`, and optionally the isolated GL
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
harness are checked before execution and again afterward. Extra files or links
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
