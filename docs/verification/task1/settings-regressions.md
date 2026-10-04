# Task 1: pause settings regression evidence

## Status and ownership

**Pending corrected-head verification; not accepted.** Source inspection on 2026-10-04 at 17:03 UTC found PR27 still at `dad6071625ce9190c69e4703c53952a2244cf1f8`. The two previously reported findings remain in that source. No Rust tests, native keyboard interactions, screenshots or runtime fault injection were executed for this report.

This document is the settings review lane's only owned repository path. Aella owns runtime, existing tests and related native capture/verifier/workflow changes. Findings return to that owner; this lane does not modify those files. ADS/transition acceptance belongs to the separate review. This report authorizes no merge, release or updater publication.

## Inspected baseline

- [PR27](https://github.com/RHS059/rust_duty/pull/27): draft/open at the above commit when checked.
- [Original findings](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5976077983): failed-save footer and missing menu keyboard control paths.
- [Menu input and tests](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/pause_menu.rs): pointer-only input; three existing tests cover drag/save-once, interrupted drag/reset isolation, and placement/walking separation.
- [Main input/save routing](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/main.rs#L1132-L1168): autosave uses a transient notice; Enter is forwarded directly to session resume.
- [Placement keys and F5/F6](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/main.rs#L1264-L1299): global paused placement nudges and separate F5 save notice path.
- [Footer forwarding](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/main.rs#L1690-L1697): only passes notice text while its timer is positive; menu falls back to "Saved automatically after adjustment".
- [Persistence implementation/tests](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/settings.rs#L261-L367): synchronous `fs::write`; successful roundtrip and input validation tests do not establish failure-status lifecycle behavior.

These are static observations. Existing PR-body test counts or native demonstrations are prior author-reported evidence, not execution by this reviewer and not acceptance of a future corrected head.

## Focused acceptance matrix

Every row below is **NOT RUN on a corrected head**. Record source SHA, platform, test/log or native witness, expected/actual result and remaining limits when evidence arrives.

| ID | Sequence | Required observation |
| --- | --- | --- |
| S1 | Change a slider; force save failure; wait beyond four seconds | Unsaved/error state and an actionable retry remain; expiry cannot imply successful persistence |
| S2 | From S1, retry while failure remains, then restore a writable target and retry | Failed retry retains error; only successful write clears it; reloaded file contains current values |
| S3 | Autosave failure, unrelated transient notice, resume and reopen pause | Unrelated notices/navigation cannot silently clear pending save failure |
| S4 | Exercise explicit F5 failure/success and keyboard-edit persistence | Same truth about saved/unsaved state across save entry points; documented edit-save policy is implemented |
| S5 | F6 reload while changes are unsaved or save has failed | Owner declares reload/discard semantics; resulting status is truthful and does not mislabel loading as saving |
| K1 | Navigate forward/backward without a pointer | All six sliders, both resets, Resume and any new Retry control are reachable in predictable order; visible focus remains identifiable |
| K2 | Adjust each focused slider and attempt both bounds | Only focused axis changes; walking clamps to [-1,+1], placement to [-0.20,+0.20] m; documented step/repeat behavior is stable |
| K3 | Activate both resets by keyboard with nonzero placement and two weapon entries | Walking reset affects only selected weapon walking XYZ; placement reset affects only placement XYZ; each requests its intended save and neither resumes |
| K4 | Use arrows/PageUp/PageDown on focused controls | No double routing to legacy placement nudges; walking adjustment leaves placement unchanged |
| K5 | Enter/Space on reset/retry; then explicit Resume/Escape | Reset/retry activation is consumed, not also resume/fire; intended resume remains usable and does not replay held input |
| G1 | Drag beyond panel; release; repeat release | Drag retains ownership; bounded value; one save for completed gesture; no resume/fire |
| G2 | Interrupt drag or keyboard interaction with focus loss/update overlay; return with held keys/buttons | Disabled menu cannot edit; stale input is cleared; intended interruption save occurs; refocus remains paused |
| G3 | Preserve existing reset/drag and settings roundtrip regressions | Existing covered behavior continues to pass against final corrected SHA; do not substitute only new happy-path checks |

## Safe native failure fixture

Use a disposable settings path beneath a deliberately absent parent directory, not the player's real settings. Launch with that settings path, change a menu value and confirm the attempted save fails. Observe beyond the notice lifetime and retry once while the parent is absent. Create that disposable parent directory, retry through the implemented UI or F5, and reload/read back the resulting settings. This exercises failure then recovery without changing permissions or security configuration. Record the actual platform error rather than hard-coding an operating-system-specific message.

Use a unique temporary root and preserve evidence before ordinary cleanup. Do not infer successful persistence only from footer text. A successful file readback and matching selected values are the persistence witness. If startup behavior prevents this fixture, report the exact blocker and agree an equivalent controlled fault fixture with the runtime owner.

## Integration risks to inspect in the corrected diff

1. **Enter collision:** menu activation and `session.step` currently receive input separately. Consumed reset/retry activation must not reach session resume in the same frame.
2. **Arrow collision:** focused slider handling must not also run the global paused placement nudge block.
3. **Status lifetime:** save outcome must outlive general-purpose notice expiry; unrelated F8/range notices cannot accidentally erase persistence failure.
4. **Shared save state:** automatic and F5 retries need a consistent state transition; successful saving of older values cannot claim newer edits are persisted if the implementation changes to asynchronous saving.
5. **Disabled input:** preserve focus-change/update-overlay gating and drag cancellation while adding keyboard focus.

The asynchronous-save item is conditional, not a claim that the inspected synchronous implementation has an asynchronous race.

## Evidence and stopping condition

Await Aella's corrected exact commit plus focused tests/native evidence. Re-read the affected diff before acceptance; do not rerun a full suite on the known-old head while fixes are in progress. A later relevant commit invalidates earlier acceptance until affected cases are rechecked.

The review finishes when the bounded cases have adequate exact-head evidence or concrete failures/blockers have been returned to Aella. Report static inspection, author-reported tests, independently executed tests and native observation separately. Compilation/CI is not proof of native keyboard behavior, and this scope makes no WCAG compliance, screen-reader, Windows Alt-Tab or ADS fidelity claim.

Current execution limit: this reviewer's cloud workspace has no `cargo` command available. No compiled/native check is represented as passed.
