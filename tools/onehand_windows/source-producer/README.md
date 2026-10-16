# One-hand v6 source-only reconstruction preparation

Revision r2: strict completion revalidation. The original r1 package is preserved unchanged in `prior-r1-pinned/`.

Status: CPU preparation only. No Blender, game, native graphics, rendering, source-input modification, solver rerun, upload or publication was performed. No actual final Action delta, regenerated source, or evaluated source-equivalence receipt exists yet.

## Frozen identities

- Existing baseline: `RHS059/rust_duty` commit `1daee9ff0d250b6ad926dedaab4977663f560406`, path `assets/authoring/mantle/r3/candidate/aella_mantle_r3.blend`.
- Exact local baseline: `reboot-recovery-20261014/aella_mantle_r3.baseline.blend`.
- Baseline SHA-256: `6b95bdcdfa78e8127ef4b4fa5ac88e4cf9a0654bd0a1271c9916b903f6ee4e79`.
- Baseline Action: `aella_mantle_onehand_r3`, fingerprint `ca59e0f53fdde2a642432345119a65e0dcb04fad11838a4a0484254fdaf958af`.
- Approved local source: `recovery/onehand-camera-solve-v6/candidate-v1/onehand-r6-camera-reconstructed-v6.blend`.
- Approved SHA-256: `b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77`.
- Final Action: `aella_mantle_onehand_r6_camera_reconstructed_v6`, fingerprint `c7ca6383364e055afe1d0246f443d33689ce86c56677570ba694a924c983ea01`.
- Exact baseline reset: `RD_00_Supplied_Base_Guarded_Recovered`, fingerprint `49b7da5f9d6ea12be52bade40b09aeb67d6adc6eb34a1a7026e3f111b3c61ed8`.
- Static camera and rig object, no camera Action, source frames 1–96 at 60 Hz.
- Exact dense grid: `a521b1e779e45f85948d94b8b9aa9f9cad41d935783ba5fcbda34decb6aec08f`, all 4,240 original times. The local grid copy is byte-identical.

Existing public repository presence does not grant permission to redistribute geometry, rest state, pose defaults, or full-scene assets. The producer uses a separately supplied, pinned existing baseline. It never downloads a scene or publishes anything.

## Implemented components

- `onehand_v6_source_delta.py`: pure sparse key/handle/settings codec, signed-zero preservation, exact hashes, bounded JSON, schema validation and explicit correction metadata.
- `onehand_v6_source_native.py`: Blender 4.3.2 extraction, replay with save/fresh reopen, and read-only exact evaluated witness chunks.
- `run_onehand_v6_source_proof.py`: owner-selected exclusive lock, one bounded native job at a time, complete package pin checks, witness sealing, and strict CPU aggregation.
- `owner_commands.py`: prints the next concrete command without executing it. It resolves delta/generated-source/receipt hashes only after verified outputs exist. Previous failed or partial outputs require inspection; there is no automatic overwrite or retry.
- `test_onehand_v6_source_proof.py`: CPU-only synthetic regression suite, including an actual 34-file, 4,240-time aggregation. Tests neither import `bpy` nor launch native software.
- `pose-corrections.json`: only original scalar deltas and hash preconditions; no inherited scalar values.
- `PINS.json`: immutable preparation package pins. The preparation receipt separately records its SHA-256 and the exact first command.

The delta is constructed directly against the original r3 Action. Every unchanged inherited curve remains a hash/index reference. Changed keys use original numeric corrections from a deterministic baseline encoding origin. Unchanged inherited keys are omitted. The codec reproduces exact FCurve order, handle positions/types, interpolation/settings and Action settings. The authored correction allowlist includes the right elbow pole from the actual v3 ancestry, root and left-target transforms, and the eleven existing left-hand controller properties. No new FCurves, camera/object co-motion, curve reordering, modifiers on edited curves, or solver approximation is accepted.

The source adds exactly one final Action to all 88 original Actions, yielding 89 Actions. It does not recreate the six intermediate author Actions or claim the approved scene's count of 95. Original Action curve, metadata and auxiliary group/marker hashes remain exact. New Action metadata carries only changed/new original scalar or text properties; inherited properties remain local references. Historical metadata such as the author's prior count remains verbatim original provenance, not a statement about the regenerated Action count.

## Sixteen tiny pose-default differences

The retained lineage identifies 16 scalar differences, maximum `2^-23`:

- Twelve unkeyed MCH components receive explicit original delta corrections, guarded by exact before/after hashes. These are eleven scale components and one magazine-target Euler component.
- Four driven outputs are never assigned. Their original drivers are required, hashed unchanged and reevaluated. Replay must reproduce their exact approved hashes.

