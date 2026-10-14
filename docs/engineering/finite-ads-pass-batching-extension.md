# Reviewed finite ADS pass-batching source equivalence

`tools/finite_ads_pass_batching_class.json` is the separate reviewed extension.
Its independently retained descriptor SHA-256 is
`2895c1f4f0039f5a850c7b30196c5d77f4b2e563bc211f8b9fb51ca15f639c4c`.
The binder pins the actual native-review receipt to
`4c2ae5f087ac1e548a9285f635fbb17de9de3defbaa4fab0da014fdb5c976699`.
Normal authored correction and both historical revalidation consumers select
this descriptor. The pending template remains pending and cannot grant a profile.

The original descriptor and its complete historical evidence remain byte-for-byte
unchanged at SHA-256
`96dfb631be9d59f6cf35d87e4f3c17a4a4303d74787bb773a8c47672efb53331`.
The original class continues rejecting batching source when selected directly.
The extension references that exact original file and supplies only the paired
source mapping and separately anchored native comparison receipt. Its summary
retains the original evidence identities and adds the distinct comparison
identity. Historical finite arithmetic proof is not relabeled as a new
production batching execution.

External descriptors cannot supply the reserved `_pass_batching` field. Only
the verified extension loader constructs it, and public class selection follows
the local verified schema branch. Both descriptors and both evidence directories
have `-text` Git attributes, preserving their anchored bytes during Windows
checkout regardless of `core.autocrlf`.

## Exact two-file boundary

The original pair is from `17023450076b668c279539e0e450b8cb58a7c1a2`; the candidate
pair is from `5abf2bca825a252fb7ad6665c444c89861ee8ef9`. Their byte sizes and SHA-256
identities are written explicitly in `PASS_BATCHING_PAIRS` and the reviewed
extension descriptor. Source text retains the existing CRLF/LF canonicalization.
The pair must be entirely baseline or entirely candidate. A mixed pair, a missing
member, or any other byte change fails. Neither file is skipped. The original
`equivalence.production` inventory is never rewritten.

Every remaining input, production inventory, exact additive overlay, 553-row
state, mask, time, compiler, build-feature/profile, GL runtime, WARP runtime,
historical native control, source flag, late-mutation, image/witness and caller
aggregate obligation stays in its original path. The extension adds no fallback
frame, tolerance or acceptance verdict. A pair check is additional to those
obligations; it does not replace them.

## Independently reviewed native comparison

