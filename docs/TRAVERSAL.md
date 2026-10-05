# Traversal and weapon-action systems

Gameplay contract and animation interface for tactical sprint, slide, dolphin
dive, weapon mounting, ledge catch/hang, hanging sidearm, pull-up/drop, wall
obstruction, look sway, first-person body and death/respawn. Reuses the
existing crouch, prone, jump and [mantle](MANTLING.md) mechanics.

**Status:** gameplay is implemented and covered by contract tests. All visuals
are **labeled placeholders** (HUD shows `[PLACEHOLDER ANIM]`). Animation
integration is **not complete** until the authored clips from Aella/Hal pass
first-person visual review. See the [acceptance checklist](TRAVERSAL_ACCEPTANCE.md).

## Ownership and shared rules

- `Simulation::update` (fixed 120 Hz) owns movement, collision, eligibility,
  ammunition and timing. Presentation reads `Simulation::action_pose()`,
  `Player::{action, mantle, mount, obstruction, tac_sprint}` and
  `Simulation::action_events`; it never moves the player or grants an action.
- Every movement state moves through the shared `integrate()` collision path or
  the mantle's continuous swept legs. Animation cannot push the body through
  geometry.
- Timing comes from clip durations and named, normalized events
  (`ActionTimings`), never frame counts. Unbound slots use the placeholder
  timings below. Binding an authored clip in `assets/animations.cfg` retimes
  the gameplay gates that read its events.
- Code: `src/action.rs` (vocabulary, timings, tuning), `src/sim/actions.rs`
  (state machines), `src/weapon_sway.rs` (layers), `src/body_presentation.rs`
  (legs/body), `src/traversal_replay.rs` (capture scripts).

### Priority order

Resolved each fixed tick. A higher state suppresses or ends a lower one.

1. **Death:** clears every action, reload and sidearm. Input is ignored until respawn.
2. **Mantle / pull-up:** owns the body; all weapon actions blocked.
3. **Ledge hang:** owns the body; the rifle is unavailable, the sidearm is optional.
4. **Dolphin dive:** committed once launched.
5. **Slide**
6. **Weapon mount**
7. **Tactical sprint**
8. **Sprint** (existing)
9. **ADS / fire / reload**, subject to the permission table, weapon lockout and obstruction.

Same-tick conflicts: prone + crouch pressed together while sprinting dives
(prone wins, matching the existing stance rule). A crouch press that starts a
slide wins over a jump in the same tick; the next jump press cancels the slide.
Movement wins over mounting. Reload and ADS/fire end tactical sprint.

### Weapon permission table

| State / phase | ADS | Fire | Reload | Sprint |
| --- | --- | --- | --- | --- |
| Normal (incl. tactical sprint) | yes | yes | yes | yes |
| Slide entry (until `slide_enter.weapon_free`) | no | no | no | no |
| Slide active | yes | yes | yes | no |
| Dive launch / impact | no | no | no | no |
| Dive airborne | no | hip only | no | no |
| Hang, rifle (both hands on ledge) | no | no | no | no |
| Hang, sidearm ready | yes | yes | **no** | no |
| Mantle / pull-up | no | no | no | no |
| Mounted | yes | yes | yes | no |
| Weapon lockout after slide/dive/drop | no | no | no | yes |
| Obstruction ≥ `obstruct_ads_block` | no | — | — | — |
| Obstruction ≥ `obstruct_fire_block` | — | no | — | — |
| Dead | no | no | no | no |

`tests/weapon_action_contract.rs::documented_weapon_permission_table` checks this table.
Existing rules still apply on top: sprint blocks ADS/fire, reload blocks
ADS/fire, sprint-out raise delay. Mantle, hang and death cancel an uncredited
reload (credited rounds stay, nothing is queued).

### Blend rules

- `ActionPose.weight` is 1 while a slot is active. Exit and Interrupted slots
  blend 1→0 over their clip duration. Mount blends 0→1 over `mount_enter` and
  1→0 over `mount_exit`.
- Look sway, locomotion, recoil and action are separate, bounded layers
  (`weapon_sway.rs`). They are summed into **one rigid camera-space root** for
  the whole viewmodel, so arms and weapon move together and grips never detach.
  The camera never receives these offsets.
