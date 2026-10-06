# U2–U4 chronological annotations

Status: **diagnostic source evidence**. All three local timelines now have contiguous descriptions, including holds, resets, hidden phases and overlays. These are annotated review ranges, not certified animation cuts or accepted Actions.

| Source | Native frames | Intervals | Visually reviewed samples |
|---|---:|---:|---:|
| U2 | 3156 | 37 | 255 |
| U3 | 1840 | 25 | 123 |
| U4 | 1840 | 29 | 215 |

The source hashes match the existing pinned upload catalog. Every existing PTS CSV row was re-read: all sources retain exact 60/1 fps, time base 1/15360, native frame n at PTS n×256. U3/U4 remain independent timelines; no original-file offset is invented.

U2 separates repeated hip stance changes, ground-height transitions, ADS entry/stance changes, and four sampled hip plus four sampled ADS jump-like cycles. The previously broad jump catalog began too early: refined frames2170–2290 show a hip-ready hold; the first clearly sampled jump rise is2325–2331. Body state and foot contact remain inferred where offscreen.

U3 separates two rear car ascents, two side ascents, descents/resets, and two hood-side ADS/mount-looking sequences. Weapon mounting is not a mantle. Visible hand release toward the trunk has native adjacent witnesses16–18; the side entry contains an offscreen weapon interval and must not be scored through it.

U4 separates three ledge entries, pistol draw/settle, sustained hanging/look changes, one pull-up, out-of-bounds overlay, and two drops. First open-hand appearance245–246 and coping catch248–250 have adjacent native witnesses. The third release separation is bracketed1688–1691. Visible silhouettes support these events; invisible finger force and full-body support are unmeasured.

## Review scope and reproducibility

All chronological stride30 sheets were actually viewed, plus every listed refinement sheet. `reviewed_samples` lists the union of inspected native indices; sparse review does not establish exhaustive frame-by-frame inspection. Semantic boundaries retain conservative uncertainty. Native every-frame review was limited to explicitly listed neighborhoods.

`sample_stance_vault.py U2 --root /path/to/repo` regenerates overview sheets; refinement filenames encode start/end/stride (end exclusive). It verifies the source SHA before decoding, selects by native decoded index, and produces full-frame320×180 samples with native frame and PTS labels. JSON manifests preserve each list. The small composite `refinement_tails.jpg` displays the one-image tail pages.

No Blender files, rigs, animation curves, source Actions, existing inventory, or runtime code were modified. Coordinator can integrate these evidence files and use the uncertainty brackets for subsequent exact-cut work.
