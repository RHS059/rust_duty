# Public-source A100 preparation and controller proposal

Status: code and offline tests only. No GPU allocation, browser change, game execution, surface success, recording success, FPS result, or GPU shutdown is established by this proposal. Coordinator review and publication are required before a future authorized runtime task.

## Isolation and immutable inputs

The published CPU script at 1357347dd08f1c2004a6d00b3d0db6d50f55521b is untouched. Its SHA-256 remains ac77ab291e5fb1abd6607a41793337a9fc51a88dc293db506f8e8ea7154e4296. All 25 original CPU tests remain unchanged. A100 code imports only an explicit list of neutral fetch, source validation, packaging, and process helpers from that verified file. It never calls or replaces the CPU frontend, CPU prepare function, CPU inventory gate, or GPU-hiding environment. A100 orchestration and its environment are separate and explicit. The CPU frontend remains fail closed when NVIDIA hardware exists.

Source is public RHS059/rust_duty commit 49c3bf9b3d0482ce81a7d50683904bda28468d7d. The original 110 production files, current UI, settings, and documentation are preserved. The reviewed tools/linux_actual_game_gl.rs and linux_gl43_context.patch bytes are unchanged. Official Rust 1.99.0, wgpu-hal 30.0.1 and GL4.3 dependency overlay pins remain unchanged. No private soldier assets, old game executable, credentials, signed private artifact URL, or prior package is accepted.

This A100 entrypoint only supports public-release assets: exact v0.1.9 Linux ZIP URL, SHA-256 b4978796abf0b3301649ae885bf5cce1c0043036ee5297cfc6220ec933b3a5d0, and 102,577,561 bytes, independently checked against source49 authoring/source contracts and production package validators. It never extracts the release executable, UI or config. Fifteen non-reload raw companions previously matched the frozen fixture; 8 of 12 reload companions differ. Existing source/parity records are revalidated; no new authoring/parity measurement or whole-asset equality is claimed. The CPU-only regeneration helper remains available separately and is not an A100 execution path.

## Entry and host contract

After review/publication, fetch the five exact tool files using public immutable URLs and verify independently supplied SHA-256 values before executing them:

- prepare_linux_actual_game.py (frozen neutral helpers and separate CPU frontend)
- a100_public_build.py
- prepare_public_a100.py
- run_public_a100_matrix.py
- prepare_a100_text_export.py

Invoke prepare_public_a100.py with /usr/bin/python3.12, --execute, the newly published --support-commit, --allocation-start-unix recorded when the A100 allocation actually began, and --deadline-unix no more than 1,800 seconds after that start. --install-system-deps permits the already authorized official distro dependencies, including Xvfb/Openbox/xdotool during initial setup before the build. Without that flag these X11 tools must already exist. --smoke-only deliberately stops after validated smoke. The default attempts the five-case pilot only when smoke is valid and the remaining budget admits it. --dry-run and --self-check do not query a GPU, create a directory, download, build, or run a game.

The entrypoint requires the actual distro Python 3.12 executable; venv creation explicitly uses /usr/bin/python3.12 because Colab's default 3.13 lacked ensurepip during the CPU proof. Hardware inventory must contain exactly index 0, NVIDIA A100-SXM4-40GB, a NVIDIA PCI vendor identifier, and the 40GB memory range. UUID, model, PCI identity, driver, and memory must remain equal before/after preparation and runtime. Missing, unknown, different, or multiple GPUs fail closed. Full nvidia-smi, lscpu, and ldd output is retained. A100 receipts are labeled A100 and never cpu_only.

## Fresh artifact and actual game gates

Preparation creates a new checkout, linked ELF executable, build identity, experimental harness receipt, package inventory, source witness, matrix package identity, evidence inventory, and NEW_EXPECTATIONS.json. New expectation hashes bind the actual build and all five preparation/export tools. The controller requires the separate expectation digest and verifies every package/evidence/tool byte before the first graphics operation. It checks the source49/GL43/asset receipt contracts and revalidates them after runtime.

Matrix tools are the exact public files at b73588d13fcf3329f1485f9bf1187dee55b7ed55. They keep normal exact PID-owned X11 window checks, actual surface extent, F8 Record lifecycle, completed frames.json, IDENTITY.json, CSV_STATUS.json, GPU_STATUS.json, gameplay.csv, and GPU counter exports. The controller recomputes the completed analysis, compares it with stored SUMMARY.json, and requires observed actual_backend Gl and the complete exact selected fingerprint:

    backend: gl
    name: NVIDIA A100-SXM4-40GB/PCIe/SSE2
    vendor_id: 4318
    device_id: 0
    device_type: Other

