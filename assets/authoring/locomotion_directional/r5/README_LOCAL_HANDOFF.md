# r5 HIP source: isolated local assembly

This is an unscored local source/export handoff. Elara owns approval and commits.
The proposed patch adds only `assets/authoring/locomotion_directional/r5/`.

## Frozen identity and timing

- Source: `halcyon_hip_directional_r5.blend`, Blender 4.3.2
- SHA-256: `36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d`
- Frozen r4 input: `d220162819fb7267aa6b93b209afc8ce5212a0692e6a4e02c5c43602b08907e3`
- Published ancestor: PR #18 commit `6bbfada1242d2d6c766c52cfc30c3ab511e41669`
- 82 Actions: all 78 prior Actions retained, plus exactly four new r5 Actions

| Action | Inclusive range | Unique frames | Duration | Fixed reference core |
|---|---:|---:|---:|---|
| `hip_walk_forward_r5` | 1–39 | 38 | 38/60 s | R2 `[48,86)` |
| `hip_walk_backward_r5` | 1–46 | 45 | 45/60 s | R2 `[211,256)` |
| `hip_strafe_left_r5` | 1–50 | 49 | 49/60 s | R2 `[886,935)` |
| `hip_strafe_right_r5` | 1–50 | 49 | 49/60 s | R1 `[361,410)` |

The source runs at 60 fps; last frames repeat closure witnesses and are excluded
from unique playback. Reference PTS is `frame * 256`, time base `1/15360`.
`preview_export_config.json` binds exact video identities, hashes and anchors.
No key timing, period or comparison-map changes are introduced by integration.
All four Actions are absolute native poses, not additive deltas.

The original 72 deform bones, three arm skins, weapon and seated-magazine
bindings remain intact. The outgoing reload-only magazine is excluded from the
isolated export. Blender world converts by `(x,y,z) -> (x,z,-y)`; the receiving
runtime applies `Ry(pi)` once. There was no runtime integration in this work.

## Completed checks

- Each creator lane passed 24 independent source checks and preserved all 302
  native evaluated arrays across 60 prior clips byte-for-byte
- Clean r4 assembly imported only the two r5 Action datablocks per lane and
  restored their append-cleared fake-user flags to the exact creator values
- Fresh combined source passed 28 checks, preserving old curves and metadata,
  active/NLA state, 185 drivers, packed textures, geometry/UV/weights, rest
  skeleton, bindings, raw pose defaults, materials and cameras
- All 302 sampled prior-motion arrays remained byte-identical with zero drift;
  both pairs of new Actions evaluate identically before and after assembly
- 1,452 samples at 480 Hz pass numeric contact and driver checks. Root, weapon
  and both hand matrices repeat exactly at each loop endpoint
- Four isolated FBX takes have 675 curves each and 305/361/393/393 keys at 480 Hz;
  native bone, actor and all three skin endpoints repeat exactly
- Portable rebuilding from frozen r4 and the two creator scripts/designs
  reproduces all 82 Action and protected source fingerprints exactly
- All r1–r4 and creator source bytes remain unchanged; the PR #18 checkout is clean

Serialized BLEND bytes may differ on reproduction despite identical data.
The supplied frozen hash above is authoritative. Prior evaluation samples 60
selected clips; it is not an exhaustive proof over every possible time.

## Reproduce without rendering

Set `D` to this folder. Use a frozen r4 input and new output destinations:

```sh
python "$D/rebuild_r5.py" --baseline /path/to/halcyon_hip_directional_r4.blend \
  --output-dir /path/to/new-r5-reproduction --blender /path/to/blender

blender --background --factory-startup --disable-autoexec "$D/halcyon_hip_directional_r5.blend" \
  --python-exit-code 1 --python "$D/validate_directional_source.py" -- \
  --baseline "$D/r4_baseline_fingerprint.json" --config "$D/preview_export_config.json" \
  --output /path/to/new-source-validation.json

blender --background --factory-startup --disable-autoexec "$D/halcyon_hip_directional_r5.blend" \
  --python-exit-code 1 --python "$D/export_directional_preview.py" -- \
  --config "$D/preview_export_config.json" --output-dir /path/to/new-preview-export

blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python "$D/verify_preview_fbx.py" -- --directory /path/to/new-preview-export \
  --config "$D/preview_export_config.json" --output /path/to/new-export-validation.json

python "$D/verify_local_handoff.py"
```

`rebuild_r5.py` needs Blender 4.3.2 with bundled NumPy and the frozen r4 input.
Frozen design JSON avoids a SciPy dependency. Each reconstructed creator lane
must match its complete independent source fingerprint before assembly. Original
lane binaries are unnecessary for this flow.

For prior-motion evaluation, run `evaluate_preserved_clips.py` using
`prior_evaluation_config.json`. A fresh r4 oracle requires a separate helper
folder with its r4 integrity sidecar; never overwrite this folder's r5 sidecar.
Compare the two oracles with `compare_preserved_evaluation.py`.

## Review limits and creator evidence

Creator packets document deeper forward lows, wider/deeper backward arcs with
roll at the corrected low phase, stronger left inward yaw/roll and deeper right
dips. `reference_gap_analysis.json` files state the measured constraints and
their limits. Coupled receiver projections and small extrema consequences are
disclosed in the creator READMEs; key timing remains fixed.

Earlier scores do not carry over to r5. Numeric checks do not establish hidden
mesh clearance, reference fidelity, gameplay, ADS or transition acceptance.
Genuine Eevee Viewport Render Animation and Elara's visual review remain separate
gates. This integration role performed no rendering or artistic scoring.

Creator subset manifests identify exactly copied scripts, designs and numeric
evidence. Reference/native inspection images, logs and redundant lane BLENDs are
excluded. There are no third-party reference images/videos in this patch, no
game-source commits, and no production/controller/gallery changes.
