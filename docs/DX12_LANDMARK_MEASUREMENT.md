# DX12 sight-landmark measurement (fail-closed)

`tools/review_dx12_landmarks.py` compares **explicitly measured** raw-pixel sight
landmarks on DX12 captures with the calibration in
[VISUAL_REFERENCE_MATCH.md](VISUAL_REFERENCE_MATCH.md). It complements the open
landmark section of [DX12_CAPTURE_REVIEW.md](DX12_CAPTURE_REVIEW.md); it does not
replace that packet, its guides, or any human gate.

| Landmark id | Pose | Feature | Calibrated center (960x540, top-left origin) |
| --- | --- | --- | --- |
| `ads-rear-aperture-center` | ads | rear-aperture center | (480,270) |
| `hip-front-sight-guard` | hip | front-sight guard | (526,280) |

A measurement is within tolerance only when **both** absolute axis deltas are
≤ 4 px (inclusive). Coordinates are pixel-index units on the unscaled 960x540
grid: 0 ≤ x ≤ 959, 0 ≤ y ≤ 539; sub-pixel values are allowed.

## What the tool will never do

- Detect, project, estimate or infer a landmark. There is no detector.
- Substitute the calibration target for a missing measurement. A measured value
  that exactly equals the target is reported `unaccepted-coincides-with-target`
  because it cannot be distinguished from a copied target.
- Treat a guide overlay, crosshair or the packet's ±4 px box as evidence.
  `*-guide.png` files, `image_role` other than `raw`, and (with `--packet`) any
  file whose SHA-256 matches a listed guide are rejected.
- Accept `unmeasurable` or `uncertain` outcomes. They are recorded with their
  reason and keep the gate open.
- Modify images. PNGs are opened read-only and re-hashed after decoding.
- Close human M2 capture approval or M4 hardware playtest approval. Every report
  has `human_m2_approval: open`, `human_m4_approval: open`,
  `acceptance_complete: false`.

## Measurement file

Schema `rust-duty-dx12-landmark-measurements/v1`. Unknown fields, duplicate JSON
keys and `NaN`/`Infinity` literals are rejected.

```json
{
  "schema": "rust-duty-dx12-landmark-measurements/v1",
  "evidence": {"repository": "RHS059/rust_duty", "run_id": "<digits>", "run_attempt": "<digits>",
               "source_commit": "<40-hex tested revision>",
               "artifact_id": "<optional digits>", "artifact_name": "<optional>",
               "artifact_zip_sha256": "<optional 64-hex>"},
  "measurements": [{
    "image": "review/dx12-ads-raw.png",
    "image_sha256": "<64-hex of that exact file>",
    "image_size": [960, 540],
    "frame": {"source_frame": "0040.png", "backend": "dx12", "pose": "ads"},
    "landmark": "ads-rear-aperture-center",
    "outcome": "measured",
    "measured_center": [481.5, 269.0],
    "reviewer": "<who measured>",
    "provenance": {"method": "manual-raw-pixel", "tool": "<viewer/zoom/script used>",
                   "image_role": "raw", "measured_at": "2026-10-05T16:30:00Z",
                   "notes": "<optional occlusion/uncertainty notes>"},
    "target_values_not_used": true
  }]
}
```

- `outcome`: `measured` requires exactly one `[x, y]`; `unmeasurable` / `uncertain`
  require a non-empty `reason` and must carry **no** coordinates.
- `provenance.method`: only `manual-raw-pixel` or `scripted-raw-pixel`. Methods
  naming overlays, guides, targets, calibration, projection, inference, detectors
  or estimates are rejected. `measured_at` needs an explicit timezone.
- One entry per backend and landmark. Two entries for the same slot, or one image
  hash claimed by two frame identities, is ambiguous and invalidates the review.
- Landmark ids are strict. Documented confusables (ADS aiming/front post, hip rear
  aperture near (625,293), crosshair, the historical `near-central-post-tip` /
  `far-aperture` projection features) are rejected with an explanation, never
  aliased.

## Identity checks

Always: the image path must be relative inside `--root`, not traverse a symlink,
match `image_sha256`, decode as PNG and be exactly 960x540. PNG framing is
checked with `verify_render_capture._verify_png_framing` before Pillow decode,
so a stream missing only its final IEND CRC is rejected (Pillow verify/load
alone would accept it). Landmark ids must be strings; non-string values such as
`[]` and coordinates outside the finite float range (for example `10**400`) are
documented invalid reports with exit 2, never uncaught `TypeError` /
`OverflowError`. Invalid UTF-8 or other parse failures write their invalid
report through the same protected `--output` writer: an already-existing output
file is left untouched and the process still exits 2.