- Placeholder action layer: the rifle is lowered out of view while hanging or
  pulling up, rolls during slide/dive, raises its muzzle in tactical sprint,
  and retracts/lowers by the obstruction amount.

## Inputs

| Input | Action |
| --- | --- |
| Shift double-tap (second fresh press within `tac_sprint_double_tap`) | Tactical sprint |
| Ctrl/C press while sprinting | Slide; otherwise the ordinary crouch |
| Z press while sprinting | Dolphin dive; otherwise the ordinary prone |
| V | Mount / unmount. Holding ADS on valid cover also mounts after `mount_auto_delay` |
| Jump toward a ledge, forward held | Automatic ledge catch |
| Space while hanging | Pull up |
| Ctrl/C while hanging | Drop |
| 2 while hanging | Draw / stow sidearm |
| F9 | Debug: kill the player (exercise death/respawn in any state) |
| Q / E (toggle) | Lean left / right; see below |
| Left Ctrl + X (toggle) | Hip cant; Left Ctrl alone crouches on release |

Look is clamped while hanging (`hang_yaw_limit`, `hang_pitch_*`) and mounted
(`mount_yaw_limit`, `mount_pitch_*`). Movement input is ignored while hanging;
there is no shimmy. Pause, reset and focus loss clear pending action presses
(`control::ActionLatch`); a held key must be released first.

## Features

### Tactical sprint

| Phase | Slot | Gameplay |
| --- | --- | --- |
| Entry | `tac_sprint_enter` | Starts on a double-tap while sprint-eligible: sprint held, forward > 0.83, grounded, standing, no ADS/fire/reload, not exhausted, charge ≥ `tac_sprint_min_charge` |
| Active | `tac_sprint_loop` | Speed is `tac_sprint_speed`; it **replaces** sprint speed and never adds to it. Charge drains 1 s/s; normal stamina also drains |
| Exit | `tac_sprint_exit` | Sprint ends (release, ADS, fire, reload, jump, crouch), charge empties (falls back to normal sprint), or a slide/dive/mount starts |
| Interrupted | `tac_sprint_exit` | Same exit slot. Ground speed returns under the normal acceleration cap within a few ticks; no tactical speed remains |

The charge recharges at 1 s/s after `tac_sprint_recharge_delay`. A jump keeps
ordinary jump momentum, cut on landing as usual. Restoring the weapon pose
uses the existing sprint-out raise (`sprint_out_time`); `tac_sprint_exit.weapon_ready`
is a presentation marker. Events: `TacSprintStarted`, `TacSprintEnded`.

### Slide

| Phase | Slot | Gameplay |
| --- | --- | --- |
| Entry | `slide_enter` | Crouch input while sprinting, grounded, standing, speed ≥ `slide_min_speed`, cooldown elapsed, slide capsule fits. Speed becomes `min(speed + slide_boost, slide_max_speed)`. Weapons blocked until `weapon_free` |
| Active | `slide_loop` | Capsule `slide_height`; friction `slide_friction` m/s²; steering rotates velocity ≤ `slide_steer_rate` °/s (never adds speed); walkable ramps add `g·sinθ·slide_slope_scale` downhill |
| Exit | `slide_recover` | Speed < `slide_stop_speed` or `slide_max_time`. Settles into the desired stance (prone > crouch > stand), dropping to the next lower stance that fits, so it never stands through a ceiling. Weapon lockout until `slide_recover.weapon_ready` |
| Interrupted | `slide_interrupt` | Jump (stands and launches only if standing fits; otherwise the press is consumed), a stance input change, or leaving the ground |

A rejected attempt emits `SlideRejected(Ineligible|Blocked)` and changes
nothing: the ordinary crouch proceeds. Toggle mode ends crouched because the
press set crouch intent; Space or Ctrl stands as usual. Events:
`SlideStarted`, `SlideEnded`, `SlideInterrupted`, `SlideRejected`.

### Dolphin dive

