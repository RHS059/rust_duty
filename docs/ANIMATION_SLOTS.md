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
- Authored ADS, firing and mantle clips are unavailable and stated on screen. Their
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

`regular_walk=unavailable` explicitly reserves the authored walking route. When
the authored loop exists, replace it with `regular_walk.asset=walk/asset.vra` and
`regular_walk.clip=regular_walk` (the actual exported name may differ). The entire
matching companion pack is loaded and the named clip must be looping and have
positive duration. This uses committed grounded movement above 0.1 m/s, not raw
W input or the sprint boolean. Reload takes priority; sprint's authored exit must
reach ready before walking can own the model. ADS, mantle and firing also suppress
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
