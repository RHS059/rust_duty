# Optional one-hand v6 HIGH-ONTO runtime

This is original source-only integration work. No private payload is embedded,
enabled, copied into this source tree, or approved by these synthetic tests.
The existing artistic review remains complete; the pending gate is exact runtime
identity and source-equivalence evidence, not another artistic review.

This r2 revision combines the 256-subdivision admission contract with the
optional platform observer and deterministic ordinary-Input capture complement.
It descends from the source-only PR73 revision plus the two Windows test-only
portability fixes. Both runtime payload approvals remain pending and untouched.

## Scope and behavior

- Optional ordinary HIGH-ONTO mantle only. An accepted bound high mantle uses the
  native endpoint span `95/60` seconds: frame 1 to frame 96 at 60 Hz, 190 committed
  fixed steps at 120 Hz. There is no retime to the legacy duration.
- Without an admitted binding, high mantle stays 0.85 seconds. Low mantle stays
  0.60 seconds. Ledge-hang pull-up keeps its own ActionSlot duration. This patch
  does not add or alter a vault-over solver or the separately owned low-vault PR.
- Existing fresh-input eligibility, height/reach/footprint rules, three-leg
  sweeps, phase boundaries, landing volume, support, reload credit and final-tick
  weapon lockout remain authoritative. Animation cannot force acceptance,
  placement, landing, or physics completion.
- The simulation owns the f64 accepted clock. Rendering never advances it.
  Completion retains the exact final source sample at outgoing weight zero.
  Pause freezes it. Existing `cancel_mantle` events start a smooth outgoing
  return; death/reset/level replacement clear immediately. Binding replacement
  cancels only a bound ordinary high traversal, never an unrelated low/pull-up.
- The complete outgoing pose is captured once. The shared PoseReturn and
  PoseReturnMap APIs blend toward the current live locomotion/ADS/reload or paired-prone pose,
  with named skeleton, hierarchy and inverse-bind checks. The same committed
  smoothstep weight controls actor opacity, ADS placement and cant/sway return.
  A long return follows paired-prone entry/return if it becomes the live route;
  its existing root/ADS weight is combined with the high return weight.
  The destination keeps moving. The finite return duration is configured by the
  pinned receipt in the inclusive range 0.05–1.0 seconds.
- The source rig and camera are static. Ordinary runtime camera placement and
  the rigid viewmodel root are applied once. No prone camera-removal contract,
  authored camera descent, extra rig motion or new artistic adjustment is used.

## Fail-closed admission

`APPROVED_RUNTIME_PINS` in `src/authored_high_mantle.rs` is deliberately `None`.
No production caller can construct a binding from arbitrary metadata. Synthetic
constructors exist only inside library unit-test compilation. Conversion alone
does not authorize filling the pins.

Only after the complete native FBX/fresh-import/Rust all-grid evidence is
independently established may a code revision supply exact approved identities
for the receipt, FBX, VRA, VRS, VRM and complete runtime/source-proof aggregate.
All 4,240 source times and 43,392,160 skin-vertex observations must remain covered.
The runtime compares actual bytes against those independent pins; it never
learns approval from hashes asserted by the supplied receipt.

The loader reads and hashes each VRA/VRS/VRM once, decodes those same bytes, checks
CRC/skeleton/mesh companions, and passes those decoded objects to the renderer.
There is no time-of-check/path-reread substitution. It requires a single
nonlooping 24,321-key clip at `i / (60 * SUBDIVISIONS)` seconds, with
`SUBDIVISIONS = 256` and a 15,360 Hz sample grid. Each timestamp must equal the
exact float32-rounded rational value. The 64-subdivision candidate is rejected,
even with a relabeled receipt. It also requires the exact logical source take,
three named rigid actors, static camera/rig basis and the shared weapon anchor.
All return maps are built before installation. A failed optional payload load
keeps existing authored paths intact and adds an inactive warning. A malformed
manifest still follows the existing manifest parser's explicit-error policy.

The 256-subdivision contract is a replacement-candidate proposal. Actual new
FBX/runtime/session/consumer proof pins remain pending. Increasing sample density
does not change the 95/60 s native gameplay duration, 190 simulation ticks, or the
planned 0.20 s outgoing return. It does not establish native parity by itself.
The failed 64-subdivision candidate remains inactive. A bounded-focus proof of
the replacement 256-subdivision FBX is pending; final conversion and the complete
4,240-time proof are still required. The estimated replacement VRA size is
**73,134,921 bytes**, below the existing 128 MiB decoder cap. That is a sizing
estimate, not a measured converted artifact or approved runtime pin.

