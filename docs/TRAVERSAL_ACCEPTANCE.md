# Traversal acceptance checklist

Scope: [traversal and weapon-action systems](TRAVERSAL.md). Branch
`claude/quirky-hawking-zi94td`. Legend:

- **Gameplay**: implemented and covered by deterministic contract tests.
- **Placeholder visual**: a labeled placeholder renders (HUD `[PLACEHOLDER ANIM]`).
- **Animation integration**: authored clips bound and passed first-person visual review.

No feature is animation-complete. Authored clips are owned by Aella/Hal. Until
they are bound in `assets/animations.cfg` and reviewed in the first-person view,
every row below stays **not complete** in the last column.

| Feature | Gameplay | Placeholder visual | Animation integration |
| --- | --- | --- | --- |
| Tactical sprint | Working | Muzzle-raise layer, HUD state | Not complete: no clips |
| Slide | Working | Roll layer, low eye, HUD state | Not complete: no clips |
| Dolphin dive | Working | Roll layer, eye, HUD state | Not complete: no clips |
| Weapon mount | Working | Small drop layer, HUD hint | Not complete: no clips |
| Ledge catch/hang | Working | Rifle lowered out of view, HUD hint | Not complete: no clips; no hand meshes on ledge yet |
| Hanging sidearm | Interface working; **no sidearm in the default loadout** (fails safely) | None: no pistol model | Not complete: no pistol asset or clips |
| Pull-up / drop | Working | Rifle lowered, eye easing | Not complete: no clips |
| Wall obstruction | Working | Retract/lower layer, "WEAPON BLOCKED" | Not complete: retract pose not authored |
| Look sway | Working layer (frame-rate and sensitivity independent) | Live on the viewmodel | **Not reference-matched**: tuning provisional, comparison tool ready |
| First-person legs/body | Working state (pose, yaw, foot lock, slopes) | Box legs | Not complete: no body mesh |
| Death/respawn | Working (`damage_player`, out-of-world, F9 debug) | Red overlay | n/a |
| Lean (Q/E toggle) | Working: head-only offset clamped by walls, camera roll, shots from the leaned eye (`tests/lean_cant_contract.rs`) | Camera roll; no body lean pose | Not complete: no lean clips |
| Hip cant (Left Ctrl+X) | Working: eased toggle, suppressed by ADS; Ctrl alone crouches on release | Weapon actor rotates about the bore, arms follow | Not complete: needs first-person review on the authored rig |
| Physical lighting (opt-in) | n/a (presentation) | `physical_lighting = 1`: sun, cascaded shadows, sky, SSAO, fog, ACES, bloom ([lighting](LIGHTING.md)) | Not reviewed: only software-rendered under Xvfb; no real-GPU or Windows run |

## Requirement evidence

| Requirement | Status | Evidence |
| --- | --- | --- |
| State diagram/table, inputs/tuning, slots, contacts, events per feature | Done | [TRAVERSAL.md](TRAVERSAL.md) |
| Entry, rejected entry, sustained, normal exit, interruption tests | Passed | `tests/traversal_movement_contract.rs`, `tests/ledge_hang_contract.rs`, `tests/weapon_action_contract.rs` |
| Conflicts: ADS, fire, reload, weapon switching (sidearm draw/stow), falling, lost support, death/respawn | Passed | Permission table test; sidearm interruption tests; `death_and_reset_clear_every_action` |
| Geometry: walls, corners, slopes, low ceilings, ledge edges, changing clearance | Passed | Slide/dive wall and ledge tests; hang thin top, ceiling over lip, lost support; mount overhang, steep ramp, moved support; obstruction off-center post |
| Frame-rate tests incl. low rates | Passed | Tick-identical traces at 15/30/60/144/240 fps (slide, dive, hang, pull-up); sway and body yaw frame-partition tests |
| Regression of existing movement and weapon behavior | Passed | Full existing suite unchanged and green (mantle, toggle controls, weapon, ammo, authored animation contracts) |
| Windows build | **Pending** | CI builds Windows for pull requests and pushes to `main`/`aella/**`/`halcyon/**`; this branch needs a PR to produce `vector-range-windows-x64`. An executable build is not a Windows gameplay test |
| Native run | Partial | Linux debug build ran the four `gameplay-*` capture replays under Xvfb. This checkout has no materialized authored assets, so the procedural fallback weapon rendered. Not an interactive playtest |
| First-person before/after captures with final clips | **Not done** | Requires authored clips. Rerun `--capture-sequence=gameplay-slide|hang|obstruct|sway` at identical timing after binding |
| Sway matched to reference footage | **Not done** | `tools/reference_compare.sh` produces fixed-timestamp side-by-side frames; no score is computed. Visual review pending |

## Commands run for this record

Linux container, Rust 1.97.0 stable:

| Command | Outcome |
| --- | --- |
| `cargo fmt --all -- --check` | Passed |
| `cargo clippy --locked --all-targets -- -D warnings` | Passed |
| `cargo clippy --locked --no-default-features --all-targets -- -D warnings` | Passed |
| `cargo test --locked --no-default-features` | Passed: 566 tests, 0 failed |
| `cargo test --locked` (audio) | **Blocked here**: the container has no ALSA `libasound` to link. CI installs it |
| `xvfb-run vector-range --no-update --reference-viewport --capture-sequence=gameplay-<slide/hang/obstruct/sway>` | Ran; frames and telemetry inspected. Procedural fallback weapon |

`src/ammo_supply.rs` received a behavior-preserving lint fix (one line). Current
stable clippy rejected the old comparison, which would have failed the CI build
job.

## Known limitations

- There is no ledge shimmy, no hang from slide or dive, no airborne mount, no
  side-of-wall mount, and no sprint jump that keeps tactical sprint. Each is
  rejected deliberately and documented.
- Ramps have no base offset, so a gentle ramp can never reach the mount height
  band. The mount angle rule is exercised by rejecting a steep wedge.
- Dive headroom validation only matters for overhangs ahead. A ceiling a
  standing player fits under always fits the dive arc.
- Placeholder legs are boxes. Turn-in-place re-plants both feet together.
