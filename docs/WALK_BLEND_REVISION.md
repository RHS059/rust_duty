# Continuous walking and ADS locomotion

Based on PR #15 commit `9f27474b3cb55a41d0f8d81afeaf516cc84d721f`.

- 160 ms smoothstep walk start, 220 ms smoothstep stop; interrupted fades retain
  the native loop phase. Rendering and pauses never change controller state.
- Canonical weapon-relative global-pose composition retains the complete source
  walk at full hip weight and preserves wrist attachment through fades.
- ADS entry, hold, exit and reversal retain walking. At full aim, the original
  depth and optical-axis roll components of walking animate the complete aimed
  assembly while preserving the sight ray. No replacement bob curve is added.
- Sprint and mantle fade the walk layer. Accepted reload keeps its explicit
  incompatible-rig cut and resets walking; full current reload remains packaged.
- Source Actions, all prior clips, rigs, meshes, game rules, lighting and FOV are
  unchanged. No reference-video fidelity or artistic approval is claimed.

Regression coverage includes envelope endpoints and reversals, pause/invalid ticks,
committed ADS/sprint/fire/reload replay with unchanged gameplay, actual-pack grip
and endpoint sweeps, and native Linux start/stop and aimed-walk capture telemetry.
Validation results and exact GitHub build links will be added after execution.
