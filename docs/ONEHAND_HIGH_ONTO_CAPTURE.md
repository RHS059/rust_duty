# Optional one-hand HIGH-ONTO capture contracts

## Current gate

This is source-only preparation. Production admission remains
`APPROVED_RUNTIME_PINS=None`; no default manifest enables one-hand mantle.
The failed 64-subdivision runtime cannot be relabeled as the proposed
256-subdivision replacement. Bounded-focus FBX proof, the converted runtime,
all 4,240 independent source times / 43,392,160 skin observations, reviewed
receipt/payload pins, a verified app build and actual gameplay remain required.
Estimated replacement VRA size: **73,134,921 bytes**, not an artifact measurement.
Both pending payload approvals remain untouched.

The capture tools contain no local geometry, runtime package, ready-to-run private
configuration or candidate hashes. Their synthetic fixtures are constructed in
tests and are never accepted as native evidence. They cannot activate a binding.

## Distinct routes

### Real platform input

`run_high_mantle_inputs.py` uses XTest on a newly owned authenticated Xvfb display.
It starts the ordinary shipped range at its normal spawn, approaches the existing
1.8 m high step using keyboard/mouse input and attempts fresh Jump. It prepares
four independent scenarios: complete traversal/live return, Escape pause and
resume, F2 reset, and F9 **debug-death**. Debug-death is not combat-death coverage.
There is no position, collision, timing or acceptance override if approach fails.

The observer records raw platform edges, app transitions, accepted source frame
1, every committed Input/state and rendered frame, outgoing weights, changing
underlying poses, camera basis/eye, landing, weapon anchor and recording errors.
Its accepted frame-1 event is not a rendered frame-1 screenshot. Committed source
96, retained outgoing source 96 and rendered source 96 at weight zero are separate
claims. Slow rendering may skip endpoint or intermediate return frames. The
verifier reports that gap rather than forcing a successful visual result.

### Deterministic ordinary-Input complement

`run_high_mantle_deterministic.py` uses the existing traversal replay schedule at
30 or 60 Hz. Its declared pre-loop start is feet `(-8.6, 0, -3)`, yaw pi, facing
the existing 1.8 m block. After that immutable setup, only ordinary Input flows
through the existing simulation update. There is no in-run state assignment.

Forward/ADS begins at 0.15 s, fresh Jump lasts one 120 Hz tick at 0.25 s, walking
continues to 2.15 s and ADS to 2.7 s. The fixture requires an independently pinned
0.20 s outgoing return; other durations fail instead of being retimed. The native
95/60 s action spans 190 simulation ticks and ends at tick 220, which lies on both
render grids. The verifier requires an actually captured source-96/weight-zero
endpoint and at least two distinct captured intermediate weights with changing
live underlying poses. Complete telemetry alone cannot establish visual return.

This route is labelled `deterministic_ordinary_input`. It does not prove OS key
edges, Escape/F2/F9 behavior, real-time performance, Windows/DX12 or artistic
approval. The platform route is labelled `platform`. Verifiers reject mixing them.

## Bounds and invocation

Native execution is explicitly Linux-only; importing and running source-only
tests does not require Unix resource limits on Windows. Each scenario/rate is
bounded to 12 selected native-window PNGs at at most 1440×900, a 16 MiB journal,
12,000 records, 32 KiB per record and 600 wall seconds. Platform input also has
4,096-command and 30-simulated-second bounds. The deterministic sequence uses
324 committed ticks and 2.7 nominal seconds, without claiming real-time rendering.

Preflight reserves worst-case output and 32 MiB margin above a 1 GiB disk floor.
Runtime stops near floor plus 16 MiB. Output must be new. The private display
refuses existing display-97 ownership, uses temporary Xauthority and disables
TCP. Cleanup stops only owned child processes. Recording errors latch as failure.
The tools do not duplicate executables or payloads.

Only after the evidence/admission/build gates pass should the native owner prepare
an independently reviewed config with schema
`rust-duty-onehand-native-owner-config/v1`. It must name a root, executable,
manifest, working directory, Xvfb, all-grid proof, source paths and runtime paths,
plus binding receipt/VRA hashes and return duration. `inputs_sha256` must pin the
exact tested code, runner/verifier scripts, executable, runtime companions,
manifest, proof and Xvfb. Supply the config's SHA256 separately. A config is input
identity, not authority to activate a runtime binding.

```sh
# Dry planning is the default; placeholders intentionally cannot run.
python tools/run_high_mantle_inputs.py --config OWNER_CONFIG \
  --config-sha256 INDEPENDENT_SHA256 --output NEW_OUTPUT --scenario complete
python tools/run_high_mantle_deterministic.py --config OWNER_CONFIG \
  --config-sha256 INDEPENDENT_SHA256 --output NEW_OUTPUT --hz 60 --hz 30

# Only a separately authorized native owner adds --execute after all gates pass.
python tools/verify_high_mantle_run.py --run OUTPUT --config OWNER_CONFIG \
  --config-sha256 INDEPENDENT_SHA256 --report NEW_REPORT
python tools/verify_high_mantle_deterministic_run.py --run OUTPUT \
  --config OWNER_CONFIG --config-sha256 INDEPENDENT_SHA256 --report NEW_REPORT

# Portable source/synthetic checks; no native app or private geometry is used.
python -m unittest discover -s tools -p 'test_high_mantle_*.py' -v
```

These source tests cover incomplete/forged clocks, inactive or mismatched binding,
low/from-hang rejection, landing/stance errors, missing actual hotkeys, paused
time advancement, stale live targets, false rendered-endpoint claims and Windows
import portability. Passing them is not native capture or gameplay acceptance.
