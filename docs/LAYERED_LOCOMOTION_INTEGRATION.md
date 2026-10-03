# Layered locomotion integration, runtime foundation

Base: PR #16, `7ffdd6eb1d6ae20d5e8e6445f07759a225c952eb`.
Status: runtime foundation; new reference-authored clips are not imported or approved here.

## Behavior

The complete authored ready/ADS pose is the lower layer. The current hip walking
Action runs once and is composed in the declared weapon actor's space. Full ADS
retains the existing optical-axis projection of that same walk, rather than
switching to a duplicate ADS walk loop. Source-authored attenuation revisions are
pending independent review.

The authored run path advances on the same committed tick as outgoing ADS and
walk. A 160 ms run fade-in and 220 ms fade-out crossfade complete weapon-relative
poses. Returning run no longer blocks ADS or walking from beginning. Quick
interruptions retain native source phase and the current envelope instead of
resetting to ready. All advancement occurs in the committed simulation observer;
render calls and paused intervals cannot change the pose.

The shared controller is `src/layered_locomotion.rs`. Its cached complete pose is
consumed by the normal native renderer, not a special capture-only implementation.
The `layers.anchor_actor` semantic manifest field names the canonical blend anchor;
older manifests with a walk anchor retain compatibility. An unavailable walk is
supported when the shared layer anchor is explicit.

## Evidence and boundaries

- Local checks: 479 Rust tests passed with committed asset witnesses enabled;
  formatting and all-target silent Clippy passed. The full Python suite and
  GitHub Windows/native-render jobs are tracked separately.
- Synthetic contracts cover concurrent run/ADS/walk, returning-run ADS, same-phase
  reversals, infinitesimal interruption continuity, pause/read idempotence, invalid
  tick atomicity, time partitioning, complete-pose validation and hand attachment.
- The actual committed packs are tested through the same controller with ordinary
  simulation replay, unchanged gameplay outcomes and 480 Hz interruption sampling.
- Initial actual-pack measurement: 26 committed ticks with all three layers
  overlapping, 26 ADS-entry ticks during run return, maximum weapon-relative wrist
  translation drift 0.00747 mm across the ten-second replay.
- Native ADS capture telemetry includes `run_weight`. Verification requires at
  least three rendered frames of concurrent outgoing ADS/walk and incoming run,
  plus ADS entry during run fade-out. Sequential route names cannot pass this gate.

This foundation changes no Blender Action, skin, rigid mesh, baked animation or
existing WIP clip. It does not establish a reference-match percentage. New source
clips require the independent supported-motion review gate before import, then
source preservation, evaluated FBX, native sampler and target-runtime checks.

Position continuity does not imply continuous velocity: reversing the smoothstep
envelope can reverse its derivative. Global weapon-relative interpolation preserves
attachment but can change intermediate bone lengths. Existing incompatible reload
packs retain their documented whole-model cut; that seam is not silently certified
as a continuous blend. Fire and mantle remain existing unavailable source slots.

## Reproduce

Materialize existing committed transports with `python tools/package_game.py
materialize --root . --include-walk --include-ads`. The complete-game pipeline also
provides its current generated reload pack. Run `cargo fmt --all -- --check`,
`cargo clippy --locked --all-targets -- -D warnings`, `cargo test --locked` with
`RUST_DUTY_ANIMATION_MANIFEST=assets/animations.cfg`, and the Python test suite.
For Linux without ALSA headers, `--no-default-features` explicitly selects silent
checks. GitHub's complete build validates the normal audio-enabled configuration,
Windows packaging and native Linux rendered evidence. Windows packaging alone is
not a Windows gameplay test.
