# Task 1: pause settings regression evidence

## Status and ownership

**Latest corrected source reviewed; independent native acceptance remains pending.** At 17:52 UTC on 2026-10-04, reviewed combined candidate `d4d9b622d42ce0aa45896f06ac338a6ae7a0be14`. The original failed-save persistence/keyboard gaps and both follow-up stale-success cases are corrected in source. No Rust tests, native keyboard interactions, screenshots or runtime fault injection were executed by this reviewer. The historical findings below record why those changes were requested; they are not unresolved defects at the latest reviewed head.

### Latest disposition: d4d9b622

- `PauseMenu::status` now chooses persistent state before transient notices. A new `new_edit_overrides_unexpired_success_notice_immediately` regression asserts that a new edit reports Unsaved both with and without an old success notice.
- Main snapshots sensitivity/FOV before their hotkeys and calls `changed()` when either value changes. Legacy placement nudges retain their change notification. This closes the previously reported indefinite stale-success case as well as the temporary notice-priority case.
- Reviewed focus traversal, focused Enter consumption, exclusion of legacy placement nudges while focused, persistent failure, reset isolation and synchronous save routing remain intact.
- Source review establishes that the requested mechanisms and focused priority regression are present. It does not establish execution of every native/integration matrix row.
- [Aella's exact-head handoff](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982758414) reports native keyboard/save-error/retry checks but supplies no settings-specific artifact or detailed sequence in that message. Those observations remain author-reported. [Combined CI run](https://github.com/RHS059/rust_duty/actions/runs/37222001387) is a link for the designated CI reviewer; this document does not claim its final outcome.

Latest sources: [status selection](https://github.com/RHS059/rust_duty/blob/d4d9b622d42ce0aa45896f06ac338a6ae7a0be14/src/pause_menu.rs#L75-L97), [new priority regression](https://github.com/RHS059/rust_duty/blob/d4d9b622d42ce0aa45896f06ac338a6ae7a0be14/src/pause_menu.rs#L513-L521), [tuning dirty-state and save/reload routing](https://github.com/RHS059/rust_duty/blob/d4d9b622d42ce0aa45896f06ac338a6ae7a0be14/src/main.rs#L1293-L1347).

Nonblocking source-only observation: once any persistence message exists, unconditional persistence-first selection also hides later transient notices in the pause footer. In particular, a failed F6 read sets a useful "current values retained" error in [main lines 1338–1347](https://github.com/RHS059/rust_duty/blob/d4d9b622d42ce0aa45896f06ac338a6ae7a0be14/src/main.rs#L1338-L1347), but [status selection lines 93–95](https://github.com/RHS059/rust_duty/blob/d4d9b622d42ce0aa45896f06ac338a6ae7a0be14/src/pause_menu.rs#L93-L95) can hide it behind an older persistence message. Current values are retained by the inspected normal failed-read path; this observation concerns feedback visibility. It does not reopen the fixed saved-state truthfulness findings or block the complete task. No native reproduction is claimed.

### Earlier corrected-head findings: edc162d / b577aaaa

These two heads had byte-identical `src/main.rs` and `src/pause_menu.rs` when checked at 17:32 UTC.

- Save failure is stored independently of the notice timer and has display priority. `changed()` preserves an existing failure. Autosave and F5 share `save_result`; explicit F6 discard clears failure only after an initial successful file read. Disabled menu input does not discard persistence status.
- Ten focus positions cover Resume, placement XYZ, position reset, walking XYZ, walking reset and Save/retry. Tab/Shift+Tab and Up/Down navigate; Left/Right adjust; Home/End set bounds; Enter/Space activate buttons. Changes save immediately per keyboard adjustment. A focus rectangle is drawn, but native visibility has not been observed by this reviewer.
- Main routing suppresses direct session Enter and legacy placement nudges when a menu control has focus. Existing drag tests remain and two new menu tests check one walking-axis/reset path and persistent failed-save state. These unit tests do not themselves execute the main input-routing boundary or rendered footer lifetime.
- The author reports 532 Rust tests, 22 capture-verifier tests, Clippy/formatting and actionlint passing at the gameplay checkpoint. This is [author-reported evidence](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982597513), not this reviewer's execution. The checkpoint used `[skip ci]`; no interim exact-source workflow pass is claimed. The subsequent b577aaaa commit changes the reload witness and contract, not the two reviewed settings/menu files.

### Historical defect, fixed in d4d9b622: previous success masking newer edits

At edc162d and b577aaaa, reproduce by starting paused with no selected menu control, saving successfully with F5, then making a legacy arrow/PageUp/PageDown placement edit before the four-second success notice expires. Main calls `pause_menu.changed()` for the new placement, but the draw path uses `status.or(self.persistence.as_deref())` whenever `save_failed` is false. The live old "Saved..." notice therefore takes priority over the new persistent "Unsaved changes" message until expiry. This was a source-proven display-state ordering defect; the native sequence has not been executed here.

Sensitivity/FOV edits through brackets or minus/equal also mutated persisted settings without calling `changed()`. After a previous successful save, the persistent saved message could therefore remain even beyond expiry. Both findings were returned to Aella in [the scoped follow-up](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5982626290); the runtime owner supplied the fixes above. No implementation was changed in this evidence lane.

Historical defect sources: [save and routing](https://github.com/RHS059/rust_duty/blob/b577aaaa4e4016bd965a4f8f89c9d03338c417e0/src/main.rs#L1155-L1211), [legacy keys and save/load](https://github.com/RHS059/rust_duty/blob/b577aaaa4e4016bd965a4f8f89c9d03338c417e0/src/main.rs#L1293-L1343), [persistent menu state and footer](https://github.com/RHS059/rust_duty/blob/b577aaaa4e4016bd965a4f8f89c9d03338c417e0/src/pause_menu.rs).

### Evidence still needed

Native keyboard traversal/activation and controlled failed-save -> expiry -> failed retry -> successful retry/file-readback remain independently unrun. The three new inspected menu tests cover one walking axis/reset, persistent failure, and corrected footer priority, but not all six keyboard axes, reverse traversal, both keyboard resets, Home/End bounds, main Enter/arrow consumption, repeated failed retry, or actual file recovery. Preserve separate labels for source inspection, reported aggregate tests and native evidence. The acceptance matrix below remains the bounded requested native/integration coverage rather than a claim that the new code fails every unexecuted row.

This document is the settings review lane's only owned repository path. Aella owns runtime, existing tests and related native capture/verifier/workflow changes. Findings return to that owner; this lane does not modify those files. ADS/transition acceptance belongs to the separate review. This report authorizes no merge, release or updater publication.

## Historical inspected baseline

- [PR27](https://github.com/RHS059/rust_duty/pull/27): draft/open at the above commit when checked.
- [Original findings](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5976077983): failed-save footer and missing menu keyboard control paths.
- [Menu input and tests](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/pause_menu.rs): pointer-only input; three existing tests cover drag/save-once, interrupted drag/reset isolation, and placement/walking separation.
- [Main input/save routing](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/main.rs#L1132-L1168): autosave uses a transient notice; Enter is forwarded directly to session resume.
- [Placement keys and F5/F6](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/main.rs#L1264-L1299): global paused placement nudges and separate F5 save notice path.
- [Footer forwarding](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/main.rs#L1690-L1697): only passes notice text while its timer is positive; menu falls back to "Saved automatically after adjustment".
- [Persistence implementation/tests](https://github.com/RHS059/rust_duty/blob/dad6071625ce9190c69e4703c53952a2244cf1f8/src/settings.rs#L261-L367): synchronous `fs::write`; successful roundtrip and input validation tests do not establish failure-status lifecycle behavior.

These are static observations. Existing PR-body test counts or native demonstrations are prior author-reported evidence, not execution by this reviewer and not acceptance of a future corrected head.

## Focused acceptance matrix

Every row below is **NOT RUN independently on a corrected head**. Corrected source and author-reported aggregate execution are summarized above; native/integration acceptance is still pending. Record source SHA, platform, test/log or native witness, expected/actual result and remaining limits when evidence arrives.

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

Await focused tests/native evidence; the reported footer defects are resolved in the latest inspected source. Re-read the affected diff before acceptance; do not rerun a full suite on a superseded head while fixes are in progress. A later relevant commit invalidates earlier acceptance until affected cases are rechecked.

The review finishes when the bounded cases have adequate exact-head evidence or concrete failures/blockers have been returned to Aella. Report static inspection, author-reported tests, independently executed tests and native observation separately. Compilation/CI is not proof of native keyboard behavior, and this scope makes no WCAG compliance, screen-reader, Windows Alt-Tab or ADS fidelity claim.

Current execution limit: this reviewer's cloud workspace has no `cargo` command available. No compiled/native check is represented as passed.
