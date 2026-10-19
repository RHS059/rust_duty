# Source-only Windows game input inventory

This successor measures the actual pull-request event commit and the established
immutable Jump input before native admission. It does not accept the result as a
source specification for a game build. Independent review of the actual Actions
run, source tree and two output files remains required.

## Narrow composition

The published `game-continuation-v1` package, its inactive game admission, its
source tests and all native proof/build/capture/delivery steps remain unchanged.
The separately pinned `game-continuation-v2` package adds a standalone exact-Git
export, an isolated measurement entry mode and focused regression tests. Its
`prepare_game_spec.py`, source selection, full-proof validation, runtime patches,
asset generators, capture observers and numerical thresholds are byte-identical
to v1. The v2 package is used only for source tests and inventory measurement by
this workflow; the native continuation still executes v1.

The existing fixed Jump checkout now also runs while admissions are inactive.
The event checkout is the actual immutable pull-request head, never a moving
branch or an artifact from another run. Jump remains commit
`e9317f90ea171976306e2f17c111325d948ea357`, with the one existing authoring input
`assets/authoring/jump/halcyon_jump.blend`. No Blender, Cargo, renderer or game
process is launched by measurement. The input is read through Git; no raw input
is uploaded.

A separate schema-only repair copies the already-reviewed all-null v4 native
admission template to `tools/onehand_windows/proof-admission.json`. The unchanged
v4 admission parser returns `blocked-incomplete-admission` and `native_ready=false`.
It continues to reject the old all-null v2 schema. This fixes the actual source
preflight failure at commit `d3bcc87bbed39115be11429c0610fa4a989a05ce`; it supplies no
accepted input, independent review or activation value.

## Verified measurement sequence

1. The workflow reads the new standalone exporter as a raw Git blob from the
   exact event commit and checks its reviewed SHA-256 before Python executes it.
2. The exporter confirms the actual checkout HEAD, reads and checks the exact
   package PINS, verifies its own bytes, exports every named original-source
   member and checks all member hashes before any local package import.
3. The isolated bootstrap verifies the complete cache-free package again. The
   source tests exercise real, small synthetic Git repositories and negative
   event, source, Jump, export, inventory and failure cases. These fixtures do
   not constitute Windows native evidence.
4. Measurement checks the actual Windows x64 Actions environment and event JSON,
   exact event/source HEAD, fixed Jump HEAD and both Git trees. It records actual
   Git executable/version, Python executable/version and loaded Python DLL
   hashes. It calls the unchanged pinned `prepare_game_spec.py` helper.
5. A separate validation pass requires the complete selected game closure, the
   one fixed Jump row, exact relative destinations, byte limits and all SHA-256
   and Git blob SHA-1 values. Every Git blob is independently reread and rehashed.
   Package, event, source trees and tool identities are rechecked afterward.
6. Only a completely successful measurement writes the step success output.
   The workflow uploads exactly `game-source-spec.json` and
   `game-source-spec-receipt.json` to the run-and-attempt-named inventory artifact.
   The spec is capped at 2 MiB and 2,048 rows; the receipt is capped at 32 KiB.

The spec contains public relative source paths, exact commit/blob identities,
byte counts and content hashes. The receipt contains event head, Actions SHA,
workflow SHA/reference, run ID, attempt, job, hashed runner identity, event-payload
hash, source trees, package/bootstrap/helper hashes, actual tool identities and
the spec's filename/hash/size/count/total. It explicitly states source-only,
not independently accepted, no candidate generated and no native admission
provided by measurement. Runner-local absolute source paths are omitted.

Unknown modes, partial arguments, redirected paths, partial/forged inventories,
source/Jump/event mismatches or changing observed identities fail closed. Python
failures expose only type and SHA-256 of the error; captured Git stderr is not
printed. Only the fixed bounded `game-source-spec-failure.json` is eligible for
the existing always-run hash-summary upload. A partial spec or receipt is never
uploaded by the successful-inventory step.

## Review and later admission

After the real CI run, independently resolve its exact commit/tree, run/attempt,
job, artifact identity and output hashes. Verify the package/helper pins, full
inventory and fixed Jump row against those immutable Git inputs. Then create a
separate genuine acceptance and populate game admission with the accepted
immutable source revision and measured spec. No placeholder spec or acceptance
is supplied here. A later admission-only commit may preserve the selected source
closure; the existing v1 `current_closure` comparison proves equality with the
admitted revision before game export.

The current source composition must also include the separately reviewed
app-edge additive/reversal contract repair. Its files live outside
`tools/onehand_windows`, so the actual event measurement includes them in the
game source closure. Historical failed CI remains evidence, not a pass.

A measured static source inventory may be reviewed after runner teardown. An
animation candidate may not: a fresh actual complete 4,240-sample proof, exact
candidate binding, game build and 30/60 Hz DX12 captures must still occur in one
admitted Windows job before teardown. Public runtime pins stay inactive.

## Local checks

The isolated v2 source suite passes 72 tests: all 46 inherited v1 tests and 26 new
measurement/export negatives. Nine preparation checks confirm exact v1 freeze,
unchanged native and game steps, bounded uploads, exact pins, fixed Jump source,
and inactive v4 schema behavior. No Rust source is changed by this successor;
no new Cargo or native result is claimed. Actual Windows inventory measurement,
source admission, native proof and game capture remain pending the real CI run
and independent review.
