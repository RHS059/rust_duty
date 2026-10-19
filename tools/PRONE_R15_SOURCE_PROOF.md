# Prone r15 source-only reconstruction route

Status: prepared and CPU-tested; native extraction, replay and evaluated proof have
not run. These tools are not evidence that a source has been reconstructed.

## Inputs and privacy boundary

The consumer must separately supply the permitted existing r5 BLEND. Existing
repository provenance does not authorize uploading or redistributing it:

- Existing commit: `659fd15ec77a7b4df5018bc7c86a54deace5333e`
- Existing path: `assets/authoring/prone_crawl/revisions/entry_r5/halcyon_prone_crawl_r5.blend`
- Existing blob: `65e82510e83cfcd2a8e6a27ee849dc5a0f1531b8`
- Base SHA-256: `67cf025fc31d9804cb0259432a91e496d7d8f84d1d4ac6be2b1914a6a98510ad`
- Approved original SHA-256: `cbed3051bb8c4bbdb78f72a49a7a51bd585db33636ddc5312dde38b05a2a86c4`

Hash the actual downloaded/provisioned bytes. Git metadata or an HTTP success is
not a byte-identity proof. These tools perform no downloads, uploads or Git writes.
Keep both BLEND inputs, regenerated BLENDs, raw logs and private runtime artifacts
local. A generated BLEND retains private assets and must never be included in a
source-only publication. Inspect the extracted JSON's original authored scope
before deciding whether that JSON may be published.

The delta JSON contains only authored changes and hash/reference metadata:

- Unchanged FCurves refer to a base ordinal and digest, without key data or names.
- Changed existing curves use remove/add/replace operations. Changed coordinates
  are float32-reconstructible differences from the existing baseline key or a
  deterministic baseline-derived encoding origin at the new time.
- New rig/camera object channels are differences from the supplied base object's
  local location/Euler defaults. Those inherited defaults are never serialized.
- Handles, interpolation and other key/FCurve evaluation settings are preserved.
  Exact equality includes positive/negative zero: sparse signed-zero flags retain
  float signs lost by subtraction/addition, without serializing baseline values.
- No geometry, rest matrices, weights, evaluated matrices or skin coordinates are
  emitted. Preservation and evaluated witnesses are hashes only.

The r5 rig Action is `prone_crawl_enter_r5`. There is no r5 camera Action. The final
pair is `aella_prone_crawl_enter_r15_roll_v1` on `Arms` and
`aella_prone_crawl_enter_camera_r9_viewray_v3` on `RD First Person Review`.
The canonical reset is `RD_00_Supplied_Base_Guarded_Recovered`.

## Commands for the serialized native owner

Do not launch these during another native job. Use the native owner's established
queue and pass a shared, owner-selected lock path. The lock protects these wrappers;
it does not discover or control unrelated native processes. No render is performed.
Blender must be 4.3.2, background, factory-startup, scripts disabled, one thread.
Each invocation requires a fresh job directory and fresh output files.

From the checkout's `tools` directory, on Windows or Linux:

```text
python run_prone_r15_source_proof.py native --blender <Blender-4.3.2-executable> --lock <owner-native-lock> --job-directory <fresh-extract-job> --timeout-seconds 1800 -- extract --base <existing-r5.blend> --approved <approved-r15.blend> --output <fresh-original-delta.json>
```

Extraction is read-only with respect to both BLENDs. It verifies all 112 baseline
Actions and non-Action preservation categories, produces sparse deltas, and proves
a pure-Python exact round trip before writing the JSON. An unknown curve/property,
non-Action difference or failed exact reconstruction stops extraction.

After inspecting the extraction and computing its SHA-256:

```text
python run_prone_r15_source_proof.py native --blender <Blender-4.3.2-executable> --lock <owner-native-lock> --job-directory <fresh-replay-job> --timeout-seconds 1800 -- replay --base <existing-r5.blend> --delta <original-delta.json> --delta-sha256 <delta-sha256> --output <fresh-regenerated-private.blend> --receipt <fresh-replay-receipt.json>
```

