# DX12 landmark review manifest (template, unfilled)

This is the per-scenario manifest a reviewer fills in **after** a native
`dx12-authored-evidence-attempt-N` packet exists. Every coordinate, hash, run
identity and outcome below is deliberately blank (`____` or `null`). Nothing in
this file is a measurement, and copying a calibration target into a measured
field is never allowed.

It is written against the harness in `tools/run_dx12_authored.py` and the
workflow `.github/workflows/wgpu-dx12-authored.yml` at
`72663e2b18dda818c800dec96af1ce452dbdd4da`. Measurement entries are checked by
`tools/review_dx12_landmarks.py` (see
[DX12_LANDMARK_MEASUREMENT.md](DX12_LANDMARK_MEASUREMENT.md)); the open review
it supports is described in [DX12_CAPTURE_REVIEW.md](DX12_CAPTURE_REVIEW.md).
If the harness changes capture naming, packet fields or frame selection after
that revision, re-check this file against it before filling anything in.

Two packet schema revisions exist. Record which one the artifact uses in
section 1 and fill only the rows for that revision; never back-fill fields a
packet does not contain.

- **72663 packet** (harness at `72663e2`, including the current native
  `72663` authored run): raw copies have no sidecars, and records carry
  `backend`, `pose`, `source_frame`, `raw`, `raw_sha256`, `guide`, `feature`,
  `calibrated_center`, `tolerance_px`, `measured_center`, `projected_center`.
- **Hal272 packet** (the raw-sidecar binding integrated in Aella's local
  checkpoint `34482609a51423cdd99ade2f7e3ba3329053f508`; not yet on a pushed
  revision): each `review/<label>-<pose>-raw.png` also has an exact byte copy of
  its source frame's primary `.png.json` beside it, and each record adds
  `source_role`, `actual_backend`, `source_sidecar`, `raw_sidecar` and
  `raw_sidecar_sha256`. Re-check these names against the pushed revision that
  first contains them.

Gates this manifest **cannot** close: human M2 capture approval and M4 real-GPU
hardware playtest approval (see [DX12_PLAYTEST_CHECKLIST.md](DX12_PLAYTEST_CHECKLIST.md)).
A `within-tolerance` landmark report closes only the measured-pixel comparison
for the four named raw frames.

## 1. Evidence pins

Fill from the actual run. Copy hashes from files; do not retype them.

| Field | Where it comes from | Value |
| --- | --- | --- |
| Repository | fixed | `RHS059/rust_duty` |
| Tested revision (40-hex) | `summary.json` `source_commit` (`GITHUB_SHA`) | `____` |
| Run ID | `summary.json` `run_id` | `____` |
| Run attempt N | `summary.json` `run_attempt` | `____` |
| Run URL | Actions UI | `____` |
| DX12 artifact name | `dx12-authored-evidence-attempt-N` | `____` |
| DX12 artifact ID | GitHub artifact API | `____` |
| DX12 artifact ZIP SHA-256 | downloaded ZIP | `____` |
| `executable_sha256` | `summary.json` | `____` |
| `renderer_contract_sha256` | `summary.json` | `____` |
| Renderer identity line | `logs/ads-gameplay/stdout.log` or `stderr.log` | `____` (must equal `renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver`) |
| Shader compiler line | same logs | `____` (must equal `renderer dx12_shader_compiler=Fxc`) |
| Companion verification | `summary.json` check `validated-same-run-companions` `result` | passed / failed: `____` |
| Legacy ADS artifact | `native-gameplay-ads-evidence-attempt-N`, same run and attempt | ID `____`, ZIP SHA-256 `____` |
| Packet schema revision | `72663` or `Hal272` (see above) | `____` |
| Landmark tool revision | commit containing `tools/review_dx12_landmarks.py` used | `____` |

The legacy ADS sequence is **not** inside the DX12 artifact. Download the
matching `native-gameplay-ads-evidence-attempt-N` from the same run and attempt;
its contents are the folder the harness used as `evidence/legacy/ads-gameplay`.
A legacy artifact from another run or attempt makes the review Blocked.

## 2. Preconditions from `summary.json`

Record each check exactly as named in `summary.json` `checks[].name`. A missing
row is `Not run`, never `Passed`.

