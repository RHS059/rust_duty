# Original ammunition supply interaction

This feature is newly authored for Vector Range. It contains no game-derived source, UI assets, or third-party model data. The crate model is a separate authored asset; these modules only define its interaction and hint.

## Behavior

- The crate is behind the initial player, beside the rear wall. The player spawns at `(0, 0, 9)`, looking toward negative Z. The wall is centered at `z = 14`, is 0.5 m thick, and its inward face is `z = 13.75`.
- The default footprint center is `SUPPLY_FLOOR_CENTER`, `(0, 0, 13.45)`. Its configurable half-extents are `(0.4, 0.25, 0.25)` for an 0.80 × 0.50 × 0.50 m crate. The bounding box center is 0.25 m above the floor; its rear face is `z = 13.70`, leaving a 5 cm gap to the wall.
- All interaction gates must pass: active play, a crosshair ray hitting the actual crate bounds within 2.25 m, no closer solid block/ramp/live target, and an unobscured world-anchored hint projected within the camera frustum. There is no permissive aim cone. Range is measured from the camera to the ray's first crate-surface hit.
- The hint is positioned 0.18 m above the lid, using world-to-screen projection. It moves with the camera and is never clamped to the screen edge. Hidden/off-screen/behind-camera hints are suppressed.
- Holding F continuously for 1.5 simulation seconds fills the current magazine to `MAGAZINE` (30) and reserve to the configured capacity (90 by default). It assigns the caps, rather than adding rounds. A pending reload is canceled safely at completion. There is no healing, health-field access, movement effect, or stat award.
- Release, look-away, lost range, obstructed view, pause, and reset discard all partial progress. This includes frames with no fixed simulation tick. A completed hold is latched until release or loss of a gate, so keeping F down while shooting does not automatically begin another refill.
- Full magazine and reserve display `AMMO FULL` instead of beginning an unnecessary hold. If either needs ammunition, the ordinary hold is available.
- The circle is shown only while holding with positive progress; an eligible idle hint is plain F and text. The hold graphic is a black circular backplate with exactly 0.25 alpha. A solid gold sector grows clockwise from 12 o'clock. The F key and instruction remain visible over it. Cancellation and completion immediately remove the circle.

## Integration

The feature deliberately leaves `main.rs`, `lib.rs`, `sim.rs`, Cargo, and settings unchanged for the integrating owner.

1. Export `ammo_supply` and `ammo_supply_view` from the library, then construct an `AmmoSupply` beside the `Simulation`.
2. Draw the model at `supply.floor_center`, with its front facing negative Z. Match `supply.half_extents` to the authored mesh. To make it physically solid, insert a `Block` with `supply.bounds()` into `sim.blocks` both at creation and after a range reset. Its own exact collider is excluded from hint-anchor occlusion; nearer independent colliders still block interaction. Avoid drawing the physical collider as an extra visible cube if the model is already rendered.
3. Build a `SupplyView::perspective(player.eye(), player.direction(), vertical_fov_radians, viewport)` using the same interpolated ADS FOV and screen dimensions as the world camera. Its perspective projection matches the current camera's 0.035 m near and 200 m far clip planes. Alternatively populate `SupplyView` directly from an existing world camera matrix. The matrix must be the world camera's, not the weapon render-target camera's.
4. After **each** fixed `sim.update`, rebuild the view and call `supply.focus(&sim, view, active)`, then `supply.tick(&mut sim.player, focus, held_f, active, FIXED_DT)`. Recompute eligibility after movement so the final hold step cannot complete after leaving range. `SupplyEvent::Refilled` is emitted exactly once when ammunition is credited; use it for a brief completion notice if desired.
5. Also recompute focus at render cadence. When `!active || !held_f || focus.is_none()`, immediately call `supply.cancel()`, even if the fixed clock advances zero ticks. This is what makes release/look-away/pause cancellation immediate. Never count paused time or raw wall-clock/render time toward the hold. Cancel before processing resume/teleport/reset transitions.
6. After weapon/HUD rendering has switched to the default 2D camera, call `draw_ammo_supply_hint(focus, supply.progress(), supply.ammo_full(&sim.player))` only when focus is `Some`. The renderer receives already-projected screen coordinates; it does not perform eligibility or mutate ammunition.
7. On reset call `supply.reset()` and reinstall the collider into the new world.

Example fixed-step call:

```rust
let view = SupplyView::perspective(
    sim.player.eye(),
    sim.player.direction(),
    h_fov_to_v(current_horizontal_fov, viewport.x / viewport.y),
    viewport,
);
let focus = view.and_then(|view| supply.focus(&sim, view, active));
let event = supply.tick(&mut sim.player, focus, held_f, active, FIXED_DT);
```

`SupplyConfig` exposes `hold_seconds`, `range`, and `reserve_capacity`. Its default is 1.5 s / 2.25 m / 90 rounds. Non-finite or non-positive duration/range values use safe defaults. A zero reserve capacity is supported. If these are added to the settings file, preserve this default and reset any active hold when changing configuration.

## Time contract

Elapsed time is accumulated in f64 from accepted finite f32 simulation steps. Time partitions at 30, 60, 100, and 120 Hz agree within a 0.1 μs completion tolerance. Zero dt does not advance time. Negative, non-finite, or greater-than-0.1-second dt cancels the hold rather than granting a refill after a stall. Integration should use the game's fixed step, not split a paused wall-clock interval into synthetic hold steps.

## Verification

Run:

```sh
cargo test --test ammo_supply_contract --no-default-features
```

The test uses path inclusion so it can run before library exports/main integration. Twenty headless contracts cover placement, exact range, strict crosshair targeting, active/pause gates, blocks/ramps/targets, anchor occlusion, projection and moving screen anchoring, invalid geometry, completion timing, full ammo, capacity assignment, reload cleanup, cancellation/reset, repeat-hold latching, time partitions, invalid timesteps, hold-only circle visibility, and gold clockwise sector geometry with 25%-opacity black background.

These deterministic contracts do not substitute for a final in-game visual check: look back from spawn, walk up, aim at/away from the crate, release and repress F partway, step away mid-hold, pause mid-hold, finish with depleted ammunition, retry with full ammunition, and verify the label remains attached to the crate under camera motion.

The current native integration uses an original geometric test fixture while the reference crate images are unavailable. It is explicitly not the completed reference model. `--capture-supply` is a deterministic screenshot mode showing a half-filled circle; it freezes movement and substitutes presentation progress only. Headless interaction tests exercise the real hold/cancel/refill logic independently.