Replay adds only the two final Actions. Every baseline Action and saved default
binding remains unchanged. No intermediate historical Actions or editorial custom
metadata are re-created. Legacy curve fingerprints and complete evaluation-state
fingerprints must match the extracted target exactly, including after fresh reopen.
Complete fingerprints use the retained r15 `support.complete_actions` field set;
they cover curve order/settings/modifiers/samples, all writable key RNA properties,
and Action frame-range/cyclic settings. They do not claim identity of editorial
custom properties or the original serialized file.

Replay emits the actual `generated_source_sha256`, separate from
`approved_source_sha256`. Replay alone explicitly does not establish evaluated
motion equivalence. Exporters must bind the rig and camera pair explicitly; saved
baseline default bindings deliberately remain intact.

Generate two independently reopened hash-only witnesses:

```text
python run_prone_r15_source_proof.py native --blender <Blender-4.3.2-executable> --lock <owner-native-lock> --job-directory <fresh-approved-witness-job> --timeout-seconds 7200 -- witness --source <approved-r15.blend> --source-sha256 cbed3051bb8c4bbdb78f72a49a7a51bd585db33636ddc5312dde38b05a2a86c4 --kind approved --output <fresh-approved-witness.json>
python run_prone_r15_source_proof.py native --blender <Blender-4.3.2-executable> --lock <owner-native-lock> --job-directory <fresh-regenerated-witness-job> --timeout-seconds 7200 -- witness --source <regenerated-private.blend> --source-sha256 <actual-generated-sha256> --kind regenerated --replay-receipt <replay-receipt.json> --replay-receipt-sha256 <receipt-sha256> --output <fresh-regenerated-witness.json>
```

Both reset to the canonical Action, restore canonical defaults at every sample,
and explicitly bind the rig plus camera. Coverage is the exact retained 1,944-time
clock: 1/8 over frames 1–69, 1/16 over 24–45, all 1/128 times over 35–45, and 1/512
boundary neighborhoods. All 148 bones, rig, camera, three rigid actors and every
vertex of all three skinned meshes are covered. Values stay in process memory;
only strict float64-byte hashes are written. There is no rounding/tolerance pass.
Cross-platform numeric differences fail and need diagnosis.

Finally compare without Blender:

```text
python run_prone_r15_source_proof.py compare --approved-witness <approved-witness.json> --approved-witness-sha256 <sha> --regenerated-witness <regenerated-witness.json> --regenerated-witness-sha256 <sha> --replay-receipt <replay-receipt.json> --replay-receipt-sha256 <sha> --delta <original-delta.json> --delta-sha256 <sha> --output <fresh-source-equivalence.json>
```

Only this comparison may set `evaluated_pair_equivalence_proved=true`. Original
and regenerated byte identities remain different even when equivalence passes.
This proof does not replace converted runtime, actual renderer or platform gates.
It must not weaken the original-source admission gate or assign the original
`cbed...` hash to regenerated bytes. An exact-equivalence success preserves the
already approved motion; the tools introduce no additional artistic gate.

## CPU verification

```text
python -m unittest discover -s tools -p test_prone_r15_source_delta.py -v
python -m py_compile tools/prone_r15_source_delta.py tools/prone_r15_source_native.py tools/run_prone_r15_source_proof.py tools/test_prone_r15_source_delta.py
```

Tests use synthetic fixtures only and never import `bpy`, launch Blender, invoke
native graphics, access the network, or mutate private source assets.

## Extraction r1 diagnosis

The first owner-run extraction passed all 112 inherited-Action and non-Action
preservation gates, then stopped at the exact pure-roundtrip hash check. It wrote
no recipe and changed neither input BLEND. A synthetic CPU regression reproduces
that failure when a changed float becomes negative zero: ordinary Python equality
ignores the sign, while the retained fingerprint distinguishes it. The corrected
producer compares canonical representations and retains zero signs explicitly.
This is a verified defect; the native r1 failure’s exact field was not logged, so
r2 must confirm whether it was the only cause. Redacted field/index diagnostics
now identify any remaining mismatch without emitting inherited values.