| Check name | Passed / Failed / Not run | Error text if failed |
| --- | --- | --- |
| `validated-same-run-companions` | `____` | `____` |
| `orientation-renderer-contract` | `____` | `____` |
| `ads-gameplay/capture` | `____` | `____` |
| `ads-gameplay/finite-images` | `____` | `____` |
| `ads-gameplay/existing-validator` | `____` | `____` |
| `ads-gameplay/strict-gameplay-time-parity` | `____` | `____` |
| `ads-placement-existing-validator` | `____` | `____` |
| `landmark-guides-not-a-landmark-pass` | `____` | `____` |
| Top-level `passed` | `____` | |
| Top-level `acceptance_complete` | must read `false` | `____` |
| Top-level `automated_landmark_gate` | must read `open` | `____` |

Landmark measurement may start only if `ads-gameplay/capture` and
`landmark-guides-not-a-landmark-pass` both passed, so `review/` exists. If either
failed, mark section 3 **Blocked** with the error text and stop. A failure in
another check does not block measurement, but it must be recorded here and it
keeps acceptance open.

## 3. Scenario `ads-gameplay`: the only landmark scenario

The harness builds landmark guides only for `captures/ads-gameplay`
(`--capture-sequence=gameplay-ads`, default 60000/1001 cadence, no
`--capture-hz`). It picks two DX12 frames by telemetry and copies the
same-named legacy frames:

- **hip**: the first `*.gameplay.json` in sorted order with `route == "ready"`.
- **ads**: the first with `route == "ads.hold"`, `run_weight == 0`,
  `speed == 0` and `simulation_ads == 1`.

### 3.1 Packet files (`review/`)

| File | Role |
| --- | --- |
| `landmark-review.json` | packet; pass it as `--packet` |
| `dx12-hip-raw.png`, `legacy-hip-raw.png`, `dx12-ads-raw.png`, `legacy-ads-raw.png` | byte-identical raw copies; the only measurable images |
| `<label>-<pose>-raw.png.json` (Hal272 packet only) | byte-identical copy of the source frame's primary `.png.json`; absent in a 72663 packet |
| `dx12-hip-guide.png`, `legacy-hip-guide.png`, `dx12-ads-guide.png`, `legacy-ads-guide.png` | guide overlays; **never** measured |
| `historical-source-sight-alignment.json` | historical projection context only |

Packet fields to transcribe per record (from `landmark-review.json`
`records[]`): `backend`, `pose`, `source_frame`, `raw`, `raw_sha256`, `guide`,
`feature`, `calibrated_center`, `tolerance_px`. In the packet,
`measured_center` and `projected_center` must still be `null`, and top-level
`status` and `automated_landmark_gate` must read `open`.

Hal272 packet only, per record:

| Field | Must be | hip DX12 | hip legacy | ads DX12 | ads legacy |
| --- | --- | --- | --- | --- | --- |
| `source_role` | `dx12-under-review` for dx12, `legacy-comparison-only` for legacy | `____` | `____` | `____` | `____` |
| `actual_backend` | `Dx12` for dx12, `OpenGl` for legacy | `____` | `____` | `____` | `____` |
| `source_sidecar` | `<source_frame>.json` | `____` | `____` | `____` | `____` |
| `raw_sidecar` | `<raw>.json` | `____` | `____` | `____` | `____` |
| `raw_sidecar_sha256` | SHA-256 of both `raw_sidecar` and the capture's `<source_frame>.json` | `____` | `____` | `____` | `____` |

Guide overlays never have a sidecar; a `*-guide.png.json` makes the slot
Blocked. A legacy record stays comparison-only: no sidecar, label or role
substitution turns it into DX12 evidence. In a 72663 packet these five fields
are absent; record them as `absent`, not blank and not inferred.

### 3.2 Frame identity (fill from the captures, not from the packet)

For each pose, open the sidecars beside `captures/ads-gameplay/<source_frame>`
(DX12) and the same name in the legacy ADS artifact.

