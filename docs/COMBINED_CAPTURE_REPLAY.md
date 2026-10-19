# Combined committed-input replay (source-only v3 verifier correction)

Original replay baseline: draft PR #74, `d6958fd8d59eb3c42d6cacf0d0e92f034be64f80`.
For the exact public successor and current proof boundary, see
[COMBINED_SOURCE_WIP.md](COMBINED_SOURCE_WIP.md). Historical overlay and test
results below describe their original snapshots, not this successor.
This source does not admit production high-mantle assets. `APPROVED_RUNTIME_PINS`
remains `None`; default animation configuration, current main/walk/ADS slots,
legacy inactive 0.60/0.85-second traversal, hang behavior and frozen art are unchanged.

## What this route does

`gameplay-combined` has one documented setup, before the first update:
feet `(-8.6, 0, -3)`, yaw π, in the existing range. Thereafter the driver only
reads committed simulation state and emits ordinary `Input` values. It never
sets feet, velocity, look, animation time, source poses or return durations.
Platform mouse deltas are ignored for this combined sequence; every state records
actual yaw/pitch and verification requires the initial fixed aim (π, 0). Ordinary
committed weapon recoil remains part of the camera direction.

The route uses an ordinary priming shot, accepted high-ONTO, a genuine tactical
reload while the high source returns, full paired-prone entry and ADS return,
a second priming shot and interrupted paired-prone reload, ordinary east-lane
travel, two accepted low mantles and live ADS/walk returns, then an ordinary
return trip and a second high mantle with an ADS/walk return. It verifies 2 high,
2 low and 2 paired-prone entries. A rejected shot, mantle, endpoint or prone
return, death, invalid state, route timeout or observer failure fails the run.
No request is relabelled as an acceptance.

The middle 1.2 m block is avoided by the east lane. The driver's lane guard
requires x ≥ -8.50. The two low actions are sequential; no high↔low outgoing
layer overlap is claimed. Paired-prone during the short traversal outgoing tail
is also not claimed: ordinary standing→crouch takes approximately that tail's
0.20 seconds before the prone transition can begin.

## Presentation budget (deliberately nonuniform)

All input and simulation states are committed and journaled at 120 Hz.
Native rendering is scheduled at:

- 5 Hz during ordinary travel/settling
- 10 Hz during active native sources
- the requested 30 or 60 Hz during outgoing returns
- every observed committed ownership/phase/endpoint boundary

`--capture-hz` selects the dense outgoing rate for this sequence only. It does
not claim uniform 30/60 Hz output or real-time performance. Existing high-only
uniform captures retain their original behavior.

The source-free CPU route takes 2,557 ticks (~21.308 s), including the final
completion observation. Its cadence tests produce 193/229 presentation
opportunities for dense30/dense60. The app increments its frame counter before
the scheduler, so there are exactly seven initial tick-zero frames: 200/236
total in the complete synthetic observer fixtures. These fixtures have no
production renderer or loaded approved package. At the prior observed ~1.22
seconds per software-rendered frame, those counts imply roughly 244/288 seconds,
not a runtime guarantee. The
external capture owner must retain a 600-second wall limit.

Per invocation: at most 32 selected PNGs, extent ≤1440×900, journal ≤64 MiB,
12,000 records, 64 KiB per record, and 60 simulated seconds. The PNG selector
keeps native endpoints and multiple actual intermediate return samples. Missing
samples fail verification rather than being synthesized. There is no native
runner in this overlay; the separately reviewed package/capture planner owns
process, wall-time, disk, log and display reservations.

## Future invocation (only after separate admission and package review)

```
/path/to/reviewed/vector-range --renderer=gl --level=range --hold-controls --no-update \
  --animation-manifest=/path/to/reviewed/combined.cfg \
  --combined-observer=/new/capture/output --combined-witness=<64-lowercase-hex> \
  --combined-deterministic --capture-sequence=gameplay-combined \
  --capture-hz=30 --capture-native-window
```

Use a new output directory for each run; the directory must not already exist.
Repeat at dense60 only when the capture owner has reserved the extra output.
The observer rejects mixed high-only observers, pose/time fixtures, fixed
viewmodel time, alternate clip selection and ambiguous level selection.
All three normal runtime bindings must be admitted before the output directory
is opened. This command cannot currently pass production admission while high
pins are inactive. Do not fill the pins from capture-produced metadata.

```
python3 tools/verify_combined_capture.py --capture=/completed/capture/output \
  --bindings=/independently/reviewed/loaded-bindings.json \
  --bindings-sha256=<independent-sha256> --identity=<same-64-hex> \
  --hz=30 --report=/new/verification.json
```

The independent bindings JSON has the same complete `high`, `low`, `prone`
projection described below, established by package review rather than copied
from the observed header. The verifier reuses the existing independently pinned
PNG witness helpers; it does not repurpose the high-only scenario verifier.

