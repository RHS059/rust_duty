# High-ONTO app-input-edge diagnostic

This opt-in source-only diagnostic is part of the consolidated WIP described
in [COMBINED_SOURCE_WIP.md](COMBINED_SOURCE_WIP.md). Production high runtime
pins remain `None`; a normal public checkout cannot satisfy high admission.

## Input and startup boundary

`high_app_edge_input::Options::parse` validates the full argument set before
awaiting the level menu. The typed result is passed to the menu's shared
startup predicate. Only a valid app-edge fixture bypasses its confirmation
prompt. Ordinary menu behavior and legacy capture/demo behavior are preserved.

The fixture requires exactly one case (`pause`, `reset`, or `debug-death`),
output directory, witness, external contract, explicit animation manifest,
settings, `--level=range`, `--no-update`, and `--hold-controls`. Alternate
capture/combined/onehand modes, time/pose overrides and alternate assets reject.
The sole fixture write sets feet (-8.6, 0, -3) and yaw PI before the first update.
No later fixture state, pose, velocity, clock, binding or health writes occur.

After sampling and draining platform events, FocusInput accepts the fixture's
ordinary key/button snapshot. W plus Space reaches the normal control/input
and collision acceptance path. Escape and Enter reach SessionController;
F2 reaches the existing reset handler; F9 reaches debug damage. The route
retains actual focus capability/state, rejects known focus boundaries and
zeroes unjournaled look input. It does not prove physical OS input, native focus
edge behavior or combat death. Ordinary input is unchanged when inactive.

The existing 120 Hz FixedClock consumes actual wall deltas and the original
0.250-second hitch clamp. Source timing remains 95/60 seconds; the independently
admitted outgoing duration remains 0.20 seconds. The fixture interrupts at the
first observed source age at least 0.45 seconds and rejects at 0.80 seconds.

## Cases and fixed limits

Each case uses a fresh process and new output directory:

- Pause: six selected native-window images, including distinct early and late
  outgoing intervals, then cleared source and restored ADS.
- Reset: three images covering source, first post-reset frame and terminal state.
- Debug death: three analogous images through the existing debug action.

Per case, the journal is bounded at 4,000 records, 5 MiB and 60 seconds.
The three-case set is bounded at 12 images, 15 MiB of journals and 180 seconds.
The owner wrapper must separately enforce process/resource limits and complete
96 MiB output accounting. Pause readiness uses a 320 x 200 single-sample window;
reset/debug-death and ordinary dimensions are unchanged. Image limits remain
at most 1440 x 900. No source or return duration is retimed for slow rendering.
Missing either outgoing image interval must fail.

## Evidence and source-only checks

The observer records actual accepted events, consumed input, session changes,
FixedClock decisions, committed steps, renderer generation/ownership, frozen
source time, current presented time, mapped live-target time, actor opacity,
pose checksums and camera vectors passed to rendering. Observations do not
control motion or resample targets.

`verify_app_edges.py` independently reconstructs the input recipe, session,
latches and fixed-clock accumulation; rejects orphan, reordered or missing
records; and verifies current bindings, source/cancellation timing, live target
changes and stale-source cleanup. Native admission additionally requires exact
external source/package/binary/receipt identity, terminal successful process
receipts, bounded complete output, actual PNGs and frame witnesses.

Its exact informational renderer status remains distinct from renderer errors.
The historical native source/manifest pins remain frozen and reject this public
composition until a fresh independent candidate is reviewed. All synthetic
positive results explicitly report no actual app-handler or OS-input proof.

Run repository-local tests with:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tools -p 'test_app_edge*.py' -v
```

These tests never run Cargo or a game. Python source-contract checks and Rust
formatter success do not replace the pending Rust/build/native-readiness gates.
The previous failed startup probe remains failed; menu repair and a separately
reviewed output-ownership correction both precede any new native claim.
