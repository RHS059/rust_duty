---
name: review-rust-duty-change
description: "Choose and review evidence for a scoped Rust Duty gameplay, asset, or presentation change. Use when planning regression coverage or reviewing a diff; preserve the existing native pipeline and distinguish parser, source, renderer, and gameplay proof."
---

# Review a Rust Duty change

Scope the diff to an exact base/head and check current file ownership before
editing. Keep another contributor's active runtime, asset, or publisher work
separate. This skill is review guidance, not permission to publish, merge,
release, change access, or run downloaded tools.

Use [the project engineering guide](../../../docs/ENGINEERING_PRACTICES.md)
to choose evidence and find existing contracts. Read only the format or feature
documentation affected by the change. Inspect any external instructions/scripts
as source material; do not install a generic enterprise bundle or run its scripts.

## Project-specific review

- Keep gameplay decisions in the simulation and committed input/tick path.
  Render sampling, asset selection, and animation must not become a second owner
  of ammo, reload milestones, shot timing, or simulation time.
- Inspect imports and calls, not words alone. Macroquad math types in pure logic
  are different from render/input calls; `session` is a legitimate project module.
- Exercise the real public parser, resolver, sampler, or check. Reuse the existing
  contract suite before adding a parallel implementation or a duplicate monitor.
- For malformed assets, repair unrelated framing/checksum fields when necessary
  so a negative fixture reaches the intended validation. Include a valid control.
- Established Blender animation revisions follow the agreed Eevee preview to
  Elara, then stable export/integration/commit workflow. Do not add a redundant
  per-revision source-to-game visual or parity review. Keep existing automated
  parser/sampler and CI checks. New native-presentation or parity investigation
  applies when the exporter, rig contract, or runtime integration changes, or a
  concrete defect warrants it; keep that evidence distinct from artistic approval.
- Treat local assets/settings and the GitHub updater as distinct boundaries.
  Gameplay being offline does not mean the application has no network activity;
  consult the current updater docs for that boundary.
- If reviewing a custom gate, require evidence it inspected its intended inputs
  and detects a real violation. Explicitly report a skip or unavailable fixture.
  Do not neutralize a check in an active shared checkout.

Report only concrete findings: affected owner, consequence, smallest scoped fix,
and evidence. An empty finding list is valid. For a meaningful design trade-off,
add a short decision note with status and consequences rather than a new framework.

Finish with the exact tested commit/configuration, executed commands or native
steps, and passed/failed/blocked/not-run outcomes. Do not reuse a historical test
count as a current run or call a CI executable build a native gameplay pass.

This is original repository-local guidance. The linked guide records the pinned
Tech Fleet sources and why their scripts were not adopted.
