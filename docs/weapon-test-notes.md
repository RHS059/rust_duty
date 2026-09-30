# Kestrel-30 public-API weapon contract tests

## Verification result

Verified on 2026-09-30 (UTC):

- `cargo test --test weapon_contract`: **29 passed, 0 failed**
- `cargo test --release --test weapon_contract`: **29 passed, 0 failed**
- `cargo test`: **22 library tests and 29 integration tests passed**, with no binary or documentation test failures
- The integration-test file was formatted independently with `rustfmt --edition 2021 tests/weapon_contract.rs`

The contract tests are independent of the production implementation. No external game code, source, or assets were used.

## Reproduce

From the repository root after installing the prerequisites in README.md:

```sh
cargo test --test weapon_contract -- --nocapture
cargo test --release --test weapon_contract
cargo test
```

For a focused boundary reproduction:

```sh
cargo test --test weapon_contract tactical_sprint_cancel_before_at_and_after_credit_conserves_ammo_exactly_once -- --exact --nocapture
cargo test --test weapon_contract empty_reload_credits_at_1800ms_and_fires_at_2550ms -- --exact --nocapture
cargo test --test weapon_contract continuous_fire_stays_on_absolute_90ms_schedule_for_whole_magazine -- --exact --nocapture
```

## Timing convention

`Simulation::update` processes action and milestone events at the beginning of its tick, then advances `Simulation::time` by `FIXED_DT`. Tests distinguish that event timestamp from the end-of-update observation time. Tick zero begins at time zero.

- Fixed step: 120 Hz, approximately 8.333333 ms
- Shot deadlines: 0, 90, 180, 270 ms, and so on
- Actual shot timestamps must fall on the first eligible fixed tick, within one tick of each absolute authored deadline
- The 2 microsecond floating-point comparison epsilon covers representation error; it does not permit a one-tick delay for milestones that land on exact fixed-tick boundaries
- Tactical credit: tick 162, 1.350 s; ready: tick 234, 1.950 s
- Empty credit: tick 216, 1.800 s; ready: tick 306, 2.550 s
- Sprint-out: 24 elapsed ticks, 200 ms
- ADS-in: reaches full ADS on step 27, 225 ms, after remaining incomplete on step 26
- ADS-out: reaches zero on step 20, approximately 166.667 ms, after remaining above zero on step 19

## Coverage

### Defaults and cadence

- Magazine capacity 30, initial magazine 30 and reserve 90
- Authored 90 ms fire interval and all requested timing defaults
- Every shot in a 30-round uninterrupted magazine checked against its original absolute deadline; final-shot drift cannot accumulate unnoticed
- 65 early-release/repress schedules around the first cadence boundary
- Repeated alternate-tick trigger taps checked for both per-shot and accumulated rate limits
- Long idle followed by resumed firing checked for absence of catch-up shots
- Render partitions at 30, 60, 75, 120, 144, and 240 FPS produce identical fixed-step shot histories and weapon state

### Reloads and ammunition

- Exact credit and ready timing for tactical and empty reloads
- Fire held throughout each reload remains blocked between ammo credit and weapon ready
- Tactical sprint cancellation one tick before, exactly at, and one tick after ammo credit
- No later credit or double credit after cancellation
- Restarting after cancellation preserves the exact total ammunition
- Empty reload resists sprint requests at six points, including before, at, and after credit and immediately before ready
- Due credit precedes simultaneous sprint and new reload input
- Due ready precedes simultaneous fire and reload input
- Partial reserve transfers only available rounds
- Full-magazine and zero-reserve invalid reloads do not block otherwise eligible fire
- Repeated dry fire cannot manufacture ammunition or start impossible reloads
- 15,000 deterministic mixed-input ticks across three seeds preserve `ammo + reserve + shots == 120`, keep the magazine at or below 30, and include completed multiple-magazine sequences

### Sprint, ADS, recoil, and spread

- Exact 200 ms sprint-to-fire delay, including alternating fire release/repress
- Linear 220 ms ADS-in and 160 ms ADS-out progress with fixed-step quantization
- Mid-transition ADS reversal preserves progress
- Hip and ADS recoil leave raw yaw/pitch unchanged
- Recoil magnitude is below 0.02 degrees within 450 ms after a single shot
- Sustained-fire recoil remains finite and within 6 degree pitch / 2 degree yaw caps, and subsequently settles
- Hip bloom caps at 2.4 degrees, waits 100 ms after the last shot, then recovers at 4 degrees/second without going negative
- Fully aimed fire adds no hip bloom and uses the authored 0.08 degree stationary spread
- Shot rays are finite, normalized, and inside their advertised spread cone
- Changing spread settings or making extra read-only spread queries does not alter recoil
- Changing recoil tuning, while holding the public aim fixture constant, does not alter spread samples
- Reset reproduces shot timestamps, directions, spread, and recoil exactly

## Scope and limits

These are black-box integration tests: they import the public `Simulation`, `Input`, `Settings`, and public constants. They do not call private methods, inspect private RNG state, lock tests to seed values, or introduce production-only testing hooks. Public state is changed only for explicit fixtures such as an incomplete magazine or isolated recoil/spread comparison.

RNG tests establish observable independence under tuning/query perturbations and deterministic reset. A public API with no independent random-stream controls cannot conclusively prove private stream architecture; a shared generator that always consumes the same fixed number of samples could satisfy these behavioral tests. Separate stream implementation therefore also warrants implementation review.

Fixed-step render partitioning is exercised in a headless accumulator fixture. This verifies simulation independence from those frame partitions, not the native application's actual input sampling, renderer, audio device, camera presentation, UI, or asset pipeline. The weapon contract tests do not claim end-to-end visual or audio validation.

No implementation contract failures were observed in the final debug or optimized runs. Keep the assertions unchanged if later production edits expose a regression; failure messages identify the relevant tick, seed, schedule, or milestone.
