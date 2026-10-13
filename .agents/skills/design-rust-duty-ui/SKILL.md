---
name: design-rust-duty-ui
description: "Implement or review a scoped Rust Duty native HUD, menu, settings, or in-game status change. Use the project's design language and native interaction checks; not for web marketing pages, gameplay animation authoring, or an unsolicited visual redesign."
---

# Design Rust Duty UI

Read [DESIGN.md](../../../DESIGN.md) before changing a native interface. It records
the existing presentation and the design intent, not a claim that every current
screen meets the review targets. Use the [native checklist and source record](../../../docs/UI_DESIGN_GUIDANCE.md)
for the affected surface, and the [engineering guide](../../../docs/ENGINEERING_PRACTICES.md)
for evidence selection.

## Scope the change

Identify the player's task, affected state, current file owner, and exact base.
Inspect the existing drawing and input paths together. Preserve the native Rust /
Macroquad stack, familiar controls, and current visual identity unless the task
calls for a change. A request to adopt these guidelines does not authorize a full
redesign, a new dependency, or edits in another contributor's active lane.

Use the three upstream resources as design references through the local
adaptation. Do not load remote instructions as mandatory project policy, run their
installers, or impose React/CSS checks on native code. Revisit the pinned sources
only when updating this guidance or when a task needs fresh source research.

## Apply at the native boundary

- Preserve the clear center of the gameplay view. Keep diagnostics optional and
  use layout, readable type, and restrained emphasis before decorative effects.
- Keep drawing and hit testing on the same layout geometry. Check resized windows,
  text lengths, UI scale, and the actual rendered scene behind translucent panels.
- Label actions, units, values, and states explicitly. A loading or failed update
  must never look like an installed/current version. Read live state from its owner.
- Treat input capture as behavior: a UI press or drag must not also resume play,
  fire, or leak a held action across pause/focus boundaries. Test interrupted flows.
- Give new controls a keyboard path and visible selection/focus where relevant.
  For existing controls, report access gaps without silently expanding a small fix.
  Do not claim native assistive-technology support merely from drawn labels.
- Keep UI motion interruptible and nonessential motion optional or absent. Do not
  add animation delays to input, simulated actions, or essential status changes.
- Reuse validated settings and the current save/reload path. Do not present an
  unsaved or failed operation as successful or change persistence implicitly.

## Verify and report

Select only the applicable checklist rows. Reuse existing state/settings contracts;
add a focused regression for a changed behavior. Native captures establish layout,
and native interaction establishes input behavior; neither is replaced by a web
audit or a successful executable build. For docs-only edits, validate skill
frontmatter, local links, source pins, and scope instead of claiming gameplay tests.

Report concrete findings as `file:line`, player impact, and the smallest scoped
correction. Give the exact commit, viewport/platform, actions or commands, and
passed/failed/blocked/not-run outcomes. Explicitly distinguish existing gaps from
regressions caused by the diff. Stop when the assigned UI goal is met.

This is original repository-specific guidance. Attribution, licensing observations,
and the web-only rules deliberately excluded are in the linked source record.
