# Bounded native GPU-selection and CPU-stage controls

This lane tests the exact published production source
`ebf4bcb7f489766e3c7ec188c35db9bb4146c62b`. It is separate from the historical
17023450/5abf pass-submission benchmark. It builds only `renderer_contract` and
`graphics_cpu_contract`, never the game or private assets.

## Inputs and baseline reuse

The source baseline is `b085f31d71e8eeb4dd9f36786a9c7e82da90b809`. Its complete
compile inventory is checked against the retained 5abf candidate inventory from
successful Windows run `37482428571`, attempt 1, full artifact `11422371812`.
The original artifact ZIP is 15,858,877 bytes with SHA-256
`f29ff7c9fada89478e86f3bae86e0382350d1ac249771116dc920274de5b8994`.

The reused `candidate-renderer_contract.exe` is 9,136,128 bytes with SHA-256
`140666c5f0191f4b819c175abeda18880b2a0ea567ba224c0a3fc070d1cc0e7e`.
The checked-in batching native review independently anchors its exact source,
compiler and executable receipts. The new lane invokes that historical binary
again on the same runner as the newly built ebf example. Its historical compile
identity remains distinct from its new invocation identity.

The current-checkout guard also accepts the exact `src/asset_path.rs` test-only
fixture repair published in `9c320cead838ffa6033359f705c462693df532f6`, using the
[independently pinned before/after reconstruction](finite-ads-profile-binding.md#exact-test-fixture-repair-2026-10-06).
All other checkout bytes still match ebf exactly; arbitrary test edits, changed
production, renamed files and CRLF normalization are rejected. The candidate
continues to compile the original ebf bytes and retains ebf as `source_commit`.
`workflow_source_commit` identifies the caller. Its separate
`current-checkout-source-inventory.json` records actual raw checkout identities
and the exact test-only mapping; the candidate receipt binds that inventory's
digest. The differing raw file is retained under `current-checkout/`, and the
mapping module is retained with verifier sources. Checkout and retained evidence
are checked again after native controls. Historical descriptors, native review
receipts and acceptance thresholds are unchanged.

Only this exact artifact is eligible. The coordinator workflow should retrieve
its actual metadata with the normal authenticated GitHub artifact API, retain
the unchanged artifact object as `baseline-provider.json`, then use the normal
authorized artifact downloader for run 37482428571/artifact 11422371812. No name
search, latest-run substitution, denied-artifact workaround or expired-artifact
skip is supported. The runner checks the provider digest against the previously
reviewed ZIP identity and verifies every consumed baseline source/binary byte;
it does not pretend the artifact downloader supplied a new local ZIP hash.

## Coordinator workflow contract

Workflow ownership and publication remain with the coordinator. A bounded
Windows job needs:

1. Read-only contents/actions permissions, a clean checkout with
   `core.autocrlf=false`, and the exact b085/ebf Git objects fetched explicitly.
   The runner checks checkout production against ebf and rejects extra or changed
   compile inputs. New tools/examples/documentation do not change that boundary.
2. Python with the existing pinned Pillow dependency; set `PYTHONPATH=tools` and run
   `python -m unittest -v test_graphics_cpu_contract test_pass_submission_benchmark`.
3. Install `1.99.0-x86_64-pc-windows-msvc`. The runner verifies original rustc
   stdout against SHA-256
   `5477f9bad65b15c4c5b31fc050fc72feba651ea1b330bc75cf356a4d6b0fbc80`.
4. Retain the exact historical artifact metadata and download described above.
5. Invoke once, with new output storage:

   `python tools/run_graphics_cpu_contract.py --repository . --verifier-root . --baseline-artifact downloaded/batching-baseline --baseline-provider baseline-provider.json --output-dir evidence/graphics-cpu`

6. Retain complete evidence on success and failure, including sources, compiler
   bytes, both contract executables, the selection example, original process
   receipts/logs, preferences, PNGs, stage trace and verifier sources. Exclude
   only build cache `target/` and compiler scratch `temp/` from the full artifact.
   A bounded companion artifact may omit executables, but independent binary
   review still requires the full artifact. Do not omit empty negative-control
   directories silently when interpreting an extracted renderer-contract tree.

The candidate examples compile once with the same optimized dev settings as the
reviewed baseline: opt-level 2, debug info 0, incremental disabled. No full-game
or second baseline build is needed. This configuration is declared and is not
relabeled as a new release arithmetic proof. Source receipts bind exact bytes
before/after compilation and after controls. The example embeds the candidate
source receipt's SHA-256 and rejects a different CLI source digest.

## Native obligations

First, both actual renderer-contract invocations must pass the unchanged fixed
validator, all 21 independent expected-pixel cases, all four expected failures
and recovery. Every corresponding decoded RGBA byte must match with zero
tolerance. Actual device fields and FXC initialization must agree and remain
within the historical finite WARP runtime identity.

Then the same candidate example runs in six separate processes/new directories:

- `seed` enumerates actual adapters and persists the unique complete DX12 WARP
  fingerprint with the production `save_choice` API.
- `windowed-saved` loads that exact saved file after restart and requests that
  explicit adapter. Actual and requested fingerprints must agree.
- `windowed-missing` loads a deliberately absent fingerprint and must reject
  without any successful render/device fallback.
- `windowed-forced` ignores its impossible saved choice and creates actual
  forced WARP windowed rendering.
- `headless-bypass` loads an impossible preference and creates actual headless
  renderers with force-fallback false and true, separately retaining both
  production device-evidence records.
- `windowed-cpu` loads the saved explicit WARP choice and renders six normal
  frames. One PNG occurs before recording; midframe activation does not invent
  earlier stages. Five presents are recorded, the latter four have all paired
  CPU stages, and a pending stop exports only after its normal final present.

Independent fixed-color probes validate each new synthetic image. The strict
existing CPU reader validates the original trace, including integer time
bounds, disjoint stages, terminal record linkage, physical dimensions and
primary present-return intervals. No PNG readback is added to measured frames.

Window/surface unavailability is a failure with retained diagnostics, not a
native pass or silent skip. The job proves WARP integration only. It does not
prove selected RTX 3080 Ti behavior, stable 1920×1080 at 60 FPS, GPU execution
duration, display scan-out, or full gameplay acceptance.

## Source-equivalence activation

The separate `finite_ads_gpu_cpu_class.pending.json` remains unavailable until
the actual new native artifact is independently reviewed. The original 96df
class and reviewed batching class/receipt remain unchanged. After real review,
finish the compact evidence reader, independently pin its receipt and a separate
reviewed descriptor, and deliberately select it for current-source validation.
All 553-state, input, mask, runtime, compiler, false-flag and aggregate checks
remain mandatory. A new hash or successful bounded fixture alone is not the
complete acceptance result.

## Historical benchmark adjustment

`run_pass_submission_benchmark.py` now reads both 17023450 and 5abf source trees
from pinned Git objects, keeps its exact two-file delta guard, and explicitly
marks its result historical/current-checkout-renderer-not-tested. The obsolete
`--candidate-root` argument remains compatible only when it names the same
repository; it does not select source bytes. The coordinator should remove
`src/render/frame.rs` and `src/render/plan.rs` from that historical workflow's
push paths, retaining its harness/tool/workflow paths, and update workflow tests
accordingly. Do not relabel this historical experiment as current ebf evidence.
