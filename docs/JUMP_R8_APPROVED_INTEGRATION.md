# Approved Jump r8 landing integration

This revision changes the generated `jump_land` runtime clip to the exact
approved two-key landing correction. It leaves the stable runtime slot,
ground-contact clock, r7 takeoff/air, physics and presentation layering intact.
PR20's source branch and PR60's original code checkpoint are not rewritten.

## Approval and identity

[Elara's final review](https://github.com/RHS059/rust_duty/pull/20#pullrequestreview-5511992220)
on 2026-10-14 recommends **82/pass**, with no measured blocking defects, for
`jump_land_r8_ease_candidate`. The user authorized game integration if Elara
says it is good. The GitHub review is a COMMENT with an artistic recommendation,
not a formal GitHub APPROVED state. It discloses frame-based inspection of a
lossy proxy and unmeasured COD angular velocity.

In a [subsequent direct approval](https://discord.com/channels/1554885571489566783/1556808474984325191/1559739304937529421),
Elara explicitly approved 82/pass after 30x slowed playback of odd frames f1–29,
reporting no snap at f5–f7, no bump at f7, smooth recovery/settle, and no blockers.
That is additional limited playback evidence, not a full consecutive-native60
playback claim. Optional pre-contact polish is outside this exact correction.

The reviewed private candidate BLEND is identified, not included, by SHA256
`db30e98a8d63cb4e9075ec2930cd5d34d385780ab374e1d6386f42d1e0fe7b3b`.
Its complete 775-curve landing Action record has canonical SHA256
`6e8daff6b1e0d81780336733cc397c965d65c2a9b5eb908cbeb5346a51965d56`.
The historical saved-file reopen verified that this Action record matched the
saved candidate and that source mesh/material/rest-rig/camera/constraint
structure and all original Actions were preserved.

## Text-only derivation

The existing workflow reads Hal's immutable source from
`e9317f90ea171976306e2f17c111325d948ea357`,
`assets/authoring/jump/halcyon_jump.blend`, SHA256
`a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`.
`tools/jump_landing_patch.py` copies `jump_land_r7`, verifies its complete curve
digest, applies the exact recorded coordinates and handles for f5/native4071
and f6/native4072 on `righthand_prop.rotation_euler[1]`, and checks the full
result against the approved Action digest. It does not rerun optimization.

The helper verifies every original Action afterward. The unchanged r7 source
BLEND is never saved. This recreates the exact approved Action inside the
existing source, not a byte-identical copy of the whole reviewed BLEND. The
baseline Action hash is
`c492d72146c1d23e054599137e40c936c1bb2b2766862d858af8316f092d6bda`.
All other 774 landing curves, translation, f4/f7 boundaries, f12 trough,
f29 exact-ready endpoint, and existing takeoff/air Actions are retained.

No BLEND, mesh, texture, private calibration data, screenshot, or video is added
to Git. The existing complete-game CI retains its established generated
runtime-artifact transport, including unchanged canonical companions.

## Source-to-runtime checks

The existing Blender 4.3.2 evaluation/export path now exports the copied Action
as the same `jump_land` FBX take. The actual FBX hash stays bound through
conversion and Rust CPU parity. Patch provenance is carried from the native
oracle into every parity report and the v2 generated manifest; packaging
requires the exact approved identity at each point. The source BLEND hash
continues to describe the real r7 input, rather than falsely naming the private
candidate as the opened file. Old r7 caches/manifests are rejected.

The existing historical companion-reuse lock is preserved byte-for-byte. Its
r7 artifacts are ineligible for this r8 source contract. The regression test
now explicitly verifies that its historical package pin rejects the changed
packager through both Git identity and worktree-byte guards, rather than
silently repinning old artifacts as current r8 evidence.

The existing parity lane now includes exact f5/f6, neighboring subframes,
f4/f7 boundaries and f12 trough. It retains the existing 1 mm geometry limit,
visibility checks, original 44 clip-byte preservation, canonical VRS/VRM bytes,
endpoint seams, air hold and actual gameplay capture gates. Runtime clips retain
12/24/29 native frames, durations 11/60, 23/60 and 28/60 seconds, and 480 Hz baking.

## Validation status at preparation

Only text/code work was performed while the graphical capture machine was
busy. Fresh local Blender export, runtime parity and native game validation were
not run for this preparation. New synthetic helper and distribution tests are
included for the ordinary CI lanes. The exact-head PR checks must establish
their results; preparing the wiring is not a claim that a new playable artifact
has already passed those checks.

The original bounded authoring checks and 19 source-free checkpoint tests are
recorded in [PR60](https://github.com/RHS059/rust_duty/pull/60); they are distinct
from this new export/runtime integration. Historical r7 evidence remains in
`docs/JUMP_R7_RUNTIME_WIP.md` and is not relabeled as r8 evidence.

## Reproduction

Use the same quiet-window command from the r7 integration with the new code:

```sh
cargo build --locked --release --no-default-features --example sample_viewmodel_clip
python tools/build_jump_assets.py --source-dir /path/to/pinned-jump-source \
  --blender /path/to/blender-4.3.2 \
  --sampler target/release/examples/sample_viewmodel_clip \
  --work build-jump/work --output build-jump/runtime
python tools/check_generated_assets.py --kind jump --directory build-jump/runtime
```

Work and output folders must be fresh. No rendering occurs in this export path.
Do not run it alongside live GUI capture on a shared resource pool.
