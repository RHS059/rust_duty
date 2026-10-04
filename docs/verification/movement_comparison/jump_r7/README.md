# Jump r7 receiver-point diagnostic

No score. Elara's earlier r6=78 assessment is unchanged; this is independent
measurement of r7, not approval. Physical correspondence and the event rubric
remain proposed. The COD rifle and native HK416 geometry differ.

## Verified artifact and review scope

- Source R3: SHA256 `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.
- Original native r7 Eevee PNG archive, all65 members reopened and hash-verified:
  `12e5aee93e50a2bc2f5b1763ee5e5afee9b4fe2477102cd07db85469e8a7e504`.
- Hal's evidence commit `e9317f90ea171976306e2f17c111325d948ea357`, directory
  `assets/authoring/jump/review/r7/`. Existing capture reused, no rerender.
- All100 reference frames4014–4113 retained with native 60Hz timing. Candidate
  ready holds and the two unused duplicate seam endpoints follow the original
  published map; no retiming or frame-specific registration.
- Independent raw viewport comparison at20Hz plus every native frame4063–4096:
  57 unique pairs. One charging-handle point inspected on all100 native reference
  and100 mapped candidate crops. Normal/slow playback is not claimed.

## Measured evidence

One provisional homologous landmark: upper outer right corner of the transverse
charging-handle body. Source seed[1002,549]; native candidate seed[1006,485].
The annotated actual image corner is observed, while exact model correspondence
is not yet jointly frozen. Source uncertainty6px; candidate2px. Sourceframe4048
has8px uncertainty following direct inspection of a1.0326px LK forward/backward
warning. All other point predictions stayed attached to the observed corner in
native crop review. Those bounds are visual estimates, not statistical CIs.

With source/candidate pixel scales1 and baseline sourceframe4033:

- Raw vector RMS68.94px,p95 80.82,max82.91. This retains fixed framing differences.
- Mean-centered vector RMS6.66px,p95 13.40,max16.74.
- Fixed pre-event-baseline residual RMS6.79px,p95 13.64,max16.56 atframe4045.
- Horizontal motion amplitude source57.95px,candidate53.72px.
- Vertical motion amplitude source154.10px,candidate170.40px.
- Point visibility coverage100/100 on both sides. This is **one point's** coverage,
  not coverage of the complete weapon rubric.

The largest baseline residual occurs around4042–4047, where the candidate corner
moves farther down. Another residual appears in the held-ready tail while the
reference continues small motion near4110–4113. Most baseline residual uncertainty
bounds are16px, and amplitude-error bounds20px. Do not interpret those small
residuals as definitive artistic failure or revise the protected takeoff/air
without further support. Landing/recovery appears close for this specific point.
The sampled full viewport review showed no new disappearance or reset, but this
is not a full contact, camera, model, axis, or runtime acceptance.

## Unsupported evidence remains visible

The physical source muzzle is hidden. A third physically agreed noncollinear
anchor and normalization L are unavailable. Their observations remain unsupported,
not replaced by an optic/sight/wrist coordinate. No angle or normalized spatial
threshold is awarded; no denominator is reduced and no percentage is computed.
An unobserved firing wrist remains outside the source comparison.

## Reproduce

Install the optional standard-registry tracker dependency
`opencv-python-headless==4.11.0.86` into an isolated environment with NumPy. Run:

```sh
python3 tools/movement_comparison/prepare_jump_receiver_review.py \
  --source /path/to/exact/R3.mp4 \
  --native-evidence /path/to/restored/r7 \
  --output /tmp/jump-point-review
```

This regenerates uncertain tracker proposals and all native point witnesses.
It never promotes proposals into reviewed observations. Compare the saved manual
review decisions in `receiver_raw_input.json`, and inspect any regenerated pixel
witnesses before adopting a track. Exact hashes and100-frame map are mandatory.
The observer made the decisions before computing candidate residuals; no residual
was used to delete a source frame or move an anchor.

```sh
python3 tools/movement_comparison/compare.py \
  docs/verification/movement_comparison/jump_r7/receiver_raw_input.json \
  --output /tmp/jump-r7-raw --plot --pts-map /path/to/R3-decoded-pts.json
```

The compact decoded map retains global frame indices and observed PTS through4113,
plus source identity/time-base metadata. It was checked against the complete9137
frame source decode. Video-byte verification is true only in the separately
recorded local run that supplied the exact source and native archive bytes. A
JSON-only Colab run must keep those byte-verification flags false.
