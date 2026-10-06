# Windows acquire/exit diagnostic

This isolated diagnostic exports production commit
`49c3bf9b3d0482ce81a7d50683904bda28468d7d` and the hash-pinned
`wgpu-hal 30.0.1` crate into separate source/dependency directories. It never
changes production Cargo files, game code, registry sources, Wait/Fifo policy,
physics, input consumption or performance-matrix thresholds. It has two explicit
modes; the workflow defaults to `timeout-return-candidate`:

- `baseline` reproduces the original logging-only Rust patches. A false HAL wait
  remains ignored. This mode is retained for reproducibility, not automatically
  rebuilt alongside the candidate.
- `timeout-return-candidate` adds one behavior change: `if
  !diagnostic_wait_result? { return Err(crate::SurfaceError::Timeout); }` before
  the first backbuffer lookup and `acquired_count` increment. Additional markers
  observe timeout propagation, skipped frames and resumed frames.

The exact pinned API defines `SwapChain::wait` as
`Result<bool, crate::SurfaceError>` and maps `WAIT_TIMEOUT` to `Ok(false)`.
Failed/abandoned waits remain `Err(SurfaceError::Lost)`. The `?` propagates every
existing error unchanged, including Lost/Outdated/Device errors; only a successful
false result becomes Timeout. The copied HAL error enum is also hash-verified.
Neither `DontWait` nor a duration threshold is substituted for the wait result.

## Historical baseline remains distinct

Observer run `37525012138`, attempt 1, artifact `11442486459` has archive SHA-256
`451784a6b7e863386eefc06371f10add8e1bc7ea6e59539c2ca55a87dd73dc31`.
Its runner commit is `fb2f606a141235a27edca5f6beac5361ba484834`;
its diagnostic EXE SHA-256 is
`d9f8f95a511a87af86738d691ec4bc5e5436d8366baa4e6dcbaaf8bc2cc69182`.
Its summary SHA-256 is
`98de25a94ee8e126ecbf8b74e85fd7ccba61127490e6329c55bcca383b09e3cf`.

That run observed 25 false results among 38 HAL waits and 28 retained eligible
intervals. F10 and `run_app` both returned. `hooks_drop` entered but did not return
within the remaining portion of the 15-second normal-exit budget. Owned-process
cleanup was verified; graceful exit remained failed. These are historical
observations, never candidate evidence. The old artifact contains no reusable
executable or image fixture. Its identity is recorded in new receipts without
redownloading or changing its files.

## One candidate build and bounded native checks

Preparation verifies all original hashes, records complete source/dependency
manifests and exact patches, and selects only the same-version copied HAL through
a separate Cargo configuration and the narrow lockfile registry-to-path change.
Build/stage/run receipts label the mode and bind every derived input and executable.
The original production identity stays separate; no production BUILD_IDENTITY is
copied beside the diagnostic EXE. The uncached target builds exactly one game EXE.
Only ordinary original Cargo registry downloads are cached.

The workflow still validates/downloads only the authorized production package
artifact `11432281909` from run `37505927104`, SHA-256
`c6454a307a95a9d36583b2e6e6e8921510e01e6dce1cf5bde34d386ef0100747`.
Its exact provider validation and download-artifact v8 digest enforcement remain
unchanged. Assets, UI and settings are reused only after their package identity
is verified.

One stationary native Windows WARP run records 25 seconds at verified
1920×1080/Fifo. F10 is the default; manual dispatch can select native close.
Candidate validation requires an actual false HAL wait, its same-sequence Timeout
return, public surface Timeout, an app-frame skip, no intervening backbuffer/app
frame acquisition, and a successful app frame after the final timeout. Missing
observations remain unproven. Every wait error fails candidate validation rather
than counting as a timeout.

The chosen exit handler, `run_app` and renderer-hook destruction must all have
paired entry/exit markers, with process exit code zero inside 15 seconds. A timeout
or failed input cleanup remains a failure. The existing owned-Popen cleanup runs
even after export, focus, control or unexpected Python failures. A four-minute
outer limit bounds this run. Neither cleanup nor a short trace satisfies the
unchanged 100-interval performance gate.

The same release target then compiles only the library test harness, reusing its
existing release dependencies. It runs the existing production surface/device
policy tests and the exact skipped-frame input-retention test. Those cover
Lost/Outdated recovery limits, terminal validation/device/out-of-memory behavior,
and retained key/button edges, mouse motion, frame generation and time across a
skip. The workflow checks the required test names actually ran. No native device
loss is injected or claimed. These tests supplement the observed timeout path.

## Fresh production image controls without another renderer build

The original package EXE and candidate EXE run the existing production static
HK416 capture path on the same Windows WARP host. Hip and ADS use the unchanged
reference viewport, Kestrel profile, frozen simulation time, exact approved public
weapon asset, explicit FXC/DX12 renderer and original calibration settings. The
existing native process, sidecar, capture structure, frame-witness, lighting and
contour/calibration validators all remain mandatory.

Each pose's shared witness identifies the comparison pair, binding both different
EXE hashes, the original production source, candidate derivation, CI attempt,
asset, settings and framing. It does not impersonate either EXE's source/build
identity. Original build labels and metadata remain intact. The commands and
process receipts retain each actual executable and working directory separately.

Both viewmodel and world captures require exact decoded RGBA8 equality across
all 960×540 pixels, including the witness: four comparisons, eight raw images,
zero channel tolerance, zero masked pixels. A visible version-label difference
or any other pixel change fails instead of being hidden. Both source inputs are
rechecked after capture. Failures and partial captures are retained; image checks
still run after a native diagnostic failure, while the job stays failed. Raw
images require independent review before production integration; this does not add a human approval gate.

This does not relabel older source-bound 21-image/16-control renderer evidence as
fresh candidate evidence. Those results can support their original unchanged
renderer/scene claims only under their existing exact provenance checks. The new
pair exercises the packaged production capture path without a baseline rebuild
or example build. Reproducing the full 21-image contract with this candidate would
require linking and executing `renderer_contract` against its copied HAL (the
package contains only the game EXE). Such an additional fixture is unnecessary for
this bounded production image pair and is not silently claimed to have run.

## Scope and checks

This is native Windows software-DX12 correctness evidence, not RTX hardware,
GPU frame time, gameplay/performance matrix completion or 1080p60 acceptance.
Observer logging adds overhead; renderer-submit timing is CPU encoding only.
Native compilation, observed safe skipping, graceful destruction, policy/input
tests and image checks remain pending until their actual Windows evidence is
reviewed. Production integration is a separate decision.

Focused local checks:
`PYTHONPATH=tools python -m unittest -v test_windows_acquire_diagnostic`.
Use `prepare --mode baseline` or `prepare --mode timeout-return-candidate` explicitly
for manual derivations. The native workflow retains raw telemetry, capture images,
process logs, policy-test output and exact patch/hash receipts under a mode-labelled
artifact, including on failure.