## Observer contract

Schema: `rust-duty-combined-observer/v1`.

- Header: build labels, exact admitted low/high receipt and VRA hashes, native
  spans/ranges, complete admitted paired-prone binding identity (now including
  the validated pair receipt SHA-256), fixture, invocation witness, all bounds,
  nonuniform cadence policy and unsupported scenarios.
- Each state: immutable loaded binding identities, actual feet/velocity/eye,
  stance, fixed-look observation, paired entry start identity, ammo/reserve/shots
  and reload credit/ready times, active mantle kind,
  from-hang flag, start/landing, low/high generations and exact native samples.
- `accepted`: a pre-advance ordinary gameplay event. Its source frame 1 is a
  committed event; it is explicitly not a rendered source frame.
- Each `step`: exact ordinary Input, 120 Hz tick and start/end committed times,
  phase, camera sample, actual presentation owners, outgoing source clocks,
  live target route/pose checksum, named target/output opacity, frozen source
  opacity, frozen pose sample time/checksum, renderer high/low generations,
  procedural/ADS/walk weights and renderer warnings/errors.
- Each `frame`: exact committed tick, the actual eye/forward/up sent to world
  rendering, current presentation and optional native PNG/witness index.
- `finished`: completion flag and repeated accepted counts. No terminal record,
  incomplete completion or route failure is a failed capture.

Pose checksums are diagnostics, not authenticated source or geometry parity.
Camera verification reconstructs one application of the paired orientation and
requires an active camera sample matching the admitted weapon clock/orientation,
checks outgoing quaternion interpolation against the frozen pair, and checks
that authored eye height replaces ordinary stance height. The native
frame record separately carries the actual camera vectors used to draw.
Opacity verification uses the source-owned frozen opacity and live targets
matched by actor name. The verifier requires at least two distinct actual
rendered intermediate outgoing weights and evolving live target checksums for
each of the six outgoing clocks, plus selected witnessed intermediate PNGs.

The v2 correction makes each state binding mandatory and observes current loader
admission rather than copying the header. It rejects admission loss, generation
changes, stale/mismatched owners or route labels, empty actor inventories, changing
frozen pose/opacity, altered native/interruption clocks, active ADS/procedural
leaks, erased moving walk samples, and missing real reload-credit/reserve events.
Frozen low/prone poses are tied to the preceding committed native snapshot; high
return starts at the actual native endpoint. Returns must run their ordinary
0.20-second lifecycle. Expected render ticks are reconstructed independently from
all 120 Hz states, including source/phase/endpoint boundaries and startup frames.
Before raster decoding, actual PNG IHDR dimensions must match metadata and remain
within the declared extent. The v3 verifier additionally checks the actual
accepted high observation at zero seconds/source1/reference7787 with no return,
then connects its generation and mantle identity to the first committed advance.
It compares every common state field on each rendered frame against the matching
committed step (or initial state for tick zero), plus the step's derived camera
and presentation fields. The terminal state must match both the final committed
state and final rendered projection. Header-only identity or nominal `--capture-hz` is not
accepted as evidence for these per-state/per-frame claims.

## What the checks prove, and what remains

Source-free Rust tests exercise ordinary shipped-range collision/action
acceptance, the real simulation clocks and the bounded presentation scheduler.
The synthetic low binding used by that simulation fixture has the existing
fixture's 0.8-second renderer return configuration; no renderer is used, so this
cannot establish production low outgoing duration/opacity. Native admission and
the verifier require the independently pinned 0.20-second production returns.
Python tests independently reproduce the emitted input sequence from preceding
committed state and reject changed requests, unsafe lane movement, missing
endpoints, stretched opacity returns, duplicate owners and double camera/height
application. The complete synthetic observer fixture additionally tests both
cadences, 26 original invalid full-trace mutations, and 13 additional cross-record
mutations at each rate covering the independent v1/v2 review findings. These invented bindings, pose checksums, camera and ammo projections
are rejection-test data, never admission or native evidence. v1/v2 and their
failed independent reviews remain preserved. In the historical replay-v3 overlay, the Rust source was byte-identical
to its tested v2 and reused those hash-verified Rust/check/format receipts.
The current public composition adds later diagnostics and preserves published
CI guards; those earlier receipts do not validate this successor. CPU renderer-feature typechecks do not
launch a window.

Still unverified here: actual combined native package loading; selected native
PNGs and outgoing targets/opacity; source-to-runtime geometry parity; OS/hotkey
input; pause/cancel/reset/debug-death in this deterministic route; direct
high↔low or traversal→active-prone overlap; Windows/DX12; real-time performance;
and artistic acceptance. Existing synthetic ownership-overlap tests remain
separate evidence. This source-only publication adds no assets, default
activation or native execution evidence.
