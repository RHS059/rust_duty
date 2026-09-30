> Intermediate source-only update: the supplied HK416 was verified locally, but its model binary and new screenshots are not in this commit. The game uses its procedural fallback until the separately authorized single asset upload finishes.

# Verification record

2026-09-30. Original prototype, not retail-equivalence validation.

## Executed locally

- Rust stable 1.98.1, Linux x86-64
- `cargo fmt --all -- --check`: passed
- `cargo clippy --locked --all-targets -- -D warnings`: passed
- `cargo test --locked`: 37 library and 29 black-box weapon tests passed
- Weapon contract tests also passed optimized (`--release`)
- Native release build: passed
- Native graphical launch and actual rendered frame exports: passed for normal,
  fully aimed, and slope-fixture camera views; see screenshots
- Audio synthesis compiled; cloud desktop has no ALSA device. Audio backend thread
  reports device-open failure while the game continues rendering. Audible quality
  and a physical audio output device were not tested. Use `--no-default-features`
  when building on an intentionally audio-less machine

## Native input smoke test and review regressions

Native Linux menu/start, telemetry toggle, a short W tap, a short mouse click,
reload from29/90 to30/89, CSV start/stop, explicit pause, click-to-resume,
reset to30/90, and clean quit were observed. A short-click latch bug found at low
render rate was fixed: accepted clicks now survive until a simulation tick.
Input bridge regressions cover short clicks, held triggers, no shot on resume,
and reset requiring trigger release/repress. A crouch-tunnel regression verifies
that a blocked stand-up cannot cancel a tactical reload.

Windows and Linux GitHub Actions passed lint, tests and executable artifact builds
on the initial draft commit. Check the latest PR checks for subsequent review fixes;
a CI build is not a Windows gameplay test.

## Measured headless values

| Quantity | Actual result |
| --- | ---: |
| Settled forward speed | 4.826000 m/s |
| Time to 99% forward speed | 0.183333 s |
| Time to less than 1 reference unit/s after release | 0.300000 s |
| Jump apex | 0.990469 m |
| Apex timestamp | 0.308333 s |
| Equal-height landing timestamp | 0.625000 s |
| Shots in [0, 0.900 s) | 10 |

Accepted shot times: 0, 0.091667, 0.183333, 0.275000, 0.366667, 0.450000,
0.541667, 0.633333, 0.725000, 0.816667 seconds. Each is the first120Hz tick at
or after its accumulated90ms deadline; cadence rounding does not accumulate.
Run `cargo run --locked --example measure` to reproduce.

## Verified behavior

Cardinal/normalized diagonal control, jump/airborne rejection and no held-key
bunnyhop, low-ceiling blocked expansion, crouch/prone clearance and camera containment,
walkable stairs,30°/45° ramp traversal and50° blocking, analytic ramp hitscan,
wall stopping, target occlusion, deterministic replay and render-partition independence.

Weapon tests independently cover reload milestone boundaries, cancellation and
ammo conservation, cadence/tap limits, delayed firing, ADS reversal, bloom/recovery,
recoil recovery without overwriting look, deterministic random behavior, and15,000
mixed-action ticks. See [detailed contract coverage](weapon-test-notes.md).

## Additional review regressions executed

The native app now uses the same f64 monotonic FixedClock that its endpoint tests
exercise. Eight render rates from30 to240FPS produce the same1200 ticks at10seconds,
including f32-rounded frame-delta input.100ms catch-up and250ms recovery budget are
tested. No interpolation or universal input-latency claim is made.

Steep wedges stay solid to airborne players and project motion downhill instead of
removing collision. Walk-off-ledge momentum, exact ordinary/prone step thresholds,
jump-intent reload cancellation, combined-pitch clamping, box/ramp muzzle obstruction,
and10,000 narrow-cone samples have explicit passing regressions.

## Not yet established

- Native Windows or macOS gameplay; CI build results are separate from runtime testing
- Physical mouse-latency/360° sensitivity measurement or controller support
- Every OS focus-loss route (explicit pause, Alt/Super shortcuts and long-hitch
  recovery exist; arbitrary focus callback coverage remains a renderer limitation)
- A full distribution goodness-of-fit test, long-session manual playtest, or arbitrary mesh collision. A10,000-sample mean/radial-moment check and cone-bounds tests passed
- Retail capture comparison, a chosen retail weapon's tuning, or blind A/B equivalence

The public behavioral reference supplied a broader checklist; this record reports
only checks actually executed against this prototype. It does not declare that
all proposed acceptance cases or every platform passed.

## Asset/profile/control update

- 139 Rust tests pass: 45 library, 2 mesh-batching, 23 asset/build-contract,
  18 M4-candidate, 22 toggle-control, and 29 existing weapon tests
- 38 Python converter tests pass, including Pillow PNG/JPEG decoding
- Formatting and Clippy with warnings denied pass; optimized M4 tests pass
- User-supplied untextured HK416A5 was converted and rendered locally in hip/ADS
  views. Full source FBX reimport reproduces the converted bytes exactly. Model
  is stored in one converted package; original FBX/GLB inputs remain excluded
- Native Linux input verified right-click ADS and crouch persist after release;
  prone replaces crouch; detected hitch pause clears ADS on resuming; F2 restores
  standing, hip fire and 30/90 rounds
- Supplied 98,522-triangle model is heavier than primitives. Cloud software
  rendering ran approximately 6–12 FPS during these checks; this is not a hardware
  performance benchmark. Windows gameplay/performance remains untested
- Static mesh subset only. Skins, morphs and animations fail explicitly; no rig
  is silently discarded. Current renderer is simple diffuse/base-color rendering,
  not full PBR. CRC/version/bounds validate data, not authenticity or licensing
