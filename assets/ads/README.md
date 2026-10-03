# Source-authored aim down sights

The private source `assets/authoring/ads/ads.blend` extends a copy of the canonical
walk source without editing its existing Actions. Three versioned Actions produce
`ads_entry_r1` (0.25 seconds), `ads_hold_r1` (1 second, seamless static aimed pose),
and `ads_exit_r1` (0.25 seconds). The pose aligns the actual gun sights to the
existing camera; camera position and viewmodel FOV are unchanged.

The distribution includes all original 44 walking/locomotion clip records unchanged
plus those three ADS clips. VRS and VRM geometry/bindings are exactly canonical.
Blender 4.3.2 evaluates constraints to FBX at 480 Hz; the importer selects each
named take, and the actual Rust CPU sampler verifies vertices and rigid actors
against independent source witnesses. Manifests bind source hashes, all output
hashes, conversion selections and passing parity reports. Cache hits are rechecked.

`assets/animations.cfg` provides the semantic slots and native reversible clock.
Gameplay ammunition and ADS deadlines stay simulation-owned. Native reversal
retraces the current authored clip; interruption policies and WIP cross-owner
seams are documented in `docs/ANIMATION_SLOTS.md`.

The repository stores deterministic gzip transports for the ADS VRA and skin.
Materialization and packaging verify encoded and decoded SHA-256/size then emit
ordinary raw `.vra`/`.vrs` companions. The runtime format is unchanged.
