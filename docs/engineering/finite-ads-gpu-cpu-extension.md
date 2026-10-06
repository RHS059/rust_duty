# Reviewed finite ADS GPU-selection / CPU-stage source extension

`tools/finite_ads_gpu_cpu_class.json` is the separately reviewed extension,
anchored to SHA-256
`91bd0030157ff8e1b4e70127b028e57543d8fc91fb3b6cc1202c4707491fb798`.
Its 39,275-byte native review has SHA-256
`bbc92e18d4092dbd8a1a005fc12d7d8457411a7e821b39dc28c7ca04a90459c5`.
The normal current-source authored correction selects this class. Fixed original
8f571 historical revalidation retains the batching descriptor, which supports
its prebatch source. The pending template remains pending and cannot grant a
profile. Candidate-generated hashes cannot replace the independent anchors.

## Exact source boundary

The new schema is `rust-duty-finite-ads-gpu-cpu-class/v1`; the class ID is
`ads-offset-8f571464-finite-gpu-cpu-v1`. Its parent is the independently pinned
reviewed batching descriptor, SHA-256
`2895c1f4f0039f5a850c7b30196c5d77f4b2e563bc211f8b9fb51ca15f639c4c`.
That parent, its original descriptor
`96dfb631be9d59f6cf35d87e4f3c17a4a4303d74787bb773a8c47672efb53331`, and its native
receipt `4c2ae5f087ac1e548a9285f635fbb17de9de3defbaa4fab0da014fdb5c976699` remain
byte-for-byte unchanged.

The two reviewed coherent variants are:

- Baseline source `b085f31d71e8eeb4dd9f36786a9c7e82da90b809`, whose complete
  production inventory matches batching source
  `5abf2bca825a252fb7ad6665c444c89861ee8ef9`.
- Candidate source `ebf4bcb7f489766e3c7ec188c35db9bb4146c62b`, containing the GPU
  selector and CPU-stage instrumentation.

The constants and descriptor map exactly the 12 changed Rust paths: `app.rs`,
`frame_performance.rs`, `frame_performance_session.rs`, `graphics_device.rs`,
`lib.rs`, `main.rs`, `pause_menu.rs`, `render/backend.rs`, `render/device.rs`,
`render/frame.rs`, `render/mod.rs`, and `render/runtime.rs`, all under `src/`.
`graphics_device.rs` must be absent in the baseline and present with the exact
pinned bytes in the candidate. One coherent mapping is required for the whole
set. All 4,094 mixed subsets are rejected in synthetic controls. The unchanged
`render/plan.rs` must retain the reviewed batching candidate identity. The
original prebatch pair remains supported only by the two historical classes,
whose behavior has not changed.

The maps contain canonical production identities and separately pinned exact
additive identities. Existing source LF/CRLF normalization is retained. For
`src/render/mod.rs`, the baseline is 713 canonical bytes or 872 bytes with the
exact existing 159-byte diagnostic suffix; the candidate is 724 canonical bytes
or 883 bytes with that same suffix. Comparing its full-file digest against its
stripped production digest would be incorrect. Both forms are checked exactly;
arbitrary suffixes, repeated suffixes, or modified bodies fail. Existing bridge,
mesh, and finite probe additions stay governed by their original checks.

The source packet still has to satisfy the unchanged complete production
inventory, input bytes, 553 states, masks, gameplay/time data, compiler/build
configuration, GL/WARP identity, false flags, late mutation controls, and every
native leaf, image, witness and aggregate check. The original production
inventory is never rewritten. No shader, arena or mesh arithmetic changed, and
this extension makes no new broad arithmetic proof or full-acceptance claim.

`_pass_batching` and `_gpu_cpu` are reserved internal fields. Every externally
parsed descriptor, including nested pinned references, rejects them before any
schema dispatch. Only the anchored loader constructs internal state. Class
selection follows the local verified schema branch, never marker presence or
the external class ID alone. Synthetic helper tests do not establish native
evidence. Both historical class summaries remain unchanged; the new summary
labels their two-file mapping as `historical_batching_parent` and reports the
new 12-file mapping and separate native-review identity explicitly.

## Independently reviewed native evidence

