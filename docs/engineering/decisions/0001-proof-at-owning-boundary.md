# 0001. Keep quality evidence at its owning boundary

Date: 2026-10-04

Status: Proposed with the engineering-guidance draft PR; no new automated gate
or runtime architecture change is implied.

## Context

Rust Duty already has native Rust/Python contracts, authored-source conversion
and parity evidence, and native capture/build workflows. The initial asset-quality
work is already integrated. Generic enterprise skill installation would duplicate
parts of that system and introduce web-oriented checks with weak relevance to Rust.

The concrete risk is misplaced confidence: checking a synthetic substitute rather
than the parser used by the game, accepting a malformed fixture for the wrong
reason, or treating a successful platform build as native gameplay verification.

## Proposed decision

Use one small repository-local review skill and the
[engineering guide](../../ENGINEERING_PRACTICES.md) to route changes to existing
owners and evidence. Add a missing regression where the affected public contract
is exercised. Keep source/format correctness, Rust sampling, native presentation,
and artistic approval separately identified.

For a new custom guard, exercise its real entry point with a valid control and a
real violation. Record missing prerequisites explicitly. Any mutation proof must
run in an isolated disposable checkout and be reported as actually executed;
no blanket mutation-coverage claim is made for current checks.

## Alternatives considered

- **Vendor the full enterprise bundle:** rejected for this change. It brings
  unrelated service/web concerns and scripts that are not drop-in Rust gates.
- **Add another asset checker or duplicate the original tests:** rejected. Existing
  [asset contracts](../../../tests/asset_contract.rs) and
  [multi-record regressions](../../../tests/asset_quality_regressions.rs) already
  exercise the production decoder.
- **Keep guidance only in a conversation:** rejected. The scoped skill and linked
  guide make project-specific distinctions reviewable alongside the repository.

## Consequences

No dependencies, runtime code, CI, publisher, or global agent settings change.
Reviewers still need judgment; this text is not mechanical enforcement. New
contract or automation work remains a separately scoped implementation. Existing
format, provenance, verification, and release documents retain their ownership.

Revisit this choice when a demonstrated gap cannot be covered at the existing
boundary or when a new check warrants a tested Rust/Python enforcement mechanism.
