# Task 1: ADS and action-transition verification

## Scope and status

Independent read-only runtime review owned by Halcyon. Aella remains the sole writer for runtime, existing tests, capture verifiers and workflows. This document records engineering evidence, not artistic/reference approval. No thresholds or authored data are changed.

- Baseline reviewed: PR [27](https://github.com/RHS059/rust_duty/pull/27), commit `dad6071625ce9190c69e4703c53952a2244cf1f8`.
- Review time: 2026-10-04, beginning 17:02 UTC.
- Corrected Task 1 candidate: pending.
- Independent execution: **not run**; this initial report is static source inspection. Existing baseline tests were not rerun while the integrator is changing the relevant ownership boundary.
- Native screenshots, ADS-offset pixel comparisons, actual-rig reload transition captures and exact corrected-head CI: **pending**.

Ownership agreement: [agreed split](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982345699), [implementation hold released](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982357711).

## Source findings on the baseline

### Saved placement also offsets authored ADS

[`src/main.rs`, lines 381–385](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/main.rs#L381-L385) constructs the saved XYZ placement and passes it directly to the authored renderer without ADS attenuation. [`src/authored_viewmodel.rs`, lines 449–476](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/authored_viewmodel.rs#L449-L476) adds the supplied offset to skinned positions; actor rendering uses the same supplied placement.

This establishes the routing defect addressed by the current task. It does not measure the corrected sight position. The native optical mapping oracle runs below this render-placement boundary and cannot alone prove the on-screen fix.

Required corrected-candidate evidence: paired native frames at identical committed tick, camera, FOV, viewport and lighting, with neutral versus nonzero saved XYZ. Compare full-ADS pixels against the neutral reference while showing that HIP placement still changes. Include partial ADS/reversals to demonstrate the transition and separate walking-translation gains from absolute placement. Report measured residuals using the integrator's explicit existing contract; do not invent or relax a tolerance.

### Reload return currently hard-switches renderer ownership

[`src/authored_viewmodel.rs`, lines 418–435](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/authored_viewmodel.rs#L418-L435) returns the reload renderer directly while a reload sample exists and otherwise renders the locomotion pose. It retains no outgoing rendered reload pose for a return crossfade. [`src/authored_reload.rs`, lines 95–108](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/authored_reload.rs#L95-L108) clears the active sample on authoritative cancellation or completion. [`src/layered_locomotion.rs`, lines 363–380](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/layered_locomotion.rs#L363-L380) resets the run path/envelope around reload and gates walking during reload.

These are source-proven ownership boundaries, not a measured pixel jump. The Task 1 integrator already owns their correction.

Required corrected-candidate witnesses:
- Actual tactical reload completion into idle, walking and running, plus ADS requested on return.
- Authoritative interruption/cancellation and a new action arriving during the return blend.
- Frames/pose witnesses immediately before, at and after ownership handoff, with route, blend weight, native reload time, walk/run/ADS clocks and actor visibility.
- Repeated paused reads and different render sampling rates observing the same committed state.
- Gameplay ammo, credit/readiness and movement remain simulation-owned; visual crossfade must not extend gameplay reload timing.

## Exact-rig and outgoing-magazine boundary

The [coordination agreement](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982345699) explicitly identifies a third outgoing-magazine actor in reload. Baseline loading keeps reload with its own checked companions and renderer ([authored_viewmodel.rs:141–182](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/authored_viewmodel.rs#L141-L182)).

A direct three-actor reload pose cannot be fed to the existing two-actor locomotion blender:
- [AnchoredPoseBlend](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/layered_locomotion.rs#L44-L63) validates both pose dimensions even before its weight-zero return.
- [AnimationSet validation](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/viewmodel_animation.rs#L568-L595) requires actor-global and visibility lengths to match the target set.
- [PoseBindings](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/authored_locomotion_adapter.rs#L58-L109) compares ordered bone names/parents, actor names, actor mesh bindings/inverse rests and skin/rigid companion checksums. Equal bone counts alone are insufficient.

This is a constraint on the in-progress implementation, not an observed defect in a corrected candidate. Acceptance must show the exact loaded reload/locomotion compatibility or explicit checked remapping, retain matching skin/rigid ownership, and account for the outgoing magazine's transform and visibility at entry, cancellation, completion and interrupted return. A missing, reordered or incompatible source must fail safely rather than silently index-blend an unrelated rig. Do not remove strict validation simply to accept the extra actor.

Generic pose visibility switches at blend weight 0.5 ([viewmodel_animation.rs:583–585](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/viewmodel_animation.rs#L583-L585)); that default is not evidence that the outgoing magazine has correct lifecycle behavior.

## Existing evidence and limits

The [baseline WIP record](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/docs/ADS_V9_RUNTIME_WIP.md) reports 26 optical witnesses with maximum component error 7.19e-7, 26 x 72 bone globals with 3.35574e-5 error, and 26 x 2 rigid actors with 8.12e-7 error. These values are author-reported evidence, not new measurements from this review.

The bone result still **fails the unchanged 1e-5 source criterion**. Passing the separate 1e-4 runtime reconstruction allowance is not source-parity acceptance. No artistic gate is added.

The complete-pose check is explicitly ignored in ordinary tests. The actual-pack v9 replay in [receiver_ads_v9_contract.rs](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/tests/receiver_ads_v9_contract.rs) returns early when `RUST_DUTY_ANIMATION_MANIFEST` is unset; a green default test count alone does not show asset-backed execution. Its two-actor pure-forward oracle does not cover a three-actor reload handoff.

## Corrected-candidate acceptance record

To complete after Aella supplies the corrected commit:
- Exact candidate SHA and source/asset provenance.
- Checks actually run, commands/environment, results and named skips.
- Workflow/job/artifact links for that exact SHA.
- Native ADS-offset paired-frame pixel comparison.
- Actual-rig reload completion/interruption and outgoing-magazine witnesses.
- Remaining numerical failures and unperformed native/platform checks.

Until then, this document records confirmed baseline source gaps and pending corrected-candidate evidence only. It does not approve merge, release, updater publication or Task 2 profiling.
