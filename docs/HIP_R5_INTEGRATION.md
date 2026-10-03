# HIP r5 in the existing gameplay slots

The directional pack now uses the four r5 Actions from source commit
`493c202477604892ee6d332fc24ef01e8703f1ae`. The frozen source SHA256 is
`36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d`.
Its full authoring history stays under `assets/authoring/locomotion_directional/r5/`.
Historical handoff labels in that folder are preserved unchanged.

| Gameplay clip in `assets/directional/asset.vra` | Native Action | Inclusive source range |
| --- | --- | --- |
| `hip_walk_forward_r1` | `hip_walk_forward_r5` | 1–39 |
| `hip_walk_backward_r1` | `hip_walk_backward_r5` | 1–46 |
| `hip_strafe_left_r1` | `hip_strafe_left_r5` | 1–50 |
| `hip_strafe_right_r1` | `hip_strafe_right_r5` | 1–50 |

The game names are stable binding IDs. The distribution manifest records the
actual r5 source Actions and hash, so the names do not imply old motion data.
The 60 fps native periods remain 38/45/49/49 frames; repeated endpoints close
each loop. The owned `runtime_export_config.json` and `tools/export_directional_fbx.py`
map Action names to those existing FBX/runtime names. The original author exporter,
source checksums, canonical locomotion/ADS sources, and controller bindings stay intact.

The normal build uses evaluated 480 Hz FBX export, existing conversion/loading
checks, and the original 44 clip payloads and canonical companions. Only the
four directional payloads are replaced. Failed validation requires a follow-up
revision; it does not convert the current WIP into an unpublished candidate.

Elara's [r5 media review](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5972558779)
scores forward/backward/left/right 82/83/82/81 for the displayed HIP motion.
Those scores exclude weapon/glove/mesh matching, a common camera solution,
gameplay transitions, and ADS. The existing `receiver_v4_wip` policy and ADS47
entry/hold/exit remain selected. Their reused walking input is now r5, so the
resulting ADS composition is new and unreviewed. No ADS score is inherited.