| Field | Sidecar | hip DX12 | hip legacy | ads DX12 | ads legacy |
| --- | --- | --- | --- | --- | --- |
| `source_frame` | packet | `____` | `____` | `____` | `____` |
| `raw_sha256` (must equal SHA-256 of source frame) | packet / file | `____` | `____` | `____` | `____` |
| `width` x `height` (must be 960x540) | `.png.json` | `____` | `____` | `____` | `____` |
| `requested` / `backend` / `adapter` | `.png.json` | `____` | `____` | `____` | `____` |
| `ads` (0 for hip, 1 for ads) | `.png.json` | `____` | `____` | `____` | `____` |
| `hfov` | `.png.json` | `____` | `____` | `____` | `____` |
| `route` | `.png.gameplay.json` | `____` | `____` | `____` | `____` |
| `segment` | `.png.gameplay.json` | `____` | `____` | `____` | `____` |
| `simulation_time` | `.png.gameplay.json` | `____` | `____` | `____` | `____` |
| `simulation_ads` | `.png.gameplay.json` | `____` | `____` | `____` | `____` |
| `run_weight` (ads must be 0) | `.png.gameplay.json` | `____` | `____` | `____` | `____` |
| `speed` (ads must be 0) | `.png.gameplay.json` | `____` | `____` | `____` | `____` |
| `clip` / `native_clip_seconds` | `.png.gameplay.json` | `____` | `____` | `____` | `____` |
| `elapsed_seconds` / `sampling_hz` | `.png.time.json` | `____` | `____` | `____` | `____` |

The legacy `backend` is the OpenGL value the legacy lane wrote; record it as
found. With the landmark tool at `762a979` or later,
`review_dx12_landmarks.py --frames` requires the harness's stationary fully held
ADS selection: `route == "ads.hold"` and finite numeric `simulation_ads == 1`,
`run_weight == 0` and `speed == 0`. Missing, boolean, string, nonfinite or
nonzero values make the report `invalid`. With an older tool revision
(`fd4f254`), `run_weight` and `speed` are not checked, so confirm both by hand
for the ads frame. Either way, a mismatch makes the slot Blocked.

### 3.3 Landmark slots

Calibration is from [VISUAL_REFERENCE_MATCH.md](VISUAL_REFERENCE_MATCH.md):
both absolute axis deltas must be at most 4 px on the unscaled 960x540 grid,
top-left origin. The deltas are computed by the tool, not by hand.

| Slot | Landmark id | Raw image | Required by default | Outcome | Measured center | Reason (if not measured) |
| --- | --- | --- | --- | --- | --- | --- |
| dx12 hip | `hip-front-sight-guard` | `dx12-hip-raw.png` | yes | `____` | `[____, ____]` | `____` |
| dx12 ads | `ads-rear-aperture-center` | `dx12-ads-raw.png` | yes | `____` | `[____, ____]` | `____` |
| legacy hip | `hip-front-sight-guard` | `legacy-hip-raw.png` | only with `--require-backend legacy` | `____` | `[____, ____]` | `____` |
| legacy ads | `ads-rear-aperture-center` | `legacy-ads-raw.png` | only with `--require-backend legacy` | `____` | `[____, ____]` | `____` |

Outcome is one of `measured`, `unmeasurable`, `uncertain`. Only `measured`
carries coordinates. Do not measure the ADS aiming or front post, the hip rear
aperture near (625,293), a crosshair, or the historical `near-central-post-tip`
/ `far-aperture` features; the tool rejects those ids.

Per slot, also record: reviewer `____`, method (`manual-raw-pixel` or
`scripted-raw-pixel`) `____`, viewer or script and zoom `____`, `measured_at`
with timezone `____`, occlusion or uncertainty notes `____`.

### 3.4 Measurement file skeleton

Generate the real file with the tool so hashes and frame names come from the
packet, then fill it by hand:

```text
python tools/review_dx12_landmarks.py template --packet <artifact>/review/landmark-review.json --root <artifact>/review --output measurements.json
```

Its shape, with every value still unfilled (image paths are relative to
`--root <artifact>/review`):

```json
{
  "schema": "rust-duty-dx12-landmark-measurements/v1",
  "evidence": {"repository": null, "run_id": null, "run_attempt": null,
               "source_commit": null},
  "measurements": [
    {"image": "dx12-hip-raw.png", "image_sha256": null, "image_size": [960, 540],
     "frame": {"source_frame": null, "backend": "dx12", "pose": "hip"},
     "landmark": "hip-front-sight-guard", "outcome": null, "measured_center": null,
     "reviewer": null,
     "provenance": {"method": null, "tool": null, "image_role": "raw", "measured_at": null},
     "target_values_not_used": null}
  ]
}
```

The tool emits one entry per packet raw record (four in total). Optional
evidence keys `artifact_id`, `artifact_name` and `artifact_zip_sha256` should be
added from section 1. Submitted unchanged, the file is rejected.

### 3.5 Review commands

```text
python tools/review_dx12_landmarks.py review measurements.json --root <artifact>/review --packet <artifact>/review/landmark-review.json --frames dx12=<artifact>/captures/ads-gameplay --frames legacy=<legacy-ads-artifact> --output landmark-measurement-report.json
```

