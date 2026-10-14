# Reviewed conditional GL supplement binding

`tools/bind_reviewed_gl_supplement.py` ingests the exact reviewed 50-frame
geometry/fragment supplement for capture `8f571464` / run `37415102452` / attempt
`1` and original source run `371bca3d` / `37427554951` / attempt `1`.
It does **not** establish native-profile closure or alter the normal acceptance
path. The 160 empty fallback rows and 19 ordinary-gate eye/near/far rows are not
added to this helper's scope. DX12 is not accepted by the GL model.

The four review anchors are embedded in the checker. A supplied receipt cannot
replace its own expected hash:

| Artifact | SHA-256 |
| --- | --- |
| Original source receipt | `241bb21d23bb711daaff9dac33b75b504e1c69104fa0949099b38f0f86453370` |
| Original GL source JSONL | `93d730d84e5f0055cd51e4e613f7210974ae7a4682bdb7e7f8e246d3ad1227ca` |
| Reviewed clipped geometry | `458655709d010fd004eccc04234094ec09d66428e286e47c892ab5578d9a3204` |
| Reviewed fragment report | `edaecbca5d3a485187a02d2662588170b32b6df59f9e1cc1e032ebfc99648696` |

## Checked boundary

The caller provides the separately established original capture/source contexts.
The checker binds the original receipt to the source JSONL, checks all 553
original frame IDs and the unchanged source profile/calibration/extent, then
requires precisely the 50 reviewed visible frame IDs in both supplements.
Duplicate keys, nonfinite JSON, boolean integers, reordered/overlapping or
out-of-extent mask runs, missing frames, substituted hashes and late file
mutation fail closed. Original evidence is read only.

The full geometry artifact hash binds its reviewed triangle inventory. The
structural checker additionally validates source mesh/triangle identities and
partition counts, unique clipping variant/fan identities, every emitted possible
mask, every original overlap, and exact geometry-to-fragment inventory equality
for all subtriangles that could win a required sample. Unsafe subtriangles remove
their **entire possible overlap**, even where another triangle has a safe bound.
Safe rows require the rigid opaque-white scope and the existing three-byte bound.
The result's required mask must narrow the original; its possible mask must
contain the original. Counts are recomputed and must reproduce 47,558 retained
samples, a minimum of four, 53,473 examined overlapping subtriangles and 1,487
unsafe subtriangles.

The helper does not rerun the numerical proof or derive new per-triangle bounds.
The exact reviewed geometry/report hashes are what authorize the already reviewed
numerical values and establish inventory completeness across omitted nonvisible
triangles. Merely updating these anchors is not a reusable producer protocol.

`bind_reviewed_gl_supplement(...)` returns frozen `ConditionalGlFrame` rows and
`BoundReviewedGlSupplement`. All native-profile fields remain false and the
verdict remains null. Boolean coercion raises `TypeError`; positive retained
support is not an acceptance boolean. Call `verify_unchanged()` again immediately
before reporting downstream results. The CLI writes only a conditional binding
summary, with an exclusive-create output path, and includes no source geometry
or private asset bytes.

```sh
python tools/bind_reviewed_gl_supplement.py \
  --source-receipt ORIGINAL_SOURCE_RECEIPT.json \
  --native-source ORIGINAL_GL_SOURCE.jsonl \
  --geometry REVIEWED_CLIPPED_GL.jsonl \
  --fragment REVIEWED_FRAGMENT_REPORT.json \
  --capture-context 8f571464be706d0abde862e124582a188f633baf 37415102452 1 \
  --source-context 371bca3d848f5b749cf9ea989fa1fbfaca8c20cc 37427554951 1 \
  --output NEW_BINDING_SUMMARY.json
python -m unittest discover -s tools -p test_bind_reviewed_gl_supplement.py -v
```

## Minimum remaining normal-path interface

1. Keep `bind_source_packet` as the independent capture/source entry point, with
   closed native shard inventory, original invocation/compiler/runtime/executable
   identities, every companion/settings byte, full gameplay/time records and
   late-mutation checks. The contexts passed here must come from that validation;
   this helper does not independently authenticate an execution or a caller.
2. A reusable producer needs a fresh, independently anchored source/input/probe
   receipt. It must enumerate before/after input, implementation, compiler and
   executable hashes, commands/environment, successful execution records,
   requested frame set, output hashes and distinct capture/source/verifier run
   contexts. Replayed mask/state equality alone does not establish intermediate
   native upload identity.
3. The reusable geometry interface needs a closed source triangle inventory keyed
   by frame, actor/kind, mesh and triangle, with an explicit result for **every**
   source triangle: hidden, certified outside, complete clip variants/fans, or
   unresolved. It must bind original vertex/index/model/projection/color bits,
   arithmetic-domain records and all post-clip intervals. Counts alone cannot
   prove that an omitted triangle was outside. Each fragment result must bind
   the exact geometry hash and all possible overlapping winners as checked here.
4. Independent native implementation/input/execution evidence must establish the
   remaining GL premises. The [package/source review](mesa-native-package-binding.md)
   establishes ordinary Mesa binary/build provenance; bind that evidence with shader lowering,
   target/sample/depth/blend state and native input identity. Independently bound
   native comparator observations and all unchanged image/telemetry/witness
   checks remain mandatory. Successful conditional ingestion cannot waive them.
5. DX12 corroboration uses the separate proposed
   `rust-duty-finite-warp-corroboration/v1` schema. Its source receipt, original
   DX12 JSONL, source trace, source asset, implementation/executable and per-frame
   hashes must bind its adapter/runtime/DLL/compiler observations. Keep
   `later_corroboration: true`, `original_capture_reproduced: false`,
   `original_native_upload_identity_verified: false`,
   `original_profile_flags_modified: false`, `universal_profile_verified: false`
   and `acceptance_verdict: null`. A source-plan-only result has
   `native_execution: false`; a later native pass is still corroboration of that
   bounded run. It cannot be silently promoted to original-execution identity or
   imported through this Mesa-specific checker.

No image tolerance, camera calibration, capture, asset or original false flag is
changed. This standalone ingestion layer can be reviewed and published before
any separate normal-path acceptance integration.
