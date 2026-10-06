# Reusable finite ADS profile binding

`tools/finite_ads_profile_binding.py` establishes a separate bounded profile for
exactly 210 ADS-offset fallback frames per backend: 160 strictly empty frames and
50 potentially visible frames. GL uses the reviewed narrowed contrast mask and
expanded possible-support mask; DX12 retains its original masks. Every other
source field, original false flag, failed capture verdict, and null source
acceptance verdict stays unchanged. The result is `BoundFiniteAdsProfile`, whose
`bounded_ads_profile_established` field is separate from original/native/global
acceptance flags. It cannot be coerced to an acceptance boolean.

The original source-packet binder must run first. The caller still owns all
closed shard inventories, exact invocation and frame-witness checks, complete
native PNG and telemetry validation, and the unchanged pair/aggregate gates.
This helper is consulted only for eligible ADS-offset coverage/structure
failures. A pending descriptor, unknown class, missing evidence or out-of-scope
frame fails closed. There is no generic conditional fallback.

## Reviewed class and native evidence

`tools/finite_ads_reviewed_class.json` is the portable review descriptor. Its
SHA-256 must come from an independently retained caller/workflow anchor, never
from a candidate request or by hashing whatever descriptor was supplied. Its
adjacent `finite_ads_reviewed_evidence/` files are individually hash-bound. The
review is automated code-and-evidence review, not a claim of human approval.

The later native anchor is Windows run
[37445275982](https://github.com/RHS059/rust_duty/actions/runs/37445275982), attempt
1, source `4e6930c56be3b6120542231c46778b33c58f9e13`, artifact `11403571693` with ZIP
SHA-256 `b39e855a9ea07cde7b925124e53ffe69ddff901b592438a9c9331eb425c9efd1`.
The bundle retains actual runner/native reports, all four 50-visible/160-empty
state/domain comparisons, compiler outputs, original build/native process
receipts, preparation inventory, before/after inventory and compiled-executable
hashes. The native report records 101,552 support guards, 50,336 color probes and
all seven exercised negative controls for every one of the 50 visible frames.
The reusable binder checks these identities and structural obligations. It does
not re-render the independent native probe on each current capture.

The original capture (`8f571464`, run `37415102452`) and its independent source
replay (`371bca3d`, run `37427554951`) remain distinct from this later native run
and from every fresh capture. The reviewed native source trace has SHA-256
`11ee6a54faf269e9db793fe1637da3bd17ffa42e9d8eea8be63edf5273e1d553`; the native probe
executable has SHA-256
`5b4d0ba1de7d418ccf54b025720b4d4469c643e2eb0742d8617faa98ed96dbb8`.

## Reuse boundary

Reuse requires every original consumed companion byte, the reviewed text-config
content, full production source inventory, Cargo/lock, compiler, target, feature
set and release profile. The three configs admit only two independently derived
whole-file identities: original uniform CRLF and exact LF. Their parsers use
Rust `str::lines()` (`settings.rs` and `animation_manifest.rs`), so this preserves
parsed lines; arbitrary whitespace, lone CR, mixed endings and content changes
are rejected. The raw native packet/input hashes still bind the actual bytes.
Only CRLF-to-LF mapping of named source text is otherwise allowed. Source normalization uses
the existing reviewed bridge and checked additive overlays, and the additive
bodies themselves must have their reviewed hashes. New production files,
unreviewed additions or changed arithmetic source reject the class.

All 553 source rows and complete headers are compared by a type-preserving,
exact-decimal canonical digest, including masks, gameplay, time, mesh state and
calibration. Only explicitly verified Windows root prefixes on the declared
companion paths map to relative names. No rounding tolerance, basename matching,
selected-field comparison or candidate PNG analysis establishes equivalence.
Fresh run IDs and rebuilt executable hashes may differ; the original capture
binder independently retains their actual identities.

Fresh runtime binding uses the actual DX12 capture log's device type, vendor,
device, driver, driver-info, adapter and FXC receipt, matched to the independent
WARP evidence. GL compares the already-sealed input manifest component by component against
the reviewed DLL/license/runtime inventory. Two exact metadata pairs are allowed:
the original CRLF lock/staging pair, and the independently derived LF lock plus
the otherwise unchanged original CRLF staging receipt with only its lock digest
replaced. Mixed pairs or changed DLL/license/metadata bytes are rejected even if
a candidate refreshes its aggregate hash. Original precision/target checks remain.
The source packet must retain the original raw native-input-manifest alongside
its compiler receipt so this mapping is independently reconstructable. This adds no comprehensive DLL-attestation prerequisite.
All capture sidecars must identify a stable actual adapter. Logs, descriptor,
evidence and source/capture files are rechecked for late changes.

## Compact GL proof

`export_reviewed_gl` accepts only the fixed-anchor
`BoundReviewedGlSupplement` returned after validating the original receipt,
original GL source, complete reviewed clipping/subtriangle inventory and fragment
proof. The checked-in compact export was produced from those actual files. It
retains all 50 mask pairs, four original evidence identities, 47,558 retained
samples (minimum four in every visible frame), 53,473 examined overlapping
subtriangles and 1,487 unsafe subtriangles. It saves rereading the 120 MB geometry
trace for each later capture; it does not replace the full proof with a new hash
chosen by a candidate. A native runner success whose
`reviewed_gl_hashes_match` is false is rejected.

## Caller API and checks

```python
profile = bind_finite_ads_profile(
    source_packet=bound_source_packet,
    source_packet_path=packet_path,
    reviewed_class=reviewed_descriptor_path,
    expected_class_sha256=independently_retained_descriptor_sha256,
    native_runtime_logs={"windows-legacy": original_gl_stderr,
                         "dx12": original_dx12_stderr},
)
row = profile.verify_frame_binding(native_png_path, role, frame_index)
# Existing image comparator consumes row; all other gates still run.
profile.verify_unchanged()  # Immediately before writing the result.
```

`profile.summary()` contains stable review/evidence/current-capture/runtime
identities and excludes local copy paths, so the leaf and aggregate can rebuild
and compare the same binding independently. The returned row is a copy; changing
it does not change the original source row or another validator's obligations.

Run `python -m unittest discover -s tools -p 'test_finite_ads_profile_binding.py'`.
The controls cover changed source, input, nonfallback state and exact decimals;
reviewed root/line-ending mappings; mixed GL metadata pairs and refreshed
candidate runtime hashes; late native-input-manifest mutation; compiler/runtime drift; absent GL/empty/frame/
triangle proof; plan-only native output; pending or mismatched descriptor anchors;
all seven missing native controls; out-of-scope fallback; and late mutation.
Synthetic tests do not claim native execution. The caller's independent tests
cover corrupt PNGs and capture boundaries.
