# Weapon comparison measurement checkpoint — 2026-10-04

Status: diagnostic tooling WIP. No new animation score or runtime approval.

## Scope

`tools/movement_comparison/` is a separate original CPU batch module and
self-contained notebook. It does not modify the existing Colab review notebook,
render Blender, fetch models, change a rig/camera, start a GPU, author source
annotations, or integrate the game. It accepts reviewed landmark evidence; it
never substitutes a tracker confidence value for actual observability.

## Verification executed

- 39 focused Python tests passed against the actual public comparison entry point.
- CLI synthetic JSON to report and residual PNG succeeded.
- Generated notebook's actual embedded CPU demo executed through result ZIP.
  Only Colab's download UI was stubbed. No actual Colab run claimed.
- No game Rust/runtime files changed; full game build and native playback not run.

Independent review found and corrected five concrete issues: underbounded
amplitude uncertainty with extrema on different frames; ambiguous angle unwrap
branches; one-frame temporal evidence; unflagged collinear third anchors; and
missing VFR maximum-speed witnesses. Follow-up corrected off-stride native
visibility gaps, duplicate phase names, and overstated decoded-map matching.
Regression tests cover each. Reports additionally retain native and per-phase
coverage, gap intervals, baseline/step uncertainty, and separate largest-speed
witnesses. Source bytes, decoded PTS values, timing metadata, and actual pixel
annotation verification are explicitly separate provenance claims.

## Research and review limits

The agreed inherited loop contract is motion-only v2 (60 points); its thresholds
are usable as diagnostics but do not automatically approve one-shot events.
The proposed event timing/join amendment and physically observable anchors/L
must be jointly frozen before score computation. This module deliberately has no
score implementation. Unsupported evidence never reduces an approval denominator.

Historical independent Elara assessment: Jump r6 78/fail. Jump r7 remains
unscored. These are reviewer assessments, not results computed by this tool.
The source-only inspection of R3 vault baseline7284 found the physical muzzle
hidden by the optic/body. Muzzle measurements are unsupported until visibility
and correspondence are demonstrated. Optic centers, charging-handle corners and
anatomical wrists are not interchangeable muzzle landmarks. Vehicle-roof climb
includes a source weapon dropout; hidden motion stays inferred and unscored.

Next evidence: jointly frozen source-visible physical anchors, native source
annotations made before candidate residuals, exact evaluated candidate projections,
whole-clip independent visual review, and an actual reproducible CPU Colab batch.
No GPU allocation is justified for these small arrays.