| Phase | Slot | Gameplay |
| --- | --- | --- |
| Entry (launch) | `dive_launch` | Prone input while sprinting, grounded, standing, speed ≥ `dive_min_speed`. Requires a clear sweep up by `dive_min_headroom` and forward by `dive_min_forward_clearance` at `dive_height`. Velocity is **set** (not added) to `dive_forward_speed` forward + `dive_up_speed` up. No steering until `steer_allowed` |
| Active (air) | `dive_air` | Gravity and collision through `integrate()`; steering ≤ `dive_steer_rate` °/s without adding speed |
| Exit (impact) | `dive_impact` | Triggered by **actual ground contact** from collision, not by time. Prone capsule; horizontal × `dive_landing_speed_scale`, then `dive_ground_friction` |
| Recovery | `dive_recover` | Hands over to the existing prone system. Stance is locked until `cancel_allowed`; weapon lockout until `weapon_ready` |
| Interrupted | — | Committed once launched: only death or reset interrupts |

Rejected: `DiveRejected(Ineligible|Blocked)`; ordinary prone proceeds. Walls and
ceilings during flight are resolved by the same collision as all movement.
Events: `DiveLaunched`, `DiveImpact`, `DiveEnded`, `DiveRejected`.

### Weapon mounting

| Phase | Slot | Gameplay |
| --- | --- | --- |
| Entry | `mount_enter` | V, or ADS held on valid cover for `mount_auto_delay`. Weight 0→1 over the clip |
| Active | `mount_hold` | Support point fixed in world space. Aim clamped to ± `mount_yaw_limit` around the mount yaw, pitch `mount_pitch_*`. Recoil × `mount_recoil_scale`. ADS, fire and reload allowed; reload keeps the mount |
| Exit | `mount_exit` | V again, movement > `mount_move_deadzone`, jump, stance change, ADS released (auto-mount only), player displaced, or the support changed/removed. Weight 1→0 |

Detection: grounded, standing or crouched (prone rejected), speed ≤
`mount_max_speed`. A top between `mount_min_below_eye` and `mount_max_below_eye`
below the eye must lie within `mount_reach` along the view, with surface angle ≤
`mount_max_angle`. The rested-weapon volume (`mount_clearance` around the barrel)
and the eye-to-support line must be clear. Rejections: `Ineligible`, `Blocked`,
`Steep`. Animation data: `MountState::{support, normal, yaw_center, weight}`.
Obstruction sampling is skipped while mounted, because mount validation already
proved the barrel volume is clear.

### Ledge catch and hang

| Phase | Slot | Gameplay |
| --- | --- | --- |
| Entry | `ledge_catch` | Automatic while airborne and standing, with forward input ≥ 0.5 and vertical speed ≤ `hang_max_rise_speed`. Inputs are accepted after `hands_planted` |
| Active | `ledge_hold` | Gravity and locomotion suspended; velocity zero; feet fixed at the hang position; eye eases to `hang_eye_height` |
| Exit | `pull_up` / `hang_drop` | See pull-up and drop below |
| Interrupted | `ledge_lost` | The held block changed or was removed, or the body/hand space became blocked. Support is released in that tick and falling resumes immediately |

Validation (all must pass):
- **Reach:** the lip is within `hang_catch_below` above to `hang_catch_above` below the hands (`hang_hand_height` above the feet).
- **Approach:** the wall face is within `hang_reach` along the view and faced within 50°.
- **Hand placement:** both hands sit on the same block top, inset `hang_hand_inset` and spaced `hang_hand_spacing`, with clear space above each hand.
- **Body:** the hang position has a clear standing volume, and the path to it is swept clear.
- **Height:** there is no floor within `hang_min_ground_gap` below the feet; that would make it a ledge to stand at, not a hang.

The catch candidate search follows the mantle's approach-ray pattern.

**Moving supports are deliberately rejected:** only static blocks are held, and
any change to the held block releases the hang. Recatch is blocked for
`hang_recatch_delay` and on the same block until grounded.

Contact targets: `HangState::hands` ([left, right] in world space), `lip`,
`ledge_relative_hands()` (right, up, inset), `normal`. `ActionPose.contacts`
gives the hand owners and `body_facing` (into the wall). Events: `LedgeCaught`, `LedgeLost`.

### Hanging sidearm (interface)

