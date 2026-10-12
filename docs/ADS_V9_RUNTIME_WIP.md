# ADS v9 runtime WIP

The runtime candidate selects `layers.ads_walk=receiver_v9_forward_wip` while
retaining the four r5 HIP slots and existing ADS47 entry/hold/exit clips. Entry
and exit keep the 0.30-second visual retiming. Gameplay readiness is unchanged.
The source is the exact published PR23 v9 checkpoint and its complete-pose oracle
under `assets/authoring/locomotion_ads/v9/`. Its comparison-bake Actions are not
looped or substituted for native walking clips.

Pure forward uses the accumulated r5 native phase for horizontal receiver motion
and 15% weapon-relative global arm articulation. Only its vertical receiver
lookup uses an auxiliary sample half a native period later (19/60 seconds).
The auxiliary sample shares the primary clock. No comparison-video alignment
offset is applied to gameplay. Optical mapping changes basis with the existing
self-inverse game root and applies that render root only once.

Backward and lateral directions keep v4 as explicit WIP fallbacks. Eased forward
weight blends the mixed-HIP v4 optical result toward independently sampled
forward v9. Partial ADS interpolates the HIP and aimed offsets and retains the
existing walk/run envelopes. Forward ADS adds articulation with weight
`walk * ((1 - aim) + 0.15 * aim * forwardWeight)`; rigid actor attachments retain
held ADS relationships. This direction/partial-ADS extension is an engineering
choice for immediate WIP inclusion, not an independently reviewed animation.

The phase rate is `1 - aim * (0.15 + 0.05 * forwardWeight)`: 0.80 at full forward
ADS, 0.85 at full nonforward ADS, and 1 at hip. Both aim and aim-times-direction
are integrated on committed intervals. The latter uses cached smoothstep segments
and analytic cubic exponential moments; partition tests include retiming,
reversals, hold boundaries and large intervals. Render queries never advance it.

Local numerical evidence, separate from visual approval:

- 26 native optical witnesses: maximum matrix-component error 7.19e-7.
- 26 x 72 bone globals after parent-local TRS reconstruction: maximum error
  3.35574e-5. This FAILS the unchanged strict source 1e-5 criterion. The test uses
  an explicit 1e-4 runtime reconstruction allowance to detect gross regressions,
  and reports the stricter failure rather than relabeling it as source parity.
- 26 x 2 rigid actors: maximum component error 8.12e-7.
- 1,320 actual-pack simulation ticks exercise direction/diagonal changes, ADS
  entry/exit, run overlap, reload ownership and repeated paused reads. XYZ walk
  settings preserve clock progression and apply to the final walking displacement.

The source also retains its known bake/shear discrepancy and joint-anchor/contact
residues. Neither these numerical checks nor successful compilation establish
reference fidelity or visual approval. Native Windows interaction and full native
v9 visual interruption review remain separate verification work.

The compact 26-case optical oracle is committed with the exact PR23 source.
The larger complete-pose JSON is generated verification output, kept separate
from the playable source tree. Its original SHA256 is
`849601ac607f858431698a857d03339aa20f33a1f38b3df64d2636b09dc3b7d7`.
The complete-pose test is explicitly ignored in an ordinary test run; run it with
`RUST_DUTY_V9_POSE_ORACLE=/path/to/v9_complete_pose_runtime_oracle.json cargo test
--test receiver_ads_v9_contract v9_complete_native_pose -- --ignored --nocapture`.
Its measured local result above remains separate from ordinary CI coverage.

Regenerate that numerical input without rendering or changing either source:

```sh
ADS_V9_HIP_SOURCE="$PWD/assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend" blender -b "$PWD/assets/authoring/ads/ads.blend" --python assets/authoring/locomotion_ads/v9/make_v9_runtime_pose_oracle.py
```

Use Blender4.3.2. The small author-supplied generator is committed beside the
source and public optical oracle. Its output path is ignored by Git, while the
source bytes and saved-bake failure remain reproducible.
