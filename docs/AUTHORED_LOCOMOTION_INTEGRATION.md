# Authored locomotion ownership adapter

Status: a tested integration API and renderer pose contract. The production
`main.rs`, reload/ADS owner, default asset selection and release remain unchanged.
This is not complete live gameplay integration and contains no native game capture.
Aella owns those integration points; its current adapter must be reconciled before
promotion. The verified published runtime base remains `9c7d1ce8`.

## Components

- `AuthoredLocomotionPath` follows the evaluated Blender entry, loop and
  phase-specific exits. It retraces authored paths on sprint reversals
- `AuthoredLocomotionAdapter` receives committed gameplay state and yields
  exclusive presentation ownership for reload, ADS, mantle, firing or another
  higher-priority action
- `AuthoredViewmodel::draw_pose` renders a complete pose with the same validated
  skin and rigid companions. It performs no IK or independent hand choreography

All adapter updates must use the same immutable `AnimationSet` used at creation.
Its supplied pack, clips and rates must not be replaced during playback. Binding
validation protects skin/rigid compatibility; it is not a content hash of every
animation key. A different animation pack needs a newly constructed controller.

## Fixed-tick boundary

The game accepts action requests at the incoming `Simulation::update` timestamp,
then increments `simulation.time` at the end. Capture that initial timestamp and
pass the resulting committed simulation:

```rust
let step_start = sim.time;
sim.update(input, &cfg, FIXED_DT);
let new_owner = locomotion.committed_step(animation, step_start, &sim)?;
```

`committed_step` first advances the old locomotion intent to `step_start`. If a
higher-priority action has begun, it emits that exact complete incoming pose,
without waiting for exit or settle. Otherwise it accepts the new sprint state and
advances through the committed interval. Passing only the post-step timestamp
would make the action handoff one 120 Hz tick late. Direct deterministic schedules
can use `committed_tick` at exact event timestamps instead.

Repeated render reads and same-time ticks do not advance motion. Pauses retain the
simulation timestamp. A clock rewind is rejected; an actual world reset must call
`reset` explicitly. Reset invalidates older handoff IDs.

## Receiving owner

On a new handoff:

1. Validate the receiver's animation with `handoff.validate_receiver`. It checks
   both companion CRCs, ordered joint names/parents, ordered actor names/mesh
   indices and complete inverse-rest transforms. These are compatibility checks,
   not cryptographic authentication
2. Initialize the new owner's complete output from `handoff.pose` at its recorded
   event time. This includes every bone local, rigid actor global and visibility
3. Evaluate that owner at the current committed simulation time. Gameplay has
   already started; do not hold reload/ADS/fire eligibility for the animation
4. While the handoff is outstanding, `locomotion.pose()` is `None`. Only the
   receiving owner supplies the renderer. New ticks never restart or replace it

The receiver may handle subsequent priority actions internally, including
reload→ADS or reload cancellation. Their rendered motion is not implemented by
this adapter. The original event receipt stays stable until explicit return or
world reset. A wrong-binding receiver must not substitute the legacy renderer.

## Returning ownership

The outgoing owner must animate a measured return to the exact authored ready
pose. Once it has displayed that endpoint, call:

```rust
locomotion.return_ready(animation, receipt.id(), sim.time, &displayed_pose)?;
```

This accepts only the last committed time, the current handoff ID, no remaining
simulation priority signal, and exact complete ready transforms and visibility.
Quaternion sign and sample-time metadata may differ without changing the display.
A different pose is rejected atomically; no unchecked crossfade or automatic snap
is supplied. If sprint is currently wanted, entry begins from that same ready
pose at zero progress. This strict endpoint API does not establish that the
receiver has actually authored or visually validated the return motion.

## Verification

The nine synthetic contracts cover all action reasons, rest/entry/loop event
poses, pause/read behavior, wrong bindings and companion checksums, changed
visibility and rigid/bone transforms, invalid clocks, stale callbacks, explicit
reset, and actual Simulation reload/ADS timing. A 500-tick side-by-side simulation
confirms unchanged ammo, credit/ready deadlines, reload progress and firing.

The actual 44-clip private pack audit executes 246 handoffs over normal, stopping
and repeatedly reversing histories, with reload and ADS at many phases. All
18,204 skin-palette/rigid matrix comparisons are exact, and 118,326 authoritative
simulation ticks match the untouched baseline. The 246 ready returns test only
the endpoint contract, not missing action/return motion. No native render, contact
clearance during reload/ADS, or visual acceptance is established by this check.

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo run --locked --no-default-features --example audit_authored_locomotion_adapter -- /private/locomotion/asset.vra
```

The frozen controller and asset checkpoint remains unmodified. This adapter is a
follow-on patch applied after source commit `a5940fd9da76259306bf18930bdddc421506147d`.