Windows [run 37498157663](https://github.com/RHS059/rust_duty/actions/runs/37498157663),
attempt 1, caller/verifier source `a9ea525a46776721c81576e642434b36bbba1e44`,
retained full artifact `11429256247`, archive SHA-256
`48f20d929f43c073900ab017732e13259e7d4413da07bf844ef9b411989aa8ec`.
Independent automated code-and-evidence review verified the source inventories,
actual binaries, compiler/runtime identities, both unchanged renderer contracts,
all 21 exact RGBA comparisons, and all six selector/timing controls. The live
trace contains five recorded presents and four complete eligible samples for
each CPU stage, with the normal final present completing export.

The archive omitted two intentional empty `capture-is-directory.png` negative
control directories. Independent fixed validation restored only those directories
in separate copies, using the original successful native validator receipts;
all raw files remained unchanged. The compact receipt explicitly retains this
limitation and binds the separate detailed independent audit.

This establishes the bounded source-equivalence review, not acceptance of an
untested fresh game capture, GPU duration, or RTX 3080 Ti 1080p60 performance.

## Independently anchored native review contract

The raw lane uses `rust-duty-graphics-cpu-native-comparison/v1`, with
`rust-duty-graphics-cpu-contract/v1` control reports. The compact review
receipt uses `rust-duty-gpu-cpu-native-review/v1`. It must be produced only
after inspecting the immutable full Windows artifact and independently running
the unchanged fixed renderer validator and all comparisons below. The actual
retained receipt above passed these evidence-review obligations. Fresh source,
native leaf and aggregate validation remain separate requirements.

Retain the exact run ID, attempt, artifact ID and archive SHA-256. Pin the raw
summary, build receipts, source receipts, process receipts, logs, control
reports, executables, preference files and traces by byte count and SHA-256.
Bind both complete immutable before/after native compile inventories, the
exact class source variants above, actual compiler stdout, and
all runtime fields required by the existing finite class. Neither a valid
SHA-256 shape nor a self-refreshed receipt supplies independent review.

### Separate class and native compile inventories

The class's original production inventory has 107 members, including
`assets/weapons/hk416a5.vrm`. The bounded native example intentionally does not
compile that game asset. Its complete inventories have 112 baseline and 113
candidate entries, plus the corresponding benchmark/control harness in each
build receipt. Native-only paths relative to the original class include
`LICENSE`, `examples/renderer_contract.rs`, `rust-toolchain.toml`,
`src/render/finite_warp_probe.rs`, `updater/.gitignore`, and
`updater/notices/README.md`. Do not equate these inventories or claim the native
example executed the omitted game asset.

`class_source_variant` identifies exactly the 12-file class mapping.
`receipts.source_inventories`, the exact 112/113 counts, and
`complete_native_compile_inventory_checked: true` attest independent review of
the complete raw native inventories. The fresh packet binder separately checks
its complete game source and asset/input inventory against the historical class
and chosen coherent variant. Neither obligation replaces the other.

The compact receipt is a review attestation, not a replacement raw-artifact
validator. At bind time, only the outer descriptor, chained parent descriptors,
and retained review/evidence files are read and added to the late-mutation
ledger. Most compact `{bytes, sha256}` identities are shape-validated references
to material checked during independent review. The immutable native-review SHA
is what establishes that review. Their presence does not claim that those raw
files were downloaded or revalidated during this binding.

### Historical baseline binary provenance

The baseline source comparison is `b085f31…`, but the reused renderer-contract
binary was compiled from `5abf2bca…` in Windows run `37482428571`, attempt `1`,
artifact `11422371812`, archive SHA-256
`f29ff7c9fada89478e86f3bae86e0382350d1ac249771116dc920274de5b8994`.
Its expected executable SHA-256 is
`140666c5f0191f4b819c175abeda18880b2a0ea567ba224c0a3fc070d1cc0e7e`.
The receipt must separately retain `compiled_source_commit` and
`equivalent_source_commit`; it must not relabel that historical executable as a
new b085 build. Validate equality of the complete native compile inventories,
including their original raw bytes and the exact additions, and pin the historical
source/build receipt and binary to the independently retained artifact. Also
bind the executable to its new invocation and output in the new Windows run.

### Production renderer contract

Retain separate baseline and candidate source/executable/log/report identities,
actual compiler and WARP/DX12/FXC device identities, process exit codes, and
unchanged fixed `run_renderer_contract.validate_outputs` results. Each run must
pass its closed 21-capture inventory, expected pixels, failure controls and
recovery case. Independently decode every PNG and compare all RGBA bytes with
zero tolerance across the 21 unchanged case names. Retain both PNG digest maps
and equal decoded RGBA digest maps. Equality between two outputs does not replace
the fixed expected-pixel validator. Runtime identity must remain within the
original finite class boundary.

### Source-bound selector and live CPU controls

Require candidate commit `ebf4bcb…` and a compiled-in SHA-256 identifying the
candidate source receipt in every report. Bind the example executable, each
actual process invocation/exit code, fresh output directory, preferences before
and after, native creation/frame counts, and unambiguous per-creation device
identity. Require these reviewed outcomes, preserving raw mode names:

- `seed`: save an exact explicit WARP preference through production persistence.
- `windowed-saved`: a separate process loads that saved preference and creates a
  compatible actual windowed WARP device. Retain evidence that this is a restart,
  not an in-process selector mutation.
- `windowed-missing`: a missing exact selection rejects explicitly without
  silently choosing another adapter.
- `windowed-forced`: forced fallback ignores an incompatible saved preference
  and successfully uses the expected WARP device.
- `headless-bypass`: both forced-fallback false and true executions ignore the
  interactive saved preference, with both creation identities retained. One
  checked mode name is insufficient to prove both executions.
- `windowed-cpu`: a real windowed renderer produces a live CPU trace with
  complete ordered `surface_acquire`, `game_recording`, `renderer_submit`, and
  `present_call` spans. Independently validate each retained sample's integer
  bounds, start/end/duration relationships, stage order, frame dimensions,
  sample count, and source/runtime/executable binding. Missing stages must not
  be inferred. These are CPU wall-clock intervals, not GPU timings or hardware
  FPS evidence.

The compact receipt should record the exact outcome inventory, the complete raw
control/process receipt identities (including both headless executions), the
CPU-reader validation result and trace digest. Preserve all historical flags as
false and `acceptance_verdict: null`; do not turn this bounded comparison into
migration acceptance, RTX performance, or gameplay approval.

## Activation and remaining acceptance

The native receipt and reviewed descriptor are pinned, have byte-preserving
`-text` Git attributes, and are selected only by normal current-source authored
correction. Both historical classes and their evidence remain unchanged; fixed
historical revalidation continues selecting the batching class. The pending
template also remains unchanged. Fresh source/native leaf and aggregate
validation is still mandatory. This activation does not supply those results or
replace any original source, pixel, mask, runtime or witness check.

Local adversarial checks:

`python -m unittest discover -s tools -p 'test_finite_ads*.py'`

## Compact receipt fields

All objects below reject missing and extra fields. Fixed values use strict type
comparison, so booleans do not substitute for integers. Every receipt identity
is exactly `{bytes, sha256}` with a positive integer byte length and lowercase
64-hex digest. The native receipt itself must match the independently retained
`GPU_CPU_NATIVE_REVIEW_SHA256`; updating an outer descriptor hash is insufficient.
`tools/test_finite_ads_gpu_cpu_native.py:fixture` contains a complete explicitly
synthetic schema example. It is never a native receipt or activation source.

Root fields:

- `schema`, `status`, `native_execution`: exactly
  `rust-duty-gpu-cpu-native-review/v1`, `passed`, and true.
- `original_class_sha256`, `batching_class_sha256`,
  `batching_native_review_sha256`: the three historical anchors above.
- `commits`: `baseline_source`, `baseline_compiled_source`, `candidate_source`,
  exactly the b085, 5abf, and ebf full revisions respectively.
- `artifact`: decimal-string positive `run_id`, `run_attempt`, `artifact_id`, and
  `archive_sha256`. The new run and artifact must differ from the historical
  batching run and artifact.
- `receipts`: exact identities named `summary`, `source_inventories`,
  `candidate_source_receipt`, `candidate_executables`, `exact_pixels`,
  `fixed_validation`, `build_process`, `build_log`, `compiler_stdout`,
  `verifier_receipt`, `completed_controls`, `cpu_reader`, and `independent_audit`.
  `cpu_reader` identifies the archived reader source, not an invented standalone
  reader-result file. The compiler stdout identity matches both byte count and
  digest from the original compiler evidence. `independent_audit` identifies the retained independent
  review report, separate from native-generated evidence.
- `baseline_origin`: `artifact`, `source_receipt`, `contract_executable`, and
  `build_receipts` must equal the already anchored batching comparison's
  candidate values; `complete_native_compile_inventory_equal` must be true.
- `native_compile_inventory_counts`: exactly baseline 112 and candidate 113.
- `archive_preservation`: `raw_files_unchanged: true`,
  `omitted_empty_directories` containing exactly the baseline and candidate
  `*-renderer-contract/capture-is-directory.png` paths in that order,
  `independent_validation_used_separate_copy: true`, and
  `original_native_fixed_validation_passed: true`. Uploads omit those intentional
  empty negative-control directories. Independent validation may restore only
  those empty directories in separate copies; all raw files remain unchanged.
  Any native-generated verifier `__pycache__` entries outside the pre-invocation
  verifier receipt must be disclosed in the independent audit, not represented
  as members of that source receipt.
- `comparison`: exactly RGBA, channel tolerance zero, capture count 21.
- `review_flags`: exact `GPU_CPU_REVIEW_FLAGS`. Complete native compile inventory,
  unchanged sources, checked compiler settings, and unchanged fixed validator
  bytes are true. Required/possible masks changed, original profile flags
  modified, original native verification, profile activation, GPU duration,
  RTX/1080p60 acceptance and migration completion are false; verdict is null.
- `control_order`: exactly seed, windowed-saved, windowed-missing,
  windowed-forced, headless-bypass, windowed-cpu.
- `control_executable`, `variants`, `controls`, `cpu_trace`: as below.

Each `variants` member, exactly baseline and candidate, has:
`class_source_variant`, `source_receipt`, `contract_executable`,
`contract_process`, `contract_report`, `contract_log`, `process_exit_code`,
`compiler_sha256`, `runtime_identity`, `fixed_contract_validation`,
`rgba_sha256`, `png_sha256`. The class variant equals the corresponding
`GPU_CPU_VARIANTS` entry. Both compiler and all eight runtime identity members
must match the original native proof. The exit code is integer zero. The
baseline executable/source receipt additionally equal the anchored parent
candidate values; the candidate source receipt equals the root receipt.
Fixed validation has exactly its original schema/passed/backend/adapter/
captures/scope/build_version/build_number fields. Both image maps contain all
21 unchanged case names, with equal decoded RGBA digests across variants.

Each of the six `controls` has exactly:
`status`, `source_commit`, `source_sha256`, `compiled_source_sha256`,
`executable`, `pid`, `process_exit_code`, `process`, `report`, `log`,
`preference_before`, `preference_after`, `preference_fingerprint`, `outcome`,
`creations`, `physical_dimensions`, `captures`.
Source and compiled-receipt hashes equal the candidate source receipt. The
executable equals the root control executable; exit is integer zero; PID is a
positive integer. Windows may reuse PIDs. Distinct invocation receipt hashes
and the reviewed mode order establish separate processes.

Seed has no preference before execution. Every other control has equal
before/after preference identities, and seed/save/CPU identities agree across
processes. Saved fingerprints match the parent WARP identity. Missing-choice
fixtures use the exact declared PID-dependent missing adapter name and maximum
u32 vendor/device IDs. `outcome` is exactly the mode's `GPU_CPU_OUTCOMES` mapping,
including unchanged preferences, required frame counts, missing-selection
rejection, restart behavior, and final normal present where applicable.

Every `creations` entry has exactly `runtime_identity`, `windowed`,
`force_fallback_requested`, `present_mode`, `selection_mode`,
`requested_fingerprint`, `actual_fingerprint`. Seed and missing-selection modes
have no successful creations. Windowed modes have one Fifo creation. Headless
has exactly two creations in false/true fallback order with no present mode or
requested fingerprint. Every actual device remains the historical WARP device.

Rendered controls have positive integer `physical_dimensions` and exactly their
expected capture names. Headless extents are fixed at 320 by 180; windowed sizes
are actual observed sizes. Each capture contains `png`, `rgba_sha256`,
`dimensions`, `fixed_pixels_verified: true`, `opaque_alpha_verified: true`.
Seed and missing-selection controls have null dimensions and no captures.

`cpu_trace` has exactly `trace`, `source_commit`, `source_sha256`,
`compiled_source_sha256`, `executable`, `runtime_identity`, `present_mode`,
`physical_dimensions`, `reader_validation`. It binds the same current source,
control executable, original native runtime, Fifo, and actual CPU-control
window dimensions. `reader_validation` has exactly the following compact
attestations derived from the independently validated raw trace and reader:

- `status: passed`, `complete_trace_validated: true`,
  `measurement: cpu_wall_clock_paired_frame_stage_ns`
- `uninstrumented_present_count: 1`, `recorded_present_count: 5`,
  `complete_cpu_sample_count: 4`,
  `first_recorded_present_has_cpu_sample: false`,
  `normal_final_present_export: true`
- `integer_time_bounds_verified`, `ordered_disjoint_spans_verified`, and
  `dimensions_match_window`: true
- `eligible_interval_samples`: exactly the four stage names above, each with
  the same integer count from two through four. All complete stages share the
  same terminal-record eligibility.
- `gpu_duration_measured`, `rtx_or_1080p60_acceptance`,
  `acceptance_complete`: false; `acceptance_verdict`: null

The raw CPU reader still checks every retained integer timestamp, ordered span,
duration relationship, boundary, eligibility and sample. The compact validator
checks the retained review's bounded conclusions and identities; it does not
fabricate raw trace rows or infer missing spans.
