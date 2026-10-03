# r5 stable-name export proposal

Reviewed proposal for Aella's single export/config/package writer. **The patch is
not applied on this source-history branch. No generated assets are included.**

## Pinned inputs

- Runtime base: [PR17, `e46f83d8`](https://github.com/RHS059/rust_duty/commit/e46f83d84ece0c28ffbd10cf4504ed4ea0f91878)
- Published source: [`493c2024`](https://github.com/RHS059/rust_duty/commit/493c202477604892ee6d332fc24ef01e8703f1ae),
  `assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend`
- Source SHA-256: `36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d`
- Patch SHA-256: `ba3000aa83390571cd428536c4788099b13082166a5801e6f4ee316c3e3cba12`

## Existing game mappings

Target remains `assets/directional/asset.vra`; `assets/animations.cfg` is unchanged.

| Source Action | Existing game/FBX name | Inclusive frames |
|---|---|---|
| `hip_walk_forward_r5` | `hip_walk_forward_r1` | 1-39 |
| `hip_walk_backward_r5` | `hip_walk_backward_r1` | 1-46 |
| `hip_strafe_left_r5` | `hip_strafe_left_r1` | 1-50 |
| `hip_strafe_right_r5` | `hip_strafe_right_r1` | 1-50 |

These are absolute poses at 60 fps, baked at 480 Hz, with repeated endpoints.
The original walk44 payloads, `normal_walk_r1` fallback, canonical companions,
ADS and controller behavior remain protected. No canonical BLEND replacement or
new per-revision runtime binding is needed.

## Applying the proposal

Reconcile the seven-file diff with the current owner checkout before applying it.
`runtime_export_config.json` pins the source revision; the production adapter
exports its Actions under existing game names. Source selection is retained in
packaged provenance and CI cache inputs. Frozen r1/r5 source packets are untouched.

Run the established `tools/build_directional_assets.py` route using a freshly
built `sample_viewmodel_clip` and new work/output directories. Then run
`tools/check_generated_assets.py --kind directional`, generated-pack tests and
normal game build/staging checks. This adds no new artistic or visual-review gate.

Commit the resulting directional gzip transports, rigid companion, manifest,
source selection, conversion/parity reports and README at `assets/directional/`,
along with the selection/export changes. The patch includes a narrow allowlist
for those outputs. Do not replace unrelated assets or apply this patch blindly
over newer shared changes.

## Verification status

Independent code review approved the proposal. Four selection/binding tests,
ten packaging tests, Python syntax and diff checks pass. The generated-pack test
class was explicitly skipped because this handoff did not run the owner's
Blender export, final48 numerical load checks or complete-game staging. Those
checks and the final game-asset commit remain outstanding.

`manifest.json` records the exact file inventory, source mapping and check scope.
