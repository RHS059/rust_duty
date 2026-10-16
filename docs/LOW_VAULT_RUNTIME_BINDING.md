# Low-vault native-clock binding (inactive WIP)

This change prepares a checked runtime path. It includes no animation/mesh asset,
no default manifest activation, and no source or artistic approval. The shipped
`assets/animations.cfg` remains unchanged.

## Gameplay boundary

The existing low mantle climbs **onto** a block. It is not a vault-over solver.
Without a valid optional binding it remains 0.60 seconds. Unbound high mantle remains
0.85 seconds; its separate optional native binding uses 95/60 seconds. Ledge pull-up is unchanged. The explicit experimental policy
`low_mantle_native_wip` uses 1.05 seconds for an accepted low mantle only.
Collision sweeps, landing clearance, fresh-input eligibility, cancellation and
weapon lockout are unchanged. Adding vault-over traversal is separate work.

A binding is installed only after the manifest, receipt, VRA, matching VRS/VRM,
and return-pose compatibility checks succeed. Missing/invalid files cannot
install it. Disabling an active binding clears its authored sample without
changing an already accepted collision trajectory's duration. Replacing a
binding during traversal is rejected atomically.

## Clock and identity

The measured window is source frames 1–64 at 60/1 fps, corresponding to decoded
reference frames n7284–n7347, half-open [7284,7348). The elapsed span between keys
is **63/60 = 1.05 seconds**, not 64/60. Runtime time zero maps to source frame 1
and reference n7284. At 120 Hz, the first committed accepted tick samples frame
1.5; the endpoint is frame 64 on tick 126. No synthetic entry hold or time stretch
is added. Rendering may skip intermediate samples; it never advances the clock.

VRA times must be exactly the complete non-looping grid from 0 through 1.05,
within floating-point tolerance: 64 integer keys, or 127/253/505 keys for
2/4/8 subdivisions. A retimed 0.60-second clip, loop, missing endpoint or partial
grid fails activation. The simulation retains the final sample for its completed
traversal tick, even though the traversal state has finished. It clears the
sample on the next committed tick, cancellation, reset or death.

The receipt SHA-256 is pinned in the manifest. The receipt pins the exact VRA
SHA-256, editable candidate SHA-256, source Action fingerprint, FBX SHA-256 and
actual export-take metadata. The renderer hashes and decodes the same VRA byte
buffer and validates the exact decoded companion buffers. These checks establish
binding integrity; metadata assertions alone do not prove source preservation,
export accuracy, visual approval, or native rendering correctness.

The historical approved r8 editable file is not present in this change. A rebuilt
candidate must carry its own identity and fresh review. Never relabel rebuilt
bytes with an older approved source hash.

## Optional manifest fields

Only add these in a separately reviewed activation revision, with actual files
and the actual receipt hash (the placeholders below deliberately are invalid):

```ini
low_vault.policy=low_mantle_native_wip
low_vault.asset=low_vault/asset.vra
low_vault.clip=<actual converted clip name>
low_vault.receipt=low_vault/runtime-receipt.json
low_vault.receipt_sha256=<sha256 of exact receipt bytes>
```

`mantle=unavailable` remains the legacy generic slot marker; it must not be
replaced with a claim that vault-over gameplay is implemented. Paths are safe,
manifest-relative paths. Any partial optional configuration fails parsing.

The JSON receipt schema is `rust-duty-low-vault-runtime/v1` and requires:

- `presentation_policy`: `low_mantle_native_wip`
- `clip_name`: the actual converted VRA clip, equal to the manifest clip
- `source_action`: the actual editable Action name
- `export_take`: the actual exported FBX stack/take name; do not assume the
  exporter preserves the Action name
- `candidate_sha256`, `source_action_fingerprint`, `source_fbx_sha256`,
  `asset_vra_sha256`: lowercase 64-character SHA-256 values from actual evidence
- `candidate_frame_range`: [1,64]
- `reference_frame_range_half_open`: [7284,7348]
- `native_fps`: [60,1]
- `native_crop`: [0,63], zero-based key offsets within the selected take
- `imported_frame_offset`: 1, mapping native key offset 0 to imported frame 1
- `subdivisions`: 1, 2, 4 or 8
- `return_seconds`: finite duration from 0.05 to 1.0 seconds, chosen and reviewed
- `actor_basis`: `canonical` or `reload_mesh_local`, explicitly established by
  export/conversion evidence, never guessed from an Action or bone name
- `anchor_actor`: the shared weapon actor name used for the return blend

The receipt's `imported_frame_offset=1` is a frame-coordinate mapping, **not**
Blender's FBX importer `anim_offset` argument. The recovered baseline probe needs
`anim_offset=0` to reimport source 1–64 as 1–64; its default of 1 shifts the range
to 2–65. Verify the actual exported/reimported take before writing a receipt.

## Outgoing transition

Native playback owns the complete arms/weapon pose and suppresses extra cant,
sway/action displacement and visual ADS placement. On completion or cancellation,
a configurable smoothstep return freezes the last displayed low pose and blends
toward the **live** underlying paired-prone, reload or locomotion pose. It is updated after those
controllers commit. It does not freeze the target or retime the source clip.

The return uses the shared weapon anchor, named bone/hierarchy/inverse-bind
checks, explicit rigid-actor basis conversion and actor opacity. Base-to-low uses
the declared canonical-to-low basis C. Reload-to-low uses B^-1*C, where B is the
existing canonical-to-reload conversion. Paired-prone uses the same explicit
reload-mesh-local basis conversion and preserves fractional live actor opacity. Missing anchors, incompatible rest
skeletons or incoming actors absent from the low pack reject activation. Extra
low-only actors fade out rather than appearing in the destination.

ADS placement, cant and procedural layers return with the same committed blend
weight. Repeated render synchronization at unchanged simulation time neither
advances nor restarts the fade. Cancellation while paused starts at weight zero.
Death and viewmodel reset discard both native and outgoing state immediately.
A rendering/binding error clears presentation and disables subsequent optional
native traversal; it does not silently substitute a guessed asset.

The runtime mapping does not prove that two packs contain visually equivalent
meshes/materials or that the source's contact and entry/exit poses are suitable.
Those remain actual-asset review requirements.

## Verification and activation gates

The source-only CPU fixtures exercise native-grid/hash rejection, companion
validation, accepted/rejected traversal, 126-tick native clock, unchanged default
0.60-second traversal, final-tick weapon lockout, render-partition independence,
pose selection, cancellation, configurable return, live targets and return root
layers. CPU draw lists are not native GPU evidence.

Before shipping an activation revision:

1. Recover or rebuild the exact editable candidate; preserve the rig/attachments
   and record its actual identity. A reconstruction needs fresh artistic review.
2. Validate the complete 64-frame source/reference window, export/reimport range,
   actual take name, actor basis and subdivision grid. Generate companions and
   the pinned receipt from those bytes.
3. Check the real manifest path, every mapped incoming actor, rest skeleton,
   weapon/hand contacts, entry, completion, paused cancel, death/reset and
   returns into moving/ADS/reload states. Resolve geometry/material seams.
4. Run real native rendering and traversal collision/lockout checks at multiple
   presentation rates. Confirm final-frame and outgoing transitions visually.
5. Decide whether the ONTO-block experimental policy is the desired gameplay.
   A true vault-over feature requires its own geometry/trajectory implementation.

No art score, metadata-only validation, CPU test, or compile result satisfies
these remaining gates by itself.


See [combined integration](COMBINED_ANIMATION_RUNTIME.md) for cross-traversal
ownership, optional-route failure isolation and the source-only validation boundary.
