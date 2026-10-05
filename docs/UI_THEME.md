# Native UI themes

Rust Duty reads a small, bounded CSS-inspired language into typed native UI
styles. This is **not** browser CSS, a DOM, a WebView, or a web dependency.
`cssparser = 0.38.0` tokenizes identifiers and values; Rust validates structure
and semantics. No network requests, imports, scripts, images, or external fonts
are supported. Native HUD, pause-menu, updater-panel and ammunition-hint drawing
uses the backend-neutral `draw::facade` on both rendering paths.

## Loading and reloading

`ui/theme.css` contains only comments by default, retaining native colors,
font sizes and layout coordinates. It and this guide are packaged resources.
Use `--ui-theme=path/to/theme.css` or `--ui-theme "path with spaces.css"` for an
explicit file. Without that option, the app first uses `ui/theme.css` beside the
stable running executable when present, then the authenticated managed package's
shipped `ui/theme.css`, then the working-directory path. This keeps an existing
local customization preferred across managed updates.

Edit a local/stable-executable theme or use an explicit external file. Do not edit
the authenticated immutable managed-package copy; use it as the shipped default
and copy it out before customizing.

Press **F7** in a focused game window to reload the selected file. This is
separate from F6, which still discards/reloads saved gameplay settings. F7 works
while the startup updater is visible. Reload happens before both hit testing and
drawing, so one frame never mixes old control bounds with a new theme. A
focus-loss or focus-return edge cannot accidentally trigger a reload.

A missing default file leaves the native defaults in place and still remembers
the path, so creating the file and pressing F7 works. An explicitly requested
missing file, malformed file, or unsupported feature reports `file:line:column`
in the log and existing notice HUD when visible. A failed reload retains the
**entire last-good theme**. There is no file watcher. Fix the file and press F7
again. Line and column are one-based Unicode-character locations; LF, CRLF, CR
and form-feed line endings are recognized. File I/O and invalid UTF-8 errors use
`1:1`.

## Stable selectors

Scopes: `#hud`, `#pause-menu`, `#updater-panel`, `#ammo-hint`.
Classes: `.panel`, `.label`, `.muted`, `.accent`, `.warning`, `.button`, `.slider`.

A selector is one scope, one class, or a scope followed by one class. Both
`#hud.label` and `#hud .label` select native elements tagged with that scope and
class; whitespace is a readability convenience, not a DOM descendant query.
Class-only rules apply in every scope. There is no inherited style tree.

```css
#hud .muted { color: #c2d0d8; }
#pause-menu .panel {
  background-color: #18212bee;
  border-color: #697887;
  border-width: 1px;
}
#pause-menu .button { font-size: 24px; }
#updater-panel .warning { color: #ffbe67; }
#ammo-hint .accent { color: #a5e0bc; }
```

Each property cascades separately: scope + class beats scope alone, which beats
class alone. Later source order breaks equal-specificity ties. Later duplicate
properties within a rule win. An element can carry several classes, such as
label + button + accent; their array order never changes precedence. Empty rules
and empty files are valid.

## Supported declarations

| Property | Accepted values | Native use |
| --- | --- | --- |
| `color` | `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`, or `transparent` | Text and foreground marks |
| `background-color` | Same colors | Panels, buttons and slider/progress tracks |
| `border-color` | Same colors | Panel, button and track borders |
| `font-size` | Decimal `px`, 6 through 96 inclusive | Text measurement, drawing and interactive row flow |
| `border-width` | Decimal `px`, 0 through 16 inclusive | Borders painted inside existing outer bounds |
| `opacity` | Decimal number, 0 through 1 inclusive | Multiplies native or overridden alpha |

Names and units are lowercase; hex digits may be uppercase. Numbers cannot
contain signs, exponents, NaN, or infinity. Fractional values such as `.5` are
supported. Semicolons separate declarations; the final semicolon is optional.
Block comments are supported between tokens. Comments inside a value cannot
join separate tokens into one value. Unterminated comments and blocks fail.

Unsupported properties, selectors (including comma lists, pseudo-classes,
multiple classes, child/sibling combinators, and escaped identifiers), functions
(including `rgb`, `calc`, `var`, and `url`), at-rules (including `@import`), CSS-wide
keywords, `!important`, percentages, and other units fail explicitly. A typo
rejects the entire replacement instead of producing a partial theme.

Files are limited to 65,536 bytes, 128 rules, and 1,024 declarations total.
File reads stop at the byte limit plus one; parsing does not fetch dependencies
or allocate recursively for nested CSS blocks.

## Native layout and interaction

- The pause menu and updater resolve typography before layout. A larger font
  grows its native row and shifts later rows. The panel is fitted to the window;
  the same transform is used for painting, keyboard-focus decoration, pointer
  hitboxes and slider endpoint normalization. Smaller fonts do not shrink the
  original control targets. Long themed control labels are fitted by truncating
  a Unicode-safe prefix using the exact rendered font metrics
- Borders are drawn inward and clamped to each shape, so they do not create a
  decorative extension outside a clickable box. No theme can add controls or
  change a button's action
- HUD text remains screen-anchored; centered notices use the resolved font for
  measurement and expand their backing panel. Large font overrides are allowed,
  but the HUD has no general-purpose responsive layout engine: use targeted
  selectors and inspect the resulting density
- The ammunition hint stays anchored to the projected crate. Its key circle and
  caption spacing grow with the key font. Cancellation and full-ammo states
  still suppress the hold circle; styling cannot change interaction progress
- `.muted`, `.accent` and `.warning` identify existing semantic roles. Pause-save
  failures and updater errors can be styled as warnings without changing their
  text or recovery action. `.slider` covers pause controls and updater progress
  tracks. Font properties apply only to text; box properties do not draw a
  rectangle behind every label

Geometry properties such as padding, margin, width and height are intentionally
outside this language. Input, layout ownership, settings persistence, focus
handling and update actions remain in the existing native controllers.

## API and verification boundary

`UiTheme::parse(source_name, text)`, `reload_str` and bounded `reload_file` produce
or atomically replace a typed snapshot. `theme.style(scope, classes)` resolves
optional properties, leaving absent values at their original native defaults.
The event-loop thread calls `load_theme(path)` / `reload_theme()`; draw sites read
that thread-local snapshot through `ui_theme::style`. `UiStyle` shares exact
fractional text metrics between measurement and drawing. Text is CPU-available
without a GPU, browser, or Macroquad context.

Automated coverage includes unsupported syntax, source locations, limits,
selector precedence, failed-first-load retry, last-good retention, native draw
commands, original layout coordinates, painted/control-bound consistency,
slider drag/release ownership, HUD styles and ammunition hint centering and
visibility. Existing updater/session and settings tests remain in place.

These tests do **not** certify native GPU text appearance, 100%/200% DPI
legibility, real pointer/window focus behavior, network update delivery, or a
Windows DX12 playtest. Those remain native/human validation gates. Before visual
sign-off, exercise F7 with valid and invalid files, resized windows, menu
keyboard/pointer controls, dragging outside a slider, focus interruption,
updater retry/cancel/current-version actions, and ammunition hold cancellation.
