# Authored gameplay animation slots (WIP)

`assets/animations.cfg` is the semantic binding contract. Paths resolve relative to
that manifest (beside the game's packaged assets), never the process working
directory. Re-export a clip with the same name/path, or change the slot's asset and
clip values: no Rust event wiring changes are needed. Unknown keys, duplicate keys,
missing required slots, missing clips and incompatible companions fail visibly.

The ready/sprint entry, loop, ordered phase bridges, exit and settle slots all use
the locomotion pack. Their existing connected-path validation is retained. Reload
slots load an entire separately validated `.vra`/`.vrs`/`.vrm` companion set. The
animation decoder verifies the exact companion CRCs, ordered bones, actors and
mesh references; the renderer uses only that set's skin and rigid model together.
It never hands the two-actor locomotion pose to the three-actor reload rig.

## Current export and playback policy

- Tactical reload points to `reload_current_wip`, the complete current authored
  action, including unfinished frames 30–48. It is not a concatenation of reviewed
  cropped segments. WIP pose/contact faults remain visible rather than repaired
  by procedural motion or hidden behind a pose-approval gate.
- `whole_model_cut` explicitly switches the entire skin, gun and magazine render
  owner at reload start/end. Seams are expected WIP limitations. No cross-rig
  blending or unsupported claim of a connected authored return is made.
- `native_complete` samples elapsed simulation seconds from the accepted reload's
  original start deadline. It does not stretch to weapon stats. Playback finishes
  its native duration even if ammunition is ready earlier; if gameplay lasts
  longer, the authored endpoint holds until gameplay completes. Weapon gameplay
  remains authoritative, including firing readiness, credit timing, and sprint
  cancellation. A new accepted reload replaces the old visual action.
- Pausing stops simulation timestamps and therefore animation. Reset clears the
  playback observer and explicitly resets the locomotion path. Rendering never
  advances either controller.
- Empty reload is explicitly `unavailable` until a real clip is supplied. An empty
  reload still obeys gameplay, but displays a missing-slot warning and the current
  locomotion/ready model. It does not silently play tactical or procedural reload.
  To add it, replace that declaration with `reload.empty.asset=...` and
  `reload.empty.clip=...`.
- Authored firing and mantle clips are unavailable and stated on screen. Their
  gameplay continues; there is no invented authored movement or legacy visual
  fallback. Extending playback to a new action needs a semantic event/controller;
  replacing any already-supported slot never does.

Real R input and replay input run through the same `Simulation::update` and
`AuthoredReload::committed_step` path. Merely pressing rejected R (full magazine,
held input, or no reserve) does not trigger or restart playback. The acceptance
signal is the simulation's committed `reload_ready_at` deadline, not raw input or
render-frame inference. Tests exercise this route and compare ammo, reserve,
credit and readiness against an unobserved simulation.

An explicit `--viewmodel-asset=... --viewmodel-clip=... --viewmodel-time=...` remains
a single-clip diagnostic preview, not proof of gameplay integration. Normal launch
uses the semantic manifest. `--animation-manifest=...` overrides its location when
using gameplay locomotion mode. No special camera or pose override is introduced:
all model routes use the existing first-person viewmodel camera and model root.

## Regular walking slot

`regular_walk.asset=walk/asset.vra` and `regular_walk.clip=normal_walk_r1` bind
the current source-authored loop. Its companion pack preserves all original 43
clip payloads and the canonical skin/rigid bytes. The entire
matching companion pack is loaded and the named clip must be looping and have
positive duration. This uses committed grounded movement above 0.1 m/s, not raw
W input or the sprint boolean. Reload takes priority; sprint's authored exit must
reach ready before walking can own the model. Active ADS (including its native exit), mantle and firing also suppress
walk. Native seconds loop without speed warping; stop/reset clears its clock and
pause freezes it. Whole-model cuts are explicit WIP transitions. No procedural
walking motion is added when the authored slot is unavailable.

For rendered gameplay-path evidence (not the old normalized-pose preview), run:

```
vector-range --no-update --reference-viewport --capture-sequence=gameplay-reload --output=reload-gameplay
```

This starts with 12 rounds, sends one R intent after 0.25 seconds through normal
fixed-tick Simulation::update, then evaluates the committed authored presentation.
It captures through the native clip end and return to locomotion, with per-frame
`.gameplay.json` containing route, native clip time, ammo, reserve and authoritative
credit/readiness deadlines. No reload timer or pose-phase override is used.

For a real grounded walking replay, use
`--reference-viewport --capture-sequence=gameplay-walk --output=walk-gameplay`.
It sends normal forward movement from 0.25 to 2.25 seconds through the normal
simulation and committed presentation; sprint stays off. It stops automatically
after 3.7 seconds and writes numbered PNGs plus `.gameplay.json` containing route,
unwrapped native clip seconds, loop duration, actual speed, grounded/sprint flags,
position and renderer-failure status. No velocity or pose override is used.

The expected proof is ready -> `regular_walk` over at least two native loops ->
ready after movement decays below 0.1 m/s. Gun and arms use the complete authored
pack. Start/stop currently make whole-model cuts; authored easing and phase-aware
walk exits have NOT been implemented. This capture exposes those seams rather
than hiding them with procedural bob or invented transitions.


## Authored ADS slots

The semantic manifest binds `ads.asset=ads/asset.vra`, `ads.entry.clip`,
`ads.hold.clip`, `ads.exit.clip`, and `ads.clock=native_reversible`. A future clip
revision changes only these bindings. Alternatively, `ads=unavailable` explicitly
removes this visual action and displays the missing-slot warning. Partial slots,
unknown policies, missing clips, nonpositive durations, wrong looping flags,
incompatible companions and disconnected endpoints fail before gameplay rendering.
The ADS companion pack preserves the canonical 44-clip walk pack and its skin and
rigid companions. All arms and rigid actors retain one complete authored owner.

`ads_entry_r1` and `ads_exit_r1` are non-looping native-time transitions.
`ads_hold_r1` loops a static authored sight pose. Entry starts at `normal_ready`;
entry end, every hold frame and exit start match; exit ends at `normal_ready`.
These source connections are checked with decode-rounding tolerance, never
corrected at runtime. No procedural ADS offsets, IK, hand posing or gameplay-phase
retargeting are used. The existing camera, field-of-view and world lighting paths
are unchanged. Playback uses the pack's own CRC-checked renderer companions.

The simulation publishes `Player.ads_requested` from its existing eligibility
calculation, after reload/mantle/sprint decisions. `AuthoredAds::committed_step`
observes that committed signal once per fixed tick. It never sees mouse input and
never changes simulation state, ammunition, readiness, recoil, movement or ADS/FOV
timings. Visual entry/exit advance at one authored second per simulation second;
weapon-profile `ads_time` and `ads_out_time` remain independent gameplay values.

Releasing during entry retraces that same entry clip from its current sample.
Re-aiming during exit retraces that same exit clip from its current sample. Another
reversal changes only playback direction: it does not restart an endpoint or swap
to a different source pose. This preserves pose continuity during rapid toggles.
A reversal changes velocity direction immediately; no additional easing filter or
procedural transition is claimed. Repeated rendering is read-only. Pause freezes
sample and direction, and range reset clears the controller explicitly.

Priority and interruptions:

- An accepted reload immediately takes its existing explicit whole-model cut and
  cancels ADS ownership. ADS cannot reacquire until the native reload tail and
  gameplay reload both finish; held, accepted aim then starts a fresh entry
- Sprint or mantle forces a native authored ADS return to ready. Sprint locomotion
  begins only after ADS returns; a sprint exit already in progress must reach ready
  before ADS enters. Gameplay movement/traversal never waits for these visuals
- Regular movement while aiming keeps the full ADS pose. ADS suppresses regular
  walk until its native exit finishes. Walk-to-ADS remains an explicit WIP model
  cut to authored entry-start, consistent with the existing walk start/stop policy
- Firing while aiming preserves authored ADS and normal shots/recoil authority.
  There is no authored fire kick until a fire slot is supplied. A rejected reload
  does not restart ADS; an automatic accepted empty reload cancels it normally
- Mantle still has no authored slot; its gameplay proceeds while ADS returns to
  ready. No mantle animation or procedural substitute is implied

For native rendered evidence through the real committed controller:

```
vector-range --no-update --reference-viewport --capture-sequence=gameplay-ads --output=ads-gameplay
```

This 9.2-second input-only replay begins with 12 rounds and exercises a complete
entry/hold/exit, mid-entry release/re-aim, mid-exit re-aim, regular walking, ADS
while moving, sprint interruption/re-entry, actual shots while aiming, accepted
reload interruption/reacquisition, and final return to ready. It sets no ADS phase,
velocity, reload timer or animation clock. The same replay inputs are used by the
real-export contract test. Each numbered native PNG has `.gameplay.json` containing
simulation time, scenario segment, actual presentation route, source clip, native
clip seconds and duration, playback direction, committed aim eligibility and ADS
fraction, movement flags, ammo/reserve/shots, reload deadlines and renderer status.
The old `--capture-sequence=ads` remains a normalized diagnostic and does not prove
authored ADS gameplay integration.

Unit contracts cover native timing independent of profile, exact reversal sample
continuity, real reload/fire/sprint/walk/mantle input decisions, pending sprint
handover, pause/repeated render/reset and invalid source contracts. The optional
`RUST_DUTY_ANIMATION_MANIFEST` asset test evaluates actual canonical source poses
and their skin/actor transforms across the shared gameplay replay, while comparing
all relevant gameplay outcomes against an unobserved baseline simulation.
