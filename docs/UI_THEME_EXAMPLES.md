# UI theme examples

Two ready-to-use themes for the native UI language described in
[UI_THEME.md](UI_THEME.md). They use only the documented scopes, classes and
properties. `tests/ui_theme_examples_contract.rs` parses both files with the
production `UiTheme::parse` and checks the resolved styles below.

| File | Purpose |
| --- | --- |
| `ui/examples/high-contrast.css` | White text, yellow accents, red warnings, 95%-opaque black panels with 2px borders |
| `ui/examples/large-type.css` | Larger pause-menu and updater text, modestly larger HUD and ammunition-hint text; colors unchanged |

## Selecting a theme

```sh
vector-range --ui-theme=ui/examples/high-contrast.css
vector-range --ui-theme "ui/examples/large-type.css"
```

Copy an example and edit the copy rather than the packaged file. Without
`--ui-theme`, the game uses `ui/theme.css` (see the loading order in
UI_THEME.md), so copying an example over a local `ui/theme.css` also works.

## Editing and reloading

1. Edit the selected file.
2. Press **F7** in the focused game window. F6 is unrelated: it reloads saved
   gameplay settings.
3. The reload is atomic. A valid file replaces the whole theme before the next
   hit test and draw.
4. An invalid file (typo, unsupported property, out-of-range value) logs
   `file:line:column: message` and keeps the **entire last-good theme**. Fix it
   and press F7 again. There is no file watcher.

Things that are rejected rather than ignored: `padding`, `margin`, `width` and
other geometry; pseudo-classes such as `:hover`; functions such as `rgb()`;
percentages; `!important`; comma selector lists; font sizes outside 6–96px;
border widths outside 0–16px; opacity outside 0–1.

## How the examples resolve

Precedence per property: scope + class, then scope alone, then class alone;
later source order breaks ties.

High contrast:

- `.label` is white in every scope. `#hud .muted` is white instead of the
  light grey `.muted` used elsewhere.
- `#ammo-hint .accent` is cyan; other accents are yellow.
- `#updater-panel .warning` is orange; other warnings are red.
- Font sizes and opacity are left native.

Large type:

- Pause menu: labels 26px, buttons 32px. Updater: labels 24px, buttons 28px.
- `#hud { font-size: 20px; }` is a scope-only rule, so it beats `.label`
  (22px) inside the HUD. HUD muted text is 18px at 0.9 opacity.
- The ammunition hint has no scope-only rule: labels take `.label` (22px), the
  key takes `#ammo-hint .accent` (24px).

## Large-font geometry limits

- Pause-menu and updater rows grow with the font and shift later rows; the
  panel is fitted to the window. Long labels are truncated to fit, not wrapped.
- Smaller fonts never shrink the original click targets.
- The HUD has no responsive layout engine. Text stays screen-anchored, so large
  HUD sizes can overlap. The example keeps HUD growth small for that reason.
- The ammunition hint circle and caption spacing grow with the key font.

## Not yet verified

These examples are checked by parser and style-resolution tests only. Native
appearance, legibility at 100% and 200% DPI, window resizing, and the DX12
build have not been exercised with them. Treat visual quality as unclaimed until
someone runs them on a native window.