Windows [run 37482428571](https://github.com/RHS059/rust_duty/actions/runs/37482428571),
attempt 1, retained full artifact `11422371812`, ZIP SHA-256
`f29ff7c9fada89478e86f3bae86e0382350d1ac249771116dc920274de5b8994`.
Independent automated code-and-evidence review verified both fixed production
renderer contracts and every RGBA byte of all 21 captures with zero tolerance.
The retained compiler output identity and complete WARP device fields match the
original finite class. No human approval is claimed.

Both restored source variants were compiled in that one run using verifier
`4c116be39e426f38f65772ae83ce539891a54e55`; their build receipts are not historical
170/5abf dispatched builds. The source receipts identify those exact production
variants and show only `frame.rs` and `plan.rs` changed. The original archives
remain unchanged. Their upload omitted the two intentional empty
`capture-is-directory.png` negative-test directories; independent validation
restored only those directories in separate copies, backed by the pinned fixture
and successful original native fixed-validator receipts. No image/report bytes
changed. Actual compiler stdout is retained exactly in both source receipts;
the standalone `rustc.txt` merely stores the same text with Windows CRLF.

The bounded source mapping is now reviewable from actual native evidence. A
fresh game's immutable packet, complete native leaf and aggregate checks remain
mandatory. This does not declare acceptance of an untested current capture.

### Evidence and review obligations

The benchmark worker's raw evidence uses
`tools/run_pass_submission_benchmark.py`. Its root `summary.json`,
`build-receipts.json`, `baseline-source-receipt.json`,
`candidate-source-receipt.json`, `production-contract-exact-pixels.json`, both
`*-renderer-contract/` directories, native logs, process receipts, and compiled
executables are the review inputs. Do not manufacture a review receipt from the
unit-test fixture or a local plan. Do not use the old independent finite probe as
a substitute: it does not execute `FramePlan` or `WgpuRenderer::submit`.

The retained receipt passed the evidence-review requirements in steps 1–5 below.
This change implements activation in step 6. Fresh source/native leaf and
aggregate validation in step 7 remains mandatory and pending; it is not a result
of the retained comparison receipt.

1. Verify the immutable GitHub run/attempt/artifact and ZIP digest, exact two
   pinned revisions, source manifests, all unchanged compile inputs, equal
   harness bytes, immutable before/after inputs, compiled executable identities,
   and successful original build/native process receipts.
2. Check that both builds use identical actual `rustc -Vv` output, matching the
   original finite class compiler identity. Inspect the complete build settings
   and note the harness's optimized dev profile; this is not a new release-mode
   finite arithmetic execution.
3. Verify both native production logs contain one unambiguous WARP/DX12 adapter,
   Fxc initialization, and identical `device_evidence` fields. Preserve
   `device_type`, `vendor_id`, `device_id`, `driver`, and `driver_info`. This
   proposal additionally requires those identities to match the original native
   finite class, retaining that runtime boundary. A different driver requires a
   separate reviewed decision; silently substituting it is not authorized.
4. Run the unchanged `run_renderer_contract.validate_outputs` against both
   retained native output directories, including every fixed pixel expectation,
   all sidecars, closed inventory, four expected failures, and recovery case.
5. Independently decode all 21 captures, compare every RGBA byte with zero
   tolerance, and verify their fixed extents and RGBA modes. Match both PNG
   inventories and decoded digests to the harness's exact-pixel receipt and
   root summary. Two equally wrong images are insufficient without step 4.
6. Only after these checks, retain the compact review record described below.
   Pin its SHA-256 independently in `PASS_BATCHING_NATIVE_REVIEW_SHA256`; retain
   its exact bytes as an adjacent evidence file. Copy the pending descriptor to
   a separate reviewed descriptor, set its status and exact receipt identity,
   and independently pin that new descriptor in the intended caller/workflow.
   Preserve the original descriptor, original anchors and historical evidence.
7. Re-run the finite binding/gate adversarial tests, then actual fresh source,
   native leaf and aggregate validation. The original 170 native leaf result is
   historical evidence, not a claim that the new current revision has passed.

No performance threshold grants source equivalence. WARP submit timing is a
separate diagnostic; this mapping does not establish gameplay FPS, window
presentation, or RTX 3080 Ti performance.

## Compact review record

This is a review of actual retained evidence, not a self-certifying runtime
report. Its schema is `rust-duty-pass-batching-native-review/v1`. It contains:

- `status: "passed"`, `native_execution: true`, the exact
  `original_class_sha256`, `original_profile_flags_modified: false`,
  `acceptance_complete: false`, and `acceptance_verdict: null`.
- `commits`: exact `baseline` and `candidate` revisions from
  `PASS_BATCHING_COMMITS`.
- `artifact`: decimal-string `run_id`, `run_attempt`, `artifact_id`, and the actual
  ZIP `archive_sha256`.
- `summary`, `build_receipts`, and `exact_pixels`: `{bytes, sha256}` identities of
  the original corresponding root files, without reformatting them.
- `comparison`: exactly `{channels: "RGBA", channel_tolerance: 0,
  capture_count: 21}`.
- `variants`, containing exactly `baseline` and `candidate`. Each contains:
  - `source_pair`: its exact two-file `{bytes, sha256}` mapping.
  - `compiler_sha256`: original-format actual compiler output identity.
  - `runtime_identity`: exactly `device_type`, `vendor_id`, `device_id`,
    `driver`, `driver_info`, `adapter`, `backend`, and `compiler`, extracted from
    actual native logs and compared with the original reviewed native identity.
  - `process_exit_code: 0` and `{bytes, sha256}` identities named
    `source_receipt`, `contract_executable`, `contract_report`, `contract_log`.
  - `fixed_contract_validation`: the successful unmodified return value from
    the existing `validate_outputs` run, retaining schema, passed, backend,
    adapter, captures, scope, build_version, and build_number.
  - `rgba_sha256` and `png_sha256`: complete filename-to-digest maps for the 21
    unchanged `run_renderer_contract.cases()` names. The RGBA maps must match
    exactly between variants; each PNG map binds that variant's actual files.

Do not confuse a valid-shaped SHA with independent review. The code accepts
this receipt only when both its independently supplied native-review constant
and the external descriptor anchor match the retained bytes. It then checks
these semantic obligations and adds all referenced loaded files to its normal
late-mutation ledger.