The default `Loadout` has **no sidearm**. Pressing 2 emits
`SidearmRejected(NoSidearm)` and changes nothing: both hands stay on the ledge.
A `SidearmSpec` with `hang_eligible` enables the full state machine below. The
tests use one.

| Phase | Slot | Right hand (pistol hand) | Gameplay |
| --- | --- | --- | --- |
| Draw | `pistol_draw` | Ledge → Free at `release_grip` → Pistol at `pistol_in_hand` | Fire-ready at `ready` |
| Ready / aim / fire | `pistol_ready` / `pistol_aim` / `pistol_fire` | Pistol | ADS and fire allowed; aim within hang look limits |
| Stow | `pistol_stow` | Pistol → Free at `pistol_holstered` → Ledge at `regrip` | Holstered at `regrip` |
| Interrupted | — | Rifle (after release) | Drop, lost support or death: `PistolInterrupted`; logically holstered at once |

The left (supporting) hand stays on the ledge throughout. Firing uses the
shared hitscan, occlusion, damage, event and recoil path with the sidearm's
rpm, damage and recoil scale, and draws from `Loadout::sidearm_ammo`. Rifle
ammo is untouched. **No reload while hanging**; an empty sidearm stays dry.
Presses during a grip transfer are consumed. Pull-up while drawn is rejected
(`PullUpRejected(PistolOut)`).

### Pull-up and drop

- **Pull-up:** a fresh Space after `hands_planted` with the sidearm holstered.
  The destination is re-planned with the mantle rules at that moment: a full
  standing footprint on the held top, and every swept leg plus the landing
  volume clear, with no collider ignored. It then runs as a mantle
  (`MantleState::from_hang`) of `pull_up` clip duration, using the mantle's
  55/35/10 rise/over/settle split (`rise_end`/`over_lip` mark those points for
  animation). If the top is blocked, the player **stays hanging**
  (`PullUpRejected(Blocked)`): no teleport, no partial climb. The eye eases from
  the hang height to standing after landing. Events: `PullUpStarted`, `PullUpCompleted`.
- **Drop:** Ctrl/C releases support once and pushes `hang_drop_push` m/s off
  the wall into ordinary airborne movement. The same press does not crouch the
  player. Recatch protection applies (above). Weapon lockout lasts until
  `hang_drop.weapon_ready`. Event: `HangDropped`.

### Wall obstruction

Each tick, five lines along the weapon (center and four `weapon_radius`
offsets) are cast from the weapon's actual hip/ADS offset, plus the
eye-to-weapon segment, for `weapon_length`. `raw = penetration /
obstruct_max_retract`. The smoothed `amount` rises at most `obstruct_rate_in`/s.
It falls at `obstruct_rate_out`/s only after the wall has stayed clear for
`obstruct_recover_delay`, with `obstruct_hysteresis` deadband, and returns
exactly to 0.

ADS is blocked at ≥ `obstruct_ads_block` (released below it minus the
hysteresis). Fire is blocked at ≥ `obstruct_fire_block` (released below
`obstruct_fire_release`). A partially retracted weapon still fires, but the
logical muzzle is clamped to the clear length minus 2 cm, so bullets never
originate beyond the wall. The existing eye-to-muzzle occlusion check is kept.

Animation data: `Obstruction::{amount, raw, direction (world surface normal),
clear_length, ads_blocked, fire_blocked}`. Events: `WeaponObstructed`,
`WeaponCleared`. The camera is never moved.

### Look sway and layers

Look sway is a critically damped spring, integrated in closed form from the
**applied view rotation**: radians after sensitivity, so the same on-screen
motion gives the same response at any sensitivity. Any frame partition of the
same motion yields the same trajectory, and release settles to exactly zero
with no drift and no snap. Bounds: `max_angle` (4°) rotation and 0.02 m
translation. Locomotion (existing bob and authored walk) and recoil (existing
simulation/weapon animation) remain owned by their modules. Tuning
(`SwayTuning`) is **provisional and not yet matched to the reference**; see the
acceptance checklist. The reference shows larger swing amplitude than the
current bound.

Reference comparison uses fixed timing, and no score is computed:

