# One-hand logical FBX stack admission

The optional `--single-stack` mode in `tools/import_fbx_viewmodel.py` handles a
complete, nonlooping one-hand take without relying on Blender's truncated Action
labels. Existing multi-take/name selection and paired-prone behavior stay separate.

`tools/single_stack_fbx.py` requires one exact logical AnimationStack and linked
AnimationLayer plus the complete required Model UUID inventory. A version and
source-signature guarded observer records the actual stack, layer, owner and
Action datablocks used by Blender 4.3.2's importer. Required owners must remain
bound to those precise Actions with the expected clock and no unexpected NLA.
Foreign or ambiguous identity, reassignment, missing curves and incomplete owner
coverage fail closed. Imported Action labels are retained as evidence; no name
renaming, suffix guessing or first-match selection is performed.

## Measured status (2026-10-16)

- 22 focused synthetic/reader-signature regressions and 41 existing importer and
  paired-prone regressions passed against the patched importer.
- The actual frozen one-hand dense FBX was converted through Blender 4.3.2 using
  this observer. The native process exited 0 and the manifest retained the exact
  sole logical take `aella_mantle_onehand_r6_camera_reconstructed_v6`, all four
  required owners (Arms and three rigid actors), 72 canonical deformation bones,
  and 6,081 runtime samples at 3,840 Hz. Source clock is frame 1–96 at 60 Hz;
  imported offset 1 is distinct from the fresh FBX verifier's anim_offset 0.
- The approved source SHA-256 is
  `b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77`;
  dense FBX SHA-256 is
  `17608683c81465964b5890b4d9869774a0f35122cf62ebd6e564cedf1b1ddbe4`.
- The static camera/rig uses the ordinary viewmodel basis and shared weapon
  anchor. This mode performs no paired-prone common-camera-motion removal.
- Complete independent 4,240-time source, fresh-FBX and actual-Rust parity is
  still running. Conversion alone is insufficient for runtime admission. The
  optional high-ONTO runtime pins remain inactive in this WIP revision.

Private BLEND, FBX, runtime mesh payloads, local geometry witnesses and raw proof
arrays are excluded from this source-only change. Neither pending source-recipe
publication request is replaced by this importer work. See
`ONEHAND_HIGH_ONTO_RUNTIME.md` for gameplay scope, outgoing return and remaining
native/Windows acceptance requirements.
