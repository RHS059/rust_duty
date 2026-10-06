# Windows acquire/exit diagnostic

This separate observer probes the repeated approximately 1000 ms DX12 acquire
waits and delayed exit. It creates one clearly named diagnostic executable from
production commit `49c3bf9b3d0482ce81a7d50683904bda28468d7d` and the exact locked
`wgpu-hal 30.0.1` crate. Production files and the existing performance-matrix
runner/workflow are unchanged.

The tool exports committed source bytes into a fresh directory, verifies pinned
SHA-256 values, extracts a hash-verified HAL into a sibling directory, and records
original/derived file manifests plus exact unified patches. The only Rust edits
log entry/exit of surface acquisition, the DX12 frame-latency wait's elapsed time
and boolean result, F10/native close handling, `run_app`, and renderer-hook
destruction. The wait's false result remains ignored exactly as before. Wait,
Fifo, physics, calibration, build features and acceptance thresholds are unchanged.
A separate Cargo configuration selects the copied HAL, and a two-line lockfile
patch replaces only that same-version registry identity with the local dependency.
The standard registry cache remains original; the derived HAL and target are not
cached.

The workflow validates and downloads only authorized artifact `11432281909` from
run `37505927104`, with SHA-256
`c6454a307a95a9d36583b2e6e6e8921510e01e6dce1cf5bde34d386ef0100747` enforced by
download-artifact v8. It reuses that package's assets, UI and settings beside the
derived executable, retaining the original identity separately. It never copies
the production BUILD_IDENTITY beside the diagnostic binary. The diagnostic build
receipt binds executable, compiler, source, patches and runtime-file hashes.

One stationary native Windows WARP baseline records for 25 seconds at a verified
1920×1080 client extent. F10 is the default exit signal. A manual dispatch can
select native close to investigate that path in a separate run. Both handlers are
instrumented; a path with no observed marker remains unproven. Normal exit gets
15 seconds. Every Python execution path after launch cleans up using only the
owned Popen handle, verifies termination, and retains RUN.json. Timeout cleanup
does not turn failed graceful exit into success. The workflow has a separate
four-minute bound for the native run.

Evidence retains game.log, raw telemetry, exact patch/hash receipts, observer
records and measured lifecycle. A marker with entry but no exit localizes an
unfinished operation; absence of entry does not prove a hang in that operation.
The wait boolean and measured duration are observations, not a proposed fix.
Logging adds overhead. Renderer submit is CPU preparation/encoding, not GPU time.
This short diagnostic never claims the existing 100-interval matrix gate passed,
full matrix completion, RTX hardware evidence, or 1080p60 acceptance.

Focused checks: `PYTHONPATH=tools python -m unittest -v test_windows_acquire_diagnostic`.
Preparation and compile checks are separate from a native Windows run. The native
workflow result and retained evidence must be reviewed before drawing conclusions.
