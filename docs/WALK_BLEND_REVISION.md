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
Independent actual-pack geometry sweep: maximum wrist drift 0.000598 mm;
full-ADS sight center displacement 0.000268 px and near/far difference 0.000115 px
at 1280×720 / 76° hFOV. Walking retains −1.450 to +3.349 mm axial movement and
up to 0.02975° optical-axis roll. No source asset bytes changed.

Global articulation blending can temporarily change forearm length by up to
1.899 mm (0.68%) in this pack. Mid-fade reversal preserves pose and phase, but
reverses envelope velocity immediately; jerk-free motion is not claimed. Matrix
composition rejects unsupported shear instead of silently changing the transform.
Final GitHub validation and build links will be added after execution.
