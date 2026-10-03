# Source-authored ADS r1 verification

Built on lighting PR #14 (`d6bafa28b496ef6dac138fc7eb7949ca72f85f8f`), preserving
its shader/world lighting changes and the frozen walk/locomotion source.

## Delivered

- Editable, packed `assets/authoring/ads/ads.blend` with three new versioned
  Actions/NLA clips, source registry, repeatable authoring/export scripts and
  full original-source preservation audits
- Source-keyed 0.250-second entry/exit and an exactly static aimed hold, using
  the existing weapon-driven arm rig and unchanged camera projection
- Native reversible gameplay controller, complete semantic bindings and strict
  source seam/companion validation; original simulation timings remain unchanged
- Canonical 47-clip runtime pack with original walk44 records unchanged and the
  exact canonical skin/rigid companions, rebuilt by same-run CI for complete builds

## Evidence actually executed

- Original-source Blender comparison: all 62 original Actions, all old NLA,
  arm/weapon geometry, weights, rest rig, bindings, camera, drivers and packed
  textures preserved; only three Actions/NLA tracks added
- Native source sweep: 723 samples at 480 Hz; exact joins across all bones, rigid
  actors and deformed arm vertices; maximum wrist solve error 0.000584 mm
- Blender→FBX→actual Rust sampler: 75 independent on/off-key witnesses across all
  three clips, maximum skin error 5.25 μm and rigid vertex error 4.48 μm
- Independent decoded endpoint audit: maximum translation difference 0.291 μm,
  angular difference 0.00000268 rad, scale component difference 0.000000596
- 467 Rust tests with real-asset contracts enabled, strict all-target Clippy,
  rustfmt and whitespace checks passed
- 134 Python tests passed with one optional Blender smoke skipped; that separate
  Blender-enabled suite then passed all 16 tests
- Real-asset gameplay replay: 524 evaluated ADS poses and unchanged gameplay
  movement, accuracy fraction, reload/shot deadlines, ammunition and shot outcomes
- Complete staged Linux game: 553 actual native rendered frames, all seven expected
  presentation routes, both authored reversals, walking, sprint, shots and reload,
  ADS reacquisition and final ready; 3 shots, final 30/69 rounds, no renderer failure

The native sequence is available in [the video](evidence/ads-r1/authored-ads-gameplay.mp4),
[contact sheet](evidence/ads-r1/ads-gameplay-contact-sheet.jpg) and
[verification record](evidence/ads-r1/native-verification.json).

## Sight geometry and limits

The supplied geometry models a near central post tip and an open far circular
aperture. It does not model a central post inside the far aperture. The authored
pose aligns those existing landmarks, without inventing or changing geometry.
They project to (640,360) within 0.000123 px at 1280×720; a ray 0.1 px above the
near tip is clear, while 0.5 px below hits the modeled post. Exact vertex/world/
camera/pixel evidence and a labelled native source crop are in
`assets/authoring/ads/sight_alignment.json` and `renders/sight_alignment_annotated.png`.

Walk-to-ADS and reload ownership retain explicit WIP whole-model cuts. Native
reversals preserve pose but reverse velocity immediately. Hidden finger contact,
every possible body intersection, artistic approval and native Windows gameplay
are not certified. Linux software rendering was used; the cloud has no physical
audio device. Windows CI build success is reported separately after completion.
