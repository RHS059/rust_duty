# Native UI design guidance and source record

Reviewed 2026-10-04. This implements the requested Taste Skill, Vercel web-design
guidelines, and Awesome DESIGN.md ideas as original, repository-local guidance for
the native Rust game. Entry points are [DESIGN.md](../DESIGN.md) and the
[design-rust-duty-ui skill](../.agents/skills/design-rust-duty-ui/SKILL.md).
No upstream skill body, installer, brand asset, dependency, or executable helper is
vendored. Runtime code and release workflows are unchanged by this adoption.

## What each source contributes

| Source | Applied here | Deliberate boundary |
| --- | --- | --- |
| Taste Skill | Understand the task; inspect the existing visual language first; use a small consistent vocabulary; preserve working behavior during scoped improvements | Its current v2 is experimental and targets landing pages/portfolios. Marketing layout, motion dials, font bans, forced imagery, and React/Tailwind defaults are not native-game requirements |
| Vercel web-design-guidelines | Review input access, focus, action/state feedback, long text, interruptible motion, and recoverable errors at the actual changed file | HTML/ARIA/CSS, hydration, URL state, browser metadata, and web performance metrics do not certify this native renderer |
| VoltAgent awesome-design-md | Keep an explicit, discoverable design document with roles, component behavior, hierarchy, and consistency | This is a collection of third-party website analyses, not a game-UI standard. No Linear/Vercel/other brand skin, font, logo, or screenshot is imported |

The repository's existing controls and measured behavior outrank generic aesthetic
preferences. The local adaptation preserves useful amber/cyan roles and real
progress/version information even where marketing-page advice would discourage
them. A source's imperative wording is reference material, not project authority.

## Native equivalents

| Web-oriented check | Native application |
| --- | --- |
| Semantic controls, labels, visible focus | Explicit action/value/unit labels, keyboard input and visible selected/focused state where implemented; verify platform assistive-technology support separately |
| Responsive layout and safe areas | Window/DPI-aware geometry, reachable controls, measured text, and draw/hit-test agreement |
| Form errors and navigation state | Validated settings, truthful save/reload outcomes, clear return/cancel paths, and consistent menu/session state |
| Reduced motion and interruptible transitions | Static/reduced alternatives for new nonessential UI motion; input and status changes remain immediate; do not alter simulation/weapon animation merely for UI styling |
| DOM performance and web vitals | Measure native frame/input cost on a named machine and scene when affected; keep IO and downloads out of the render path. Do not translate LCP/CLS/INP numbers into invented native budgets |
| Browser Back, URL state, deep links | Preserve native pause/resume/cancel behavior and current settings persistence. Do not invent a browser/history layer |
| Alt text and ARIA live regions | Provide meaningful native labels/status, then assess actual accessibility integration. Drawn text alone is not screen-reader support |

## Scoped review checklist

Mark each applicable item passed, failed, blocked, or not run with evidence. Mark
inapplicable items with a reason. This is a review aid, not an automated CI gate or
a claim of baseline compliance; do not require every unrelated surface for a small fix.

- [ ] **Task and ownership:** record exact base/head, changed surface, player goal,
  state owner, and active contributor overlap. Preserve current controls and identity.
- [ ] **Readability:** inspect primary/secondary hierarchy, numeric alignment,
  units, long/empty/error text, and labels against actual bright/dark scene content.
- [ ] **Geometry:** draw bounds and hit targets agree after resize/fullscreen and
  supported DPI/UI scaling. At minimum, exercise the configured 1440x900 window
  and the existing 960x540 reference viewport when the changed surface appears there.
  Report unsupported or clipped sizes; do not call these universally supported.
- [ ] **Interaction:** test mouse and available keyboard path, press/hold/release,
  repeated activation, drag leaving its target, and cancellation. Inspect selection
  visibility and ensure a menu action cannot also resume play or fire.
- [ ] **Interrupted flow:** exercise pause/resume, reset, focus-shortcut return,
  blocked startup, and reopen as relevant. A renderer limitation is a stated gap,
  not a passing OS focus test.
- [ ] **State and persistence:** test valid/boundary values, save/reload and failure
  outcomes using an isolated settings file. Update work needs checking, unknown
  progress, paused/cancelled, offline/error, ready, and confirmed-current states as
  applicable, with the existing updater owner. Do not perform a real release to
  prove UI styling.
