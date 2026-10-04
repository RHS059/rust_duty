# Remaining movement source map, 2026-10-04

This is a source-evidence checkpoint, not animation acceptance. It preserves the
149 existing R1/R2 timeline intervals without changing their IDs, bounds or text,
and adds verified native-60-fps excerpts from R3 for the agreed jump, prone,
mantle/vault and climb lanes. There are no soldier assets or game runtime edits.

## What is verified now

- R3 original restored from seven GitHub binary parts. Full file SHA-256:
  `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.
- 9,137 decoded native frames, 1280 x 720, exact `60/1` rate. All 9,136 observed
  PTS differences are 256 ticks with timebase `1/15360`. The source starts at
  PTS 0; last decoded PTS is 2,338,816; exclusive video end is 2,339,072.
- Five exact, lossless source excerpts were reopened, decoded and compared
  against the source. Every decoded YUV420P pixel hash is equal. Every output
  frame/PTS, original frame/PTS and one-based Blender frame is in its sidecar.
- Original R1/R2 annotation JSON is byte-identical to the prior private packet,
  SHA-256 `490fbf8c2177ac45c0d59c651d7821ca813f9bfab9061c784bace8ef0e788122`.
- Six tests cover bounds, missing final frame/duration, PTS gaps, all 149
  interval records, inclusive selected-excerpt semantics and exact cut metadata.

## Exact selected R3 excerpts

All ranges below are zero-based and half-open. They include a little contextual
lead/tail. A cut boundary is exact; an inferred action onset is not automatically
an exact engine input event.

| Clip | Source range | Frames |
| --- | --- | ---: |
| Low obstacle mantle/vault | [7284, 7348) | 64 |
| Slower one-hand mantle/vault | [7787, 7883) | 96 |
| Vehicle-roof climb | [8507, 8583) | 76 |
| First hip jump | [4028, 4095) | 67 |
| First prone-height entry | [2241, 2310) | 69 |

`source_map.json` records the observed phases and their remaining uncertainty.
For example, jump takeoff f4034 and visual impact f4067 are observed to about
one frame; a chosen animation-ready endpoint or previously authored range is
not revised by this source-only map. The prone entry was reviewed at a three-
frame stride, so its semantic boundaries retain +/-3 frames. All excerpt frames
are nevertheless preserved at native 60 fps.

The climbing reference depicts ascent onto a vehicle roof. No ladder/rung
animation is shown. The weapon and hands leave the screen during the middle of
the climb; those invisible tracks cannot receive measured image-space scores.
The physical muzzle is hidden in some ready/low-wall frames. Do not silently
substitute an optic, barrel projection or different landmark for it.

## Reproduce clips

Restore R3 from the source commit first:

`https://github.com/RHS059/rust_duty/tree/58dad13f51db3dd951f43f3fd7ddc3fbd020ad00/references/movement`

Run that commit's `references/movement/restore_movement_reference.py`. Then use
this checkpoint's cutter, which requires Python 3, FFmpeg and ffprobe:

```sh
python references/movement/remaining_20261004/cut_reference.py \
  --source-id R3 --source /path/to/modern_warfare_2022_movement_reference.mp4 \
  --out /path/to/verified-clips
python -m unittest discover -s references/movement/remaining_20261004 -p 'test_*.py' -v
```

The cutter verifies the original SHA-256, reads actual decoded PTS, writes only
new lossless MP4 files, reopens them, checks every frame's pixels, and writes a
verification sidecar. Existing files are validated rather than overwritten.
There is no optical flow, warping, resizing, time stretching or audio. `--only`
can select one or more exact clip IDs. MP4 encoder bytes can vary by FFmpeg
version; the native source identity and decoded-pixel comparisons are the
authoritative reproduction test.

An initial diagnostic encode with `-fps_mode passthrough` advertised N frames
but could decode N-1 because the final MP4 packet duration was missing. Those
provisional files are rejected. The current cutter supplies explicit 60-fps
packet durations and rejects a recurrence through decoded-frame, final-duration
and every-pixel checks. Only sidecars under `verification/` describe verified
outputs.

## Preserved history and remaining work

The complete prior 149-interval record is in `prior/reference_annotation.json`.
It remains historical evidence; its old workflow status and publication flags
are not current production approvals. Original R1/R2 media recovery is being
handled separately by its source owner. This checkpoint does not claim that
those unavailable native pixels were newly reviewed.

R1 `segments` and R2 `intervals` already use exclusive ends. R2
`selected_excerpts` use inclusive ends. Convert those selected ends by +1 before
cutting, then refine against actual video. The historical unified clean-interior
selection is a separate range and must not be confused with the original table.

The other labeled R3 chapters (crouch, tactical sprint, sliding and dolphin dive)
are catalogued only. A source chapter alone does not establish an unfinished
runtime task or expand the agreed authoring assignment. Chapter times are
search hints; for example, the visible edit into the vehicle scene follows
f8420, later than the metadata's nominal f8400 climbing boundary.

No scores, candidate matching, full-body transforms, collision contacts,
hidden input events, FBX success or runtime completion are asserted here.
