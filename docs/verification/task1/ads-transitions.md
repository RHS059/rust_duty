# Task 1: ADS and action-transition verification

## Scope and status

Independent read-only runtime review owned by Halcyon. Aella remains the sole writer for runtime, existing tests, capture verifiers and workflows. This document records engineering evidence, not artistic/reference approval. No thresholds or authored data are changed.

- Baseline reviewed: PR [27](https://github.com/RHS059/rust_duty/pull/27), commit `dad6071625ce9190c69e4703c53952a2244cf1f8`.
- Baseline review began 2026-10-04 at 17:02 UTC; corrected-source review began 17:32 UTC.
- Corrected source inspected: `edc162d59e18225ba0da238424a769b68d7efb32`, follow-up `b577aaaa4e4016bd965a4f8f89c9d03338c417e0`, and combined candidate **`d4d9b622d42ce0aa45896f06ac338a6ae7a0be14`**.
- Independent execution: **9 Python capture-verifier unit tests passed** from exact d4d9b622 connector-fetched source at 17:52 UTC (4 ADS, 5 reload-return). Earlier edc162d run passed 7 tests. No Rust tests or native captures were run by this reviewer.
- **Bounded ADS/transition review complete:** native CI artifacts were independently downloaded, decoded and reverified at 18:09–18:11 UTC. [Complete candidate pipeline 37222001387](https://github.com/RHS059/rust_duty/actions/runs/37222001387) succeeded; publication was skipped. Interim `[skip ci]` checkpoints remain distinct from this final run.

Ownership agreement: [agreed split](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982345699), [implementation hold released](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982357711).

## Final scoped acceptance: native d4d9b622 evidence

**Pass for the requested saved-XYZ ADS invariance and bounded completion/cancellation/restart transition checks.** No new actionable defect remains in this lane. This is not a merge/release decision or artistic approval.

All artifacts below are from [run 37222001387](https://github.com/RHS059/rust_duty/actions/runs/37222001387), bound to commit `d4d9b622d42ce0aa45896f06ac338a6ae7a0be14`.

### ADS placement

Independently downloaded [neutral ADS artifact 11311066181](https://github.com/RHS059/rust_duty/actions/runs/37222001387/artifacts/11311066181) and [offset artifact 11310643328](https://github.com/RHS059/rust_duty/actions/runs/37222001387/artifacts/11310643328). Reran the exact candidate's placement verifier, then independently decoded every PNG pair with Pillow:
- 553 paired images, each 960 x 540.
- 135 full-ADS image pairs exactly identical in both PNG bytes and decoded pixels; 23 are moving ADS.
- 60 HIP image pairs differ; placement affects HIP before and after aiming.
- Gameplay/animation telemetry matches across the paired runs.
- Matching full-ADS images were visually inspected for capture sanity only.

The final CI artifact has **135** full-ADS pairs, distinct from the author's earlier local report of 136. This report uses the independently verified final-run count.

ZIP SHA256:
- Neutral: `f736c3a5e6126826e8d8881cb37015ec088783d8850b02758e9844df37e2b1c2`.
- Offset: `700018aa8014df68588bfd6694979e352e18452c9fba3892eeb3b3db71bc9ff4`.

### Reload return and extra actor

Independently downloaded [return artifact 11311480530](https://github.com/RHS059/rust_duty/actions/runs/37222001387/artifacts/11311480530), decoded all 391 native 960 x 540 PNGs and reran the exact v2 verifier:
- 3 outgoing return episodes: 1 completion, 2 cancellations, 1 restart during a live return.
- 28 outgoing-return frames, with live walk/run overlap.
- 17 frames have a partially visible outgoing magazine during return; it retires by final ready.
- Maximum sampled anchor translation step: **0.019267385211712684 m**, within the unchanged 0.04 m verifier bound.
- Ammunition conservation and final ready/zero extra-prop visibility pass.
- Completion boundary: frames 0171→0172, 2.850000→2.866667 s; source native time 2.600000 s, duration 2.602600 s.
- Cancellation: 0258→0259, 4.300000→4.316667 s; native time 0.750000 s, extra opacity 1→0.9803241.
- Restart: 0264→0265, 4.400000→4.416667 s; return weight 0.50000006 followed by native time 0.01666667 s.
- Second cancellation: 0268→0269, 4.466667→4.483334 s; native time 0.06666667 s.

The eight boundary images above were visually inspected for obvious capture/ownership failures, without judging motion fidelity or artistic quality. ZIP SHA256: `ba5dd3805ea24effab8889aa3a50e4af25cfdea245d7b777c47dc66510695b50`.

### Remaining limits

The independent Rust/runtime execution was performed by CI, not this reviewer; this reviewer executed 9 synthetic Python verifier tests and reran both native artifact verifiers, plus full PNG decoding and selected boundary inspection. Translation bounds do not establish angular, every-joint or skin continuity. Native Windows interactions, artistic/reference approval and the inherited strict 1e-5 source-pose failure remain outside this scoped pass. No new threshold, source-data change or runtime edit was made by this lane.

The following sections are historical review records; their pending-evidence statements are superseded by this final exact-head artifact section.

## Combined-candidate follow-up: d4d9b622

Source reviewed and tests independently rerun on 2026-10-04 at 17:52 UTC.

The prior return-verifier finding is **closed in source and regression tests**. The [v2 verifier](https://github.com/RHS059/rust_duty/blob/d4d9b622d42ce0aa45896f06ac338a6ae7a0be14/tools/verify_reload_return_capture.py) now requires:
- A valid native clip duration and preceding active reload sample for each outgoing return.
- Source endpoint timing that distinguishes a complete return from an early cancellation.
- At least one completion, two cancellations and a fresh native reload while an earlier return is still active.
- Advancing return weights, visible cancellation and decreasing extra-prop opacity.
- The existing movement overlap, translation bound, final ready/prop retirement and ammo-conservation checks.

Its scope explicitly says the sampled anchor metric measures translation only, not angular, joint or skin continuity. [main.rs](https://github.com/RHS059/rust_duty/blob/d4d9b622d42ce0aa45896f06ac338a6ae7a0be14/src/main.rs#L1879-L1890) emits actual reload sample time and clip duration into the replay telemetry.

Independent execution: all **9 tests passed** from the exact candidate's four verifier/test modules. The two added regressions reject a ready/return-only fixture with no preceding native reload and frozen return weights. This closes the reported false-evidence case; it does not substitute for native capture.

[Aella's combined-candidate handoff](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982758414) reports the strengthened native replay passed with 391 frames, 1 completion, 2 cancellations, 1 restart, 28 return frames, 17 visible extra-magazine fade frames and maximum sampled anchor translation approximately 19.3 mm. These are still author-reported results until the native artifact is independently inspected. No new actionable runtime defect was found in this source pass.

## Earlier corrected-source review: edc162d / b577aaaa

The baseline defects described below are historical; both now have structural fixes:
- [main.rs](https://github.com/RHS059/rust_duty/blob/edc162d59e18225ba0da238424a769b68d7efb32/src/main.rs#L381-L398) derives placement from visible authored ADS rather than saved XYZ unconditionally. The layered controller includes run weight, and reload entry/return preserves its current visible ADS amount.
- [authored_viewmodel.rs](https://github.com/RHS059/rust_duty/blob/edc162d59e18225ba0da238424a769b68d7efb32/src/authored_viewmodel.rs#L445-L615) holds the reload renderer through incoming/outgoing 0.20-second blends, snapshots the displayed pose/opacity when interrupted and targets current live locomotion.
- [PoseReturnMap and PoseReturn](https://github.com/RHS059/rust_duty/blob/edc162d59e18225ba0da238424a769b68d7efb32/src/authored_pose_return.rs) map evaluated bone globals by name with matching named hierarchy/inverse binds, retain strict pack bindings and apply an explicit rigid actor basis conversion. The extra outgoing actor remains at its last transform while opacity decays. No mismatched-length arrays are directly blended.
- Actual-pack tests exercise named mapping, incompatible rests, restart from current pose and extra-actor retirement. They require the animation-manifest environment variable; source inspection is not their execution.

No concrete new runtime defect was found in this static pass. This is not native rendering or artistic acceptance.

### Evidence actually checked

Independently executed the four tests in `tools/test_ads_placement_capture.py` and three in `tools/test_reload_return_capture.py`: **7 passed** using Python unittest against exact edc162d source loaded into isolated in-memory modules; test fixtures used temporary directories. No repository runtime files were edited. Both reload-verifier files remain byte-identical at b577aaaa. These tests validate the verifier's current assertions using synthetic fixture data, not game rendering.

[Aella's handoff](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982597513) reports 532 focused Rust tests, 22 capture tests, Clippy/actionlint and a native Linux paired ADS capture: 553 frames, 136 identical full-ADS images including 23 moving, 60 changed HIP images and matching telemetry. This is author-reported local evidence. The native files/logs were not independently retrieved or visually inspected by this reviewer. The dedicated reload-return capture was explicitly still finishing.

### Historical verifier evidence-scope gap (fixed in d4d9b622)

[verify_reload_return_capture.py](https://github.com/RHS059/rust_duty/blob/b577aaaa4e4016bd965a4f8f89c9d03338c417e0/tools/verify_reload_return_capture.py#L21-L25) counts three non-null return-weight episodes, then reports completion/cancellation/restart coverage. It does not validate each episode's native reload progress or event reason. Its [passing positive fixture](https://github.com/RHS059/rust_duty/blob/b577aaaa4e4016bd965a4f8f89c9d03338c417e0/tools/test_reload_return_capture.py#L11-L22) contains only ready/return routes with constant intermediate weights and no active reload source/event witness.

Return continuity checks cover finite/bounded weapon-anchor **translation**, not rotation or every hand/bone. The owner should label that coverage accurately or establish the actual completion, cancellation and restart state witnesses in the dedicated native replay. This is an evidence-scope correction, not a new artistic gate or proof that the runtime transition is broken.

## Historical source findings on the baseline

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

## Historical corrected-candidate acceptance checklist

To complete after Aella supplies the corrected commit:
- Exact candidate SHA and source/asset provenance.
- Checks actually run, commands/environment, results and named skips.
- Workflow/job/artifact links for that exact SHA.
- Native ADS-offset paired-frame pixel comparison.
- Actual-rig reload completion/interruption and outgoing-magazine witnesses.
- Remaining numerical failures and unperformed native/platform checks.

Until then, this document records historical baseline gaps, corrected-source inspection, independent synthetic verifier tests and pending native/final-build evidence. It does not approve merge, release, updater publication or Task 2 profiling.
