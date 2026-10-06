# Four HIP walk visual candidates

Four experimental Actions were authored directly in Google Colab on copies of the approved HIP r5 motion. They are **not visually reviewed or approved**. The source's 82 original Actions remain unchanged beside the four new Actions in the supplied BLEND.

## Proposed changes

- Forward: a small second downward pulse, reaching 3.5 native pixels at the support-cuff witness around Actions 30–32.
- Backward: redistribute at most 3 native pixels of the support-hand dip from Actions 26–29 toward 34–38. No global retiming.
- Left: reduce the late rotational excursion by 7.5%, with translation compensation holding the native cuff path.
- Right: reduce the existing horizontal camera-space translation excursion by 12.5% around its fixed mean.

These conservative hypotheses came from direct inspection of the pinned r5 paired previews and their original reference videos. Legacy coordinates named `muzzle_tip` and `receiver_center` were rejected as cross-weapon visual-match landmarks after inspection showed that they were not homologous visible features. Their use as internal motion witnesses does not turn them into a similarity score.

## Exact files and timing

- Candidate: `hip_four_walks_colab_visual_v1.blend`
- Candidate SHA-256: `f7d6e76d387a07508f61b2ade708fa930b93bd73b167110469a43c88ecf8eaf4`
- Baseline source: `assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend`
- Baseline SHA-256: `36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d`
- Baseline runtime/source pin used for the trial: `eedd2910d339e1b6df6dae23bc9878e43478cc0c`
- Pinned approved paired preview media: `RHS059/rust_duty_updates` at `e8206ee38fadaf34af4b90d4ffd8ab15b3b087e2`

| Direction | Original Action | New Action | Inclusive range | Unique frames | Reference core |
|---|---|---|---|---:|---|
| Forward | hip_walk_forward_r5 | hip_walk_forward_colab_visual_v1 | 1–39 | 38 | R2 [48,86) |
| Backward | hip_walk_backward_r5 | hip_walk_backward_colab_visual_v1 | 1–46 | 45 | R2 [211,256) |
| Left | hip_strafe_left_r5 | hip_strafe_left_colab_visual_v1 | 1–50 | 49 | R2 [886,935) |
| Right | hip_strafe_right_r5 | hip_strafe_right_colab_visual_v1 | 1–50 | 49 | R1 [361,410) |

All clips are 60 fps absolute poses. The final frame repeats the first as a closure witness and is excluded from unique playback. Camera, key times, duration and source-frame mapping remain fixed. `render-contract.json` provides the exact handoff and priority witnesses.

## Actual Colab execution

Notebook: https://colab.research.google.com/drive/13t6LekgpJnziBnyeSqdOOvkIM6NRjaC9?authuser=1

The final selected run used official Blender Foundation `bpy==4.3.0`, Python 3.11.17, NumPy 1.26.4 and uv 0.12.23 in an isolated Colab CPU environment. `requirements.lock` pins dependency hashes. The source was authored in Blender 4.3.2; this version difference is explicit. Blender warns when loading that newer file. Protected data was checked both before save and after reopening the exact saved candidate.

An earlier NumPy 2.4.6 run produced an ABI warning and was superseded. This checkpoint contains the clean NumPy 1.26.4 result. The Blender download endpoint returned Cloudflare 1010; no bypass was attempted, and the supported PyPI distribution was used instead.

## Passed checks

- All 82 original Action fingerprints, metadata, and extended curve settings unchanged.
- Original meshes, rest rig, skin bindings, materials, camera, raw pose defaults, drivers, NLA and packed-image fingerprints unchanged after save and reopen.
- 2,904 evaluated 480 Hz samples across the four originals and four candidates passed wrist attachment, guard, driver and exact loop-closure checks.
- Intended screen-space changes were measured. Forward cuff Y reached +3.5004 px; backward ranged from −3.0000 to +3.0002 px. Left cuff drift stayed below 0.001 px. Right cuff X changes ranged from −3.9060 to +3.5343 px while Y drift stayed below 0.001 px.
- Output archive was saved outside Colab and independently CRC/hash verified before the runtime was deleted. Colab's session list then showed no active sessions.

## Remaining acceptance gate

Capture and review genuine foreground Eevee viewport animation, comparing original and candidate Actions against the fixed source mapping. No render was performed in Colab. Numeric passes do not establish visual improvement, anatomy, hidden clearance, runtime parity, or a 90% rating. None of these candidates is activated in the game or replaces the approved source or scores.

The original approved Actions are retained in the candidate file so before/after captures can use exactly the same scene. If a candidate looks worse or the change is not useful, keep the approved original. Do not merge or activate this experiment merely because its numerical tests pass.
