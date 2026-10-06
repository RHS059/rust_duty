# Disabled finite ADS GPU-selection / CPU-stage source extension

`tools/finite_ads_gpu_cpu_class.pending.json` is a pending proposal only. It cannot
bind a finite ADS profile. `GPU_CPU_NATIVE_REVIEW_SHA256` is `None`; neither
changing the descriptor status nor supplying a candidate-generated digest can
activate it. The native receipt reader is deliberately unimplemented until the
actual bounded Windows evidence has been independently reviewed. No workflow or
caller selects this class.

## Exact source boundary

The new schema is `rust-duty-finite-ads-gpu-cpu-class/v1`; the class ID is
`ads-offset-8f571464-finite-gpu-cpu-v1`. Its parent is the independently pinned
reviewed batching descriptor, SHA-256
`2895c1f4f0039f5a850c7b30196c5d77f4b2e563bc211f8b9fb51ca15f639c4c`.
That parent, its original descriptor
`96dfb631be9d59f6cf35d87e4f3c17a4a4303d74787bb773a8c47672efb53331`, and its native
receipt `4c2ae5f087ac1e548a9285f635fbb17de9de3defbaa4fab0da014fdb5c976699` remain
byte-for-byte unchanged.

The two proposed coherent variants are:

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
this proposal makes no new broad arithmetic proof or acceptance claim.

`_pass_batching` and `_gpu_cpu` are reserved internal fields. Every externally
parsed descriptor, including nested pinned references, rejects them before any
schema dispatch. There is currently no production path that constructs the new
internal marker. Synthetic helper tests do not establish native evidence.

## Proposed independent native review contract

The raw lane uses `rust-duty-graphics-cpu-native-comparison/v1`, with
`rust-duty-graphics-cpu-contract/v1` control reports. A future compact review
receipt should use `rust-duty-gpu-cpu-native-review/v1`. It must be produced only
after inspecting the immutable full Windows artifact and independently running
the unchanged fixed renderer validator and all comparisons below. This is a
proposed review contract, not an activated schema or a successful run report.

Retain the exact run ID, attempt, artifact ID and archive SHA-256. Pin the raw
summary, build receipts, source receipts, process receipts, logs, control
reports, executables, preference files and traces by byte count and SHA-256.
Bind both complete immutable before/after production inventories and all
compile inputs, the exact source variants above, actual compiler stdout, and
all runtime fields required by the existing finite class. Neither a valid
SHA-256 shape nor a self-refreshed receipt supplies independent review.

### Historical baseline binary provenance

The baseline source comparison is `b085f31…`, but the reused renderer-contract
binary was compiled from `5abf2bca…` in Windows run `37482428571`, attempt `1`,
artifact `11422371812`, archive SHA-256
`f29ff7c9fada89478e86f3bae86e0382350d1ac249771116dc920274de5b8994`.
Its expected executable SHA-256 is
`140666c5f0191f4b819c175abeda18880b2a0ea567ba224c0a3fc070d1cc0e7e`.
The receipt must separately retain `compiled_source_commit` and
`equivalent_source_commit`; it must not relabel that historical executable as a
new b085 build. Validate equality of the complete production inventories,
including exact source normalization and additions, and pin the historical
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

## Activation remains separate

After actual independent evidence review, a separate change must finish and
test compact receipt ingestion, pin the native receipt hash, create a separate
reviewed descriptor with byte-preserving Git attributes, and deliberately select
it in an authorized caller. Keep the pending template and historical files
unchanged. Then fresh source/native leaf and aggregate validation is still
required. This scaffold supplies none of those results.

Local adversarial checks:

`python -m unittest discover -s tools -p 'test_finite_ads*.py'`
