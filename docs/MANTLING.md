# Authored mantling

This is an original, provisional movement feature for the primitive collision
range. Its limits and timing are authored here; they are **not verified MW2
values or a claim of retail parity**. Both weapon profiles use the same traversal.

## Controls and eligibility

While standing and grounded, face a nearby block and make a **fresh Space press
with forward movement intent**. Diagonal forward movement is accepted; movement
must have a normalized forward component of at least 0.5. Detection follows
horizontal view direction, independent of camera pitch or recoil. Strafe does
not extend reach. The existing 0.5-second jump cooldown still applies.

| Parameter | Authored value |
| --- | --- |
| Minimum ledge rise above current feet | 0.50 m, inclusive |
| Low mantle | 0.50–1.20 m, inclusive; 0.60 s / 72 fixed ticks |
| High mantle | Above 1.20 m through 1.85 m, inclusive; 0.85 s / 102 fixed ticks |
| Forward reach beyond the player footprint | 0.65 m |
| Maximum forward feet travel | 1.85 m |
| Player collision radius / standing height | 0.381 m / 1.778 m |
| Landing footprint inset beyond player radius | 0.03 m |
| Clearance above the ledge during translation | 0.035 m |

The destination must fit the entire standing footprint on one actual block top,
with the full standing body volume clear. Consequently, a single supporting
block must be wider and deeper than 0.822 m. Thin rails, a narrow corner, low
ceilings that only permit crouching, and empty space beyond a ledge do not qualify.

If no eligible traversal exists, the original normal-jump behavior runs. Jump
from crouch/prone retains its existing stand-up and clearance behavior; it does
not silently force the player upright or trigger a mantle. A held jump cannot
start another mantle or jump. Presses made during traversal are consumed, not
queued. Release and press again after landing to request another action.

## Collision and trajectory

Physics advances at the existing fixed 120 Hz through `Simulation::update`;
render delta never advances mantle progress. The trajectory has three authored,
smoothstep-eased legs: rise in place (55% of duration), move forward above the
ledge (35%), and settle onto its top (10%). The next simulation pose is swept
against every collider. A timestep crossing a phase boundary is split at that
boundary before testing, so a diagonal chord cannot cut through the ledge.

Before starting, all three complete legs and the standing landing volume are
checked. Block sweeps are exact segment tests through the box's Minkowski
expansion by the standing player. Solid ramp wedges also obstruct the full
player volume through their expanded convex planes, including their top cap;
they are not replaced with an over-large bounding box. Touching a support face
is allowed; entering its interior is not. No collider, including the climbed
ledge itself, is ignored. Thin intermediate walls and overhead obstructions
cannot be skipped between sampled poses.

Only static axis-aligned block tops are mantle candidates. Ramps remain normal
walk/slide geometry and can obstruct mantles. There are no airborne ledge grabs,
hanging states, moving-platform traversal, crouched mantles, vaults, skeletal
hand-placement matching, or arbitrary-mesh ledges. Live support removal, a newly
blocked landing, or a newly blocked path cancels traversal at the last verified
pose. Arbitrary geometry insertion already overlapping the player is outside
the static collision map contract; this is not a dynamic-world depenetration
system.

## Movement, weapon, and cancellation behavior

During traversal, normal acceleration, gravity, jumping, stance changes, and
sprinting are suspended. The player remains standing. Sprint stamina can
recover normally; look input may continue without redirecting the committed
trajectory. The visible eye follows the existing player-position/camera path.

Fire and new reload requests are blocked through the final traversal tick;
ADS eases out. Starting a mantle cancels either type of in-progress reload:
rounds already credited at that timestamp remain, and uncredited rounds are
never granted. Held fire/ADS may resume on the next normal tick. A reload held
through traversal is not queued; it requires release and another press. Normal
weapon behavior and timing outside traversal are unchanged.

`Player::mantle: Option<MantleState>` is the presentation hook. A state exposes
`kind` (`Low`/`High`), `start`, `landing`, `progress()`, and `duration()`.
`Simulation::cancel_mantle()` is an idempotent interruption hook for pause and
focus loss. It retains the last collision-checked position, clears traversal and
velocity, and leaves jump-held history intact. Supported players remain on the
surface; unsupported players fall under ordinary physics when stepping resumes.
It never teleports back through a wall. Calling it outside a mantle leaves
ordinary movement unchanged. `Simulation::reset()` discards the entire mantle
state with the rest of the player. There is no new death system.

## Verification

`tests/mantle_contract.rs` covers low/high and exact height limits, full standing
landing support/clearance, overheads and thin intermediate walls, diagonal input
and view, reach and view direction, ramp obstruction, normal-jump fallback,
stance and jump cooldown preservation, no held/requeued triggers, weapon/reload
exclusion, interruption/reset, and changes to support/path/landing geometry.

It also checks every fixed pose and sampled render interpolants for ledge
penetration, and compares the entire authoritative tick trace under
30/60/144/240 FPS render partitions. These are deterministic simulation tests,
not a substitute for subjective traversal/animation playtesting.