No checked-in manifest enables this path. The optional syntax is:

    high_mantle.policy=high_onto_onehand_v6_native
    high_mantle.asset=onehand/asset.vra
    high_mantle.clip=aella_mantle_onehand_r6_camera_reconstructed_v6
    high_mantle.receipt=onehand/receipt.json
    high_mantle.receipt_sha256=<independently approved receipt SHA-256>

The generic `mantle=unavailable` entry remains unchanged. The optional receipt
schema is `rust-duty-high-onto-onehand/v1`; exact required fields are exercised by
the original synthetic `receipt` fixture in `authored_high_mantle.rs`. The receipt
pins source Action/fingerprint, dense FBX/runtime companions, all-grid proof,
native/reference frame ranges, camera/actor basis, weapon anchor and return time.
The reference range is `[7787, 7883)` (inclusive final frame 7882).

## Real-input/native validation plan

Do not use a replay that sets player position, stance, velocity, traversal state,
or completion merely to get a desired shot. Do not make ADS or movement cancel
physics to manufacture interrupt footage.

1. After actual payload admission and app build verification, launch the ordinary
   supported game executable and optional manifest. Keep the executable hash,
   build/source identity, receipt/payload hashes, OS/GPU/driver, resolution and
   refresh rate with the evidence. Repeat on the required Windows path.
2. Use normal keyboard/mouse input from the normal spawn to approach the existing
   1.8 m high-ONTO step and perform forward + fresh Jump. Record uninterrupted
   traversal, frame-96 handoff and return to live movement. Repeat held fire/ADS,
   interrupted uncredited reload and already credited reload using normal inputs.
3. For an actual interrupt, press Escape during an accepted mantle. Existing
   `app.rs` pause/focus transitions call `sim.cancel_mantle`; resume and record the
   smooth outgoing return. Test focus pause through the existing app path. F2 is
   the existing reset input. F9 is the existing debug-death input; label its
   footage debug-death, not combat death. Do not claim death gameplay footage
   from a direct `kill` assignment; the synthetic death test is separate evidence.
4. Exercise low mantle and a ledge-hang pull-up through ordinary gameplay inputs
   and verify they retain their own timing/presentation. Repeat high acceptance
   with release/repress and after reset. Verify a missing/invalid optional pack
   leaves legacy high gameplay and previously loaded authored rendering intact.
5. Observe each accepted fixed step and rendered frame, without mutating either.
   The required trace records committed time, input edges actually delivered by
   the platform, route, binding/receipt identity, generation, high/low/from-hang,
   source seconds/frame/reference frame, outgoing begin/duration/weight,
   position/velocity/grounded, camera eye/direction, ammo/reserve/shots/reload,
   visual ADS/procedural weight, presented weapon anchor, and renderer errors.
   Keep pause/resume/reset events and both simulated and wall-clock timestamps.
   This can be a bounded local JSONL observer attached to the existing recording
   session; it must not drive input or mutate physics.

### Prepared capture routes and remaining evidence gap

The existing F8 gameplay CSV samples approximately every 0.1 seconds and omits
the one-hand source clock, generation and detailed input/pause events. It cannot
prove the final committed sample or the exact interrupt path by itself. Existing
capture-sequence modes generate replay input and do not cover native Escape/F2
events as actual user input. The optional read-only observer now records those
events and every committed step. Separate bounded tools prepare actual platform
Escape/F2/F9 capture and a clearly labelled 60/30 Hz ordinary-Input replay for
rendered endpoint/live-return sampling. See [capture contracts and commands](ONEHAND_HIGH_ONTO_CAPTURE.md).
These routes have source/synthetic tests; neither has executed against an
admitted one-hand candidate. No game, Blender, graphical capture or Windows
validation was run for this integrated revision. Missing native evidence must
not be represented as acceptance.

## Focused verification

See the accompanying integration handoff for exact commands, logs, exit codes,
counts and final file hashes. Tests use small original synthetic fixtures and
prove admission/controller/return contracts, not actual soldier geometry parity.
The frozen prone source and shared PoseReturn implementation are not modified.