All other static categories must match exactly. The full pose-default hash is preserved as a separate field; an explicitly named exception projection checks every unmodified pose field. The exception projection cannot turn a failed full-pose replay into a pass. Replay fails before saving if driver recomputation or any unrelated saved-state value differs. After saving, the re-opened 89-Action source must pass the same checks again.

## Full evaluated witness

There are 17 chunks per source: 16 chunks of 256 times and one chunk of 144 times. Each chunk reopens its independently pinned source, validates complete Action/static-state hashes, evaluates the unchanged canonical reset once, binds the exact final Action, establishes frame 1, then evaluates its original times. No key rewrite or default reset is performed during each sampled frame.

At every time the witness hashes:

- All 148 evaluated bone-world matrices
- Rig, camera and projection; exact frame-1 constancy is required
- Actual `hk416_weapon`, `hk416_magazine`, `hk416_magazine_outgoing` actor-world matrices
- All source object-world matrices
- All three full evaluated skin meshes, totaling 10,234 vertices
- All three full evaluated rigid meshes
- Exact local/world positions plus full edge, loop and polygon topology hashes

Bone hierarchy, world rest matrices, object/bone order, frame-1 full geometry and all existing source preservation categories are independently hash-bound. Local rigid geometry and all topology must remain byte-exact against frame 1 at every time.

Only names, counts, times, schema metadata and SHA-256 digests are serialized into witnesses. Floating-point geometry/matrices use strict little-endian float64 bytes; topology uses little-endian int64 bytes. There is no tolerance or quantization. Per-chunk JSON is normally under 1 MiB and is capped by the 32 MiB JSON bound. No raw pose/skin/rigid oracle files or NPZ arrays are written. Native work is serial, background, one thread, with a 1,800-second default deadline per process. The wrapper rejects deadlines outside 30–7,200 seconds.

The aggregate requires all 34 exact chunk files with pinned evidence hashes, the complete ordered 4,240-time coverage, identical scopes across chunks, matching input/code identities, and strict paired evaluated hashes. A single missing sample, changed bit, topology order, source byte identity, camera drift, relaxed numeric contract or unexpected payload fails.

## Native-owner handoff

Do not run these commands concurrently with the ongoing runtime chunk proof or other native work. The owner must coordinate the existing native queue and pass its chosen shared lock. This preparation does not approve or replace either pending vault-delta or prone-witness request.

Run the CPU planner with the package SHA from `preparation-receipt.json`:

    PYTHONDONTWRITEBYTECODE=1 python onehand-runtime-20261016/source-producer-preparation/owner_commands.py --pins-sha256 <verified PINS.json SHA-256> --lock <owner-selected shared native lock>

The planner prints one command in this sequence:

1. Extract sparse original delta from both frozen inputs, with no source save.
2. Replay against the baseline into a new private BLEND; save and re-open; record the new SHA-256.
3. For each chunk 0–16, generate approved and regenerated hash-only witnesses in that order.
4. Seal the exact 34 witness-file hashes, then run the CPU strict comparison.

Execute a printed native command only when the serialized native owner is free and that specific work is authorized. Run the planner again after each successful stage. The first fully resolved extraction request is in `first-owner-request.json`; its proposed proof-local lock does not coordinate external native jobs by itself. The owner must serialize with those jobs and may substitute its shared lock. All default future outputs stay in this directory's fresh `native-r1/` subdirectory. The planner itself creates no native result directory and launches nothing. Its complete path rereads all 34 current witness files, checks them against the current sealed index, validates the current replay and index byte hashes, binds the recipe to the actual current producer code, rebuilds the complete strict equivalence result, and compares the entire saved proof exactly. Minimal summaries, stale proofs, coherently replaced pairs, extra proof fields and stale producer versions fail. A valid completed check writes nothing.

CPU validation:

    PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s onehand-runtime-20261016/source-producer-preparation -p 'test_*.py' -v

## Concrete limits

- Actual Blender extraction, native Action installation, automatic handle behavior, unchanged-driver recomputation, serialization/reopen preservation and evaluated equivalence are not yet run or proved.
- Native schema/RNA differences or exact floating-point differences fail closed; use a new reviewed code revision rather than relaxing the proof.
- Exact evidence at 4,240 times is a sampled guarantee, not a continuous-time proof.
- The regenerated serialized BLEND must have a different SHA-256 from both inputs, even when Action/evaluated-source equivalence passes.
- Source equivalence does not prove FBX conversion, Rust importer/runtime consumption, placement, collision, actual native rendering or artistic acceptance.
- The regenerated BLEND and any inherited scene content remain private. Original code/delta metadata and hash-only witnesses are merely source-only candidates; this task performs no publication or upload.
