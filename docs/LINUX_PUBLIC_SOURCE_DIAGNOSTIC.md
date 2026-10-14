# Linux diagnostic preparation from public inputs

`tools/prepare_linux_actual_game.py` prepares an isolated Linux game package on a CPU runtime. It downloads public inputs directly on that runtime, avoiding browser uploads of a large executable or asset archive. It does not launch a graphics window, allocate a GPU, or publish output.

The initial diagnostic uses production source `49c3bf9b3d0482ce81a7d50683904bda28468d7d`, Rust 1.99.0, an explicitly identified native-wgpu-GL harness, and the reviewed wgpu-hal 30.0.1 GL4.3 context patch. Production application modules remain byte-identical. The harness is stored under `tools/` and copied into the disposable build tree; it is not an automatically discovered example in the normal checkout. Validation remains enabled.

## Public asset mode

Use `--asset-mode public-release` for the initial CPU proof. It downloads the existing v0.1.9 Linux ZIP, verifies its 102,577,561-byte size and SHA-256 `b4978796abf0b3301649ae885bf5cce1c0043036ee5297cfc6220ec933b3a5d0`, and stages only six authored asset groups. The release executable is never extracted or executed. Current source49 settings, UI, profiles, configuration, documentation, and optional weapon mesh remain the inputs for the new package.

All groups must pass the current production package contracts. The original public manifests and historical parity records are retained; this mode performs no new Blender export or parity measurement. Its reload provenance differs from the earlier frozen Linux candidate: 8 of 12 reload VRA/VRS/VRM companions differ, while the 15 non-reload raw companions match. The package receives a new executable hash, build label, asset inventory, harness receipt, and package identity. It is a separate diagnostic, not an identical replay of that earlier candidate.

After the tooling is published and its exact commit is known, run:

```sh
python3 tools/prepare_linux_actual_game.py \
  --support-commit EXACT_REVIEWED_TOOLING_COMMIT \
  --asset-mode public-release \
  --install-system-deps --archive
```

The support commit must be an immutable 40-character commit containing the reviewed harness and patch. CPU preparation records phase durations and compiler, source, dependency, asset and executable identities. Quiet work counts as progress when owned processes consume CPU. A 180-second inactivity limit stops stalled commands; no cold-build completion time is promised.

`--dry-run` prints the preparation contract without downloads or builds. `--self-check` validates embedded pins. The optional `regenerate` mode uses `build_linux_authored_inputs.py` and requires its separately supplied SHA-256; it performs data-only source export through pinned Blender 4.3.2 and the production Rust sampler. It does not render previews.

## Output and later runtime testing

Read the terminal `RESULT.json`, fresh `NEW_EXPECTATIONS.json`, package manifests and evidence before using the package. Preparation also creates new source-witness and matrix plans. The old controller with frozen executable pins must not be reused for a newly compiled package.

A subsequent hardware test still needs an observed A100 allocation, an exact adapter match, a real NVIDIA window-surface/Record smoke, and valid completed telemetry before a performance pilot. Successful CPU packaging is not graphics execution or an FPS result. Preserve results and disconnect the runtime after each task.
