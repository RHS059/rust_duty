# Visual-reference calibration

The visual target is the user's supplied newer-era BETA M4 footage. This is
separate from the proposed 2009 multiplayer simulation profile. Reference
observations are image measurements, not recovered engine transforms or timing.
The HK416 and supplied Soldier arms have different geometry/materials from the
reference, so matching selected landmarks is not full visual identity.

## Reproducible native captures

The native renderer accepts `--reference-viewport` and renders the real weapon
and skinned arms into a fixed 960x540 offscreen target. It exports this texture,
not a resized/cropped desktop screenshot. Captures use a neutral background.
Use `--capture`, `--capture-ads`, or `--capture-reload=0.35 --capture-empty` and
`--output=/absolute/path.png`. Specify authorized local sidecars with
`--weapon-asset=...` and `--arms-asset=...`. The output JSON records presentation
state. Deterministic captures are presentation probes, not gameplay executions.

Default viewmodel horizontal FOV is 76 degrees. Hip translation is
(0.05930,-0.04831,-0.30806)m with YXZ rotation (0.04118,-0.01252,0)rad;
ADS translation is (0,-0.03794,-0.2322)m with identity rotation.
These are original inverse-projection fits to the supplied HK416 geometry.
They are not COD transform values.

At 960x540 the current calibrated native hip rear-aperture center and front
sight guard are approximately (625,293)/(526,280), versus reference
(624,293)/(526,279). Estimated observation uncertainty is +/-4px. ADS rear
aperture center is (480,270), with outer diameter approximately 50 px. The hip
front-guard landmark and ADS central aiming-post landmark are distinct features;
no cross-pose one-point identity is assumed. The receiver proportions and
complete hand silhouette still require separate review.

`profiles/m4a1-beta-visual.cfg` keeps the separately documented simulation
candidate and uses an ADS camera override matching the observed background
magnification (~1.103x, medium confidence). With authored hip HFOV90 this implies
ADS HFOV84.40. The clip cannot establish an absolute world FOV by itself.

## Arms and reloads

Wrist targets are explicit weapon-local positions. Finger hinges are derived
from the supplied rig's bind axes. Support, magazine, receiver, and open hand
modes are continuously normalized; cancel blending preserves their sum and
composes live recoil/trigger after residual reload motion. Natural reload
completion does not introduce a cancellation delay.

Pose contracts validate finite values, continuity, timing windows and modes.
They do not establish visual matching. `tools/export_sampler_poses.py` compiles
the exact Rust sampler and emits its source hash plus JSON/CSV pose samples.
The schedule has elapsed-time and normalized-phase comparisons: elapsed time
must remain visible so normalized phase does not conceal duration mismatch.

Native hip/ADS capture and independent mesh contact checks are complete for the
current calibration. Distinct tactical/empty root curves, late tactical overshoot, rotated held
magazines and separate hand modes are integrated. Continuous native time-series
comparison is ongoing. Do not describe this checkpoint as verified COD parity.

### Continuous sequence capture and timing

`--reference-viewport --capture-sequence=tactical --output=/absolute/directory`
emits native frames and elapsed-time metadata at 60000/1001 presentation samples
per second. `empty` and `ads` are also accepted. Host rendering speed does not
change the sampled trajectory. The visual tactical duration is 2.21 seconds:
exact decoded frames show a raised weapon at 9.5095, lowering at 9.6096, a late
return/overshoot around 9.81, and near-settled recovery around 10.01. The earlier
coarse 9.7–9.8 estimate was too early. Empty presentation remains approximately
2.2 seconds. The late tactical downward overshoot now uses fitted sight centers; its depth
and roll are authored near-idle priors because the muzzle is occluded.

The gameplay ready/credit deadlines remain independent. A natural completion
may retain a short presentation recovery tail; firing recoil/trigger remains
live over it. Cancellation clears the presentation clock and uses the existing
residual-pose blend. A new reload supersedes any prior visual tail.

The empty-replacement attachment regression is fixed: wrist targets track the
rotated magazine's fitted pivot. A shared rigid transform and skin-level tests
preserve contact; the discarded old magazine separates during the visible
throw. The source wrist is ambiguous during tactical pickup, so the current
foreground hand/magazine silhouette remains an approximation requiring native
comparison. Matching sparse sight landmarks is not a claim of full-motion parity.

### ADS and prop rotation

Dense entry measurements support a 250 ms cubic smoothstep for weapon placement,
with fitted visual onset 10.4811 s and rear-center horizontal RMSE 1.78 px. Input
onset is unknown and several easing curves fit within measurement uncertainty.
World zoom is delayed43ms and eases over186ms as a separate presentation fit.
Symmetric exit is an authored fallback because firing obscures clean exit data.

Magazine rotation uses weapon-local YXZ about the fitted wrist seat, composed
with the exact same hand orientation while in magazine-grip mode. Actual skinned
fingertip-to-magazine nearest-vertex distances stay approximately0.9–2.4mm in the
fitted closed-grip poses; these are contact measurements, not proof every surface
is penetration-free. The supplied HK416 and Soldier assets remain different
from the reference M4/operator art.

For the integrated renderer-independent adapter, run
`cargo run --example export_presentation > presentation.csv`. This export includes
root overrides and presentation-tail timing that the standalone sampler exporter
does not apply. Reproduce results with the exact source revision and capture
binary; elapsed-time alignment must remain separate from normalized phase.

ADS presentation uses a 250 ms cubic smoothstep. Dense rear-center fitting gives horizontal RMSE 1.78 px and two-axis 3.81 px, conditional on fitted visual onset 10.4811 s. Onset is not recovered button timing. World zoom follows a separate delayed smoothstep (43 ms delay, 186 ms rise); symmetric exit remains an authored choice because source exit is contaminated by firing. The default settings file uses 84.4-degree ADS HFOV; the retained simulation-only M4 candidate file remains available separately.

### Current dense-pose refinements

Raised weapon roots now fit aperture scale and receiver contour as well as sight
centers. Center-only fitting had placed the weapon too far away. All raised keys
were corrected together, retaining explicit uncertainty for blurred features.

Tactical reload uses two visual instances of the same magazine mesh. The old
magazine remains seated while the replacement is held, then drops separately
around source8.55–8.66s. The replacement enters the well around8.7421s. Empty
reload has distinct discard, pickup, separated approach, insertion, outward hand
release, brief receiver contact, withdrawal and return poses. These roles do not
alter simulation ammo accounting.

Wrist orientation and held-magazine orientation use coherent shortest-path
quaternion interpolation. Finger-mode weights remain separate, so a change from
open hand to receiver slap does not apply the wrist correction twice. Dense
contracts verify the angular grip relation as well as the positional pivot.

The user's delivered-video0:02 example maps to nativeframe120/elapsed2.002s and
sourceframe588/PTS9.8098s. A support-only pose probe exposes a remaining late hand
arrival: the old curve was still16.385% magazine grip. The corrected arrival and
intervening open-hand key poses are being fitted; this checkpoint must not be
represented as a completed visual match.
