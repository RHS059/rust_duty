# Rust Duty preview: manual three-run diagnostic

[Download the small launcher ZIP](rust-duty-preview-38186441859-launchers.zip?raw=1), then get the [verified Windows preview](https://github.com/RHS059/rust_duty/actions/runs/38186441859/artifacts/11720411165). Extract both into one writable local folder, with the three BAT files beside `vector-range.exe`. Keep every game asset. Do not run from inside either ZIP.

The original game ZIP is unchanged and contains only `PLAYTEST_DX12.cmd`; these are separate additional launchers. No command-line typing is needed.

## Run one at a time

1. `PLAY_DX12_GPU_IMMEDIATE.bat`: DX12, Immediate, GPU timestamps requested.
2. `PLAY_DX12_GPU_FIFO.bat`: DX12, FIFO, GPU timestamps requested.
3. `PLAY_LEGACY_GL.bat`: legacy OpenGL, CSV and GPU-counter diagnostics.

Close the previous game before the next. These launchers disable update checks; they do not select a specific GPU, force physical 1920x1080, or change display settings. Keep the same graphics selection, window size, display settings and scene. If Immediate is unsupported, preserve the launch error rather than silently substituting another mode.

For each run:
- Start/resume gameplay. Once loading finishes, stay still for **5 seconds**.
- Press **F8** once. Stay still without moving the mouse for **30 seconds**, then look around with the mouse while standing in place for **30 seconds**. Use approximately the same view movement each time.
- Press **F8** once to stop. Stay in-game until **STOPPING** resolves; do not close during export.
- Open the new `telemetry-sessions/session-.../` folder beside the game. Wait for `GPU_STATUS.json`, which is written asynchronously.
- Add the launcher name and only relevant device/driver, display resolution/scale/refresh, scene and glitch/export observations to `OBSERVATIONS.txt`. Personal information is unnecessary.
- ZIP that whole new session folder, including any error/incomplete files. Post it in the [existing Rust Duty Discord thread](https://discord.com/channels/1554885571489566783/1556808474984325191) and mention **@halcyon**. Halcyon will analyze the evidence first. Do not send only `telemetry.csv`; it is overwritten on the next recording. Nothing uploads automatically.

## What the files can establish

DX12 normally writes `frames.json`, `frames.cpu-substages.json`, and `frames.gpu-timing.json`, alongside CSV, identity/status and GPU-counter files. Check each file's completion/availability; presence alone does not prove valid timing. Missing timestamp support must remain unavailable, not zero.

Legacy intentionally lacks those three native timing files. Its CSV `render_fps` is simulation-clock sampled through a different timing API, not the same per-frame estimator. GPU engine occupancy/memory counters are not GPU frame duration, and their adapter binding is unverified. Do not compare legacy CSV averages against DX12 frame-time percentiles as if equivalent.

This is one mixed manual recording per run, not fixed traversal, a stationary-only benchmark, a verified 1080p/RTX result, or a CPU baseline/candidate speedup test. The short warmup is for this diagnostic only.

## Exact package and verification

- Build: `0.1.11+build.38186441859.1`; artifact `11720411165` (expires 2026-10-19).
- ZIP: 113,505,373 bytes; SHA256 `993e8dfd1dedfcd9a292cf428a8cd699de170c803fe309e4908c575541e3e842`.
- EXE SHA256: `01299162e5675dca91050e65313e7fff1163aa6d2bf7fcd563d9530b42d70b12`.
- Receipt source: `b0e925964dc60353cff41213b1b68e13d7b812c5`, the PR merge with the same complete tree as `d2f28c691b41698ed2d12d7e65de6648f2eac427`.
- Package hashes/receipts, BAT structure/arguments, source control paths and ZIP contents were checked. **These BATs were not executed on Windows; no new gameplay or hardware test is claimed.** Launchers check executable presence, not its hash.
