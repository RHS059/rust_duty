# Authored DX12 capture acceptance and open review

This lane ports the existing native capture acceptance to Windows DX12 WARP. It
does not change gameplay, animation sources, bindings, asset generation, the
updater, or the historical Linux/OpenGL validation lane. It adds no Vulkan work.
A successful job means the **automated checks** passed. Measured sight landmarks,
human visual approval and a real-GPU Windows playtest remain separate open gates.

## Exact CI prerequisites

The caller in `build.yml` uses `./.github/workflows/wgpu-dx12-authored.yml` with no
inputs and depends on `animation-assets`, `walk-assets`, `ads-assets`,
`directional-assets`, `jump-assets`, and `native-validation`.

The Windows job checks out the same caller revision, downloads this run's
`generated-{reload,walk,ads,directional,jump}-runtime` artifacts, then runs the
existing `package_game.py materialize --include-walk --include-ads
--include-directional --include-jump --require-generated`. It verifies source
identity, companion hashes and passed sampler witnesses; it never launches
Blender or generates replacement animation companions.

Matched legacy inputs are the successful `native-validation` job's immutable
`native-gameplay-{jump,reload,walk,ads}-evidence-attempt-N`,
`native-ads-placement-evidence-attempt-N`,
`native-layered-locomotion-evidence-attempt-N`, and
`native-reload-return-evidence-attempt-N`, where N is the current run attempt.
Downloads have no alternate run ID, repository or token. A rerun of just the
Windows job cannot silently reuse a prior attempt's baseline: rerun all jobs if
this attempt's native evidence is absent. Existing Linux artifacts remain
historical-compatibility evidence, not DX12 evidence.

The build is `cargo build --locked --release --no-default-features --features
wgpu-runtime --bin vector-range --example renderer_contract`. Every actual game
process requests `--renderer=dx12 --force-fallback-adapter --no-update` and an
explicit source-validated animation manifest. No procedural weapon fallback is
requested. The renderer must log both:

- `renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver`
- `renderer dx12_shader_compiler=Fxc`

This requires the explicit FXC device pin; earlier Auto/DXC binaries cannot pass.
The actual capture sidecars must independently identify Dx12, explicit dx12,
WARP and the image extent. Request flags alone are not execution proof.

## Executed acceptance

The new harness uses the existing acceptance scripts without threshold changes:

| Capture | Cadence matching native-validation | Existing check |
| --- | --- | --- |
| Authored jump and ADS/reload interruption | 60 Hz | `verify_jump_capture.py` |
| Committed reload and return to locomotion | Default 60000/1001 | `verify_gameplay_capture.py` |
| Walking start, loops and stop | Default 60000/1001 | `verify_gameplay_walk_capture.py` |
| ADS entry/hold/exit, reversals and interruptions | Default 60000/1001 | `verify_gameplay_ads_capture.py` |
| ADS with saved XYZ offset (+0.20, -0.20, +0.20) | Default 60000/1001 | ADS check above and `verify_ads_placement_capture.py` |
| Four-direction concurrent layers | 30 and 60 Hz | `verify_layered_locomotion_capture.py`, with no legacy-walk exemption |
| Complete/cancel/restart reload return | 60 Hz | `verify_reload_return_capture.py` |
| Frozen ready/reload world-fixed lighting | Six yaw/pitch views per pose | `verify_lighting_capture.py` |

The lighting producer currently accepts `--renderer` but has no fallback-adapter
argument. The new harness reproduces its exact twelve asset/clip/sample/camera
commands, adds the required backend/fallback/manifest flags, then calls its
existing image validator and contact-sheet routines unchanged. All twelve raw
world captures and viewmodel captures are retained and checked for visible
structure. World capture size follows its actual framebuffer metadata; the
reference viewmodel is always 960x540.

Every sequence PNG is fully decoded and checked by `verify_render_capture.py`
against the explicit reference clear color (36,48,61,255), with minimum coverage
0.01 and color tolerance 8. Both foreground and independent nonuniform-structure
checks must pass. Every sequence has contiguous zero-based frame names and all
three sidecars. Missing files, orphan sidecars, symlinks, duplicate JSON keys and
nonfinite numbers fail. The existing asymmetric `renderer_contract` executable
also runs on this Windows build; fixed quadrants and padded-width readback are
independently rechecked. This is renderer/readback orientation evidence, not a
pixel classifier proving an authored weapon is upright.