Add `--require-backend dx12 --require-backend legacy` only if the legacy slots
are being gated too. `--frames` is mandatory for both packet revisions. In a
72663 packet the raw copies have no sibling `.png.json`, so `--frames` is the
only binding to the capture sidecars. In a Hal272 packet the copied sibling
`.png.json` gets the tool's typed raw/display checks, but the original capture
telemetry (`.png.gameplay.json`, including `route`, `simulation_ads`,
`run_weight` and `speed`) is read only through `--frames`; do not omit it.

| Report field | Value |
| --- | --- |
| `status` | `____` |
| `automated_landmark_gate` | `____` |
| `missing` | `____` |
| `errors` | `____` |
| Exit code | `____` |
| Report SHA-256 | `____` |

## 4. Other scenarios: no landmark measurement defined

These captures have no calibrated landmark and no packet raw copies. Do not
apply the (480,270) or (526,280) targets to them, and do not record landmark
coordinates for them. They carry only human M2 visual items. Frame ranges are
the reviewer's choice and must use the actual capture names.

| Scenario | Capture folder | Cadence | Automated checks to record | Human items (frames reviewed) |
| --- | --- | --- | --- | --- |
| `jump-gameplay` | `captures/jump-gameplay/` | 60 Hz | `/capture`, `/finite-images`, `/existing-validator` (`verify_jump_capture.py`), `/strict-gameplay-time-parity` | orientation, grips, takeoff/landing transitions, ADS/reload interruption: `____` |
| `reload-gameplay` | `captures/reload-gameplay/` | default | same four, `verify_gameplay_capture.py` | magazine opacity, grips, return to locomotion: `____` |
| `walk-gameplay` | `captures/walk-gameplay/` | default | same four, `verify_gameplay_walk_capture.py` | start, loop, stop, clipping: `____` |
| `ads-gameplay` | `captures/ads-gameplay/` | default | section 2 | entry/hold/exit, reversals, interruptions: `____` |
| `ads-offset` | `captures/ads-offset/` | default, settings `ads-offset.cfg` | same four plus `ads-placement-existing-validator` | offset placement looks deliberate, no clipping: `____`. Calibrated landmarks do **not** apply: the saved XYZ offset moves the viewmodel. |
| `layered-30` / `layered-60` | `captures/layered-30/`, `captures/layered-60/` | 30 / 60 Hz | `/capture`, `/finite-images`, `/strict-gameplay-time-parity`, plus `layered-rates-existing-validator` | four-direction blending, foot/weapon stability: `____` |
| `reload-return` | `captures/reload-return/` | 60 Hz | same four, `verify_reload_return_capture.py` | complete/cancel/restart return. The `anchor` field is a weapon translation, not a landmark: `____` |
| lighting | `captures/lighting/{ready,reload}_{front,right,back,left,up,down}.png` and `.world.png` | frozen | `lighting/<pose>_<view>` x12, `lighting-existing-validator-and-images` | ready/reload lighting from `ready_directions.png`, `reload_directions.png`, `ready_world_directions.png`: `____` |
| renderer contract | `renderer-contract/quadrant.png`, `readback-width-65.png` | n/a | `orientation-renderer-contract` | orientation evidence only; does not prove authored weapon is upright: `____` |

Every sequence frame is `NNNN.png` (zero-based, contiguous) with `.png.json`,
`.png.time.json` and `.png.gameplay.json`; validators may add
`verification.json`. Logs for each are under `logs/<scenario>/` and
`logs/<scenario>-validator/`.

## 5. Sign-off (left open)

| Gate | Owner | Status | Reviewer | Date (with timezone) | Notes |
| --- | --- | --- | --- | --- | --- |
| Measured-pixel landmark comparison (section 3) | reviewer | open | `____` | `____` | `____` |
| Human M2 capture approval (section 4 and raw `ads-gameplay` frames) | human | open | `____` | `____` | `____` |
| Human M4 real-GPU playtest | human, via DX12_PLAYTEST_CHECKLIST.md | open | `____` | `____` | `____` |

The M4 checklist's `PLAYTEST_DX12.cmd` preview launcher is integrated in the
same local checkpoint `34482609`; until it is on a pushed revision and in the
staged preview artifact, the checklist's Blocked rule for a missing or
different launcher still applies.

`acceptance_complete` stays `false` until all three rows are closed by the
people who own them. This manifest never closes M2 or M4 on its own.