- [ ] **Motion and performance:** justify any UI animation, verify interruption
  and reduced/static behavior, and measure affected frame/input cost when relevant.
- [ ] **Evidence:** reuse the affected Rust contracts and native capture/interaction
  workflow. Record exact commit, platform, dimensions/scale, settings, test commands,
  outcome, and limits. A screenshot is layout evidence, not keyboard/focus proof.

Existing starting points: [session transitions](../src/session.rs),
[input handling](../src/control.rs), [settings tests](../src/settings.rs),
[update-panel tests](../src/game_update.rs), [toggle contracts](../tests/toggle_controls.rs),
and [verification commands](../README.md#verify). Follow
[engineering evidence guidance](ENGINEERING_PRACTICES.md) for the affected boundary.
Historical [verification records](VERIFICATION.md) are not fresh results.

Documentation-only changes need frontmatter, local-link, source-pin, and scope
checks. Future UI changes need the relevant behavior and native evidence above;
do not add a web linter or duplicate the game test suite just to use these sources.

## Pinned upstream review and licensing

- **Taste Skill:** [requested site](https://www.tasteskill.dev/), which links to
  Leonxlnx/taste-skill. Reviewed [main skill](https://github.com/Leonxlnx/taste-skill/blob/ce26fc25c0e5e8cab638f883de62d9a86ee5e45b/skills/taste-skill/SKILL.md)
  and [redesign skill](https://github.com/Leonxlnx/taste-skill/blob/ce26fc25c0e5e8cab638f883de62d9a86ee5e45b/skills/redesign-skill/SKILL.md)
  at `ce26fc25c0e5e8cab638f883de62d9a86ee5e45b`.
  [MIT license, copyright 2026 Leonxlnx](https://github.com/Leonxlnx/taste-skill/blob/ce26fc25c0e5e8cab638f883de62d9a86ee5e45b/LICENSE).
- **Vercel agent skill:** reviewed [web-design-guidelines/SKILL.md](https://github.com/vercel-labs/agent-skills/blob/063bee94c3f4df8453406c830b0a7df0f2860278/skills/web-design-guidelines/SKILL.md)
  at `063bee94c3f4df8453406c830b0a7df0f2860278`. It is a wrapper that fetches rules
  from another repository. The [repository README declares MIT](https://github.com/vercel-labs/agent-skills/blob/063bee94c3f4df8453406c830b0a7df0f2860278/README.md#license);
  no standalone LICENSE file was found in that pinned tree. The wrapper is not copied.
  Reviewed the actual [command.md rules](https://github.com/vercel-labs/web-interface-guidelines/blob/e3d624baaf29dc1fc645aff3e38f03e564d2d6b1/command.md)
  separately at `e3d624baaf29dc1fc645aff3e38f03e564d2d6b1`, with its
  [MIT license, copyright 2025 Vercel Labs](https://github.com/vercel-labs/web-interface-guidelines/blob/e3d624baaf29dc1fc645aff3e38f03e564d2d6b1/LICENSE).
- **Awesome DESIGN.md:** reviewed the [README](https://github.com/VoltAgent/awesome-design-md/blob/f6961238d5cddcf8042a74a70fc400ec67181abb/README.md),
  [contribution guidance](https://github.com/VoltAgent/awesome-design-md/blob/f6961238d5cddcf8042a74a70fc400ec67181abb/CONTRIBUTING.md),
  and [Linear analysis example](https://github.com/VoltAgent/awesome-design-md/blob/f6961238d5cddcf8042a74a70fc400ec67181abb/design-md/linear.app/DESIGN.md)
  at `f6961238d5cddcf8042a74a70fc400ec67181abb`.
  [MIT license, copyright 2026 VoltAgent](https://github.com/VoltAgent/awesome-design-md/blob/f6961238d5cddcf8042a74a70fc400ec67181abb/LICENSE).
  The example was inspected for document structure, not adopted as a theme.

These files contain original project-specific text and observations of Rust Duty.
If future work vendors upstream text/code, preserve its applicable copyright and
license notices. Repository licensing does not establish rights to referenced
third-party trademarks, proprietary fonts, or images. No external install scripts
were run. Refresh source pins only after reviewing upstream content, licensing,
and native applicability in a scoped change; builds and reviews need no live fetch.
