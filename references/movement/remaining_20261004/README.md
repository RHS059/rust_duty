# Remaining movement source map, 2026-10-04

This is a source-evidence checkpoint, not animation acceptance. It preserves the
149 existing R1/R2 timeline intervals without changing their IDs, bounds or text,
and adds verified native-60-fps excerpts from all three sources for the agreed jump, prone,
mantle/vault and climb lanes. There are no soldier assets or game runtime edits.

## What is verified now

- R3 original restored from seven GitHub binary parts. Full file SHA-256:
  `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.
- 9,137 decoded native frames, 1280 x 720, exact `60/1` rate. All 9,136 observed
  PTS differences are 256 ticks with timebase `1/15360`. The source starts at
  PTS 0; last decoded PTS is 2,338,816; exclusive video end is 2,339,072.
- Fourteen exact, lossless source excerpts were reopened, decoded and compared
  against the source. Every decoded YUV420P pixel hash is equal. Every output
  frame/PTS, original frame/PTS and one-based Blender frame is in its sidecar.
- Original R1/R2 annotation JSON is byte-identical to the prior private packet,
  SHA-256 `490fbf8c2177ac45c0d59c651d7821ca813f9bfab9061c784bace8ef0e788122`.
- R1 and R2 original files were restored losslessly from source commit
  `4b9236a0f6378af926d74a3bfd56781fde52c5e5`. Their SHA-256 pins match, and all
  6,822 / 7,976 decoded frames have observed PTS `n * 256`, at `1/15360`.
- Eight tests cover bounds, missing final frame/duration, PTS gaps, all 149
  interval records, inclusive selected-excerpt semantics, exact cut metadata,
  all three complete native PTS tables, and every cut sidecar against the final
  manifest and its SHA-256-pinned verification index.

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
| Ground-to-higher-camera exit | [2373, 2430) | 57 |

Additional prone source excerpts:

| Source / clip | Source range | Frames |
| --- | --- | ---: |
| R1 prone entry | [3653, 3720) | 67 |
| R2 prone entry | [4725, 4800) | 75 |
| R2 crawl forward | [4932, 5173) | 241 |
| R2 crawl backward | [5280, 5509) | 229 |
| R2 crawl right | [5628, 5767) | 139 |
| R2 crawl left short clean segment | [5844, 5899) | 55 |
| R1 crawl left supporting context | [4944, 5250) | 306 |
| R2 crawl left longer context | [5814, 6150) | 336 |

`source_map.json` records the observed phases and their remaining uncertainty.
For example, jump takeoff f4034 and visual impact f4067 are observed to about
one frame; a chosen animation-ready endpoint or previously authored range is
not revised by this source-only map. R3 prone entry was initially reviewed at a
three-frame stride; native boundary neighborhoods refine visible onset to
f2243 +/-1 and ready return to f2300 +/-2. Its middle phase retains +/-3 frames.
All excerpt frames are preserved at native 60 fps.

Native review refines the R1-44 transition from the old [3660, 3708) grid to
visible hand departure f3659 +/-1 and ready return f3714 +/-2. R2 S059 similarly
has departure f4730 +/-1 and ready return f4790 +/-2. These are explicit overlays,
not silent rewrites of adjacent historical intervals. All frames in both focused
entry neighborhoods were inspected.

The four R2 hip crawling cuts preserve the original selected-excerpt interiors
with the inclusive end corrected by +1. Native endpoint neighborhoods and
surrounding movement were checked. They are source excerpts, not certified
closed loops. The 55-frame clean left segment cannot prove a complete loop;
longer R1/R2 left context is also provided. R1 weapon landmarks repeatedly leave
the screen. The longer R2 left context includes independent moving players in
the background; do not use them as camera/static-world landmarks. Foreground
weapon clipping still needs explicit per-frame masks.

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

For R1/R2, use the source transfer directory at commit
`4b9236a0f6378af926d74a3bfd56781fde52c5e5` and its explicit per-video manifests,
then run the same cutter with `--source-id R1` or `--source-id R2`.
`review_samples.json` records exactly which native sample images were visually
reviewed, and `make_review_sheets.py` regenerates their labeled grids with a
supplied TTF font. These grids are review aids, never quantitative input.

An initial diagnostic encode with `-fps_mode passthrough` advertised N frames
but could decode N-1 because the final MP4 packet duration was missing. Those
provisional files are rejected. The current cutter supplies explicit 60-fps
packet durations and rejects a recurrence through decoded-frame, final-duration
and every-pixel checks. Only sidecars under `verification/` describe verified
outputs.

## Preserved history and remaining work

The complete prior 149-interval record is in `prior/reference_annotation.json`.
It remains historical evidence; its old workflow status and publication flags
are not current production approvals. All original media are now recovered and
their full native PTS revalidated. This focused pass does not claim that every
historical interval boundary was visually rereviewed: existing locomotion
annotations are preserved, and the remaining-prone excerpts receive explicit
new observations and native transition refinements.

R1 `segments` and R2 `intervals` already use exclusive ends. R2
`selected_excerpts` use inclusive ends. Convert those selected ends by +1 before
cutting, then refine against actual video. The historical unified clean-interior
selection is a separate range and must not be confused with the original table.

The other labeled R3 chapters (crouch, tactical sprint, sliding and dolphin dive)
are catalogued only. A source chapter alone does not establish an unfinished
runtime task or expand the agreed authoring assignment. Chapter times are
search hints; for example, the visible edit into the vehicle scene follows
f8420, later than the metadata's nominal f8400 climbing boundary.

Prone ADS directions are catalogued as secondary evidence and integration/review
cases for the existing ADS layer. They do not silently create four new authored
Actions. An observed mismatch should produce a bounded proposal. Repeated R3
action search windows are separately labelled coarse; they are not final cuts.

No scores, candidate matching, full-body transforms, collision contacts,
hidden input events, FBX success or runtime completion are asserted here.
