# Combined optional animation runtime (inactive source WIP)

## Source provenance and scope

This integration starts from PR73 commit `a18e98ab267a307f614f23f57ef0f00ff59906cc`
(the PR71 → PR72 → PR73 stack). It selectively ports PR68's eleven-file source
change, whose head is `c677651473b3e27fd8e7582c2bf0fc05c370b85d`, onto the newer
renderer. It does not copy the older checkout or its uncommitted working files.

No frozen editable animation, native export, payload, private soldier asset,
production manifest binding or approved-runtime pin changes in this revision.
Existing walks, ADS, jump, reload, camera pairing, rendering, lighting, UI,
session and clock paths remain the baseline. The high-ONTO production admission
remains closed while its independent dense-source/native proof is pending.
Each animation retains its separate source/artistic identity. Synthetic CPU
fixtures establish code contracts, never artistic approval or real asset proof.

## Explicit ownership and live return targets

- Optional low climbs ONTO a low block. It does not implement vault-over.
- Without bindings, low remains 0.60 seconds and high remains 0.85 seconds.
- Admitted low uses the exact 63/60-second key span. Admitted high uses 95/60.
  Hang and pull-up are unchanged. Final traversal ticks retain weapon lockout.
- Every newly accepted ordinary traversal clears both old traversal presentations
  before admitting its own source. A cancelled or completed high tail cannot
  obscure a new low, and a low tail cannot reappear after a new high.
- Low and high returns target live paired-prone, reload, or layered locomotion
  in that order. Returns never target each other, preventing dependency cycles.
- Prone returns itself target live reload or locomotion. Nested actor opacity,
  hidden-actor transforms, ADS placement and procedural weights stay continuous.
- The current shared `PoseReturn::pose_with_opacity_at_weight` remains the only
  fractional-opacity implementation. Low adds a configurable return duration.
- The existing single `procedural_root` interpolation is retained. Cant is
  weighted once at the selected renderer. No second scaled-Euler sway path is
  added.

The production committed observer runs after every accepted simulation tick,
including ticks skipped by presentation. Low retains frame 64 on its completion
tick; its return begins on the next committed observer update, or immediately
on paused cancellation. Read-only synchronization cannot advance simulation time.
A simulation generation invalidates low outgoing state after reset, level change,
rebind or supersession. Death clears both traversal states immediately.

## Optional admission and error isolation

All required configuration remains strict: partial, unsafe or unknown manifest
keys are errors. Once an optional reference parses, missing/corrupt payloads,
companions, receipts or incompatible return mappings reject only that optional
route and append a warning. Paired prone is staged atomically; failed camera or
weapon admission cannot leave a half-pair installed. Unrelated base/walk/ADS/
reload/jump and successfully admitted optional routes remain available.

Simulation timing is installed only from a successfully admitted renderer.
Before every input tick, and after every committed observer update, the app
removes bindings whose renderer has failed. A late draw failure therefore cannot
let the next frame accept native timing without an admitted presentation.
Global renderer failure removes every optional binding. Paused synchronization
performs the same removal without a clock advance.

Replacing low's binding during traversal is rejected atomically; explicitly
removing it preserves the already accepted collision trajectory duration while
clearing its authored presentation. High retains its existing replacement rule,
which cancels the accepted high trajectory. Reset preserves admitted bindings
but discards source/outgoing state; level changes and death discard both states.

## Verification boundary

Focused tests cover synthetic optional combinations, independent admission
failure, low/high ownership switches, live targets and nested opacity, cancellation,
pause, death, reset, level changes, rebinds, 30/60/144/240 presentation partitions,
legacy timing, final-tick lockout and unchanged hang behavior. High's genuine
combined simulation/renderer test uses a same-crate, `cfg(test)`-only synthetic
binding. No public production admission bypass is introduced.

This source-only change must remain inactive until the real combined candidate
has its own native collision, rendering, visual-transition and source-preservation
proof. Individual frozen art/provenance and their outstanding approvals remain
separate and unchanged. No test result here activates or approves a payload.

## Consolidated review and remaining dependencies

The intended publication is one consolidated draft against `main`, carrying the
existing PR71/PR72/PR73 ancestry plus this scoped PR68 port. The local integration
baseline remains the exact PR73 head above. Existing draft PRs remain open and
unchanged; this work does not close or merge them.

The two held-payload approvals remain separate and unresolved. This source review
does not grant those approvals or move their payloads. Actual-candidate Windows,
packaged-game and combined native execution still depend on the separately
approved payloads, the remaining source/runtime proof, and the required Windows
and package validation. A source-only compile, synthetic fixture or consolidated
draft does not satisfy any of those dependencies or activate production assets.