`verify_capture_telemetry.compare` compares every relative `*.gameplay.json` and
`*.time.json` against the matched legacy sequence. Fields, types, array contents,
exact decimal values and file sets must match. Nothing is excluded, rounded,
normalized or given a renderer-specific tolerance. The default fractional
cadence is deliberately not replaced with 60 Hz. These are cross-platform
Linux/OpenGL versus Windows/DX12 comparisons; any platform math or pose-checksum
difference remains a reported hard failure requiring diagnosis, not a waiver.
Lighting has no gameplay/time sidecars, so it uses its existing frozen-time and
world-light-vector checks rather than claiming a nonexistent parity comparison.

Failure of one capture or check does not suppress the remaining independent
captures. Logs, invocation arguments, binary SHA-256, run identity, companion
verification/hashes and partial results are retained. The final exit code is
nonzero if any automated check fails. Raw inputs are never rewritten, and an
existing output directory is refused so stale evidence cannot create a pass.

## Sight landmarks: explicit human review still required

[Visual-reference calibration](VISUAL_REFERENCE_MATCH.md) documents top-left
origin 960x540 coordinates with ±4 px tolerance:

- ADS rear-aperture center: **(480,270)**
- Hip front-sight guard: **(526,280)**

These are distinct features. Do not use the ADS aiming post as the hip guard,
confuse the hip rear aperture at approximately (625,293) with the guard, or treat
a displayed crosshair as a measured feature.

No supported measured-pixel detector or live sight-specific projected anchor was
found in the current DX12 capture schema. Reload-return `anchor` is a sampled weapon
translation, not an aperture/guard pixel position. Pose CRCs, finite matrices,
and an upright asymmetric fixture cannot certify these landmark coordinates.
The calibration document also describes model-specific fits: establish that the
selected current authored pose is comparable before accepting its landmark fit.

There IS historical geometric projection evidence in
`assets/authoring/ads/sight_alignment.json`, explained in
[Source-authored ADS r1](AUTHORED_ADS_REVISION.md#sight-geometry-and-limits).
Its two modeled features are the **near central post tip** and **far aperture**;
the source explicitly says the old front/rear keys are depth aliases. They were
projected near (640,360) at 1280x720. The packet records that file's SHA-256,
source geometry hash, original projected coordinates and a labeled 0.75 scaling
to 960x540. This is historical source projection context, not fresh DX12 pixel
measurement, a live actor projection, or verification that current geometry is
identical. Do not silently relabel those modeled features to satisfy the older
rear-aperture/hip-guard calibration. Resolve the feature identity during review.

`review/` contains byte-identical raw copies and separately labeled guide PNGs
for one authored ready frame and one stationary fully held ADS frame, selected
from actual telemetry. Each has matching legacy/DX12 frame names. Guides mark
the documented center and ±4 px box but perform **no detection or measurement**.
The JSON report leaves `measured_center` and `projected_center` null and explicitly
sets `automated_landmark_gate: open`. Even a green job leaves
`acceptance_complete: false`.

For review, record:

1. Run URL, exact tested revision, attempt, adapter and binary/companion hashes
2. Raw frame filenames and the measured center of each named feature; signed
   X/Y deltas from calibration and whether both absolute deltas are ≤4 px
3. The measurement method and any occlusion or uncertainty; an unmeasurable
   landmark remains open rather than passing by inference
4. Upright orientation, hands on grips, complete transitions and interruption
   return, magazine opacity, clipping, and ready/reload lighting in raw captures
5. Reviewer, outcome and any remaining real-GPU playtest/performance evidence

A future projection witness must be labeled **projection evidence**, not measured
pixels. A measured-pixel gate needs independently validated positive/negative
fixtures and calibration before it can replace this open manual check. No such
implementation or native Windows run is claimed by the synthetic harness tests.

## Running after materialization

On Windows, with same-run legacy artifacts laid out as in the workflow:

```text
python tools/run_dx12_authored.py --executable target/release/vector-range.exe --renderer-contract target/release/examples/renderer_contract.exe --root . --legacy evidence/legacy --evidence evidence/dx12-authored --timeout 900
```

The artifact is `dx12-authored-evidence-attempt-N`. Inspect `summary.json` first,
then `logs/`, `captures/`, `renderer-contract/`, and `review/`. This is a CI
evidence bundle, not a distributable game or artistic acceptance certificate.
