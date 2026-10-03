# Layered locomotion integration, runtime foundation

Base: PR #16, `7ffdd6eb1d6ae20d5e8e6445f07759a225c952eb`.
Status: all four current HIP clips and ADS v4 are now included as user-authorized WIP.
The earlier foundation/history sections below remain as the development record;
no80% fidelity or full visual approval is implied by inclusion.

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
Optional `regular_walk.direction.forward`, `.backward`, `.left` and `.right`
slots select four reviewed HIP Actions from the same walk pack. They share native
elapsed seconds, preserve their individual native durations, and blend direction
in camera-relative horizontal-velocity space. A 60 ms exponential response retains
current weights across directional reversals; stopping or entering run holds those
weights while the walk fades. ADS consumes the same already-composed HIP pose.
All four slots must be supplied together; absent slots keep the previous walk.
No production directional slot is selected in this foundation.

The `layers.anchor_actor` semantic manifest field names the canonical blend anchor;
older manifests with a walk anchor retain compatibility. An unavailable walk is
supported when the shared layer anchor is explicit.

## Evidence and boundaries

- Local checks: 485 Rust tests passed with committed asset witnesses enabled;
  formatting and all-target silent Clippy passed. The Python suite runs
  145 tests, with one pre-existing optional Blender smoke skip. GitHub
  Windows/native-render jobs are tracked separately.
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

## Native trace correction and rate diagnostics

PR17's first GitHub run built and verified the complete Windows package. Its native
ADS capture rendered all 553 frames, but an older verifier compared walk phases
across two separate episodes. The trace contains a fully faded/inactive interval
between 3.7333 and 4.2000 seconds, followed by a new walk cycle. The verifier now
checks committed-time phase continuity in every adjacent active interval, with
negative tests rejecting resets or freezing while a layer remains active. The
unchanged 553-frame trace passes: nine simultaneous incoming run/outgoing ADS+walk
frames, thirteen ADS-entry frames during run return, and the expected final ready.

The additional `gameplay-layered` capture mode accepts `--capture-hz=30` or `60`,
uses ordinary movement/aim/run input for all four directions, and saves pose-only
CRC32 plus committed state. The rate verifier compares common fixed ticks. CRC32
is diagnostic, not authentication or a visual/anatomical approval. These are
simulation-time sampling rates, not a claim about wall-clock game performance.

While new source clips are still unapproved, CI explicitly uses
`--allow-legacy-walk` for these diagnostics. That result cannot satisfy the
four-direction source gate. The strict default requires the correct direction
weights in every HIP and ADS segment; it must be used when reviewed clips are bound.

## Independent diagnostic QA correction

Independent inspection of `0423f0fd` confirmed that all 337 common 30/60-rate
samples have identical telemetry and PNG bytes. It also found that float32
capture timestamps sometimes requested uneven fixed-step intervals: 60-rate
samples could advance one then three ticks instead of two, and 30-rate samples
could advance three then five instead of four. That earlier capture must not be
called perfectly uniform cadence.

The capture driver now targets an integer count of committed simulation ticks:
two per 60 Hz diagnostic frame and four per 30 Hz frame. This changes diagnostic
sampling only, not the game clock, animation clocks or gameplay. Both native
verification and regression tests require the exact stride.

Three-layer *partial overlap* now requires `0 < run_weight < 1`. The earlier
10/19 overlap counts included some fully weighted run frames that hide the lower
layers; true partial overlap in those archived artifacts is 7/14 frames at the
declared 30/60 rates. This corrects the reporting definition, without invalidating
the observed concurrent fades. Fresh exact-stride captures must be reverified.


## Current WIP inclusion

The current manifest activates `directional/asset.vra`, the four PR18 HIP Actions,
and `receiver_v4_wip` ADS composition. Source PR18 is pinned at
`6bbfada1242d2d6c766c52cfc30c3ab511e41669`; Blender source hash is
`6d6d5c6a150bd8d74f24b29bf18b192e2f5fe2cd93a531c77b7a1e5ce93a8b35`.
The new directional48 pack preserves original walk44 clip bytes and companions.
Existing locomotion43, walk44, ADS47 and full reload are retained in the package.

ADSv4 reuses the existing aligned source poses with0.30s visual entry/exit,
40% receiver target motion, lateral vertical attenuation and a continuously
accumulated0.85 full-ADS native phase rate. The held-ADS source composition has
sight/contact evidence; other cases and reference fidelity are explicitly WIP.
See `assets/authoring/ads_wip/` for the frozen source contract and mathematical
witnesses. New-policy review continues after inclusion rather than gating it.