`--packet <review>/landmark-review.json` (from the authored DX12 packet): each
annotated hash must be a packet raw record whose backend, pose, source frame,
feature, calibrated center and 4 px tolerance match the annotation.

`--frames dx12=<captures> [--frames legacy=<legacy captures>]`: the annotated
image must be byte-identical to `<captures>/<source_frame>`, its `.png.json`
must report 960x540 (and `Dx12` for the dx12 backend), and its
`.png.gameplay.json` must identify the same review frame the packet selects:
`route == "ready"` for hip; `route == "ads.hold"` with numeric `simulation_ads == 1`
for ads. Capture sidecars that mark raw render targets
(`diagnostic_raw_target: true` or
`alpha_representation: "raw-associated-emissive-rgba8"`) are rejected; opaque
display sidecars (`diagnostic_raw_target: false`,
`alpha_representation: "opaque-rgba8-rgb-preserved-over-black"`) are accepted.
Wrongly typed fields are also invalid reports: string `"true"` for
`diagnostic_raw_target`, and string `"1"` for sidecar `ads` or gameplay
`simulation_ads`, instead of real JSON boolean / number values. When present,
numeric sidecar `ads` must match the pose (0 for hip, 1 for ads).

## Usage

```text
python tools/review_dx12_landmarks.py template --packet evidence/review/landmark-review.json --root evidence/review --output measurements.json
# fill outcome, measured_center, reviewer, provenance, target_values_not_used by hand
python tools/review_dx12_landmarks.py review measurements.json --root evidence/review \
    --packet evidence/review/landmark-review.json --frames dx12=evidence/captures/<sequence> \
    --output landmark-measurement-report.json
```

The template leaves coordinates and outcome `null`; submitted unchanged it is
rejected. `--output` refuses to overwrite an existing file. `--require-backend`
(default `dx12`, repeatable) selects which backends must have both landmarks.

| Report `status` | `automated_landmark_gate` | Exit |
| --- | --- | --- |
| `within-tolerance` (both required landmarks measured, accepted) | `measured-within-tolerance` | 0 |
| `open` (missing, unmeasurable, uncertain or target-coincident) | `open` | 1 |
| `outside-tolerance` (any required measurement > 4 px on an axis) | `failed` | 1 |
| `invalid` (any rejected input; no partial pass) | `open` | 2 |

Exit 0 means only that the measured-pixel comparison passed for the named raw
frames. Orientation, grips, transitions, magazine opacity, clipping, lighting,
human M2 approval and the M4 real-GPU playtest are still separate reviews.

## Raw targets versus display images

The renderer contract writes two kinds of PNG; their `.png.json` sidecars say
which (`diagnostic_raw_target`, `alpha_representation`):

- **Display/main captures** (`opaque-rgba8-rgb-preserved-over-black`, alpha 255):
  safe to view as ordinary images.
- **Raw render targets** (`raw-associated-emissive-rgba8`,
  `diagnostic_raw_target: true`): associated (premultiplied) RGBA that may hold
  emission with zero coverage, e.g. `[127,0,0,0]`. Ordinary viewers treat PNG as
  straight alpha and will hide or misweight such pixels. Inspect the bytes, not
  the viewer rendering.

Landmark measurement uses only the 960x540 viewmodel captures, which are opaque
display images. Raw targets are never landmark inputs; when `--frames` is used,
a sidecar that still carries raw-target metadata fails the review as `invalid`
(exit 2) instead of producing `measured-within-tolerance`.

## 100% / 200% text raster checks: scope

`renderer_contract` draws `"Ag"` with the built-in fixed ProggyClean raster at
16 px (100%) and 32 px (200%) into 64x48 and 128x96 offscreen targets, checks
`measure_text("Ag ")` returns exactly (21,11,8)×scale and that ink bounds are
exactly `[11,12,23,23]`×scale. It proves that physical-pixel text sizing scales
by an integer factor and the ink lands at the expected pixel bounds on the tested
adapter. It does **not** prove native window DPI handling (no window, no OS scale
factor, no per-monitor DPI change), hinting/anti-aliasing quality (the 200%
capture is pixel-identical to a nearest-neighbour 2× of the 100% capture and has
only two colors), non-integer scales such as 125%/150%, UI layout or HUD text, or
human readability approval.

## Tests

`python -m unittest discover -s tools -p test_dx12_landmarks.py -v` uses only
synthetic PNGs and JSON. Those tests are not evidence of any native capture.