```sh
vector-range --no-update --reference-viewport --capture-hz=60 \
  --capture-sequence=gameplay-sway --output=sway
tools/reference_compare.sh "uploaded_references/Call of Duty Modern Warfare 2 - Weapon Swinging Animation Reference.mp4" \
  sway compare 1.0:0.6 2.0:1.0 3.0:1.25
```

The `gameplay-sway` script turns left at 90°/s for 0.5–1.0 s, settles, then
turns right at 90°/s for 1.6–2.1 s. Pick reference timestamps for matching
turn onset, peak and settle, record the pairs, and judge them visually in the
first-person view.

### First-person legs/body

`BodyPresentation` produces a pose for every state (standing, crouched, prone,
airborne, mantling, sliding, diving, dive impact, hanging, pull-up, mounted,
dead). Body yaw follows movement, clamped to ± 60° from view (backpedal faces
the view). When stationary it holds, until a > 70° view difference triggers a
turn-in-place step. Planted feet are world-locked: no sliding on small turns.
They re-plant on a large turn. Moving feet advance by distance travelled and sit
on the actual block/ramp height under each foot. Pelvis height scales with the
live eye height, so stance transitions never show the wrong height.

**Ownership:** the camera and eye belong to the simulation only. Head and arms
are hidden on the body (`head_visible`/`arms_visible` false); the viewmodel
alone owns the hands, so nothing is duplicated. The torso is placed
`torso_back` behind the camera. Placeholder legs are drawn as labeled boxes
until an authored body exists.

### Lean

The Q/E desire is eased over `lean_time` toward ±`lean_distance` (or
`lean_crouch_distance` when crouched). The offset is horizontal and moves only
`Player::eye()`: body, collision and stance are unchanged. Three casts from the
unleaned eye (−0.15, 0, +0.08 m) clamp the offset so the head
(`lean_head_radius`) never enters geometry. `Player::lean_fraction` is the
fraction actually reached, and the camera rolls by `lean_fraction × lean_roll`.
Hitscan, muzzle and obstruction all start at the leaned eye. Lean returns to
zero while prone, sprinting, mounted, traversing or dead; a toggle intent
resumes afterwards.

### Hip cant

Left Ctrl+X toggles `Input::cant`. `Player::cant` eases 0→1 over `cant_time`
when no traversal action owns the body. The visible value is
`cant_visual() = cant × (1 − ads)`, so there is no cant while aimed and the
toggle survives ADS. Rendering rotates the **weapon actor (`hk416_weapon`)
about its bore line** (mesh −Z through the muzzle) by `cant_angle`.

Because the arms follow the weapon in weapon space, the rotation is applied
through the shared viewmodel root. Hands stay on the grips; shoulders are
offscreen. On the legacy model path, the canted weapon transform feeds the
hand IK targets. Cant is presentation only: aim, spread and hit detection do
not change.

### Death and respawn

`Player::health` (starts at 100; respawns with `max_health`).
`Simulation::damage_player(amount)` kills at ≤ 0. Falling below y = −10 is
death. `kill()` clears every action. While dead, input is ignored, and after
`respawn_delay` the player respawns at the range spawn. Events: `Died`,
`Respawned`. F2 reset (`Simulation::reset`) clears all action state and keeps
`timings` and `loadout`.

## Tuning

All keys load and save with `settings.cfg` (F6 reload, F5 save). Units are
meters, seconds, m/s, m/s² and degrees.

