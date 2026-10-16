# Six uploaded movement references: detailed annotations

The six source timelines now have **150 chronological intervals** covering all
14,017 native frames. Reviewers actually inspected **1,135 distinct source samples**,
with denser/native neighborhoods listed per file. Complete timeline coverage is
not a claim of every-frame visual inspection. Uncertain boundaries retain their
native-frame tolerance; these diagnostic ranges are not certified action cuts,
approved loops, candidate match scores, or animation approval.

| Source | Content | Intervals | Viewed samples | Annotation |
| --- | --- | ---: | ---: | --- |
| U1 | Visible legs, locomotion and downward ADS | 15 | 233 | [JSON](U1_annotations.json), [notes](U1_annotations.md) |
| U2 | Stance, prone, ADS and jump transitions | 37 | 255 | [JSON](U2_annotations.json) |
| U3 | Vehicle ascent, descent and separate weapon mounting | 25 | 123 | [JSON](U3_annotations.json) |
| U4 | Ledge catches, pistol hang, pull-up and drops | 29 | 215 | [JSON](U4_annotations.json) |
| U5 | Wall approach, obstruction, withdrawal and reapproach | 19 | 163 | [JSON](U5_annotations.json), [notes](U5_annotations.md) |
| U6 | Horizontal, vertical and combined look-driven swing | 25 | 146 | [JSON](U6_annotations.json), [notes](U6_annotations.md) |

[U2–U4 review notes](U2_U3_U4_review.md) provide representative native-index
witnesses and the limits of the event classifications. Source inputs remain
pinned to main commit `e14e5f7b14216f2e90ea8791a0b58c65638ea7a6`.
Each annotation retains the original file hash, local frame origin and time base.
U3 and U4 are independent timelines; no invented concatenation offset is used.

## Corrections to the historical coarse catalog

- U1 ADS entry is observed near1474±2, with alignment1488±3; the old1320
  partition was too early. The first non-gameplay overlay is native5081,
  observed against every adjacent frame5070–5100; exclude5081 onward.
- U2's old broad jump discovery window includes a long ready hold. The refined
  hold is2170–2290, with the first sampled jump rise2325–2331.
- U4 separates three ledge entries, one pull-up and two drops. Pistol hanging
  is distinct from the vehicle-roof ascent and does not automatically authorize
  a new weapon asset or gameplay feature.
- U5 withdraws, then reapproaches around950–1000 and ends close to the wall.
  The final interval is not simply backing away.
- U6 separates horizontal/vertical/combined sweeps and settling without
  inventing mouse inputs, angular velocity or a spring constant.

The old inventory's coarse windows are retained as historical discovery evidence;
its new links point here for event lookup. No prior R1/R2 interval or verified R3
cut was changed. Hidden geometry, input timing and body state remain explicitly
unobserved/inferred where applicable.

## Reproduce and verify

The two sheet scripts retain full source frames scaled uniformly for inspection,
with frame labels outside the image. Images are reference evidence only and must
not enter game distribution packages. See each script's `--help` for extraction.

```sh
python references/movement/remaining_20261004/uploaded_detailed/verify_annotations.py \
  --source-dir /path/to/uploaded_references
```

This checks exact original source hashes, all14,017 retained PTS rows, gapless
half-open intervals, sample bounds, sample manifests and declared sheet hashes.
[verification.json](verification.json) records the executed result. It verifies
source and metadata integrity, not a reviewer's semantic judgment.
