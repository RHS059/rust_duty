# Rust Duty native UI

The interface is a movement and gunplay laboratory: quick to read, precise about
state, and visually secondary to the scene. Preserve the existing VECTOR / RANGE
presentation unless a task explicitly changes it. This document adopts design
guidance for development; it does not announce a runtime redesign or accessibility
certification.

For implementation/review, use the [native UI skill](.agents/skills/design-rust-duty-ui/SKILL.md)
and [native checklist / source record](docs/UI_DESIGN_GUIDANCE.md). Engineering and
evidence boundaries remain in [the engineering guide](docs/ENGINEERING_PRACTICES.md).

## Existing language, observed in source

Observed at [`70372028`](https://github.com/RHS059/rust_duty/tree/70372028c6ae9fb0c990f2c9a22ca603a1a2bff3),
2026-10-04. Recheck the actual branch before implementation. Values below document
the current game, not a new theme implementation or an approved replacement palette.

| Role | Current source value | Use |
| --- | --- | --- |
| Menu surface | `(0.035, 0.057, 0.074, 0.97)` | Cool, dark pause-menu backing |
| Emphasis | `ACCENT = (0.98, 0.62, 0.22, 1.0)` | Amber emphasis and selected gameplay feedback |
| Information | `CYAN = (0.33, 0.84, 0.87, 1.0)` | Values, labels, and informational status |
| Secondary text | `MUTED = (0.62, 0.69, 0.72, 1.0)` | Supporting labels |
| HUD panel | `(0.025, 0.042, 0.058, 0.88)` | Scene-readable dark backing |
| Main text | Macroquad `WHITE` | Primary labels and numbers |

These are normalized RGBA values from [src/main.rs](src/main.rs). The update panel
has its own nearby colors in [src/game_update.rs](src/game_update.rs); do not silently
unify an independently owned surface. Amber and cyan have distinct useful roles.
An upstream marketing rule favoring one accent is not a reason to remove either.

The existing interface uses Macroquad's default text drawing, rectangular panels,
thin accent bars, and padded numeric strings. Keep that family coherent; padding
alone does not guarantee tabular glyph widths.
Font replacement requires a real need, readable native rendering, and verified
distribution rights. A brand analysis does not license that brand's proprietary font.

## Layout and hierarchy

- Protect the crosshair/aim area; reserve the center for aiming and essential
  interaction feedback. Anchor routine HUD information to predictable edge regions.
- Keep primary actions, current values, and units legible before secondary help.
  Telemetry is diagnostic content; keep its existing optional role.
- Derive panel, label, and hit bounds from the same geometry. Measure actual text.
  New or changed UI must remain reachable at its declared minimum window size;
  use wrapping, scrolling, or a scoped layout adaptation rather than clipping.
- Check dense and long content, resize/fullscreen transitions, and available DPI
  scaling. An old pixel constant is an observed baseline, not a universal size rule.
- Evaluate translucent surfaces against light and dark game backgrounds. Preserve
  enough contrast with backing/outline where needed; color alone must not carry
  an essential distinction. Measure contrast before claiming a numerical pass.

## Components and state

- HUD values reflect simulation state. UI code does not become a second owner of
  ammunition, reload milestones, timing, or movement.
- Settings show a meaningful label, value, unit, range, and current interaction
  state. A new drag control needs a non-drag path. Preserve the selected settings
  file and current save/reload semantics; show persistence outcomes honestly.
- Menus expose a clear route back. Keep pointer capture and press-edge handling
  consistent across pause, resume, reset, focus shortcuts, and blocked startup.
  Clicking a setting or updater control must not also resume or fire.
- Update and asset statuses distinguish working, unavailable, cancelled, ready,
  and confirmed success. Preserve the current offline recovery choice. Use specific
  action labels and a useful next step on errors; never fabricate progress.
- Prefer stable readable text and brief feedback. No decorative camera movement,
  looping HUD flourishes, forced font changes, or marketing-page asymmetry. New
  nonessential UI motion should have a reduced/static option and remain interruptible.

## Ownership and review

Start with [src/main.rs](src/main.rs) for HUD/menu drawing and input routing,
[src/settings.rs](src/settings.rs) for setting validation/persistence,
[src/session.rs](src/session.rs) and [src/control.rs](src/control.rs) for safe input
transitions, and [src/game_update.rs](src/game_update.rs) for in-game update status.
Coordinate with the current owner before touching updater, runtime integration,
or release work. This design guide grants no additional publication permissions.

Keyboard paths, platform accessibility APIs, controller input, layout scaling,
and native platform coverage must be reported from actual implementation and
tests. Their inclusion as review targets here does not establish that the current
prototype already supports them. Preserve existing controls and add missing
capabilities only within the assigned work.