| Key | Default | Range |
| --- | --- | --- |
| `tac_sprint_speed` | 8.6 | 1 – 18 |
| `tac_sprint_duration` | 3 | 0 – 20 |
| `tac_sprint_recharge_delay` | 1 | 0 – 10 |
| `tac_sprint_min_charge` | 0.5 | 0 – 5 |
| `tac_sprint_double_tap` | 0.3 | 0.05 – 1 |
| `slide_min_speed` | 5.5 | 0 – 18 |
| `slide_boost` | 1.5 | 0 – 6 |
| `slide_max_speed` | 9.5 | 1 – 20 |
| `slide_friction` | 6 | 0.1 – 40 |
| `slide_stop_speed` | 2.5 | 0.1 – 10 |
| `slide_max_time` | 1.1 | 0.1 – 5 |
| `slide_steer_rate` | 70 | 0 – 360 |
| `slide_slope_scale` | 1 | 0 – 2 |
| `slide_height` | 0.9 | 0.762 – 1.27 |
| `slide_eye` | 0.7 | 0.3 – 1.1 |
| `slide_cooldown` | 0.4 | 0 – 5 |
| `dive_min_speed` | 5 | 0 – 18 |
| `dive_forward_speed` | 7 | 1 – 15 |
| `dive_up_speed` | 3.8 | 0 – 8 |
| `dive_steer_rate` | 45 | 0 – 360 |
| `dive_height` | 0.9 | 0.762 – 1.27 |
| `dive_eye` | 0.6 | 0.25 – 1.1 |
| `dive_min_headroom` | 0.5 | 0 – 2 |
| `dive_min_forward_clearance` | 1.2 | 0 – 4 |
| `dive_landing_speed_scale` | 0.35 | 0 – 1 |
| `dive_ground_friction` | 10 | 0.1 – 40 |
| `hang_hand_height` | 1.95 | 1.8 – 2.4 |
| `hang_catch_below` | 0.25 | 0 – 1 |
| `hang_catch_above` | 0.3 | 0 – 1 |
| `hang_reach` | 0.35 | 0.05 – 1 |
| `hang_max_rise_speed` | 2 | -5 – 10 |
| `hang_hand_spacing` | 0.45 | 0.1 – 0.8 |
| `hang_hand_inset` | 0.06 | 0.01 – 0.3 |
| `hang_wall_gap` | 0.02 | 0.001 – 0.2 |
| `hang_eye_height` | 1.7 | 0.5 – 1.77 |
| `hang_min_ground_gap` | 0.45 | 0 – 2 |
| `hang_yaw_limit` | 70 | 0 – 180 |
| `hang_pitch_up` | 60 | 0 – 85 |
| `hang_pitch_down` | 50 | 0 – 85 |
| `hang_recatch_delay` | 0.5 | 0 – 5 |
| `hang_drop_push` | 0.6 | 0 – 4 |
| `mount_min_below_eye` | 0.1 | 0 – 1 |
| `mount_max_below_eye` | 0.55 | 0.05 – 1.5 |
| `mount_reach` | 0.75 | 0.1 – 2 |
| `mount_max_angle` | 15 | 0 – 45 |
| `mount_yaw_limit` | 35 | 0 – 90 |
| `mount_pitch_up` | 25 | 0 – 85 |
| `mount_pitch_down` | 30 | 0 – 85 |
| `mount_recoil_scale` | 0.45 | 0 – 1 |
| `mount_max_speed` | 0.5 | 0 – 5 |
| `mount_auto_delay` | 0.15 | 0 – 2 |
| `mount_clearance` | 0.06 | 0.01 – 0.5 |
| `mount_move_deadzone` | 0.2 | 0 – 1 |
| `weapon_length` | 0.85 | 0.3 – 1.5 |
| `weapon_radius` | 0.045 | 0 – 0.2 |
| `obstruct_max_retract` | 0.4 | 0.05 – 1 |
| `obstruct_rate_in` | 6 | 0.5 – 60 |
| `obstruct_rate_out` | 3 | 0.5 – 60 |
| `obstruct_recover_delay` | 0.12 | 0 – 1 |
| `obstruct_hysteresis` | 0.05 | 0 – 0.5 |
| `obstruct_ads_block` | 0.35 | 0 – 1 |
| `obstruct_fire_block` | 0.85 | 0.05 – 1 |
| `obstruct_fire_release` | 0.7 | 0 – 1 |
| `max_health` | 100 | 1 – 1000 |
| `respawn_delay` | 3 | 0 – 30 |
| `lean_distance` | 0.4 | 0 – 0.8 |
| `lean_crouch_distance` | 0.3 | 0 – 0.8 |
| `lean_roll` | 12 | 0 – 30 |
| `lean_time` | 0.18 | 0.02 – 1 |
| `lean_head_radius` | 0.15 | 0.05 – 0.4 |
| `cant_angle` | 22 | -60 – 60 |
| `cant_time` | 0.14 | 0.02 – 1 |

## Animation slots

