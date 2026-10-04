# Engineering practices for Rust Duty

Review date: 2026-10-04. Inspected game baseline:
[`70372028`](https://github.com/RHS059/rust_duty/tree/70372028c6ae9fb0c990f2c9a22ca603a1a2bff3).
This guide applies selected ideas from Tech Fleet to the existing native game;
it does not report a new runtime audit or add an automated merge gate.

## What is applied

The repository-local [review skill](../.agents/skills/review-rust-duty-change/SKILL.md)
provides scoped review and evidence selection. It adds no executable helper,
dependency, global agent configuration, runtime change, or workflow.
The [decision note](engineering/decisions/0001-proof-at-owning-boundary.md)
records the rationale and remains proposed while this change is under review.

| Source practice | Rust Duty application | Boundary |
| --- | --- | --- |
| `comprehensive-test-strategy` | Choose the lowest useful real API, then native evidence for integration/presentation | Reuse Cargo/Python suites; no new BDD or service-contract framework |
| `judge-arch` | Review module placement, data ownership, dependencies, and failure behavior on the scoped diff | Findings need concrete consequences; no generic keyword-based Rust lint |
| `verifiable-quality-gates` | Test a custom guard's actual entry point with valid and violating inputs; record what ran | No claim that every existing gate has mutation proof; no shared-checkout mutation |
| `arch-encode` | Turn an observed regression into a narrow contract or local decision | Do not accumulate speculative rules or duplicate a check already owned elsewhere |
| `architectural-decision-records` | Record significant format, ownership, or proof choices with status and trade-offs | Short notes; no retroactive claim that a proposed choice is accepted |
| `owasp-secure-coding-bdd` | Apply bounded parsing, path validation, and explicit failure outcomes at the affected boundary | Follow existing binary/asset contracts; no wholesale web-auth checklist |
| Release/SRE guidance | Identify exact tested artifacts and remaining operational evidence | Existing release/updater owners and safeguards remain authoritative |
| Accessibility/usability guidance | Review native feedback, recoverable errors, pause/focus flows, and non-color-only status | Browser/ARIA tooling does not certify native accessibility |

Microservices, databases, cloud service infrastructure, broad compliance programs,
and browser/device matrices are not introduced by this adoption.

## Find the existing proof before adding more

| Changed boundary | Start here | What it does not establish |
| --- | --- | --- |
| Gameplay, input, fixed time | [weapon contracts](../tests/weapon_contract.rs), [clock](../src/clock.rs), [input bridge](../src/control.rs) | Native input latency, rendering, or retail-game equivalence |
| Static binary assets | [asset contracts](../tests/asset_contract.rs), [multi-record regressions](../tests/asset_quality_regressions.rs), [format](ASSET_FORMAT.md) | Rendered appearance or rights to distribute a model |
| Authored animation and companions | [skinned format](SKINNED_ASSET_FORMAT.md), [source-to-game verification](AUTHORED_ASSET_CI.md), the affected authored/layered contract suite | Artistic approval, reference fidelity, or untested platforms |
| Native integration | [verification record](VERIFICATION.md) and the affected feature's capture evidence | A different commit, device, or interrupted flow that was not exercised |
| Updating and packaging | [updater boundary](UPDATER.md), [release process](RELEASE_CHANNEL.md) | Permission to publish or evidence that a live update occurred |

The eight multi-record asset regressions are already present at the inspected
baseline. They are not recreated by this change. Historical results in
[asset-test-notes.md](asset-test-notes.md) and other records retain their original
date/scope; they are not results for this documentation PR.

## Review and verification workflow

1. Name the affected owner and its observable contract. Read the current feature
   docs and active diff; confirm file ownership before overlapping edits.
2. Look for existing evidence at that owner. Add only the missing case. Prefer
   small original fixtures and independent expected values to private model data
   or a second implementation of production logic.
3. Make negative cases discriminating. A corrupt index hidden behind a bad CRC
   tests checksum rejection, not index validation. A parser accepting an empty
   result does not prove expected geometry survived.
4. Separate logical proof from integration. For presentation, exercise relevant
   repeated/interrupted flows and actual native playback. For asset changes,
   preserve source/companion identity and sampler parity. Keep numerical validity,
   visual inspection, and aesthetic approval distinct.
5. Use the existing [verification commands and prerequisites](../README.md#verify)
   for the affected scope. Typical Rust checks are `cargo fmt --all -- --check`,
   `cargo clippy --locked --all-targets -- -D warnings`, and `cargo test --locked`.
   Record any feature flags, materialization requirements, skipped fixtures, or
   unavailable native environment. A documentation-only change needs link,
   scope, and skill validation; it does not manufacture fresh gameplay evidence.
6. Record commit, platform/toolchain, command or native steps, fixture/artifact
   identity, outcome, and limitations. Distinguish passed, failed, blocked,
   not run, and not applicable with a reason. Recheck affected evidence after
   later edits; do not weaken the contract to recover a green result.

When a custom check is involved, verify the actual entry point and both a valid
control and the intended violation. Missing required input must not become a
silent pass. A genuinely inapplicable check may be reported as such with its
reason. Any later mutation experiment needs a disposable isolated checkout;
this guide neither installs a mutation runner nor claims one ran.

Performance claims need a named machine, representative scene, and measured
baseline before a budget is agreed. Offline gameplay and the application's
GitHub update traffic are different scopes; read the updater contract rather
than carrying forward an obsolete blanket claim that the application never
uses the network.

## Source review, license, and deliberate non-adoption

Reviewed source: [Tech Fleet snapshot `0d439618`](https://github.com/techfleetworks/enterprise-software-AI-skills/tree/0d4396187746e5f9c67db7b9650d6e0c415150b6),
unchanged from the initial 2026-09-30 review. The upstream is
[MIT licensed, copyright 2026 Tech Fleet](https://github.com/techfleetworks/enterprise-software-AI-skills/blob/0d4396187746e5f9c67db7b9650d6e0c415150b6/LICENSE).
This guide and skill are original project-specific text, not copied skill bodies,
templates, or scripts. Vendoring upstream material later requires retaining its
applicable notices and a separate scoped review.

The upstream [architecture scanner](https://github.com/techfleetworks/enterprise-software-AI-skills/blob/0d4396187746e5f9c67db7b9650d6e0c415150b6/judge-arch/scripts/arch-gate.mjs)
has JS/TS-oriented built-ins and a React/Supabase starter configuration. Its
source skips unreadable inputs and permits a pass with no applicable Rust rules.
A generic scan could therefore provide false confidence here. Its
[mutation helper](https://github.com/techfleetworks/enterprise-software-AI-skills/blob/0d4396187746e5f9c67db7b9650d6e0c415150b6/verifiable-quality-gates/scripts/verify-check-discrimination.mjs)
rewrites check files into Node no-ops and warns about interruption recovery.
Neither tool was installed or executed for this adoption. Upstream imperative
wording does not expand project permissions or establish that a check passed.