A CLI renderer flag does not prove a backend. Production main --renderer=gl selects the legacy path. This explicitly labeled experimental entrypoint imports unchanged production application modules and executes native wgpu GL; its actual telemetry must prove that path. There is no fallback adapter or software rendering acceptance. A surface or Record failure stops the task without an FPS claim.

A private owned Xvfb display :97 uses 4096x2304x24, -nolisten tcp and -noreset, followed by Openbox and xdotool. Existing display :97 is rejected. NVIDIA EGL vendor selection is process-local and points to the existing /usr/lib64-nvidia/libEGL_nvidia.so.0. There is no driver install or system security change. All own process groups and observed descendants are terminated on failure or timeout.

Plans are generated afresh at their actual hashes: one 10-second warmup + 10-second smoke, then five 15-second warmup + 30-second captures in baseline, 720p, 1440p, ADS, baseline order. They are not the full 33-run matrix. A change from the older CPU default plans requires newly generated and explicitly rebound expectations; the controller rejects other timings or plan identities. Fifo, single-sample native targets, fixed viewmodel size and unsupported AA/LOD/application-cap selectors remain truthful. No PNG readback occurs during measurement. Linux GPU frame duration remains explicitly unavailable. CPU present-return intervals do not establish display scan-out cadence, GPU frame time, or RTX performance.

## Budget, progress, and completion

The observed unchanged CPU retry completed in 870.439 seconds (14 minutes 30 seconds), including its full archive. It reused system dependencies and is not a pristine cold-start measurement. The linked build took 449.970 seconds, asset validation 33.942 seconds, and package staging 100.157 seconds. A further 236.789 seconds were outside the measured subprocess phases (downloads, extraction, archive and other orchestration); the receipt does not attribute that remainder more precisely. A100 duration remains unmeasured. The approved total allocation cap is now 30 minutes: the same observed preparation duration would leave approximately 839.561 seconds after the 90-second reserve, allowing the conservative 150-second smoke and 480-second pilot admission budgets, without guaranteeing actual completion.
The clock is tied to observed allocation start, never reset at build or controller start, and protected against wall-clock rollback by a monotonic end. Build/log growth or own group/descendant CPU time counts as progress; three minutes with no progress stops the subprocess. Preparation is externally supervised so direct downloads and packaging cannot escape the allocation work cutoff. Smoke requires a conservative 150 seconds remaining; pilot requires 480 seconds. If insufficient for pilot, mark it skipped, still verify the final source/host state, then export validated smoke evidence immediately. Failed postflight clears the proven-stage flags. If insufficient even for smoke, stop and export build evidence. Do not wait until the budget expires. No new allocation is started by these scripts.

The workflow skips the optional full pre-runtime package archive. Its default a100-evidence-only.tar.gz contains every retained raw runtime file, including partial/failed frames, CSV, GPU JSONL/metadata, status, identity, START/RESULT, game/driver logs, plus source witness, plans, manifests and preparation/validation logs. Executable bytes, raw assets, checkout and toolchain are excluded. EVIDENCE_EXPORT_RECEIPT.json binds the archive SHA-256 and every archived member's size/hash. Archive creation is bounded to at most 45 seconds, leaving at least 45 seconds for preservation/disconnect. Repeating an export cannot delete its existing verified archive.

The archived RESULT.json is explicitly a pre-export snapshot. The final top-level RESULT.json and EVIDENCE_EXPORT_RECEIPT.json are authoritative and must accompany the archive. The text route embeds both exact final files separately and reconstructs them as FINAL_RESULT.json and EVIDENCE_EXPORT_RECEIPT.json; it does not leave only the pending snapshot.

The separate export_executable(root) function is optional and is never called automatically. Use it only after the evidence has been independently preserved, if enough allocation time remains. An executable download is not a shutdown prerequisite. Neither a successful local archive nor emitted text proves external retrieval.

See NOTEBOOK_A100_RUN_AND_EXPORT.md for the reviewed pinned launcher and acknowledged, one-chunk-at-a-time notebook fallback. The fallback has an 8 MiB compressed evidence ceiling and never truncates or drops raw files to fit. Its per-call 30-second emission cap preserves 15 seconds for disconnect and checks both the original persisted monotonic deadline and the same boot identity. At the ceiling it requires 171 separately acknowledged chunks; the reserve does not guarantee notebook preservation. If output is missing, truncated, oversized or time expires, report external export incomplete. Do not extend the allocation or disguise incomplete evidence as a successful transfer.

The browser operator must verify the archive/final receipts were downloaded, or that all requested text outputs and their END digest are present and the private notebook is saved, then disconnect and delete runtime immediately. DOM-based reconstruction can happen after GPU shutdown. The scripts kill their own processes but cannot release the Colab GPU or claim shutdown. Record browser-confirmed disconnect separately.