Every slot is declared in `assets/animations.cfg` as `action.<slot>=unavailable`
until an authored clip exists. To bind one, replace that line with
`action.<slot>.asset=...`, `action.<slot>.clip=...` and, optionally,
`action.<slot>.events=name:0.4,other:1`. Unknown or misspelled slots, bad
paths and non-normalized events are rejected. A bound clip that cannot be
loaded is reported on screen.

**Gameplay gates** (an authored clip retimes gameplay):
- `slide_enter.capsule_low`, `slide_enter.weapon_free`
- `slide_recover.weapon_ready`
- `dive_launch.steer_allowed`
- `dive_impact` duration
- `dive_recover.cancel_allowed`, `dive_recover.weapon_ready`
- `ledge_catch.hands_planted`
- `pistol_draw.ready`, `pistol_stow.regrip`
- `pull_up` duration
- `hang_drop.weapon_ready`

The remaining events are presentation markers.

| Slot (`action.<slot>`) | Loop | Placeholder s | Events (normalized) |
| --- | --- | --- | --- |
| `tac_sprint_enter` | no | 0.18 | `speed_reached` 1 |
| `tac_sprint_loop` | yes | 0.6 | — |
| `tac_sprint_exit` | no | 0.22 | `weapon_ready` 0.8 |
| `slide_enter` | no | 0.2 | `capsule_low` 0.5, `weapon_free` 1 |
| `slide_loop` | yes | 0.5 | — |
| `slide_recover` | no | 0.3 | `weapon_ready` 0.6 |
| `slide_interrupt` | no | 0.15 | — |
| `dive_launch` | no | 0.25 | `steer_allowed` 0.4 |
| `dive_air` | yes | 0.5 | — |
| `dive_impact` | no | 0.3 | `impact` 0 |
| `dive_recover` | no | 0.45 | `cancel_allowed` 0.4, `weapon_ready` 0.7 |
| `mount_enter` | no | 0.15 | `supported` 1 |
| `mount_hold` | yes | 1 | — |
| `mount_exit` | no | 0.15 | — |
| `ledge_catch` | no | 0.25 | `hands_planted` 0.4 |
| `ledge_hold` | yes | 1 | — |
| `ledge_lost` | no | 0.2 | — |
| `pistol_draw` | no | 0.55 | `release_grip` 0.15, `pistol_in_hand` 0.55, `ready` 1 |
| `pistol_ready` | yes | 1 | — |
| `pistol_aim` | no | 0.2 | — |
| `pistol_fire` | no | 0.12 | — |
| `pistol_stow` | no | 0.5 | `pistol_holstered` 0.6, `regrip` 1 |
| `pull_up` | no | 1 | `rise_end` 0.55, `over_lip` 0.9, `complete` 1 |
| `hang_drop` | no | 0.2 | `weapon_ready` 1 |

## Capture replays

`--reference-viewport --capture-sequence=gameplay-slide|gameplay-hang|gameplay-obstruct|gameplay-sway`
replays fixed input timing through `Simulation::update`, with no pose,
velocity or clock overrides. It writes PNG frames plus `.gameplay.json`:
slot, phase, normalized time, weight, placeholder flag, hand anchors and
owners, obstruction, position, eye height and look-sway angle. Rerun the same
sequences after authored clips land to get before/after captures at identical
timing.

## Verification

| Suite | Covers |
| --- | --- |
| `tests/traversal_movement_contract.rs` | Tactical sprint, slide and dive: entry, rejection, sustained, exit, interruption, walls, ledges, slopes, low ceilings, render rates (15–240 fps) |
| `tests/ledge_hang_contract.rs` | Catch validation, look limits, weapon lockout, drop/recatch, lost support (removed, moved, blocked), pull-up and blocked top, sidearm draw/fire/stow/interruption, render rates |
| `tests/weapon_action_contract.rs` | Mount detection, limits, recoil and unmount; obstruction rate, partial retraction, off-center detection, hysteresis and recovery; death/respawn; reset; permission table |
| `tests/action_manifest_contract.rs` | Slot declarations, authored retiming, malformed bindings |
| Unit tests | Sway (frame rate, sensitivity, settle, bounds), body (foot lock, yaw, slopes, camera independence), action latch, replays |

These are deterministic gameplay tests. They are not visual acceptance.
